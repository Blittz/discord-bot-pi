from pathlib import Path
import pytest
from src.cogs.audio import Audio, AudioView, DeleteConfirmView, ImportConfirmView, ImportDestinationView, ImportView, LibraryView, PlaybackState, PlaybackView, SelectedAudioView, UploadChoiceView, EXPIRATION_TEXT, friendly_audio_name, list_audio_files, validate_audio_path, list_import_files
from src.audio_storage import AudioStorage

def test_list_audio_files_filters_and_sorts(tmp_path: Path):
    (tmp_path / "z.mp3").write_bytes(b"")
    (tmp_path / "A.WAV").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in list_audio_files(tmp_path)] == ["A.WAV", "z.mp3"]

def test_validate_audio_path_rejects_escape(tmp_path: Path):
    root = tmp_path / "audio"; root.mkdir()
    good = root / "ok.mp3"; good.write_bytes(b"")
    assert validate_audio_path(good, root) == good.resolve()
    outside = tmp_path / "outside.mp3"; outside.write_bytes(b"")
    with pytest.raises(ValueError): validate_audio_path(outside, root)

def test_playback_controls_are_simplified_and_session_bound():
    class Cog:
        sessions = {}
    cog = Cog()
    state = PlaybackState(None, 42, "token", Path("track.mp3"), 120.0)
    cog.sessions[7] = state
    view = PlaybackView(cog, 7, 42)
    labels = {getattr(item, "label", "") for item in view.children}
    assert {"Pause", "Volume", "Stop"}.issubset(labels)
    assert "Restart" not in labels
    assert not {"⏪ 30s", "30s ⏩", "Forward", "Rewind"} & labels
    assert view.timeout is None

def test_volume_accepts_one_to_one_hundred_and_preserves_transformer():
    cog = Audio(None)
    state = PlaybackState(None, 42, "token", Path("track.mp3"), 120.0)
    cog.sessions[7] = state
    import asyncio
    asyncio.run(cog.set_volume(7, "token", 1))
    assert state.volume == 0.01
    asyncio.run(cog.set_volume(7, "token", 37))
    assert state.volume == 0.37
    asyncio.run(cog.set_volume(7, "token", 100))
    assert state.volume == 1.0

def test_storage_scopes_are_id_based_and_isolated(tmp_path):
    storage = AudioStorage(tmp_path)
    personal, meta = storage.reserve_path(10, "personal", "../private.mp3", owner_id=20)
    assert personal.parent == tmp_path / "servers" / "10" / "personal" / "20"
    assert ".." not in personal.name
    personal.write_bytes(b"audio")
    storage.write_metadata(personal, "friendly name.mp3", 20, "personal")
    assert storage.list_files(10, "personal", owner_id=20) == [personal]
    assert storage.list_files(11, "personal", owner_id=20) == []

def test_storage_save_enforces_quotas_and_metadata(tmp_path):
    storage = AudioStorage(tmp_path); source = tmp_path / "upload.mp3"; source.write_bytes(b"12345")
    saved = storage.save_file(source, 1, "personal", "voice.mp3", 9, personal_quota=5, server_quota=100)
    assert saved.exists() and storage.metadata_path(saved).exists()
    source.write_bytes(b"123456")
    with pytest.raises(ValueError): storage.save_file(source, 1, "personal", "again.mp3", 9, personal_quota=5, server_quota=100)

def test_all_audio_views_initialize_with_saved_file(tmp_path):
    class Permissions: administrator = True
    class User:
        id = 9; guild_permissions = Permissions(); voice = None
    class Cog:
        sessions = {}; storage = None
    cog = Cog()
    saved = tmp_path / "stored.mp3"; saved.write_bytes(b"x")
    audio_view = AudioView(cog, User(), [saved])
    assert any(getattr(item, "label", "") == "Upload Audio" for item in audio_view.children)
    assert hasattr(audio_view, "_upload_help")
    library_view = LibraryView(cog, User())
    assert {getattr(item, "label", "") for item in library_view.children} == {"My Audio", "Channel Audio", "Server Audio"}
    assert isinstance(DeleteConfirmView(cog, User(), saved), DeleteConfirmView)
    assert isinstance(UploadChoiceView(cog, User(), tmp_path, saved, "stored.mp3"), UploadChoiceView)

