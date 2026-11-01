#!/usr/bin/python3 -I
"""配色（hackdeck/theme.py の THEMES）の点検。全部の配色について、

  - 文字の色と背景の明るさの比（WCAG のコントラスト比）が目安以上か（本文 7・見出しと変数 4.5・薄い字 3。選んでいる行の上の
    本文と見出しも 4.5）。背景を変えない配色は、暗い端末の背景 #1e1e1e で測る。縞（altbg）のある配色は、縞の地の上でも
  - fzf がその配色の --color と形（選んでいる行の印・入力欄の頭・線・枠の線・--no-unicode）を受け付けるか（名前の間違いで fzf が
    起動しなくならないように）。tmux の窓の枠の線（popup）が tmux の知っている形か

  python3 -I tests/themes.py     問題があれば出して、終わりの状態 1
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def lum(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


POPUP_LINES = ("single", "rounded", "double", "heavy", "simple", "padded", "none")   # tmux の popup-border-lines


def main():
    import os
    import atexit
    import shutil
    home = tempfile.mkdtemp(prefix="hackdeck-themes-")   # 本物の設定を読まない（終わったら消す）
    atexit.register(shutil.rmtree, home, True)
    os.environ["HOME"] = home
    from hackdeck import theme
    bad = 0
    for name, t in theme.THEMES.items():
        bg = t.get("bg", "1e1e1e")
        checks = [("snippet", t["snippet"], 7), ("tag", t["tag"], 4.5), ("comment", t["comment"], 4.5),
                  ("hint", t["hint"], 3.0)] + [(f"vars[{i}]", v, 4.5) for i, v in enumerate(t["vars"])] \
            + ([("fg", t["fg"], 7)] if "fg" in t else [])
        low = [f"{n} {ratio(c, bg):.1f}" for n, c, need in checks if ratio(c, bg) < need]
        if t.get("altbg"):
            low += [f"{n} の縞の地 {ratio(c, t['altbg']):.1f}" for n, c, need in checks if ratio(c, t["altbg"]) < need]
        sel = [("selfg", t["selfg"])] if t.get("selfg") else [("snippet", t["snippet"]), ("tag", t["tag"])]
        low += [f"{n} の選んだ行 {ratio(c, t['selbg']):.1f}" for n, c in sel if ratio(c, t["selbg"]) < 4.5]
        if t.get("popup", "single") not in POPUP_LINES:
            low.append(f"tmux の窓の枠の線 {t['popup']} は無い")
        theme.apply_theme(name)
        r = subprocess.run(["fzf", "--color", theme._fzf_theme_color_opt(), *theme.fzf_shape_args(),
                            "--preview-window", f"up,3,border-{theme.FRAME},noinfo", "--filter", "x"], input="",
                           capture_output=True, text=True)
        if r.returncode not in (0, 1) or r.stderr.strip():
            low.append(f"fzf が受け付けない: {r.stderr.strip()[:120]}")
        if low:
            bad += 1
            print(f"[NG] {name}: " + "・".join(low))
    print(f"配色 {len(theme.THEMES)} 個" + ("、問題なし" if not bad else f"、問題 {bad} 個"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
