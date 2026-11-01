"""Safe local audio playback for Discord voice channels."""
import asyncio
import logging
import json
import os
import subprocess
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from src.audio_storage import AudioStorage

log = logging.getLogger(__name__)
AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "~/discord-audio")).expanduser().resolve()
MAX_UPLOAD_BYTES = int(float(os.getenv("AUDIO_MAX_UPLOAD_MB", "125")) * 1024 * 1024)
MAX_AUDIO_SECONDS = int(os.getenv("AUDIO_MAX_DURATION_SECONDS", "7200"))
EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}

def friendly_audio_name(path: Path) -> str:
    """Resolve display text from stored metadata, then embedded tags, then filename."""
    metadata = {}
    try: metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError): pass
    name = None
    try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=artist,title", "-of", "json", str(path)], capture_output=True, text=True, timeout=3, check=False)
            tags = json.loads(result.stdout or "{}").get("format", {}).get("tags", {})
            artist = tags.get("artist") or tags.get("ARTIST"); title = tags.get("title") or tags.get("TITLE")
            if artist and title: name = f"{artist} – {title}"
            elif title: name = title
            elif artist: name = artist
    except (OSError, ValueError, subprocess.SubprocessError): pass
    name = name or metadata.get("display_name") or metadata.get("original_filename")
    name = str(name or path.stem).rsplit(".", 1)[0].strip() or "Audio Recording"
    name = discord.utils.escape_mentions(name).replace("@", "@\u200b").replace("`", "'")
    return name[:200] or "Audio Recording"

@dataclass
class PlaybackState:
    vc: discord.VoiceClient
    requester_id: int
    token: str
    path: Path
    duration: float | None = None
    source: discord.AudioSource | None = None
    paused: bool = False
    volume: float = 1.0
    operation_lock: asyncio.Lock | None = None

    def display(self) -> str:
        total = f"{int(self.duration)//60}:{int(self.duration)%60:02d}" if self.duration else "unknown"
        return f"{'⏸️ Paused' if self.paused else '▶️ Playing'} — duration {total}\nVolume: {int(self.volume*100)}%"


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
    """Validate a local upload as an audio stream without network protocols."""
    probe = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(probe.communicate(), timeout=20)
    if probe.returncode != 0:
        raise ValueError("FFprobe could not read this audio file.")
    import json
    data = json.loads(out or b"{}")
    if not data.get("streams") or float((data.get("format") or {}).get("duration") or 0) > MAX_AUDIO_SECONDS:
        raise ValueError("Audio is missing a valid stream or exceeds the duration limit.")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise ValueError("FFmpeg could not decode that file as audio.")

async def audio_duration(path: Path) -> float | None:
    proc = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    try: return float(out.strip()) if proc.returncode == 0 else None
    except (TypeError, ValueError): return None


class AudioView(discord.ui.View):
    def __init__(self, cog, requester: discord.Member, files: list[Path]):
        super().__init__(timeout=120)
        self.cog, self.requester, self.files, self.page = cog, requester, files, 0
        self.selected_path = None
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
            discord.SelectOption(label=friendly_audio_name(p)[:100], value=str(i), description="Play this file")
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
        self.selected_path = path
        await self.cog.start_playback(interaction, path, self.requester)

    @discord.ui.button(label="Delete Selected", style=discord.ButtonStyle.danger, row=2)
    async def delete_selected(self, interaction, button):
        if not self.selected_path:
            return await interaction.response.send_message("Select a file first, then choose Delete Selected.", ephemeral=True)
        name = friendly_audio_name(self.selected_path)
        try:
            scope = json.loads(self.cog.storage.metadata_path(self.selected_path).read_text(encoding="utf-8")).get("scope", "audio")
        except (OSError, ValueError, TypeError): scope = "audio"
        await interaction.response.send_message(f"**Delete permanently?**\nRecording: **{name}**\nLibrary: **{scope.title()} Audio**\nThis action cannot be undone.", view=DeleteConfirmView(self.cog, self.requester, self.selected_path, self), ephemeral=True)

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

