"""測試集腳本解析、文字正規化、逐字對齊。

計分單位：中文一字一個 token，英文連續字母算一個 token（先去空白，所以 "landing page" 是一個 token）。
數字統一轉成中文讀法再比，例如「11月」和「十一月」視為相同。
"""
import difflib
import re
from dataclasses import dataclass, field

import opencc

KEY_RE = re.compile(r"\{([^|{}]+)\|(\w+)\}")
NUM_RE = re.compile(r"(\d+(?:\.\d+)?)([%％]?)")
DIGITS = "零一二三四五六七八九"
NEGATIONS = set("不沒")  # 「別」「未」常見於非否定用法（別的、未來），不列入
NUMERAL_CHARS = set("零一二三四五六七八九十百千萬點")
COLLOQUIAL_WAN_RE = re.compile(r"(\d+)萬(\d)(?![\d萬千百])")  # 4萬8 = 48000
_s2tw = opencc.OpenCC("s2tw")


@dataclass
class Line:
    n: int
    speaker: str
    text: str                     # 去掉標記後的台詞（給 TTS 與參考答案）
    pieces: list = field(default_factory=list)  # [(文字, 類別或 None)]


def parse_script(path) -> list[Line]:
    lines = []
    for raw in open(path, encoding="utf-8"):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        speaker, body = raw.split(":", 1)
        body = body.strip()
        pieces, pos = [], 0
        for m in KEY_RE.finditer(body):
            if m.start() > pos:
                pieces.append((body[pos:m.start()], None))
            pieces.append((m.group(1), m.group(2)))
            pos = m.end()
        if pos < len(body):
            pieces.append((body[pos:], None))
        lines.append(Line(len(lines) + 1, speaker.strip(), "".join(p for p, _ in pieces), pieces))
    return lines


def _under_10k(n: int, leading: bool) -> str:
    s, zero = "", False
    for unit_val, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        d = n // unit_val % 10
        if d == 0:
            zero = bool(s)
            continue
        if zero:
            s, zero = s + "零", False
        s += "十" if (unit == "十" and d == 1 and not s and leading) else DIGITS[d] + unit
    return s


def int_to_cn(n: int) -> str:
    if n == 0:
        return "零"
    if n >= 10**8:
        return "".join(DIGITS[int(c)] for c in str(n))
    hi, lo = divmod(n, 10000)
    if hi == 0:
        return _under_10k(lo, True)
    s = _under_10k(hi, True) + "萬"
    if lo == 0:
        return s
    return s + ("零" if lo < 1000 else "") + _under_10k(lo, False)


def _num_to_cn(m: re.Match) -> str:
    num, pct = m.group(1), m.group(2)
    whole, _, frac = num.partition(".")
    s = int_to_cn(int(whole)) + ("點" + "".join(DIGITS[int(c)] for c in frac) if frac else "")
    return ("百分之" + s) if pct else s


def normalize(text: str, fold_simplified: bool = False) -> list[str]:
    """fold_simplified：先簡轉繁再比。評測預設不轉，因為轉錄結果本來就該是正體，
    兩邊都轉會把轉換本身的錯（最多只能→最多隻能）抵銷掉，分數看不出來。"""
    t = (_s2tw.convert(text) if fold_simplified else text).lower()
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = COLLOQUIAL_WAN_RE.sub(lambda m: str(int(m.group(1)) * 10000 + int(m.group(2)) * 1000), t)
    t = NUM_RE.sub(_num_to_cn, t)
    t = t.replace("兩", "二").replace("〇", "零")
    t = re.sub(r"[^a-z一-鿿]", "", t)
    return re.findall(r"[a-z]+|[一-鿿]", t)


def reference_tokens(lines: list[Line]):
    """回傳參考 token 列、每個 token 屬於第幾行、關鍵資訊區間 [(起, 迄, 類別, 原文, 行號)]。"""
    tokens, line_of, keys = [], [], []
    for ln in lines:
        for text, cat in ln.pieces:
            toks = normalize(text)
            if cat:
                keys.append((len(tokens), len(tokens) + len(toks), cat, text, ln.n))
            tokens += toks
            line_of += [ln.n] * len(toks)
    return tokens, line_of, keys


def align(ref: list[str], hyp: list[str]):
    """先用 difflib 錨定最長的相同片段，空隙裡再做最小編輯距離對齊。

    純編輯距離在模型重複段落時，成本相同的對齊方式很多，可能把一個關鍵詞的字分散配到不同副本，
    錨定後配對會留在連續的位置。回傳 [(op, ref_i, hyp_j)]，op 為 eq／sub／del／ins。
    """
    ops = []
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ops += [("eq", i1 + k, j1 + k) for k in range(i2 - i1)]
        else:
            ops += [(op, None if i is None else i + i1, None if j is None else j + j1)
                    for op, i, j in edit_align(ref[i1:i2], hyp[j1:j2])]
    return ops


def edit_align(ref: list[str], hyp: list[str]):
    """最小編輯距離對齊，回傳 [(op, ref_i, hyp_j)]。"""
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    back = [[2] * (m + 1)]  # 0=對角 1=上(del) 2=左(ins)
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        row = [1] + [0] * m
        r = ref[i - 1]
        for j in range(1, m + 1):
            diag = prev[j - 1] + (r != hyp[j - 1])
            up = prev[j] + 1
            left = cur[j - 1] + 1
            if diag <= up and diag <= left:
                cur[j], row[j] = diag, 0
            elif up <= left:
                cur[j], row[j] = up, 1
            else:
                cur[j], row[j] = left, 2
        back.append(row)
        prev = cur
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        b = back[i][j] if i > 0 and j > 0 else (1 if i > 0 else 2)
        if b == 0:
            ops.append(("eq" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif b == 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    return ops[::-1]
