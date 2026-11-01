#!/usr/bin/python3 -I
"""画面に何が書かれたかを、時刻つきで記録して数える（チカチカの原因を探すとき。2026-11-01、メモのタブに入るときに vim が画面を
全部消し、端末を調べる試しの字を書いていたのを、これで見つけた）。隔離した tmux のペインで hackdeck ui を開き、キーを送り、
ペインに書かれたもの（fzf・vim の出力）を tmux の pipe-pane で時刻つきで残して、キーごとに目立つ制御を数えて出す。

  python3 -I tests/pane_record.py [--memo] [--root <場所>] [キー ...]
      キー: tmux の send-keys の名前（Tab・BTab・Enter・Escape・Down・C-g など）。無ければ Tab を4回（--memo ならメモのタブを
      通る）。--root: ほかの置き場所の hackdeck を試す

出すもの（キーごとに、キーを押してからのミリ秒・大きさ・目立つ制御）: 画面を全部消す（ESC[2J）・下を消す（ESC[J）・代わりの
画面（?1049）・カーソルを出す／隠す・同期描画（?2026）・端末への問い合わせ・スクロールの範囲など。画面を全部消すものがあれば、
前の画面の上に描いていない（消えている間が見える）。
隔離: 偽の HOME（試しの案件）・別の TMUX_TMPDIR・別のソケット名（hdrecord）。本物の tmux には触らない。
"""
import json
import ast
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import snapshot  # noqa: E402

SOCK = "hdrecord"
STAMP = r'''
import sys, time
out = open(sys.argv[1], "w", encoding="utf-8")
while True:
    b = sys.stdin.buffer.read1(65536)
    if not b:
        break
    out.write(f"{time.time():.4f}\t{b!r}\n")
    out.flush()
'''
MARKS = [(rb"\x1b\[2J", "画面を全部消す"), (rb"\x1b\[[0-1]?J", "下を消す"), (rb"\x1b\[\?1049[hl]", "代わりの画面"),
         (rb"\x1b\[\?25l", "カーソルを隠す"), (rb"\x1b\[\?25h", "カーソルを出す"), (rb"\x1b\[\?2026[hl]", "同期描画"),
         (rb"\x1b\][0-9]+;\?", "色の問い合わせ"), (rb"\x1b\[[>=]?c", "端末の問い合わせ"), (rb"\x1b\[6n", "位置の問い合わせ"),
         (rb"\x1b\[[0-9;]*r", "スクロールの範囲"), (rb"\x1b\[[0-9]*[SLM]", "行をずらす")]


def main(argv):
    memo = "--memo" in argv
    root = ROOT
    keys = []
    it = iter(argv)
    for a in it:
        if a == "--root":
            root = Path(next(it, ".")).expanduser().resolve()
        elif a != "--memo":
            keys.append(a)
    keys = keys or ["Tab"] * 4
    t = Path(tempfile.mkdtemp(prefix="hackdeck-record-"))
    env, work = snapshot.build(t)
    env = {k: v for k, v in env.items() if k not in ("COLUMNS", "LINES")}
    env["PATH"] = f"{root / 'bin'}:" + env["PATH"]
    (Path(env["HOME"]) / ".config" / "hackdeck" / "settings.json").write_text(
        json.dumps({**snapshot.GENERIC, **({"memo": True} if memo else {})}), encoding="utf-8")
    log, stamp = t / "pane.log", t / "stamp.py"
    stamp.write_text(STAMP, encoding="utf-8")

    def tm(*a):
        return subprocess.run(["tmux", "-L", SOCK, *a], env=env, capture_output=True, text=True)

    pressed = []
    try:
        tm("-f", "/dev/null", "new-session", "-d", "-s", "rec", "-x", "160", "-y", "45", "-c", str(work),
           "bash --norc --noprofile")
        path = tm("display", "-p", "#{socket_path}").stdout.strip()
        if not path.startswith(str(t)):
            raise SystemExit(f"tmux の置き場所が隔離されていない: {path}")
        exports = " ".join(f"{k}='{v}'" for k, v in env.items())
        tm("send-keys", "-t", "rec", f"export {exports}; cd '{work}'; clear", "Enter")
        time.sleep(1)
        tm("pipe-pane", "-o", "-t", "rec", f"{sys.executable} -I {stamp} {log}")
        time.sleep(0.5)
        tm("send-keys", "-t", "rec", "hackdeck ui > /dev/null", "Enter")
        time.sleep(3)
        for k in keys:
            pressed.append((time.time(), k))
            tm("send-keys", "-t", "rec", k)
            time.sleep(2.5)
        tm("send-keys", "-t", "rec", "C-g")
        time.sleep(1)
    finally:
        tm("kill-server")
        rows = []
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                ts, rep = line.split("\t", 1)
                rows.append((float(ts), ast.literal_eval(rep)))
        shutil.rmtree(t, ignore_errors=True)
    total = {}
    for i, (k0, key) in enumerate(pressed):
        k1 = pressed[i + 1][0] if i + 1 < len(pressed) else float("inf")
        print(f"===== {i + 1}: {key}")
        for ts, b in rows:
            if k0 <= ts < k1:
                tags = [f"{name}×{len(re.findall(p, b))}" for p, name in MARKS if re.search(p, b)]
                for p, name in MARKS:
                    total[(key, i, name)] = total.get((key, i, name), 0) + len(re.findall(p, b))
                text = re.sub(r"\x1b\[[0-9;]*m", "", b.decode("utf-8", "replace"))
                print(f"  +{(ts - k0) * 1000:7.1f}ms {len(b):6d}B  {' '.join(tags)}  {text[:90]!r}"[:220])
    clears = sum(v for (key, i, name), v in total.items() if name == "画面を全部消す")
    print(f"\n画面を全部消した回数: {clears}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
