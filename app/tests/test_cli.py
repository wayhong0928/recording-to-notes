"""minutes 指令：scan、new 的 JSON 輸出和結束代碼。"""
import json

import pytest

from conftest import make_wav

from minutes.cli import main


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_scan_two_days_two_groups(workspace, capsys):
    inbox = workspace / "錄音放這裡"
    for name in ("語音 261006_100000.wav", "語音 261006_100005.wav", "語音 261007_140000.wav", "語音 261007_160000.wav"):
        make_wav(inbox / name)
    assert main(["scan", "--json"]) == 0
    data = out_json(capsys)
    assert [g["date"] for g in data["groups"]] == ["2026-10-06", "2026-10-07"]
    assert [g["default"] for g in data["groups"]] == [False, True]
    assert data["groups"][1]["long_gaps"] == 1
    assert data["groups"][1]["recordings"][1]["flags"] == ["long_gap"]

    assert main(["scan"]) == 0
    text = capsys.readouterr().out
    assert "分成 2 組" in text and "預設：最新的一組" in text


def test_scan_without_workspace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINUTES_WORKSPACE", str(tmp_path / "沒有"))
    assert main(["--json", "scan"]) == 1
    assert out_json(capsys)["ok"] is False


def test_new_json(workspace, capsys):
    make_wav(workspace / "錄音放這裡" / "a.wav")
    assert main(["new", "週會", "a.wav", "--date", "2026-10-06", "--json"]) == 0
    data = out_json(capsys)
    assert data["folder"].endswith("2026-10-06_週會")
    assert main(["new", "週會", "a.wav", "--date", "2026-10-06", "--json"]) == 1  # 已經搬走了
    assert "找不到錄音" in out_json(capsys)["error"]


def test_version_json_has_ok(capsys):
    assert main(["version", "--json"]) == 0
    assert out_json(capsys)["ok"] is True


def test_argument_errors_in_chinese(capsys):
    with pytest.raises(SystemExit) as e:
        main(["new", "週會", "--json"])
    assert e.value.code == 2
    assert out_json(capsys) == {"ok": False, "error": "缺少參數：recordings, --date"}
    with pytest.raises(SystemExit):
        main(["transcribe", "x", "--model", "foo"])
    err = capsys.readouterr().err
    assert "--model 不能用「foo」" in err and "invalid" not in err
