"""轉錄進度：進度檔、百分比和預估剩餘時間、minutes progress、視窗開不起來不影響轉錄。"""
import json
import subprocess

import pytest
from conftest import make_wav

from minutes import progress, transcribe
from minutes.cli import main


def data(**kw):
    d = {"state": "transcribing", "folder": "2026-10-06_週會", "total": 1000.0, "done": 100.0, "part": 1,
         "parts": 2, "started": 0.0, "updated": 200.0, "speed_from": [100.0, 0.0], "done_at": 200.0, "error": ""}
    d.update(kw)
    return d


def test_no_file_is_none(tmp_path):
    assert progress.summarize(progress.read(tmp_path)) == {"state": "none"}


def test_eta_uses_this_run_speed():
    s = progress.summarize(data(), now=205.0)
    assert s["percent"] == 10
    assert s["eta"] == 895  # 100 秒轉了 100 秒的錄音，剩 900 秒，再扣掉上次更新後過的 5 秒
    assert s["elapsed"] == 205
    assert s["stale"] is False


@pytest.mark.parametrize("kw", [
    {"done_at": 150.0, "updated": 150.0},  # 轉錄開始不到 60 秒
    {"total": 10000.0},  # 還不到 5%
    {"state": "loading", "speed_from": None, "done_at": None, "done": 0.0},
])
def test_no_eta_too_early(kw):
    assert progress.summarize(data(**kw), now=205.0)["eta"] is None


def test_stale_only_while_running():
    assert progress.summarize(data(), now=231.0)["stale"] is True
    assert progress.summarize(data(state="done"), now=999.0)["stale"] is False
    assert progress.summarize(data(state="error", error="壞了"), now=999.0)["stale"] is False


def test_text():
    assert progress.text(progress.summarize(data(), now=205.0)) == "第 1／2 段，已轉 10%，大概還要 15 分鐘。"
    assert progress.text(progress.summarize(data(done_at=150.0), now=205.0)) == "第 1／2 段，已轉 10%，正在估算還要多久。"
    assert "停了" in progress.text(progress.summarize(data(), now=300.0))
    assert progress.fmt_minutes(20) == "不到 1 分鐘"
    assert progress.fmt_minutes(3900) == "1 小時 5 分鐘"


class ProgressEngine:
    """每段報一次進度，同時記下當下進度檔的內容。"""

    def __init__(self, folder):
        self.folder, self.device, self.fallback_reason, self.seen = folder, "cpu", "", []

    def count_tokens(self, text):
        return len(text)

    def run(self, audio, prompt, on_progress):
        on_progress(1.0, 2.0)
        progress.progress_file(self.folder).unlink()  # 強迫下一次更新一定寫檔
        on_progress(1.5, 2.0)
        self.seen.append(progress.read(self.folder) or {})
        return [(0.0, 1.0, "一句")]


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "2026-10-06_週會"
    make_wav(f / "語音 261006_143000.wav", 2)
    make_wav(f / "語音 261006_143005.wav", 2)
    return f


def test_transcribe_writes_progress(folder, monkeypatch):
    monkeypatch.setattr(progress, "WRITE_EVERY", 0)
    engine = ProgressEngine(folder)
    transcribe.run(folder, "breeze", "cpu", log=lambda m: None, engine=engine)
    first, second = engine.seen
    assert (first["state"], first["part"], first["done"]) == ("transcribing", 1, 1.5)
    assert (second["part"], second["done"]) == (2, 3.5)  # 前一段的 2 秒算已轉
    final = progress.read(folder)
    assert final["state"] == "done" and final["done"] == final["total"] == 4.0


def test_transcribe_failure_recorded(folder):
    class Broken(ProgressEngine):
        def run(self, audio, prompt, on_progress):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        transcribe.run(folder, "breeze", "cpu", log=lambda m: None, engine=Broken(folder))
    assert progress.read(folder)["state"] == "error"
    assert progress.read(folder)["error"] == "轉錄被中斷"


def test_launch_disabled_or_failing(folder, monkeypatch):
    assert progress.launch_window(folder) is False  # conftest 設了 MINUTES_NO_WINDOW
    monkeypatch.delenv("MINUTES_NO_WINDOW")

    def boom(*a, **kw):
        raise OSError("開不了")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert progress.launch_window(folder) is False


def test_cli_transcribe_survives_window_failure(folder, monkeypatch, capsys):
    monkeypatch.delenv("MINUTES_NO_WINDOW")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(OSError("開不了")))
    monkeypatch.setattr(transcribe, "Engine", lambda *a, **kw: ProgressEngine(folder))
    assert main(["transcribe", str(folder), "--device", "cpu", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cli_window_only_when_something_to_do(folder, monkeypatch):
    called = []
    monkeypatch.setattr(progress, "launch_window", lambda f: called.append(f))
    monkeypatch.setattr(transcribe, "Engine", lambda *a, **kw: ProgressEngine(folder))
    main(["transcribe", str(folder), "--device", "cpu", "--no-window", "--json"])
    assert called == []
    main(["transcribe", str(folder), "--device", "cpu", "--json"])
    assert called == []  # 全部轉過了，不用開
    for f in (folder / "_暫存").glob("*.轉錄.json"):
        f.unlink()
    main(["transcribe", str(folder), "--device", "cpu", "--json"])
    assert len(called) == 1
    assert progress.read(folder) is not None  # 進度檔先寫好才開視窗


def test_early_failure_opens_no_window(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(progress, "launch_window", lambda f: called.append(f))
    assert main(["transcribe", str(tmp_path / "沒有這個資料夾"), "--json"]) == 1
    (tmp_path / "空的").mkdir()
    assert main(["transcribe", str(tmp_path / "空的"), "--json"]) == 1  # 沒有錄音
    assert called == []


def test_old_progress_files_cleaned(tmp_path):
    import os
    import time

    progress.progress_dir().mkdir(parents=True)
    old = progress.progress_dir() / "舊的.json"
    old.write_text("{}", encoding="utf-8")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    progress.Tracker(tmp_path, 1.0, 1).finish()
    assert not old.exists()
    assert progress.read(tmp_path)["state"] == "done"


def test_cli_progress_json(folder, capsys):
    assert main(["progress", str(folder), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "state": "none"}
    progress.Tracker(folder, 4.0, 2).finish()
    main(["progress", str(folder), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert (out["state"], out["percent"]) == ("done", 100)
    main(["progress", str(folder), "--window", "--json"])
    assert json.loads(capsys.readouterr().out) == {"ok": True, "opened": False}  # 已經轉完，不開
