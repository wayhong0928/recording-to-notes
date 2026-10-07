"""minutes 指令的入口。只有 Claude 和安裝檔會打這個指令，給使用者看的訊息都用中文。

結束代碼：0 成功、1 失敗或檢查有問題、2 參數錯誤（argparse）。
--json 放在子指令前後都可以。加 --json 時，最後的結果印到 stdout，過程的訊息印到 stderr。
"""
import argparse
import json
import platform
import re
import sys
from pathlib import Path

from minutes import __version__

FAILED = 1


# argparse 的錯誤訊息是英文，常見的幾種換成中文
_ARG_ERRORS = [
    (r"the following arguments are required: (.+)", r"缺少參數：\1"),
    (r"argument (\S+): invalid choice: '?([^' ]+)'? \(choose from (.+)\)", r"\1 不能用「\2」，可以用：\3"),
    (r"argument (\S+): expected one argument", r"\1 後面要接一個值"),
    (r"unrecognized arguments: (.+)", r"不認得的參數：\1"),
    (r"argument (\S+): ignored explicit argument '(.*)'", r"\1 後面不接值（收到「\2」）"),
]


def zh_error(message: str) -> str:
    for pat, repl in _ARG_ERRORS:
        if re.fullmatch(pat, message):
            return re.sub(pat, repl, message)
    return f"參數錯誤：{message}"


class Parser(argparse.ArgumentParser):
    json_argv = False  # 指令裡有 --json：錯誤訊息也印成 JSON

    def error(self, message: str):
        text = zh_error(message)
        if self.json_argv:
            print(json.dumps({"ok": False, "error": text}, ensure_ascii=False))
        else:
            print(text + "\n用 minutes -h 看用法。", file=sys.stderr)
        sys.exit(2)


def build_parser(json_argv: bool = False) -> argparse.ArgumentParser:
    ap = Parser(prog="minutes", description="會議紀錄小幫手")
    ap.json_argv = json_argv
    ap.add_argument("--json", action="store_true", help="印給 skill 讀的 JSON")
    # 子指令也收 --json；預設 SUPPRESS，才不會把寫在前面的 --json 蓋回 False
    common = Parser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="印給 skill 讀的 JSON")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="指令", parser_class=Parser)

    def add(name: str, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help, parents=[common])
        p.json_argv = json_argv
        return p

    p = add("check", "檢查環境，只檢查不安裝")
    p.add_argument("--before-install", action="store_true", help="安裝前的檢查")
    p.add_argument("--quick", action="store_true", help="只看 skill 每次都會用到的部分")

    p = add("install", "安裝（由安裝檔呼叫）")
    p.add_argument("--yes", action="store_true", help="不等按 Enter 直接安裝")
    p.add_argument("--no-shortcut", action="store_true", help="不建桌面捷徑（測試用）")
    p.add_argument("--no-trial", action="store_true", help="不試跑（測試用）")
    add("scan", "列出「錄音放這裡」的錄音並依開始時間分組")

    p = add("new", "建會議資料夾，把這場的錄音搬進去")
    p.add_argument("name", help="會議名稱")
    p.add_argument("recordings", nargs="+", help="這場的錄音（完整路徑，或「錄音放這裡」裡的檔名）")
    p.add_argument("--date", required=True, help="會議日期 YYYY-MM-DD")
    p.add_argument("--to", help="會議資料夾放的位置，沒給就放工作區的「會議」")

    p = add("transcribe", "轉錄會議資料夾裡的錄音並合併成逐字稿")
    p.add_argument("folder", help="會議資料夾")
    p.add_argument("--model", choices=["breeze", "turbo", "large-v3"], default="breeze")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")

    p = add("word-status", "最新一版 Word 產生後有沒有被改過")
    p.add_argument("folder")

    p = add("render", "md 轉 docx 並打開 Word")
    p.add_argument("folder")
    p.add_argument("--no-open", action="store_true", help="產生後不打開 Word（測試和 CI 用）")

    add("version", "版本、預設模型、轉錄裝置")
    return ap


def emit(args, data: dict, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)


