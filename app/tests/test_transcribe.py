"""轉錄流程（用假的轉錄引擎，不需要模型）：合併、續跑、名單和術語、提示文字截斷、顯卡失敗改 CPU。"""
from datetime import datetime

import pytest
from conftest import make_wav

from minutes import merge, transcribe
from minutes import recordings as rc


class FakeEngine:
    def __init__(self, fail_on=None):
        self.device = "cpu"
        self.fallback_reason = ""
        self.calls = []
        self.fail_on = fail_on

    def count_tokens(self, text):
        return len(text)  # 一個字算一個 token

    def run(self, audio, prompt, on_progress):
        self.calls.append((audio.name, prompt))
        if audio.name == self.fail_on:
            raise KeyboardInterrupt  # 模擬轉到一半被中斷
        return [(0.0, 1.5, f"{audio.stem} 第一句"), (61.2, 63.0, "第二句")]


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "2026-10-06_週會"
    make_wav(f / "語音 261006_143000.wav", 2)
    make_wav(f / "語音 261006_143005.wav", 2)
    return f


def run(folder, engine, **kw):
    return transcribe.run(folder, "breeze", "cpu", log=lambda m: None, engine=engine, **kw)


def test_merge_uses_clock_time_and_part_markers(folder):
    data = run(folder, FakeEngine())
    text = (folder / "1_逐字稿.md").read_text(encoding="utf-8")
    assert "## 第 1 段，14:30:00 開始（語音 261006_143000.wav，長 00:02）" in text
    assert "## 第 2 段，14:30:05 開始，和上一段隔 3 秒（語音 261006_143005.wav，長 00:02）" in text
    assert "- [14:30:00] 語音 261006_143000 第一句" in text
    assert "- [14:31:06] 第二句" in text  # 14:30:05 + 61.2 秒
    assert [p["file"] for p in data["parts"]] == ["語音 261006_143000.wav", "語音 261006_143005.wav"]


def test_rerun_skips_finished_parts(folder):
    with pytest.raises(KeyboardInterrupt):
        run(folder, FakeEngine(fail_on="語音 261006_143005.wav"))
    assert (folder / "_暫存" / "語音 261006_143000.wav.轉錄.json").is_file()
    assert not (folder / "_暫存" / "語音 261006_143005.wav.轉錄.json").exists()
    assert not (folder / "1_逐字稿.md").exists()

    engine = FakeEngine()
    run(folder, engine)
    assert [c[0] for c in engine.calls] == ["語音 261006_143005.wav"]

    engine = FakeEngine()
    run(folder, engine)
    assert engine.calls == []  # 全部做過，只重新合併
    assert (folder / "1_逐字稿.md").is_file()


def test_changed_terms_or_model_retranscribe(folder):
    run(folder, FakeEngine())
    (folder / merge.TERMS_FILE).write_text("王經理\n# 註解\n資訊安全\n", encoding="utf-8")
    engine = FakeEngine()
    run(folder, engine)
    assert len(engine.calls) == 2
    assert engine.calls[0][1] == "王經理、資訊安全"


def test_build_prompt_drops_whole_lines_from_the_end():
    terms = ["甲" * 100, "乙" * 100, "丙" * 100]
    prompt, dropped = merge.build_prompt(terms, len)
    assert prompt == "甲" * 100 + "、" + "乙" * 100
    assert dropped == ["丙" * 100]
    assert merge.build_prompt([], len) == (None, [])


def test_empty_folder_and_bad_file(tmp_path):
    with pytest.raises(transcribe.TranscribeError, match="沒有錄音"):
        run(tmp_path, FakeEngine())
    (tmp_path / "壞掉.m4a").write_bytes(b"x")
    with pytest.raises(transcribe.TranscribeError, match="壞掉.m4a"):
        run(tmp_path, FakeEngine())


def test_uncertain_and_overlap_notes_in_transcript(tmp_path):
    a = rc.Recording(tmp_path / "a.m4a", datetime(2026, 10, 6, 9, 0), 600, rc.FROM_NAME, True)
    b = rc.Recording(tmp_path / "b.m4a", datetime(2026, 10, 6, 9, 5), 600, rc.FROM_MTIME, False)
    rc.order([a, b])
    text = merge.render(tmp_path, [(a, []), (b, [(0.0, 1.0, "嗨")])], "breeze", "cuda")
    assert "模型：breeze（顯卡）" in text
    # 說明前面空一行、每條一個項目，Markdown 才不會跟上一句黏成同一段
    assert "方括號裡是時鐘時間，過了午夜的標「（隔天）」。\n\n- 第 2 段的開始時間來自檔案修改時間，不一定準。\n" in text
    assert "- 第 2 段和前面的錄音時間重疊" in text
    assert "（這段沒有聽到說話）" in text


def test_transcript_marks_times_after_midnight(tmp_path):
    a = rc.Recording(tmp_path / "a.m4a", datetime(2026, 10, 6, 23, 0), 3000, rc.FROM_NAME, True)
    b = rc.Recording(tmp_path / "b.m4a", datetime(2026, 10, 7, 0, 30), 600, rc.FROM_NAME, True)
    rc.order([a, b])
    text = merge.render(tmp_path, [(a, [(0.0, 1.0, "開始"), (2940.0, 2941.0, "快結束")]), (b, [(5.0, 6.0, "第二段")])],
                        "breeze", "cpu")
    assert "- [23:00:00] 開始" in text
    assert "- [23:49:00] 快結束" in text
    assert "## 第 2 段，00:30:00（隔天）開始，和上一段隔 40 分 00 秒" in text
    assert "- [00:30:05（隔天）] 第二段" in text


def test_to_traditional_keeps_zhi():
    assert transcribe.to_traditional("每天最多只能收") == "每天最多只能收"
    assert transcribe.to_traditional("这只能这样") == "這只能這樣"
    assert transcribe.to_traditional("两只狗") == "兩隻狗"  # 量詞照轉
    assert transcribe.to_traditional("这个信息") == "這個信息"  # 只轉字形，不換詞彙


def test_breeze_is_not_converted():
    # Breeze 本來就輸出正體，再轉會把「最多只能」改成「最多隻能」
    assert transcribe.Engine("breeze", "cpu", print).simplified is False
    assert transcribe.Engine("turbo", "cpu", print).simplified is True


def test_result_has_device_note(folder):
    assert run(folder, FakeEngine())["device_note"] == "指定用 CPU"