class DeleteConfirmView(discord.ui.View):
    def __init__(self, cog, requester, path, parent=None):
        super().__init__(timeout=60); self.cog, self.requester, self.path, self.parent = cog, requester, path, parent
    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        is_admin = getattr(interaction.user.guild_permissions, "administrator", False)
        owner_id = None
        try:
            import json
            owner_id = json.loads(self.cog.storage.metadata_path(self.path).read_text(encoding="utf-8")).get("owner_id")
            scope = json.loads(self.cog.storage.metadata_path(self.path).read_text(encoding="utf-8")).get("scope")
        except (OSError, ValueError, TypeError):
            scope = None
        if (scope != "personal" and not is_admin) or (scope == "personal" and not is_admin and interaction.user.id != owner_id):
            return await interaction.followup.send("You are not allowed to delete this file.", ephemeral=True)
        try:
            deleted_name = friendly_audio_name(self.path)
            await asyncio.to_thread(self.cog.storage.delete_file, self.path, interaction.guild_id)
            if self.parent and self.path in self.parent.files:
                self.parent.files.remove(self.path); self.parent.selected_path = None; self.parent._refresh_items()
            await interaction.followup.send(f"Deleted **{deleted_name}** permanently. The library listing has been refreshed.", ephemeral=True)
        except (OSError, ValueError):
            await interaction.followup.send("That file is no longer available or cannot be deleted.", ephemeral=True)
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button): await interaction.response.edit_message(content="Deletion cancelled.", view=None)