def test_friendly_name_prefers_metadata_and_sanitizes(tmp_path):
    path = tmp_path / "random-123.mp3"; path.write_bytes(b"x")
    path.with_suffix(".mp3.json").write_text('{"display_name":"<@123>  Song `Name`"}', encoding="utf-8")
    name = friendly_audio_name(path)
    assert "@123" not in name and "`" not in name and "Song" in name

def test_friendly_name_falls_back_to_original_filename(tmp_path):
    path = tmp_path / "id123.mp3"; path.write_bytes(b"x")
    path.with_suffix(".mp3.json").write_text('{"original_filename":"My Unicode Song.mp3"}', encoding="utf-8")
    assert friendly_audio_name(path) == "My Unicode Song"

def test_library_selection_exposes_play_and_delete_actions(tmp_path):
    class Permissions: administrator = True
    class User: id = 9; guild_permissions = Permissions(); voice = None
    class Cog: sessions = {}; storage = None
    path = tmp_path / "song.mp3"; path.write_bytes(b"x")
    library = AudioView(Cog(), User(), [path])
    selected = SelectedAudioView(library.cog, library.requester, path, library)
    assert {getattr(item, "label", "") for item in selected.children} == {"▶️ Play", "🗑️ Delete"}
    assert selected.parent is library

def test_import_directory_lists_only_direct_regular_audio_files(tmp_path, monkeypatch):
    import src.cogs.audio as audio
    monkeypatch.setattr(audio, "IMPORT_DIR", tmp_path)
    (tmp_path / "large.mp3").write_bytes(b"x")
    (tmp_path / "note.txt").write_text("x")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.mp3").write_bytes(b"x")
    assert list_import_files() == [tmp_path / "large.mp3"]

def test_import_views_and_admin_gate(tmp_path):
    class Permissions: administrator = True
    class User: id = 1; guild_permissions = Permissions()
    class Cog: storage_lock = __import__('asyncio').Lock(); storage = None
    path = tmp_path / "recording.mp3"; path.write_bytes(b"x")
    assert isinstance(ImportView(Cog(), User(), [path]), ImportView)
    assert isinstance(ImportDestinationView(Cog(), User(), path), ImportDestinationView)
    assert isinstance(ImportConfirmView(Cog(), User(), path, "personal", None), ImportConfirmView)

def test_player_message_edit_reuses_existing_message():
    import asyncio
    class Message:
        def __init__(self): self.edits = []
        async def edit(self, **kwargs): self.edits.append(kwargs)
    cog = Audio(None); message = Message(); cog.player_messages[55] = message
    assert asyncio.run(cog._edit_player(55, "updated", None)) is True
    assert len(message.edits) == 1 and message.edits[0]["content"] == "updated"

def test_expiring_menu_has_fresh_play_stop_instructions():
    assert "Audio Player — Menu Expired" in EXPIRATION_TEXT
    assert "`/play`" in EXPIRATION_TEXT and "`/stop`" in EXPIRATION_TEXT
    class Cog: sessions = {}
    assert PlaybackView(Cog(), 1, 1).timeout is None

def test_presence_tracks_pause_resume_and_stale_sessions(tmp_path):
    import asyncio
    class Bot:
        def __init__(self): self.activities = []
        async def change_presence(self, activity): self.activities.append(activity.name)
    bot = Bot(); cog = Audio(bot)
    state = PlaybackState(None, 1, "old", tmp_path / "old.mp3", 10)
    state.path.write_bytes(b"x")
    async def run():
        await cog._presence_start(state)
        state.paused = True; await cog._presence_state(state)
        assert bot.activities[-1].startswith("⏸ Paused:")
        state.paused = False; await cog._presence_state(state)
        assert bot.activities[-1].startswith("Playing ")
        newer = PlaybackState(None, 1, "new", tmp_path / "new.mp3", 10); newer.path.write_bytes(b"x")
        await cog._presence_start(newer); await cog._presence_end("old")
        assert bot.activities[-1].endswith("new")
        await cog._presence_end("new"); assert "overlord" in bot.activities[-1]
    asyncio.run(run())
