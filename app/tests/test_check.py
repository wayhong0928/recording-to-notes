"""環境檢查和兩個平台的路徑。"""
import sys
from pathlib import Path

from minutes import check, models, paths


def test_cuda_needed_for_rtx50():
    assert check.cuda_needed({"compute_cap": "12.0"}) == "12.8"
    assert check.cuda_needed({"compute_cap": "8.6"}) == "12.0"


def test_driver_cuda_both_formats():
    assert check.driver_cuda("| NVIDIA-SMI 572.16   Driver Version: 572.16   CUDA Version: 12.8 |") == "12.8"
    assert check.driver_cuda("| NVIDIA-SMI 616.92   KMD Version: 616.92   CUDA UMD Version: 13.4 |") == "13.4"
    assert check.driver_cuda("沒有") == ""


def test_old_driver_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(check, "nvidia_info", lambda: {"name": "RTX 5060", "driver": "560.0", "compute_cap": "12.0", "cuda": "12.6"})
    usable, why, fix = check.gpu_status()
    assert not usable and "太舊" in why and fix
    assert check.pick_device("auto")[0] == "cpu"
    assert check.pick_device("cpu")[0] == "cpu"


def test_no_gpu_is_ok(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(check, "nvidia_info", lambda: None)
    item = check._device()
    assert item.status == check.OK and "CPU" in item.detail


def test_mac_always_cpu(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert check.pick_device("auto")[0] == "cpu"


def test_requested_cuda_note_is_not_contradictory(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(check, "nvidia_info", lambda: None)
    device, why = check.pick_device("cuda")
    assert device == "cuda" and "，用 CPU" not in why and "自動改用 CPU" in why
    assert check.pick_device("auto") == ("cpu", "用 CPU（沒有 NVIDIA 顯卡）")


def test_check_json_has_error_when_failed():
    items = [check.Item("packages", "轉錄套件", check.ERROR, "缺少 av"), check.Item("disk", "硬碟空間", check.OK, "夠")]
    data = check.as_json(items)
    assert data["ok"] is False and data["error"] == "檢查有問題：轉錄套件"
    assert "error" not in check.as_json(items[1:])


def test_paths_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("MINUTES_HOME", raising=False)
    monkeypatch.delenv("MINUTES_WORKSPACE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.app_home() == tmp_path / "Library" / "Application Support" / "MeetingMinutes"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.app_home() == tmp_path / "Local" / "MeetingMinutes"
    assert paths.workspace() == tmp_path / "會議紀錄"
    assert paths.inbox() == tmp_path / "會議紀錄" / "錄音放這裡"


def test_quick_check_reports_missing_workspace_and_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MINUTES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MINUTES_WORKSPACE", str(tmp_path / "沒有這個"))
    items = {i.key: i for i in check.run(quick=True)}
    assert items["workspace"].status == check.ERROR
    assert items["model"].status == check.WARN
    assert not check.as_json(list(items.values()))["ok"]
    assert "network" not in items  # quick 不連網路

    before = {i.key: i for i in check.run(quick=True, before_install=True)}
    assert before["workspace"].status == check.INFO and before["model"].status == check.INFO


def test_model_downloaded_detection(workspace):
    d = models.path("breeze")
    assert not models.is_downloaded("breeze")
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    (d / "config.json").write_text("{}")
    assert not models.is_downloaded("breeze")  # tokenizer、vocabulary 還沒下載
    (d / "tokenizer.json").write_text("{}")
    (d / "vocabulary.json").write_text("[]")
    assert models.is_downloaded("breeze")
    # 下載到一半中斷：huggingface_hub 留下 .incomplete 暫存檔
    part = d / ".cache" / "huggingface" / "download" / "model.bin.abc.incomplete"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"x")
    assert not models.is_downloaded("breeze")
