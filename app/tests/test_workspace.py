import os
import stat
import sys

import pytest

from minutes import paths
from minutes import workspace as wsp

MINUTES = "C:/程式/MeetingMinutes/minutes.exe"


def skill_dir(ws):
    return ws / wsp.SKILL_DIR


def test_setup_builds_workspace(tmp_path):
    ws = tmp_path / "會議紀錄"
    result = wsp.setup(ws, MINUTES)

    assert (ws / paths.INBOX).is_dir()
    assert (ws / paths.MEETINGS).is_dir()
    skill = (skill_dir(ws) / "SKILL.md").read_text(encoding="utf-8")
    assert wsp.PLACEHOLDER not in skill
    assert f'"{MINUTES}" <指令> --json' in skill
    for name in wsp.CONTENT_FILES:
        src = paths.templates() / "content" / name
        assert (skill_dir(ws) / name).read_bytes() == src.read_bytes()
    assert result["workspace"] == str(ws)
    assert result["minutes"] == MINUTES
    assert str(skill_dir(ws) / "SKILL.md") in result["files"]


def test_rerun_keeps_recordings_and_meetings(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    rec = ws / paths.INBOX / "語音 261001_100000.m4a"
    rec.write_bytes(b"audio")
    note = ws / paths.MEETINGS / "2026-10-01_週會" / "2_會議紀錄.md"
    note.parent.mkdir()
    note.write_text("改過的紀錄", encoding="utf-8")

    wsp.setup(ws, "D:/新位置/minutes.exe")

    assert rec.read_bytes() == b"audio"
    assert note.read_text(encoding="utf-8") == "改過的紀錄"
    assert '"D:/新位置/minutes.exe"' in (skill_dir(ws) / "SKILL.md").read_text(encoding="utf-8")


def test_rerun_backs_up_edited_rules(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    rules = skill_dir(ws) / "整理規則.md"
    rules.write_text("使用者自己改的規則", encoding="utf-8")

    wsp.setup(ws, MINUTES)

    backup = skill_dir(ws) / "整理規則.舊.md"
    assert backup.read_text(encoding="utf-8") == "使用者自己改的規則"
    assert rules.read_bytes() == (paths.templates() / "content" / "整理規則.md").read_bytes()


def test_rerun_without_edits_makes_no_backup(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    wsp.setup(ws, MINUTES)
    assert not list(skill_dir(ws).glob("*.舊.md"))


def test_default_target_and_command(workspace):
    # conftest 的 workspace fixture 把 MINUTES_WORKSPACE 指到暫存資料夾
    result = wsp.setup()
    assert result["workspace"] == str(workspace)
    assert result["minutes"].endswith("minutes.exe" if sys.platform == "win32" else "minutes")
    assert "\\" not in result["minutes"]


@pytest.mark.skipif(sys.platform != "win32", reason="只有 Windows 隱藏 .claude")
def test_claude_folder_hidden_on_windows(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    attrs = os.stat(ws / ".claude").st_file_attributes
    assert attrs & stat.FILE_ATTRIBUTE_HIDDEN

