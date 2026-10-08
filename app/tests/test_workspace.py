import hashlib
import json
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
    assert not list(ws.glob("*.舊.md"))


def test_blank_template_at_workspace_root(tmp_path):
    ws = tmp_path / "會議紀錄"
    result = wsp.setup(ws, MINUTES)
    blank = ws / wsp.BLANK
    assert blank.read_bytes() == (paths.templates() / "content" / wsp.BLANK).read_bytes()
    assert str(blank) in result["files"]


def test_rerun_backs_up_edited_blank_template(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    (ws / wsp.BLANK).write_text("加了主席欄的範本", encoding="utf-8")

    wsp.setup(ws, MINUTES)

    assert (ws / "會議紀錄範本.舊.md").read_text(encoding="utf-8") == "加了主席欄的範本"
    assert (ws / wsp.BLANK).read_bytes() == (paths.templates() / "content" / wsp.BLANK).read_bytes()


def test_backups_listed_in_result(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    (skill_dir(ws) / "整理規則.md").write_text("使用者自己改的規則", encoding="utf-8")
    (ws / wsp.BLANK).write_text("加了主席欄的範本", encoding="utf-8")

    result = wsp.setup(ws, MINUTES)

    assert sorted(result["backups"]) == sorted([str(skill_dir(ws) / "整理規則.舊.md"), str(ws / "會議紀錄範本.舊.md")])
    assert wsp.setup(ws, MINUTES)["backups"] == []


def test_unedited_previous_install_makes_no_backup(tmp_path):
    """上一版裝的、使用者沒改過：.installed.json 記的雜湊對得上，換新版不備份。"""
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    rules = skill_dir(ws) / "整理規則.md"
    rules.write_text("上一版的整理規則", encoding="utf-8")
    manifest = skill_dir(ws) / wsp.MANIFEST
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["整理規則.md"] = wsp.digest(rules)
    manifest.write_text(json.dumps(record), encoding="utf-8")

    result = wsp.setup(ws, MINUTES)

    assert result["backups"] == []
    assert not (skill_dir(ws) / "整理規則.舊.md").exists()
    assert rules.read_bytes() == (paths.templates() / "content" / "整理規則.md").read_bytes()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_unedited_release_without_manifest_makes_no_backup(tmp_path, monkeypatch, newline):
    """v0.2.0 以前裝的沒有 .installed.json：內容等於發布過的版本就不備份。"""
    old = "v0.2.0 的整理規則\n第二行\n"
    released = {**wsp.RELEASED_SHA256, "整理規則.md": {hashlib.sha256(old.encode("utf-8")).hexdigest()}}
    monkeypatch.setattr(wsp, "RELEASED_SHA256", released)
    ws = tmp_path / "會議紀錄"
    skill_dir(ws).mkdir(parents=True)
    (skill_dir(ws) / "整理規則.md").write_bytes(old.replace("\n", newline).encode("utf-8"))

    result = wsp.setup(ws, MINUTES)

    assert result["backups"] == []
    assert not (skill_dir(ws) / "整理規則.舊.md").exists()


def test_line_endings_only_is_not_an_edit(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    rules = skill_dir(ws) / "整理規則.md"
    # checkout 出來的公版可能是 LF 也可能是 CRLF（Windows 的 autocrlf），換成另一種
    data = rules.read_bytes()
    rules.write_bytes(data.replace(b"\r\n", b"\n") if b"\r\n" in data else data.replace(b"\n", b"\r\n"))

    assert wsp.setup(ws, MINUTES)["backups"] == []


@pytest.mark.parametrize("broken", ["不是 JSON", "[]", "null", "{}"])
def test_broken_manifest_still_backs_up_edits(tmp_path, broken):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    (skill_dir(ws) / "整理規則.md").write_text("使用者自己改的規則", encoding="utf-8")
    (skill_dir(ws) / wsp.MANIFEST).write_text(broken, encoding="utf-8")

    result = wsp.setup(ws, MINUTES)

    assert result["backups"] == [str(skill_dir(ws) / "整理規則.舊.md")]


def test_manifest_records_installed_files(tmp_path):
    ws = tmp_path / "會議紀錄"
    wsp.setup(ws, MINUTES)
    record = json.loads((skill_dir(ws) / wsp.MANIFEST).read_text(encoding="utf-8"))
    content = paths.templates() / "content"
    assert record == {name: wsp.digest(content / name) for name in (*wsp.CONTENT_FILES, wsp.BLANK)}


V020_FORMAT = """<!-- 〔〕是要換成實際內容的地方；括號裡的「有才寫」是說明，不要照抄。會議名稱以外的欄位留空，使用者自己填（會議時間的格式是 yyyy/mm/dd hh:mm ~ hh:mm） -->

專案名稱：
會議名稱：
會議地點：
會議時間：
與會人員：
記錄人：

## 會議內容

1. 〔議題一〕
2. 〔議題二〕

## 決議事項

1. …

## 討論事項

〔議題一〕
1. 〔客戶名稱〕詢問：…
   我方回覆：…
   結論：…（或「後續：…」，有才寫）

〔議題二〕
2. …（編號整份連續）
"""


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_unedited_legacy_format_is_removed(tmp_path, newline):
    ws = tmp_path / "會議紀錄"
    skill_dir(ws).mkdir(parents=True)
    (skill_dir(ws) / wsp.LEGACY).write_bytes(V020_FORMAT.replace("\n", newline).encode("utf-8"))

    wsp.setup(ws, MINUTES)

    assert not (skill_dir(ws) / wsp.LEGACY).exists()
    assert not (skill_dir(ws) / "問答式.舊.md").exists()


def test_edited_legacy_format_is_backed_up(tmp_path):
    ws = tmp_path / "會議紀錄"
    skill_dir(ws).mkdir(parents=True)
    (skill_dir(ws) / wsp.LEGACY).write_text("使用者改過的問答式", encoding="utf-8")

    wsp.setup(ws, MINUTES)

    assert not (skill_dir(ws) / wsp.LEGACY).exists()
    assert (skill_dir(ws) / "問答式.舊.md").read_text(encoding="utf-8") == "使用者改過的問答式"


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

