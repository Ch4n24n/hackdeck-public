#!/usr/bin/python3 -I
"""隔離した tmux で hackdeck ui を開き、キーを送って画面を文字で出す（手で確かめるとき。2026-11-01、どのタブの検索欄も打つと
絞るようにしたときに使った）。試しの環境は tests/snapshot.py と同じ（偽の HOME の試しの案件・資格情報・環境変数）。

  python3 -I tests/keys.py '<題>|<キー>|<キー>...' ...
      1つの引数が1つの手順。キーを順に送ってから、題をつけて画面を出す（題が空なら出さない）。キーは tmux の send-keys の名前
      （Tab・BTab・Enter・Escape・Up・C-u など）か、L:<文字>（その文字をそのまま打つ）
  例: python3 -I tests/keys.py '設定|BTab' '絞る|L:ログ' '当たらない|L:zzz'

出すもの: 画面の空でない行（行の番号つき。高さが変わっていないかも見られる）。
隔離: 偽の HOME・別の TMUX_TMPDIR・別のソケット名（hdkeys）。本物の tmux には触らない。
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import snapshot  # noqa: E402

SOCK = "hdkeys"


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    t = Path(tempfile.mkdtemp(prefix="hackdeck-keys-"))
    env, work = snapshot.build(t)
    env = {k: v for k, v in env.items() if k not in ("COLUMNS", "LINES")}

    def tm(*a):
        return subprocess.run(["tmux", "-L", SOCK, *a], env=env, capture_output=True, text=True)

    try:
        tm("-f", "/dev/null", "new-session", "-d", "-s", "keys", "-x", "160", "-y", "45", "-c", str(work),
           "bash --norc --noprofile")
        path = tm("display", "-p", "#{socket_path}").stdout.strip()
        if not path.startswith(str(t)):
            raise SystemExit(f"tmux の置き場所が隔離されていない: {path}")
        exports = " ".join(f"{k}='{v}'" for k, v in env.items())
        tm("send-keys", "-t", "keys", f"export {exports}; cd '{work}'; clear; hackdeck ui > /dev/null", "Enter")
        time.sleep(3)
        for step in argv:
            title, *keys = step.split("|")
            for k in keys:
                tm("send-keys", "-t", "keys", *(["-l", k[2:]] if k.startswith("L:") else [k]))
                time.sleep(0.5)
            time.sleep(1.5)
            if title:
                lines = [l.rstrip() for l in tm("capture-pane", "-p", "-t", "keys").stdout.splitlines()]
                print(f"===== {title}")
                print("\n".join(f"{i:2d} {l}" for i, l in enumerate(lines) if l.strip()))
    finally:
        tm("kill-server")
        shutil.rmtree(t, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
