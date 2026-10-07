"""掃描錄音、判斷開始時間、分組（計畫第 9 節）。

開始時間的判斷順序：
1. 檔名帶時間，例如 `語音 YYMMDD_HHMMSS`、`YYYYMMDD_HHMMSS`，當作開始時間（本機時間）。
2. 檔內中繼資料的 creation_time（UTC）。目前測過的手機存的是結束時間，所以減掉長度；
   其他手機存的是什麼還不知道，標成時間不確定。
3. 檔案修改時間，通常是錄完的時間，也減掉長度。複製檔案時可能變成複製當下，標成時間不確定。

分組：同一天預設是同一場，不自動拆；兩段之間空了 1 小時以上只標出來，由 Claude 問使用者。
不同天的，空了 1 小時以上才拆成兩組；不到 1 小時（例如 23:00 開始、過午夜才結束的會議）算同一組，
過了午夜的時間標「（隔天）」。
間隔和重疊都跟前面所有段落裡最晚的結束時間比，不只跟上一段比。
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".mp4", ".webm", ".aac"}
LONG_GAP = 3600  # 秒
OVERLAP_TOLERANCE = 2  # 秒；檔名時間只到秒，小於這個的重疊當作誤差

FROM_NAME, FROM_META, FROM_MTIME = "檔名", "檔內時間", "檔案修改時間"

_NAME_PATTERNS = [
    # YYYYMMDD_HHMMSS，日期和時間中間可以有 - _ 空白 T，時間中間可以有 - _ . :
    re.compile(r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})[ _T-]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})(?!\d)"),
    # YYMMDD_HHMMSS
    re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?!\d)"),
]


@dataclass
class Recording:
    path: Path
    start: datetime | None = None
    duration: float = 0.0
    source: str = ""
    certain: bool = False
    error: str = ""
    gap_before: float | None = None  # 和前面最晚結束的那段的間隔（秒），負數是重疊
    gap_to_prev: bool = True  # 最晚結束的就是上一段
    flags: list[str] = field(default_factory=list)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.duration)


@dataclass
class Group:
    date: str
    recordings: list[Recording]

    @property
    def long_gaps(self) -> int:
        return sum("long_gap" in r.flags for r in self.recordings)


def time_from_name(name: str) -> datetime | None:
    for pat in _NAME_PATTERNS:
        for m in pat.finditer(name):
            y, mo, d, h, mi, s = (int(x) for x in m.groups())
            if y < 100:
                y += 2000
            try:
                t = datetime(y, mo, d, h, mi, s)
            except ValueError:
                continue
            if 2000 <= t.year <= 2099:
                return t
    return None


def probe(path: Path) -> tuple[float, datetime | None]:
    """回傳（長度秒數、檔內 creation_time 換成本機時間）。讀不到 creation_time 回傳 None。"""
    import av

    with av.open(str(path)) as c:
        dur = c.duration / av.time_base if c.duration else 0.0
        if not dur and c.streams.audio:
            s = c.streams.audio[0]
            dur = float(s.duration * s.time_base) if s.duration else 0.0
        raw = c.metadata.get("creation_time") or (c.streams.audio[0].metadata.get("creation_time") if c.streams.audio else None)
    created = None
    if raw:
        try:
            t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if t.tzinfo is not None and t.year >= 2000:  # 1904、1970 這類是沒填
                created = t.astimezone().replace(tzinfo=None)
        except ValueError:
            pass
    return dur, created


def describe(path: Path, probe_fn=probe) -> Recording:
    rec = Recording(path)
    try:
        rec.duration, created = probe_fn(path)
    except Exception as e:  # 壞掉或不支援的檔案，列出來，不擋其他錄音
        rec.error = f"檔案壞掉或格式不支援（{e.__class__.__name__}）"
        return rec
    if t := time_from_name(path.name):
        rec.start, rec.source, rec.certain = t, FROM_NAME, True
    elif created:
        rec.start, rec.source = created - timedelta(seconds=rec.duration), FROM_META
    else:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        rec.start, rec.source = mtime - timedelta(seconds=rec.duration), FROM_MTIME
    rec.start = rec.start.replace(microsecond=0)
    return rec


def audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS)


def order(recs: list[Recording]) -> list[Recording]:
    """依開始時間排序，算出和前面最晚結束的那段的間隔並加上標記。"""
    recs = sorted((r for r in recs if r.start), key=lambda r: (r.start, r.path.name))
    latest = None  # 前面最晚結束的那段
    for prev, cur in zip([None, *recs], recs):
        cur.flags = [] if cur.certain else ["uncertain"]
        cur.gap_before, cur.gap_to_prev = None, True
        if latest is not None:
            cur.gap_before = (cur.start - latest.end).total_seconds()
            cur.gap_to_prev = latest is prev
            if cur.gap_before >= LONG_GAP:
                cur.flags.append("long_gap")
            elif cur.gap_before < -OVERLAP_TOLERANCE:
                cur.flags.append("overlap")
        if latest is None or cur.end > latest.end:
            latest = cur
    return recs


def splits_here(cur: Recording) -> bool:
    """空了 1 小時以上、而且中間跨過午夜（前面最晚結束的那段和這段不同天），才拆成兩組。"""
    if "long_gap" not in cur.flags:
        return False
    latest_end = cur.start - timedelta(seconds=cur.gap_before)
    return latest_end.date() != cur.start.date()


def group(recs: list[Recording]) -> list[Group]:
    recs = order(recs)
    groups: list[list[Recording]] = []
    for prev, cur in zip([None, *recs], recs):
        if prev is None or splits_here(cur):
            cur.gap_before = None  # 換一組不算間隔
            cur.flags = [f for f in cur.flags if f != "long_gap"]
            groups.append([])
        groups[-1].append(cur)
    return [Group(rs[0].start.date().isoformat(), rs) for rs in groups]


def day_mark(t: datetime, base: date) -> str:
    """跨午夜的會議，時間後面標（隔天）。"""
    days = (t.date() - base).days
    if days <= 0:
        return ""
    return "（隔天）" if days == 1 else f"（第 {days + 1} 天）"


def clock(t: datetime, base: date) -> str:
    return f"{t:%H:%M:%S}{day_mark(t, base)}"


def start_text(t: datetime, base: date) -> str:
    """「14:30:00 開始」；跨午夜時是「00:10:00（隔天）開始」，全形括號後面不空格。"""
    c = clock(t, base)
    return f"{c}開始" if c.endswith("）") else f"{c} 開始"


def fmt_duration(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_gap(sec: float) -> str:
    sec = int(round(abs(sec)))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h} 小時 {m:02d} 分"
    if m:
        return f"{m} 分 {s:02d} 秒"
    return f"{s} 秒"


def gap_text(r: Recording) -> str:
    if r.gap_before is None:
        return ""
    other = "上一段" if r.gap_to_prev else "前面的錄音"
    if "overlap" in r.flags:
        return f"和{other}重疊 {fmt_gap(r.gap_before)}"
    return f"和{other}隔 {fmt_gap(r.gap_before)}"


def to_dict(r: Recording) -> dict:
    d = {"file": r.path.name, "path": str(r.path)}
    if r.error:
        return d | {"error": r.error}
    return d | {
        "start": r.start.isoformat(sep=" "), "end": r.end.replace(microsecond=0).isoformat(sep=" "),
        "duration": round(r.duration, 1), "time_source": r.source, "time_certain": r.certain,
        "gap_before": None if r.gap_before is None else round(r.gap_before), "flags": r.flags,
    }


def scan(folder: Path, probe_fn=probe) -> tuple[list[Group], list[Recording]]:
    """回傳（分組、讀不到的檔案）。"""
    recs = [describe(p, probe_fn) for p in audio_files(folder)]
    return group([r for r in recs if not r.error]), [r for r in recs if r.error]


def report(folder: Path, groups: list[Group], errors: list[Recording]) -> str:
    total = sum(len(g.recordings) for g in groups)
    if not total and not errors:
        return f"「{folder.name}」裡沒有錄音（{folder}）。"
    if not total:
        lines = [f"「{folder.name}」裡的 {len(errors)} 個錄音檔都讀不到："]
    else:
        lines = [f"「{folder.name}」有 {total} 段錄音，依開始時間分成 {len(groups)} 組："]
    for i, g in enumerate(groups, 1):
        base = date.fromisoformat(g.date)
        tag = "（預設：最新的一組）" if i == len(groups) else ""
        total_len = fmt_duration(sum(r.duration for r in g.recordings))
        lines.append(f"\n第 {i} 組：{g.date}，{len(g.recordings)} 段，共 {total_len}{tag}")
        for j, r in enumerate(g.recordings, 1):
            src = f"時間來自{r.source}" + ("" if r.certain else "，不確定")
            parts = [f"  {j}. {r.path.name}", start_text(r.start, base), f"長 {fmt_duration(r.duration)}", src]
            if gap := gap_text(r):
                parts.append(gap)
            lines.append("，".join(parts))
            if "long_gap" in r.flags:
                lines.append("     ↑ 和前面的錄音空了 1 小時以上，要問使用者是不是同一場")
            if "overlap" in r.flags:
                lines.append("     ↑ 和前面的錄音時間重疊，開始時間可能不準")
    if errors and total:
        lines.append("\n讀不到的錄音檔：")
    for r in errors:
        lines.append(f"  {r.path.name}：{r.error}")
    return "\n".join(lines)
