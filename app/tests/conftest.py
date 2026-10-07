import wave
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """假的工作區和程式資料夾，不碰使用者真的家目錄。"""
    ws = tmp_path / "會議紀錄"
    (ws / "錄音放這裡").mkdir(parents=True)
    (ws / "會議").mkdir()
    monkeypatch.setenv("MINUTES_WORKSPACE", str(ws))
    monkeypatch.setenv("MINUTES_HOME", str(tmp_path / "MeetingMinutes"))
    return ws


def make_wav(path: Path, seconds: float = 1.0) -> Path:
    """寫一段靜音 wav，PyAV 讀得到長度，不需要模型。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * seconds))
    return path


@pytest.fixture(autouse=True)
def no_progress_window(tmp_path, monkeypatch):
    """測試不開進度視窗，進度檔寫到暫存資料夾。"""
    monkeypatch.setenv("MINUTES_NO_WINDOW", "1")
    monkeypatch.setenv("MINUTES_PROGRESS_DIR", str(tmp_path / "progress"))