def fail(args, message: str) -> int:
    emit(args, {"ok": False, "error": message}, message)
    return FAILED


def cmd_version(args) -> int:
    from minutes import check, models

    device, why = check.pick_device("auto")
    m = models.DEFAULT
    info = {"ok": True, "version": __version__, "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "model": m, "model_downloaded": models.is_downloaded(m), "device": device, "device_note": why}
    text = (f"會議紀錄小幫手 {info['version']}（Python {info['python']}，{info['platform']}）\n"
            f"預設模型：{m}（{'已下載' if info['model_downloaded'] else '還沒下載'}）\n"
            f"轉錄裝置：{why}")
    emit(args, info, text)
    return 0


def cmd_check(args) -> int:
    from minutes import check

    items = check.run(quick=args.quick, before_install=args.before_install)
    data = check.as_json(items)
    emit(args, data, check.report(items))
    return 0 if data["ok"] else FAILED


def cmd_scan(args) -> int:
    from minutes import paths, recordings

    inbox = paths.inbox()
    if not inbox.is_dir():
        return fail(args, f"找不到「{paths.INBOX}」資料夾：{inbox}。重跑安裝檔會補建工作區。")
    groups, errors = recordings.scan(inbox)
    data = {
        "ok": True, "inbox": str(inbox),
        "groups": [{"date": g.date, "default": i == len(groups) - 1, "long_gaps": g.long_gaps,
                    "total_duration": round(sum(r.duration for r in g.recordings), 1),
                    "recordings": [recordings.to_dict(r) for r in g.recordings]}
                   for i, g in enumerate(groups)],
        "unreadable": [recordings.to_dict(r) for r in errors],
    }
    emit(args, data, recordings.report(inbox, groups, errors))
    return 0


def cmd_new(args) -> int:
    from minutes import meeting

    try:
        folder, moved = meeting.create(args.name, args.date, args.recordings, args.to)
    except (meeting.MeetingError, OSError) as e:
        return fail(args, f"建會議資料夾失敗：{e}")
    data = {"ok": True, "folder": str(folder), "recordings": [str(p) for p in moved]}
    text = f"會議資料夾：{folder}\n搬進去的錄音：" + "、".join(p.name for p in moved)
    emit(args, data, text)
    return 0


def cmd_transcribe(args) -> int:
    from minutes import transcribe

    log = (lambda msg: print(msg, file=sys.stderr, flush=True)) if args.json else (lambda msg: print(msg, flush=True))
    try:
        data = transcribe.run(Path(args.folder), args.model, args.device, log=log)
    except transcribe.TranscribeError as e:
        return fail(args, str(e))
    except Exception as e:  # 下載模型、解碼這類錯誤，給 Claude 看得懂的一行，細節照印
        return fail(args, f"轉錄失敗（{e.__class__.__name__}）：{e}。做完的段落已存，修好後重跑會接著做。")
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    return 0


def cmd_word_status(args) -> int:
    from minutes import render

    folder = Path(args.folder)
    if not folder.is_dir():
        return fail(args, f"找不到會議資料夾：{folder}")
    st = render.status(folder)
    emit(args, {"ok": True, **st}, render.status_text(st))
    return 0


def cmd_render(args) -> int:
    from minutes import render

    try:
        result = render.render(Path(args.folder), open_word=not args.no_open)
    except (render.RenderError, OSError) as e:
        return fail(args, f"產生 Word 失敗：{e}")
    emit(args, result, render.render_text(result))
    return 0


def cmd_install(args) -> int:
    from minutes import installer

    return installer.install(yes=args.yes, shortcut=not args.no_shortcut, trial=not args.no_trial)


COMMANDS = {"install": cmd_install, "version": cmd_version, "check": cmd_check, "scan": cmd_scan, "new": cmd_new,
            "transcribe": cmd_transcribe, "word-status": cmd_word_status, "render": cmd_render}


def main(argv: list[str] | None = None) -> int:
    # 被 Claude Code 這類程式接管輸出時，Windows 預設用 cp950，中文會亂碼
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser("--json" in argv).parse_args(argv)

    return COMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
