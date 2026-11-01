#!/usr/bin/python3 -I
"""反応の速さを測る。fzf から打つたび・画面を出すたびに hackdeck が起き直すので、1回の起動から終わりまでの時間が、そのまま
反応の遅さになる（2026-11-01、本人の希望「反応速度がはやくなると嬉しい」で、綺麗化の前後を比べるために作った）。

  python3 -I tests/timing.py                      いまの置き場所の hackdeck を測る（それぞれ 9 回の中央値）
  python3 -I tests/timing.py --against <場所>      ほかの置き場所（直す前の本人の実物 ~/git/hackdeck など）と並べる

測るもの: fzf から呼ばれる補助（カーソル合わせ・変数の画面で1字打つ・Tab の補完・ファイルの画面で1字打つ・各タブで1字打つ）、
変数の画面の候補（ホスト）、窓を開く処理（読み込みから最初の fzf を起こすまで。fzf は起こさない）。
隔離: 偽の HOME（試しの案件）・無いソケット名。本物の tmux には触らない。測るだけで、OK・NG は出さない。
"""
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import snapshot  # noqa: E402

CMDS = [("画面を出すときのカーソル合わせ", ["findpos", "x", "/dev/null"]),
        ("変数の画面で1字打つ", ["pick", "a", "/dev/null"]),
        ("Tab の補完", ["complete", "a", "x", "/dev/null"]),
        ("ファイルの画面で1字打つ", ["files", "user", "--typed", "--query", "a"]),
        ("変数の画面を開く（ホストの候補）", ["hosts"]),
        ("案件のタブで1字打つ", ["caserows", "x"]),
        ("設定のタブで1字打つ", ["settingrows", "x"]),
        ("資格情報のタブで1字打つ", ["credsrows", "x"]),
        ("環境のタブで1字打つ", ["envrows", "x"])]
OPEN = r'''
import os, sys, time
sys.path.insert(0, sys.argv[1])
t = time.perf_counter()
from hackdeck import builder
import hackdeck.prompt as prompt
class Stop(Exception):
    pass
def stop(*a, **k):
    raise Stop()
prompt.fzf_run = stop
try:
    builder.run_builder(dict(os.environ))
except Stop:
    pass
print(time.perf_counter() - t)
'''


def measure(root, env, work, n=9):
    res = {}
    for name, cmd in CMDS:
        ts = []
        for _ in range(n):
            t = time.perf_counter()
            subprocess.run([str(root / "bin" / "hackdeck"), *cmd], env=env, cwd=work, capture_output=True)
            ts.append(time.perf_counter() - t)
        res[name] = statistics.median(ts) * 1000
    ts = []
    for _ in range(n):
        r = subprocess.run([sys.executable, "-I", "-c", OPEN, str(root)], env=env, cwd=work, capture_output=True, text=True)
        try:
            ts.append(float(r.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            pass
    res["窓を開く処理"] = statistics.median(ts) * 1000 if ts else float("nan")
    return res


def main(argv):
    other = Path(argv[1]).expanduser().resolve() if argv[:1] == ["--against"] and len(argv) > 1 else None
    t = Path(tempfile.mkdtemp(prefix="hackdeck-timing-"))
    try:
        env, work = snapshot.build(t)
        env = {k: v for k, v in env.items() if k not in ("COLUMNS", "LINES")}
        env["HACKDECK_TMUX_SOCKET"] = "hdtiming-none"
        now = measure(ROOT, env, work)
        before = measure(other, env, work) if other else None
    finally:
        import shutil
        shutil.rmtree(t, ignore_errors=True)
    for name, ms in now.items():
        if before:
            print(f"{name:24s} {before[name]:6.0f} ms → {ms:5.0f} ms")
        else:
            print(f"{name:24s} {ms:6.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
