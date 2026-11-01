from pathlib import Path
import pytest
from src.cogs.audio import PlaybackState, PlaybackView, list_audio_files, validate_audio_path

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
