"""minutes new：建會議資料夾、搬錄音、--to、名稱裡的特殊字元。"""
import sys

import pytest
from conftest import make_wav

from minutes import meeting


def test_new_moves_recordings_into_workspace(workspace):
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "語音 261006_100000.wav")
    make_wav(inbox / "語音 261006_100005.wav")
    folder, moved = meeting.create("週會", "2026-10-06", ["語音 261006_100000.wav", "語音 261006_100005.wav"])
    assert folder == workspace / "會議" / "2026-10-06_週會"
    assert sorted(p.name for p in folder.iterdir()) == ["語音 261006_100000.wav", "語音 261006_100005.wav"]
    assert not list(inbox.iterdir())
    assert moved[0].parent == folder


def test_new_with_to_and_full_path(workspace, tmp_path):
    src = make_wav(tmp_path / "別處" / "a.wav")
    folder, _ = meeting.create("專案會議", "2026-10-06", [str(src)], to=str(tmp_path / "專案A" / "會議"))
    assert folder == tmp_path / "專案A" / "會議" / "2026-10-06_專案會議"
    assert (folder / "a.wav").is_file() and not src.exists()


def test_new_does_not_overwrite_existing_folder(workspace):
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "a.wav")
    make_wav(inbox / "b.wav")
    f1, _ = meeting.create("週會", "2026-10-06", ["a.wav"])
    f2, _ = meeting.create("週會", "2026-10-06", ["b.wav"])
    assert f2.name == "2026-10-06_週會_2" and f1 != f2


def test_new_sanitizes_name(workspace):
    make_wav(workspace / "錄音放這裡" / "a.wav")
    folder, _ = meeting.create('Q3 檢討: A/B "測試"?', "2026-10-06", ["a.wav"])
    assert folder.name == "2026-10-06_Q3 檢討： A／B ＂測試＂？"


def test_new_checks_everything_before_moving(workspace):
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "a.wav")
    with pytest.raises(meeting.MeetingError, match="找不到錄音"):
        meeting.create("週會", "2026-10-06", ["a.wav", "不存在.wav"])
    assert (inbox / "a.wav").is_file()
    assert not list((workspace / "會議").iterdir())
    with pytest.raises(meeting.MeetingError, match="日期"):
        meeting.create("週會", "10/6", ["a.wav"])


def test_new_prefers_inbox_and_checks_extension(workspace, tmp_path, monkeypatch):
    make_wav(workspace / "錄音放這裡" / "a.wav")
    make_wav(tmp_path / "cwd" / "a.wav")
    (tmp_path / "cwd" / "筆記.txt").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "cwd")
    _, moved = meeting.create("週會", "2026-10-06", ["a.wav"])
    assert (tmp_path / "cwd" / "a.wav").is_file()  # 目前資料夾那個沒動
    assert not (workspace / "錄音放這裡" / "a.wav").exists()
    with pytest.raises(meeting.MeetingError, match="不是錄音檔"):
        meeting.create("週會", "2026-10-06", ["筆記.txt"])


def test_new_rolls_back_when_move_fails(workspace, monkeypatch):
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "a.wav")
    make_wav(inbox / "b.wav")
    real_move = meeting.shutil.move

    def flaky(src, dst):
        if src.endswith("b.wav"):
            raise PermissionError("檔案被別的程式開著")
        return real_move(src, dst)

    monkeypatch.setattr(meeting.shutil, "move", flaky)
    with pytest.raises(meeting.MeetingError, match="放回原處"):
        meeting.create("週會", "2026-10-06", ["a.wav", "b.wav"])
    assert sorted(p.name for p in inbox.iterdir()) == ["a.wav", "b.wav"]
    assert not list((workspace / "會議").iterdir())


def test_new_rolls_back_when_copy_done_but_delete_fails(workspace, monkeypatch):
    # move 改名失敗時會複製再刪原檔；刪原檔失敗會在會議資料夾留下複本
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "a.wav")
    make_wav(inbox / "b.wav")
    real_move = meeting.shutil.move

    def copy_then_fail(src, dst):
        if src.endswith("b.wav"):
            meeting.shutil.copy2(src, dst)
            raise PermissionError("檔案被別的程式開著")
        return real_move(src, dst)

    monkeypatch.setattr(meeting.shutil, "move", copy_then_fail)
    with pytest.raises(meeting.MeetingError):
        meeting.create("週會", "2026-10-06", ["a.wav", "b.wav"])
    assert sorted(p.name for p in inbox.iterdir()) == ["a.wav", "b.wav"]
    assert not list((workspace / "會議").iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="只有 Windows 開著的檔案不能刪")
def test_new_rolls_back_when_recording_is_open(workspace):
    inbox = workspace / "錄音放這裡"
    make_wav(inbox / "a.wav")
    make_wav(inbox / "b.wav")
    with open(inbox / "b.wav", "rb"):
        with pytest.raises(meeting.MeetingError, match="放回原處"):
            meeting.create("週會", "2026-10-06", ["a.wav", "b.wav"])
    assert sorted(p.name for p in inbox.iterdir()) == ["a.wav", "b.wav"]
    assert not list((workspace / "會議").iterdir())


def test_new_rejects_long_name(workspace):
    make_wav(workspace / "錄音放這裡" / "a.wav")
    with pytest.raises(meeting.MeetingError, match="太長"):
        meeting.create("會" * 51, "2026-10-06", ["a.wav"])
    assert (workspace / "錄音放這裡" / "a.wav").is_file()
