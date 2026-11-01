"""Safe local audio playback for Discord voice channels."""
import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "~/discord-audio")).expanduser().resolve()
MAX_UPLOAD_BYTES = int(float(os.getenv("AUDIO_MAX_UPLOAD_MB", "25")) * 1024 * 1024)
EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".webm", ".opus"}


def list_audio_files(directory: Path = AUDIO_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return sorted((p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS), key=lambda p: p.name.lower())


def validate_audio_path(path: Path, root: Path = AUDIO_DIR) -> Path:
    path = path.resolve()
    root = root.resolve()
    if root not in path.parents or path.suffix.lower() not in EXTENSIONS or not path.is_file():
        raise ValueError("The selected file is not an allowed audio file.")
    return path


async def validate_audio_file(path: Path) -> None:
    """Ask ffmpeg to decode enough metadata to reject non-audio uploads."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise ValueError("FFmpeg could not decode that file as audio.")


class AudioView(discord.ui.View):
    def __init__(self, cog, requester: discord.Member, files: list[Path]):
        super().__init__(timeout=120)
        self.cog, self.requester, self.files, self.page = cog, requester, files, 0
        self._refresh_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester.id and not getattr(interaction.user, "guild_permissions", None).administrator:
            await interaction.response.send_message("Only the playback requester can use this menu.", ephemeral=True)
            return False
        return True

    def _refresh_items(self):
        self.clear_items()
        start = self.page * 25
        select = discord.ui.Select(placeholder="Choose a saved audio file", options=[
            discord.SelectOption(label=p.name[:100], value=str(i), description="Play this file")
            for i, p in enumerate(self.files[start:start + 25], start=start)
        ])
        select.callback = self._selected
        self.add_item(select)
        if len(self.files) > 25:
            prev = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            nxt = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, disabled=(start + 25 >= len(self.files)))
            prev.callback = self._previous
            nxt.callback = self._next
            self.add_item(prev)
            self.add_item(nxt)
        upload = discord.ui.Button(label="Upload Audio", style=discord.ButtonStyle.primary)
        upload.callback = self._upload_help
        self.add_item(upload)

    async def _selected(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        path = validate_audio_path(self.files[int(interaction.data["values"][0])])
        await self.cog.start_playback(interaction, path, self.requester)

    async def _previous(self, interaction):
        self.page -= 1; self._refresh_items(); await interaction.response.edit_message(view=self)

    async def _next(self, interaction):
        self.page += 1; self._refresh_items(); await interaction.response.edit_message(view=self)

    async def _upload_help(self, interaction):
        if hasattr(discord.ui, "FileUpload"):
            try:
                modal = discord.ui.Modal(title="Upload Audio")
                modal.add_item(discord.ui.FileUpload(label="Audio file", required=True))
                await interaction.response.send_modal(modal)
                return
            except (AttributeError, TypeError):
                log.exception("Native FileUpload API was present but could not be constructed")
        await interaction.response.send_message("Native file-upload dialogs are unavailable in this library build. Use `/play` with its optional audio attachment field.", ephemeral=True)


class PlaybackView(discord.ui.View):
    def __init__(self, cog, guild_id, requester_id):
        # Playback can last for hours; the old 120-second timeout disabled Stop.
        super().__init__(timeout=None)
        self.cog, self.guild_id, self.requester_id = cog, guild_id, requester_id
        self.token = cog.sessions.get(guild_id, (None, requester_id, None))[2]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        session = self.cog.sessions.get(self.guild_id)
        if not session or session[2] != self.token:
            await interaction.response.send_message("This playback session has ended.", ephemeral=True)
            return False
        if interaction.user.id != session[1] and not getattr(interaction.user.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the requester or an administrator can control playback.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        member = interaction.user
        if member.id != self.requester_id and not getattr(member.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the requester or an administrator can stop playback.", ephemeral=True)
            return
        session = self.cog.sessions.get(self.guild_id)
        if session and session[2] == self.token:
            vc, _, _ = session
            if vc.is_playing(): vc.stop()
            if vc.is_connected(): await vc.disconnect()
        await interaction.response.edit_message(content="⏹️ Playback stopped.", view=None)


class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # guild_id -> (voice client, requester user id, immutable session token)
        self.sessions: dict[int, tuple[discord.VoiceClient, int, str]] = {}

    async def _stop_authorized(self, interaction, session):
        return interaction.user.id == session[1] or getattr(interaction.user.guild_permissions, "administrator", False)

    @app_commands.command(name="stop", description="Stop audio playback in this server")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if not session: return await interaction.followup.send("No audio is playing.", ephemeral=True)
        if not await self._stop_authorized(interaction, session): return await interaction.followup.send("Only the requester or an administrator can stop playback.", ephemeral=True)
        vc, _, token = session
        self.sessions.pop(interaction.guild_id, None)
        if vc.is_playing() or vc.is_paused(): vc.stop()
        if vc.is_connected(): await vc.disconnect(force=True)
        await interaction.followup.send("Playback stopped.", ephemeral=True)

    @app_commands.command(name="play", description="Play a saved audio file or an uploaded audio attachment")
    @app_commands.describe(audio="Optional audio attachment to play once")
    async def play(self, interaction: discord.Interaction, audio: discord.Attachment | None = None):
        await interaction.response.defer(ephemeral=True)
        if not await self.bot_allowed(interaction):
            await interaction.followup.send("Not allowed in this channel.", ephemeral=True); return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if not member or not member.voice or not member.voice.channel:
            await interaction.followup.send("Join a voice channel first.", ephemeral=True); return
        if audio:
            await self._uploaded(interaction, audio, member); return
        files = list_audio_files()
        view = AudioView(self, member, files)
        text = "Choose an audio file to play." if files else f"No saved audio files found. Add files to `{AUDIO_DIR}` or use the optional audio attachment field."
        await interaction.followup.send(text, view=view if files else None, ephemeral=True)

    async def bot_allowed(self, interaction):
        allowed = getattr(self.bot, "allowed_channel", None)
        return await allowed(interaction) if allowed else True

    async def _uploaded(self, interaction, attachment, member):
        name = Path(attachment.filename).suffix.lower()
        if attachment.size > MAX_UPLOAD_BYTES or name not in EXTENSIONS:
            await interaction.followup.send(f"Upload an audio file ({', '.join(sorted(EXTENSIONS))}) under {MAX_UPLOAD_BYTES // 1024 // 1024} MB.", ephemeral=True); return
        temp_dir = Path(tempfile.mkdtemp(prefix="discord-audio-"))
        path = temp_dir / f"{uuid.uuid4().hex}{name}"
        try:
            await attachment.save(path)
            await validate_audio_file(path)
            await self.start_playback(interaction, path, member, cleanup=temp_dir)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            await interaction.followup.send("That upload could not be decoded as audio.", ephemeral=True)

    async def start_playback(self, interaction, path: Path, requester, cleanup: Path | None = None):
        guild = interaction.guild
        if not guild or guild.id in self.sessions:
            await interaction.followup.send("Playback is already active in this server.", ephemeral=True); return
        channel = requester.voice.channel if requester.voice else None
        if not channel:
            await interaction.followup.send("Join a voice channel first.", ephemeral=True); return
        perms = channel.permissions_for(guild.me)
        if not perms.connect or not perms.speak:
            await interaction.followup.send("I need Connect and Speak permissions in that voice channel.", ephemeral=True); return
        vc = None
        try:
            vc = await asyncio.wait_for(channel.connect(timeout=10, reconnect=False), timeout=15)
            if not vc.is_connected():
                raise discord.ClientException("Voice connection did not become ready")
            token = uuid.uuid4().hex
            self.sessions[guild.id] = (vc, requester.id, token)
            source = discord.FFmpegPCMAudio(str(path))
            done = asyncio.get_running_loop().create_future()
            def after(error):
                if not done.done(): done.set_result(error)
            vc.play(source, after=after)
            await interaction.followup.send(f"▶️ Playing **{path.name}** in {channel.mention}.", view=PlaybackView(self, guild.id, requester.id), ephemeral=True)
            error = await done
            if error: log.error("Audio playback failed: %s", type(error).__name__)
        except Exception:
            await interaction.followup.send("I could not start playback. Check voice permissions and that the file is valid.", ephemeral=True)
        finally:
            self.sessions.pop(guild.id, None)
            if vc and vc.is_connected(): await vc.disconnect()
            if cleanup: shutil.rmtree(cleanup, ignore_errors=True)


async def setup(bot):
    await bot.add_cog(Audio(bot))
