"""錄音開始時間判斷、排序、分組、間隔和重疊標記。"""
import os
from datetime import datetime, timedelta
from pathlib import Path

from conftest import make_wav

from minutes import recordings as rc


def fake_probe(table):
    """table：檔名 → (長度秒數, 檔內時間或 None)"""
    return lambda p: table[p.name]


def rec(name, start, dur, certain=True):
    return rc.Recording(Path(name), start=start, duration=dur, source=rc.FROM_NAME, certain=certain)


def test_time_from_name_formats():
    assert rc.time_from_name("語音 261006_153008.m4a") == datetime(2026, 10, 6, 15, 30, 8)
    assert rc.time_from_name("20261006_153008.m4a") == datetime(2026, 10, 6, 15, 30, 8)
    assert rc.time_from_name("錄音 2026-10-06 15.30.08.mp3") == datetime(2026, 10, 6, 15, 30, 8)
    assert rc.time_from_name("會議.m4a") is None
    assert rc.time_from_name("261399_999999.m4a") is None  # 不是合法日期


def test_describe_prefers_name_then_meta_then_mtime(tmp_path):
    end = datetime(2026, 10, 6, 16, 0, 0)
    probe = fake_probe({"語音 261006_153008.m4a": (60, end), "b.m4a": (60, end), "c.m4a": (60, None)})
    a = rc.describe(tmp_path / "語音 261006_153008.m4a", probe)
    assert (a.start, a.source, a.certain) == (datetime(2026, 10, 6, 15, 30, 8), rc.FROM_NAME, True)

    b = rc.describe(tmp_path / "b.m4a", probe)
    # 檔內時間當作結束時間，減掉長度；不確定
    assert (b.start, b.source, b.certain) == (end - timedelta(seconds=60), rc.FROM_META, False)

    c_path = tmp_path / "c.m4a"
    c_path.write_bytes(b"x")
    mtime = datetime(2026, 10, 5, 9, 0, 0)
    os.utime(c_path, (mtime.timestamp(), mtime.timestamp()))
    c = rc.describe(c_path, probe)
    assert (c.start, c.source, c.certain) == (mtime - timedelta(seconds=60), rc.FROM_MTIME, False)


def test_describe_unreadable_file(tmp_path):
    def boom(p):
        raise ValueError("bad")
    r = rc.describe(tmp_path / "壞掉.m4a", boom)
    assert r.error and r.start is None


def test_group_by_day_and_default_latest():
    recs = [
        rec("d1a.m4a", datetime(2026, 10, 6, 9, 0), 600),
        rec("d2a.m4a", datetime(2026, 10, 7, 14, 0), 600),
        rec("d1b.m4a", datetime(2026, 10, 6, 9, 10, 3), 600),
        rec("d2b.m4a", datetime(2026, 10, 7, 14, 10, 5), 60),
    ]
    groups = rc.group(recs)
    assert [g.date for g in groups] == ["2026-10-06", "2026-10-07"]
    assert [r.path.name for r in groups[0].recordings] == ["d1a.m4a", "d1b.m4a"]
    assert groups[0].recordings[0].gap_before is None
    assert groups[0].recordings[1].gap_before == 3
    assert groups[1].recordings[0].gap_before is None  # 換一天不算間隔
    assert groups[1].recordings[1].gap_before == 5


def test_same_day_long_gap_is_flagged_not_split():
    recs = [rec("a.m4a", datetime(2026, 10, 6, 9, 0), 1800),
            rec("b.m4a", datetime(2026, 10, 6, 10, 30), 600)]
    groups = rc.group(recs)
    assert len(groups) == 1
    assert groups[0].recordings[1].flags == ["long_gap"]
    assert groups[0].long_gaps == 1
    assert "1 小時以上" in rc.report(Path("錄音放這裡"), groups, [])


def test_three_hour_meeting_stays_one_group():
    recs = [rec(f"{i}.m4a", datetime(2026, 10, 6, 9, 0) + timedelta(hours=i), 3590) for i in range(3)]
    groups = rc.group(recs)
    assert len(groups) == 1 and groups[0].long_gaps == 0


