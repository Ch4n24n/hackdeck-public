#!/usr/bin/python3 -I
"""hackdeck の画面を、隔離した tmux で順に開いて文字で記録し、あとで比べる（作り替えの前後で、見た目が変わっていないかを見る）。

  python3 -I tests/ui_snapshot.py record <出力.json>
  python3 -I tests/ui_snapshot.py compare <記録.json>

試しの環境は tests/snapshot.py と同じ（偽の HOME・tmux の置き場所も別）。本物の tmux サーバー・ペインには触らない。
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snapshot  # noqa: E402

SOCK = "hdsnap"
# (名前, 送るキー) の並び。キーを送ったあと、画面を記録する。案件のセッションの中（HACK_ROOT あり）
STEPS = [("最初の画面", []), ("資格情報", ["Tab"]), ("netexec の一覧", ["C-n"]), ("資格情報に戻る", ["C-n"]),
         ("環境", ["Tab"]), ("案件", ["Tab"]), ("設定", ["Tab"]), ("設定の項目を開く", ["Enter"]),
         ("設定に戻る", ["Escape"]), ("コマンドに戻る", ["Tab"]), ("履歴", ["C-r"]), ("履歴から戻る", ["C-r"]),
         ("変数の画面", ["Enter"]), ("次の変数", ["Enter"])]
# 案件のセッションの外（HACK_ROOT なし）。タブは案件と設定だけ
OUTSIDE = [("外: 最初の画面", []), ("外: 設定", ["Tab"]), ("外: 案件に戻る", ["Tab"]), ("外: 新しい案件の名前", ["n", "e", "w"])]


def tm(env, *args):
    return subprocess.run(["tmux", "-L", SOCK, *args], env=env, capture_output=True, text=True)


def run_steps(env, t, cwd, steps, res, out):
    """隔離した tmux のペインで hackdeck ui を開き、steps のキーを送って画面を記録する。閉じたあとの出力も"""
    exports = " ".join(f"{k}='{v}'" for k, v in env.items())
    unset = "" if "HACK_ROOT" in env else "unset HACK_ROOT; "
    tm(env, "send-keys", "-t", "keep", f"{unset}export {exports}; cd '{cwd}'; clear; hackdeck ui > {out}", "Enter")
    time.sleep(3)
    for name, keys in steps:
        for k in keys:
            tm(env, "send-keys", "-t", "keep", k)
            time.sleep(0.4)
        time.sleep(2)
        lines = tm(env, "capture-pane", "-p", "-t", "keep").stdout.splitlines()
        res[name] = [l.rstrip() for l in lines]
    tm(env, "send-keys", "-t", "keep", "C-g")
    time.sleep(1)


def collect():
    t = Path(tempfile.mkdtemp(prefix="hackdeck-ui-"))
    env, work = snapshot.build(t)
    env = {k: v for k, v in env.items() if k not in ("COLUMNS", "LINES")}
    res = {}
    try:
        sock = tm(env, "-f", "/dev/null", "new-session", "-d", "-s", "keep", "-x", "238", "-y", "53", "-c", str(work),
                  "bash --norc --noprofile")
        path = tm(env, "display", "-p", "#{socket_path}").stdout.strip()
        if not path.startswith(str(t)):
            raise SystemExit(f"tmux の置き場所が隔離されていない: {path} {sock.stderr}")
        run_steps(env, t, work, STEPS, res, t / "out.txt")
        res["閉じたあとの出力"] = [(t / "out.txt").read_text(encoding="utf-8") if (t / "out.txt").exists() else None]
        outside = {k: v for k, v in env.items() if k != "HACK_ROOT"}
        run_steps(outside, t, t, OUTSIDE, res, t / "out2.txt")
    finally:
        tm(env, "kill-server")
        shutil.rmtree(t, ignore_errors=True)
    return json.loads(json.dumps(res, ensure_ascii=False).replace(str(t), "<T>"))


def main(argv):
    if len(argv) != 2 or argv[0] not in ("record", "compare"):
        print(__doc__)
        return 2
    now = collect()
    if argv[0] == "record":
        Path(argv[1]).write_text(json.dumps(now, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"記録した: {len(now)} 画面 → {argv[1]}")
        return 0
    old = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    diffs = 0
    for k in old:
        if old[k] != now.get(k):
            diffs += 1
            print(f"=== 違う: {k}")
            for i, (a, b) in enumerate(zip(old[k], now.get(k) or [])):
                if a != b:
                    print(f"  {i:2d} 前: {a}\n  {i:2d} 後: {b}")
    print(f"{len(old)} 画面のうち、違うのは {diffs} 画面")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
