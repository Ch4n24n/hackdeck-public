#!/usr/bin/env python3
"""GNOME Terminal と同じ VTE（libvte-2.91）を外側の端末にした試し。tmux の窓（display-popup）の中で画面を移ったあとに、前の画面の
全角の字の地の色（注意書きの黄色い帯・選んでいた行の地）が、字の右半分だけ1マスおきに残っていないかを、画面を撮って見る
（2026-11-01、本人の報告「直前の画面に出た忠告文が次の画面でも残骸が残る」）。tests/e2e.sh の外側の tmux は、tmux と同じ
消し方をするので、この残り方をしない。

  python3 -I tests/vte.py          流して OK・NG と数を出す（NG があれば終わりの状態 1）
  KEEP=1 python3 -I tests/vte.py   撮った画像を残す（場所を最後に出す）

要るもの: xvfb-run、python3-gi と VTE（gir1.2-vte-2.91）、PIL。無ければ飛ばす（その旨を出して終わりの状態 0）。
隔離: 偽の HOME・別の TMUX_TMPDIR・別のソケット名（hdvte）・Xvfb の仮の画面（本人の画面には出さない）。本物の tmux には触らない。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS, ROWS = 238, 53   # 本人の端末と同じ大きさ（帯の長さ・行の位置を同じにする）
# 画面の手順（空白区切り）: キーの名前・s:<名前>（撮る）。キーのあとは描き終わるまで待つ
STEPS = "cg tab tab tab tab down down down enter s:item altleft s:back tab s:cmdtab btab s:settings"
EXPECT = {"item": "設定の項目の一覧 → 項目の画面（前の画面の選んでいた行の地）",
          "back": "注意書きの帯のある画面 → Alt+← で項目の一覧（帯の黄色）",
          "cmdtab": "設定のタブ → コマンドのタブ",
          "settings": "コマンドのタブ → 設定のタブ（コマンドの一覧の選んでいた行の地）"}
KEYS = {"cg": b"\x07", "tab": b"\t", "btab": b"\x1b[Z", "down": b"\x1b[B", "enter": b"\r", "altleft": b"\x1b[1;3D"}


def outer():
    missing = [n for n in ("xvfb-run",) if not shutil.which(n)]
    probe = subprocess.run([sys.executable, "-I", "-c", "import gi; gi.require_version('Vte', '2.91'); "
                            "from gi.repository import Vte; import PIL"], capture_output=True)
    if missing or probe.returncode:
        print(f"飛ばした（要るものが無い: {' '.join(missing) or 'python3-gi・VTE・PIL'}）")
        return 0
    t = Path(tempfile.mkdtemp(prefix="hackdeck-vte."))
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "ZDOTDIR", "HACK_ROOT", "WAYLAND_DISPLAY", "DISPLAY")
           and not k.startswith("XDG_") and not k.startswith("HACKDECK_")}
    env.update(HOME=str(t / "home"), TMUX_TMPDIR=str(t / "tmux"), HACKDECK_TMUX_SOCKET="hdvte", LANG="C.UTF-8",
               GDK_BACKEND="x11", NO_AT_BRIDGE="1",
               # 描画（Mesa）のシェーダーのキャッシュを偽の HOME に書かせない（終わって消したあとに書き込まれて残ることがあった）
               MESA_SHADER_CACHE_DISABLE="true", MESA_GLSL_CACHE_DISABLE="true")
    for d in ("home", "tmux", "shots"):
        (t / d).mkdir()
    # 配色は端末の背景のままのもの（背景を変える配色は、空いた所も地の色で書くので残らない）
    subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                    "from hackdeck import settings; settings.save(theme='rose', template='', work_dir='work', state_dir='work/.hack', log_file='logs/session.log')"], env=env, check=True)
    (t / "home" / ".zshrc").write_text("PROMPT='$ '\n")
    subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "make", "demo"], env=env, check=True, capture_output=True)
    try:
        r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 2560x1440x24", sys.executable, "-I", __file__, "--inner",
                            str(t / "shots")], env=env, capture_output=True, text=True, timeout=180)
        found = {}
        for line in r.stdout.splitlines():
            if line.startswith("{"):
                found.update(json.loads(line))
        npass = nfail = 0
        for name, label in EXPECT.items():
            rows = found.get(name)
            good = rows == []
            npass, nfail = npass + good, nfail + (not good)
            what = "撮れなかった" if rows is None else f"残骸のある行 {rows}" if rows else ""
            print(f"[{'OK' if good else 'NG'}] {label}" + (f"（{what}）" if what else ""))
        good = found.get("selfcheck") not in (None, [])
        npass, nfail = npass + good, nfail + (not good)
        print(f"[{'OK' if good else 'NG'}] 残骸を見つけられる（VTE に直に書いた見本で）")
        if r.returncode or nfail:
            sys.stderr.write(r.stderr[-2000:])
        print(f"\nOK {npass} / NG {nfail}")
        return 1 if nfail else 0
    finally:
        subprocess.run(["tmux", "-L", "hdvte", "kill-server"], env=env, capture_output=True)
        if os.environ.get("KEEP"):
            print(f"残した: {t / 'shots'}（片づけ: rm -rf {t}）")
        else:
            shutil.rmtree(t, ignore_errors=True)


def inner(shots):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import GLib, Gdk, Gtk, Pango, Vte
    from PIL import Image

    assert os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"), "Xvfb の中で動かす"
    win, term = Gtk.Window(), Vte.Terminal()
    term.set_font(Pango.FontDescription("Monospace 10"))
    term.set_size(COLS, ROWS)
    win.add(term)
    win.show_all()
    term.spawn_async(Vte.PtyFlags.DEFAULT, os.environ["HOME"], ["/usr/bin/zsh", "-i"],
                     [f"{k}={v}" for k, v in os.environ.items() if k not in ("DISPLAY", "XAUTHORITY")],
                     GLib.SpawnFlags.DEFAULT, None, None, -1, None, None, None)

    def remnant_rows():
        """全角の字の半分だけ地の色が残った行（色のあるマスと無いマスが1マスずつ交互に3回以上）。最後の行（tmux の帯）は見ない"""
        w = win.get_window()
        path = f"{shots}/shot.png"
        Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height()).savev(path, "png", [], [])
        im = Image.open(path).convert("RGB")
        cw, ch = term.get_char_width(), term.get_char_height()
        rows = []
        for r in range(ROWS - 1):
            y = int(r * ch + ch / 2)
            # マスの左右の端と上の端（字の形を避ける）がどれも地の色でなければ、色のあるマス
            line = "".join("#" if all(sum(im.getpixel(p)) > 60 for p in ((int(c * cw + 1), y), (int(c * cw + cw - 2), y),
                                                                          (int(c * cw + 1), int(r * ch + 2))))
                           else "." for c in range(COLS))
            if "#.#.#" in line:
                rows.append(r)
        return rows

    def snap(name):
        rows = remnant_rows()
        os.replace(f"{shots}/shot.png", f"{shots}/{name}.png")
        print(json.dumps({name: rows}), flush=True)

    def selfcheck():
        # VTE そのものに、黄色の地の全角の字を書いて、左半分だけ半角の空白で上書きする（右半分の黄色が残る）
        term.feed(b"\x1b7\x1b[30;20H\x1b[43m\xe6\xb3\xa8\xe6\x84\x8f\xe6\xb3\xa8\xe6\x84\x8f\x1b[0m"
                  b"\x1b[30;20H \x1b[30;22H \x1b[30;24H \x1b[30;26H \x1b8")
        GLib.timeout_add(300, lambda: (print(json.dumps({"selfcheck": remnant_rows()}), flush=True), Gtk.main_quit())[1])

    steps, t = [(1500, lambda: term.feed_child(f"{ROOT}/bin/hackdeck case attach demo\r".encode()))], 5000
    for tok in STEPS.split():
        if tok.startswith("s:"):
            steps.append((t, lambda n=tok[2:]: snap(n)))
            t += 300
        else:
            steps.append((t, lambda d=KEYS[tok]: term.feed_child(d)))
            t += 500 if tok == "down" else 1500
    steps.append((t + 500, selfcheck))
    for ms, fn in steps:
        GLib.timeout_add(ms, lambda fn=fn: (fn(), False)[1])
    Gtk.main()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inner"]:
        inner(sys.argv[2])
    else:
        sys.exit(outer())
