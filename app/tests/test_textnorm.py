"""textnorm 的單元測試，不需要 GPU。執行（在 app\\ 底下）：uv run pytest"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from textnorm import align, edit_align, int_to_cn, normalize, parse_script, reference_tokens  # noqa: E402


def test_int_to_cn():
    cases = {0: "零", 10: "十", 11: "十一", 40: "四十", 110: "一百一十", 200: "二百", 1005: "一千零五",
             1500: "一千五百", 2300: "二千三百", 10010: "一萬零一十", 860000: "八十六萬"}
    for n, want in cases.items():
        assert int_to_cn(n) == want, (n, int_to_cn(n), want)


def test_normalize_numbers_and_forms():
    assert normalize("11月11日") == normalize("十一月十一日")
    assert normalize("12%") == list("百分之十二")
    assert normalize("1.8%") == list("百分之一點八")
    assert normalize("兩個") == normalize("2個")
    assert normalize("1,500件") == list("一千五百件")
    assert normalize("这并不容易", fold_simplified=True) == list("這並不容易")
    # 預設不簡轉繁，轉換本身的錯才算得出來
    assert normalize("最多隻能") != normalize("最多只能")


def test_normalize_english():
    assert normalize("用 Landing Page 看") == ["用", "landingpage", "看"]
    assert normalize("KPI是") == ["kpi", "是"]


def test_align_counts():
    ops = edit_align(list("我不同意"), list("我同意了"))
    kinds = [op for op, _, _ in ops]
    assert kinds.count("del") == 1 and kinds.count("ins") == 1 and kinds.count("eq") == 3


def test_align_keeps_key_contiguous_when_model_repeats():
    # 模型把下一句重複三次；關鍵詞「四日」要配到原本的位置，不能被分散到副本上
    ref = list("訂在四日好那我三日做完四號測")
    hyp = list("訂在四日") + list("好那我三日做完四號測") * 3
    ops = align(ref, hyp)
    key = [op for op, i, _ in ops if i in (2, 3)]
    assert key == ["eq", "eq"]
    assert sum(op == "ins" for op, _, _ in ops) == 20


def test_colloquial_wan():
    assert normalize("4萬8") == normalize("48,000") == list("四萬八千")
    assert normalize("86萬") == list("八十六萬")


def test_key_number_with_extra_digit_is_wrong(tmp=Path(__file__).parent / "_tmp_script2.txt"):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from evaluate import score
    tmp.write_text("A: 預計開{40|num}分鐘，{9|num}折\n", encoding="utf-8")
    try:
        ref, line_of, keys = reference_tokens(parse_script(tmp))
    finally:
        tmp.unlink()

    def keys_ok(text):
        hyp = {"model": "t", "device": "cpu", "elapsed": 0, "segments": [{"start": 0, "text": text}]}
        return [k["ok"] for k in score(hyp, ref, line_of, keys, {1: 0.0})["keys"]]

    assert keys_ok("預計開40分鐘，9折") == [True, True]
    assert keys_ok("預計開140分鐘，19折") == [False, False]
    assert keys_ok("預計開四十分鐘，九折") == [True, True]


def test_parse_and_keys(tmp=Path(__file__).parent / "_tmp_script.txt"):
    tmp.write_text("# 註解\nA: 我{不|neg}去，{3|num}點見\n", encoding="utf-8")
    try:
        lines = parse_script(tmp)
        assert lines[0].text == "我不去，3點見"
        ref, line_of, keys = reference_tokens(lines)
        assert ref == list("我不去三點見")
        assert [(a, b, c) for a, b, c, _, _ in keys] == [(1, 2, "neg"), (3, 4, "num")]
    finally:
        tmp.unlink()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
