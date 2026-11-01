from pathlib import Path
import pytest
from src.cogs.audio import Audio, PlaybackState, PlaybackView, list_audio_files, validate_audio_path
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
    assert {"Pause", "Restart", "Volume", "Stop"}.issubset(labels)
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