class LibraryView(discord.ui.View):
    """Private scope picker; every callback rechecks the member and guild IDs."""
    def __init__(self, cog, requester):
        super().__init__(timeout=300); self.cog, self.requester = cog, requester
    async def interaction_check(self, interaction):
        if interaction.user.id != self.requester.id and not getattr(interaction.user.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the requester or an administrator can browse this library.", ephemeral=True); return False
        return True
    async def _scope(self, interaction, scope):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        channel_id = getattr(self.requester.voice.channel, "id", None) if self.requester.voice else None
        owner = self.requester.id if scope == "personal" else None
        files = self.cog.storage.list_files(guild_id, scope, owner_id=owner, channel_id=channel_id)
        if not files: return await interaction.followup.send("That audio library is empty.", ephemeral=True)
        await interaction.followup.send(f"{scope.title()} Audio", view=AudioView(self.cog, self.requester, files), ephemeral=True)
    @discord.ui.button(label="My Audio", style=discord.ButtonStyle.secondary)
    async def personal(self, interaction, button): await self._scope(interaction, "personal")
    @discord.ui.button(label="Channel Audio", style=discord.ButtonStyle.secondary)
    async def channel(self, interaction, button): await self._scope(interaction, "channel")
    @discord.ui.button(label="Server Audio", style=discord.ButtonStyle.secondary)
    async def server(self, interaction, button): await self._scope(interaction, "server")

class UploadChoiceView(discord.ui.View):
    def __init__(self, cog, requester, temp_dir, path, display_name):
        super().__init__(timeout=300); self.cog, self.requester, self.temp_dir, self.path, self.display_name = cog, requester, temp_dir, path, display_name
        if not getattr(requester.guild_permissions, "administrator", False):
            for child in self.children:
                if getattr(child, "label", "") in {"Save to Channel Audio", "Save to Server Audio"}: child.disabled = True
    async def interaction_check(self, interaction):
        if interaction.user.id != self.requester.id and not getattr(interaction.user.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the uploader or an administrator can choose how to save this file.", ephemeral=True); return False
        return True
    async def _choose(self, interaction, scope=None):
        await interaction.response.defer(ephemeral=True)
        try:
            if scope:
                if scope in {"channel", "server"} and not getattr(interaction.user.guild_permissions, "administrator", False):
                    return await interaction.followup.send("Only server administrators can save shared audio.", ephemeral=True)
                channel_id = interaction.channel_id if scope == "channel" else None
                voice_name = getattr(getattr(self.requester, "voice", None), "channel", None)
                destination = f"channel {getattr(voice_name, 'name', interaction.channel.name)}" if scope == "channel" else f"server {interaction.guild.name}" if scope == "server" else "your private My Audio library"
                size = self.path.stat().st_size
                await interaction.followup.send(
                    f"**Confirm permanent save**\nFile: `{self.display_name}`\nSize: {size / 1024 / 1024:.1f} MB\nDestination: **{destination}**",
                    view=SaveConfirmView(self.cog, self.requester, self.temp_dir, self.path, self.display_name, scope, channel_id), ephemeral=True)
                return
            else:
                await self.cog.start_playback(interaction, self.path, self.requester, cleanup=self.temp_dir)
                return
        except (OSError, ValueError) as error:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            await interaction.followup.send(str(error), ephemeral=True)

    async def on_timeout(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    @discord.ui.button(label="Play Once", style=discord.ButtonStyle.primary)
    async def play_once(self, interaction, button): await self._choose(interaction)
    @discord.ui.button(label="Save to My Audio", style=discord.ButtonStyle.secondary)
    async def save_personal(self, interaction, button): await self._choose(interaction, "personal")
    @discord.ui.button(label="Save to Channel Audio", style=discord.ButtonStyle.secondary)
    async def save_channel(self, interaction, button): await self._choose(interaction, "channel")
    @discord.ui.button(label="Save to Server Audio", style=discord.ButtonStyle.secondary)
    async def save_server(self, interaction, button): await self._choose(interaction, "server")

class SaveConfirmView(discord.ui.View):
    def __init__(self, cog, requester, temp_dir, path, display_name, scope, channel_id):
        super().__init__(timeout=120)
        self.cog, self.requester, self.temp_dir, self.path = cog, requester, temp_dir, path
        self.display_name, self.scope, self.channel_id = display_name, scope, channel_id

    @discord.ui.button(label="Confirm Save", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            # Recheck authorization and quota at commit time, under the save lock.
            if self.scope in {"channel", "server"} and not getattr(interaction.user.guild_permissions, "administrator", False):
                return await interaction.followup.send("You are no longer authorized to save to that shared library.", ephemeral=True)
            async with self.cog.storage_lock:
                saved = await asyncio.to_thread(self.cog.storage.save_file, self.path, interaction.guild_id, self.scope, self.display_name, self.requester.id, self.channel_id)
            await interaction.followup.send(f"Saved **{friendly_audio_name(saved)}** to **{self.scope.title()} Audio**.", ephemeral=True)
            await interaction.edit_original_response(view=None)
        except (OSError, ValueError) as error:
            await interaction.followup.send(str(error), ephemeral=True)
        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        await interaction.response.edit_message(content="Upload cancelled; the temporary file was removed.", view=None)

    async def on_timeout(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class PlaybackView(discord.ui.View):
    def __init__(self, cog, guild_id, requester_id):
        # Playback can last for hours; the old 120-second timeout disabled Stop.
        super().__init__(timeout=None)
        self.cog, self.guild_id, self.requester_id = cog, guild_id, requester_id
        self.token = cog.sessions.get(guild_id, None).token if guild_id in cog.sessions else None
        state = cog.sessions.get(guild_id)
        for child in self.children:
            if getattr(child, "label", None) == "Pause":
                child.label = "Resume" if state and state.paused else "Pause"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        session = self.cog.sessions.get(self.guild_id)
        if not session or session.token != self.token:
            await interaction.response.send_message("This playback session has ended.", ephemeral=True)
            return False
        if interaction.user.id != session.requester_id and not getattr(interaction.user.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the requester or an administrator can control playback.", ephemeral=True)
            return False
        return True

    async def _control(self, interaction, method, *args):
        await interaction.response.defer(ephemeral=True)
        await getattr(self.cog, method)(self.guild_id, self.token, *args)
        state = self.cog.sessions.get(self.guild_id)
        if state and state.token == self.token:
            await interaction.followup.send(state.display(), view=self.cog.control_view(self.guild_id), ephemeral=True)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction, button):
        state = self.cog.sessions.get(self.guild_id)
        await self._control(interaction, "resume_playback" if state and state.paused else "pause_playback")

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.secondary, row=0)
    async def restart(self, interaction, button): await self._control(interaction, "restart_playback")

    @discord.ui.button(label="Volume", style=discord.ButtonStyle.primary, row=2)
    async def volume(self, interaction, button):
        await interaction.response.send_message("Use `/volume` with any whole-number percentage from 1 to 100.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, button):
        member = interaction.user
        if member.id != self.requester_id and not getattr(member.guild_permissions, "administrator", False):
            await interaction.response.send_message("Only the requester or an administrator can stop playback.", ephemeral=True)
            return
        session = self.cog.sessions.get(self.guild_id)
        if session and session.token == self.token:
            vc = session.vc
            if vc.is_playing(): vc.stop()
            if session.source: session.source.cleanup()
            if vc.is_connected(): await vc.disconnect()
            self.cog.sessions.pop(self.guild_id, None)
        await interaction.response.edit_message(content="⏹️ Playback stopped.", view=None)


class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.storage = AudioStorage(AUDIO_DIR)
        self.storage_lock = asyncio.Lock()
        # guild_id -> (voice client, requester user id, immutable session token)
        self.sessions: dict[int, PlaybackState] = {}

    async def _stop_authorized(self, interaction, session):
        return interaction.user.id == session.requester_id or getattr(interaction.user.guild_permissions, "administrator", False)

    @app_commands.command(name="stop", description="Stop audio playback in this server")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        session = self.sessions.get(interaction.guild_id)
        if not session: return await interaction.followup.send("No audio is playing.", ephemeral=True)
        if not await self._stop_authorized(interaction, session): return await interaction.followup.send("Only the requester or an administrator can stop playback.", ephemeral=True)
        vc, token = session.vc, session.token
        self.sessions.pop(interaction.guild_id, None)
        if vc.is_playing() or vc.is_paused(): vc.stop()
        if session.source: session.source.cleanup()
        if vc.is_connected(): await vc.disconnect(force=True)
        await interaction.followup.send("Playback stopped.", ephemeral=True)

    @app_commands.command(name="volume", description="Set playback volume from 1 to 100 percent")
    async def volume_command(self, interaction: discord.Interaction, percent: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        state = self.sessions.get(interaction.guild_id)
        if not state or not 1 <= percent <= 100: return await interaction.followup.send("Choose a whole-number volume from 1 to 100 percent while audio is playing.", ephemeral=True)
        if not await self._stop_authorized(interaction, state): return await interaction.followup.send("Only the requester or an administrator can change volume.", ephemeral=True)
        await self.set_volume(interaction.guild_id, state.token, percent)
        await interaction.followup.send(f"Volume set to {percent}%.", view=self.control_view(interaction.guild_id), ephemeral=True)

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
        await interaction.followup.send("Choose an audio library, or upload an audio file.", view=LibraryView(self, member), ephemeral=True)

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
            await interaction.followup.send(f"Upload validated: **{attachment.filename}**. Choose what to do:", view=UploadChoiceView(self, member, temp_dir, path, attachment.filename), ephemeral=True)
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
            state = PlaybackState(vc, requester.id, token, path, await audio_duration(path), operation_lock=asyncio.Lock())
            self.sessions[guild.id] = state
            source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(path)), volume=1.0)
            state.source = source
            done = asyncio.get_running_loop().create_future()
            def after(error):
                if not done.done(): done.set_result(error)
            vc.play(source, after=after)
            await interaction.followup.send(f"**Now Playing:**\n{friendly_audio_name(path)}\n\n{state.display()}", view=PlaybackView(self, guild.id, requester.id), ephemeral=True)
            error = await done
            if error: log.error("Audio playback failed: %s", type(error).__name__)
        except Exception:
            await interaction.followup.send("I could not start playback. Check voice permissions and that the file is valid.", ephemeral=True)
        finally:
            state = self.sessions.pop(guild.id, None)
            if state and state.source: state.source.cleanup()
            if vc and vc.is_connected(): await vc.disconnect()
            if cleanup: shutil.rmtree(cleanup, ignore_errors=True)

    async def _state(self, guild_id, token):
        state = self.sessions.get(guild_id)
        if not state or state.token != token: return None
        if state.operation_lock is None: state.operation_lock = asyncio.Lock()
        return state

    async def pause_playback(self, guild_id, token):
        state = await self._state(guild_id, token)
        if state:
            async with state.operation_lock:
                if state.vc.is_playing():
                    state.vc.pause(); state.paused = True

    async def resume_playback(self, guild_id, token):
        state = await self._state(guild_id, token)
        if state:
            async with state.operation_lock:
                if state.vc.is_paused(): state.vc.resume(); state.paused = False

    async def restart_playback(self, guild_id, token):
        state = await self._state(guild_id, token)
        if state:
            async with state.operation_lock:
                if state.vc.is_playing() or state.vc.is_paused(): state.vc.stop()
                if state.source: state.source.cleanup()
                state.source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(state.path)), volume=state.volume)
                state.paused = False
                state.vc.play(state.source)

    def control_view(self, guild_id):
        state = self.sessions.get(guild_id)
        return PlaybackView(self, guild_id, state.requester_id) if state else None

    async def set_volume(self, guild_id, token, percent):
        state = await self._state(guild_id, token)
        if state:
            async with state.operation_lock:
                state.volume = max(0.01, min(1.0, percent / 100));
                if isinstance(state.source, discord.PCMVolumeTransformer): state.source.volume = state.volume


async def setup(bot):
    await bot.add_cog(Audio(bot))