def test_overlap_flag_and_uncertain_flag():
    recs = [rec("a.m4a", datetime(2026, 10, 6, 9, 0), 600),
            rec("b.m4a", datetime(2026, 10, 6, 9, 5), 600, certain=False)]
    b = rc.group(recs)[0].recordings[1]
    assert b.flags == ["uncertain", "overlap"]
    assert rc.gap_text(b) == "和上一段重疊 5 分 00 秒"


def test_fmt():
    assert rc.fmt_duration(65) == "01:05"
    assert rc.fmt_duration(3725) == "1:02:05"
    assert rc.fmt_gap(3) == "3 秒"
    assert rc.fmt_gap(65) == "1 分 05 秒"
    assert rc.fmt_gap(3900) == "1 小時 05 分"


def test_scan_real_wav_files(tmp_path):
    inbox = tmp_path / "錄音放這裡"
    make_wav(inbox / "語音 261006_100000.wav", 2)
    make_wav(inbox / "語音 261006_100005.wav", 1)
    (inbox / "筆記.txt").write_text("不是錄音", encoding="utf-8")
    (inbox / "壞掉.m4a").write_bytes(b"not audio")
    groups, errors = rc.scan(inbox)
    assert len(groups) == 1
    a, b = groups[0].recordings
    assert round(a.duration) == 2
    assert b.gap_before == 3
    assert [e.path.name for e in errors] == ["壞掉.m4a"]
    text = rc.report(inbox, groups, errors)
    assert "壞掉.m4a：檔案壞掉或格式不支援（" in text and "）（" not in text


def test_only_bad_files_report():
    bad = rc.Recording(Path("壞掉.m4a"), error="檔案壞掉或格式不支援（ValueError）")
    text = rc.report(Path("錄音放這裡"), [], [bad])
    assert "0 段" not in text and "都讀不到" in text


def test_meeting_across_midnight_is_one_group():
    # 23:00 開始，第二段隔天 00:30 結束，中間不到 1 小時
    recs = [rec("a.m4a", datetime(2026, 10, 6, 23, 0), 3000),
            rec("b.m4a", datetime(2026, 10, 6, 23, 55), 2100)]
    groups = rc.group(recs)
    assert len(groups) == 1 and groups[0].date == "2026-10-06"
    assert groups[0].recordings[1].end == datetime(2026, 10, 7, 0, 30)
    recs = [rec("a.m4a", datetime(2026, 10, 6, 23, 0), 3000),
            rec("b.m4a", datetime(2026, 10, 7, 0, 10), 1200)]
    groups = rc.group(recs)
    assert len(groups) == 1 and groups[0].recordings[1].gap_before == 1200
    assert "00:10:00（隔天）開始" in rc.report(Path("錄音放這裡"), groups, [])


def test_different_days_one_hour_apart_split():
    recs = [rec("a.m4a", datetime(2026, 10, 6, 22, 0), 3000),
            rec("b.m4a", datetime(2026, 10, 7, 0, 0), 600)]
    groups = rc.group(recs)
    assert [g.date for g in groups] == ["2026-10-06", "2026-10-07"]
    assert groups[1].recordings[0].gap_before is None and "long_gap" not in groups[1].recordings[0].flags


def test_overlap_compares_with_latest_end():
    # a 很長，b 在 a 裡面，c 跟 b 不重疊但跟 a 重疊
    recs = [rec("a.m4a", datetime(2026, 10, 6, 9, 0), 3600),
            rec("b.m4a", datetime(2026, 10, 6, 9, 10), 600),
            rec("c.m4a", datetime(2026, 10, 6, 9, 30), 600)]
    a, b, c = rc.group(recs)[0].recordings
    assert "overlap" in b.flags and "overlap" in c.flags
    assert c.gap_before == -1800
    assert rc.gap_text(c) == "和前面的錄音重疊 30 分 00 秒"
