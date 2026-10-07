import sys

import pytest

from minutes import installer, paths


@pytest.fixture
def home(workspace, tmp_path, monkeypatch):
    h = tmp_path / "MeetingMinutes"
    monkeypatch.setenv("MINUTES_HOME", str(h))
    return h


def test_plan_lists_gpu_and_model_only_when_needed(home):
    with_gpu = installer.plan_text(gpu=True)
    assert "顯示卡加速套件" in with_gpu
    assert "下載語音辨識模型 breeze" in with_gpu
    without = installer.plan_text(gpu=False)
    assert "捷徑" not in installer.plan_text(gpu=False, shortcut=False)
    assert "試跑" not in installer.plan_text(gpu=False, trial=False)
    assert "顯示卡" not in without
    # 編號連續，不會因為少了一項而跳號
    nums = [ln.split(".")[0].strip() for ln in without.splitlines()[1:]]
    assert nums == [str(n) for n in range(1, len(nums) + 1)]

    (home / "models" / "breeze").mkdir(parents=True)
    for f in ("model.bin", "config.json", "tokenizer.json", "vocabulary.json"):
        (home / "models" / "breeze" / f).write_text("x")
    assert "下載語音辨識模型" not in installer.plan_text(gpu=False)


def test_copy_app_skips_dev_files(home):
    log = installer.Log(home)
    installer.copy_app(home, log)
    log.close()
    dst = home / "app"
    assert (dst / "minutes" / "cli.py").is_file()
    assert (dst / "workspace_template").is_dir()
    assert (dst / "uv.lock").is_file()
    assert not list(dst.rglob("__pycache__"))
    assert not (dst / ".venv").exists()
    assert "開始安裝" in (home / "logs" / "install.log").read_text(encoding="utf-8")


def test_copy_app_replaces_old_version(home):
    old = home / "app" / "minutes" / "舊的.py"
    old.parent.mkdir(parents=True)
    old.write_text("x")
    log = installer.Log(home)
    installer.copy_app(home, log)
    log.close()
    assert not old.exists()


def test_failed_command_message_has_tail(home):
    log = installer.Log(home)
    with pytest.raises(installer.InstallError) as e:
        installer.run([sys.executable, "-c", "import sys; print('最後一行'); sys.exit(3)"], log)
    log.close()
    assert "結束代碼 3" in str(e.value)
    assert "最後一行" in str(e.value)


def test_venv_paths_per_platform(home):
    exe = installer.venv_minutes(home)
    assert exe.parent.name == ("Scripts" if sys.platform == "win32" else "bin")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 的捷徑")
def test_shortcut_points_to_workspace(home, tmp_path):
    desk = tmp_path / "桌面"
    desk.mkdir()
    log = installer.Log(home)
    installer.make_shortcut(log, desk)
    log.close()
    if installer.ansi_ok(desk, paths.workspace()):
        assert (desk / "會議紀錄.lnk").is_file()
    else:
        # 英文語系的 Windows（例如 GitHub Actions）：只說明一句，不能誤報成功
        assert not (desk / "會議紀錄.lnk").exists()
        assert "系統語系不支援" in (home / "logs" / "install.log").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 的捷徑")
def test_shortcut_failure_not_reported_as_success(home, tmp_path, monkeypatch):
    # 舊捷徑還在、這次建捷徑的指令沒有作用時，不能因為檔案存在就說已建立
    desk = tmp_path / "桌面"
    desk.mkdir()
    (desk / "會議紀錄.lnk").write_text("舊的")
    monkeypatch.setattr(installer, "ansi_ok", lambda *a: True)
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: None)
    log = installer.Log(home)
    installer.make_shortcut(log, desk)
    log.close()
    text = (home / "logs" / "install.log").read_text(encoding="utf-8")
    assert "已建立" not in text and "沒建成功" in text
