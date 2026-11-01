#!/usr/bin/env python3
"""配色の見本を撮る（新しい配色を作る・比べるとき。2026-11-01、身の回りの物・見やすさの配色を作るときに使った）。GNOME Terminal と
同じ VTE（libvte-2.91）で、tmux の窓の中の主な画面（コマンド・変数・資格情報・メモ・案件・配色の一覧）を撮り、配色ごとに 2×3 に
並べた1枚を作る。

  python3 -I tests/theme_shots.py <出力フォルダ> <配色> [<配色> ...]
      配色は英字の名前（ocean・notebook など）。出すもの: <配色>-<画面>.png と、並べた <配色>.png（1つの配色に1分ほど）

要るもの: xvfb-run、python3-gi と VTE（gir1.2-vte-2.91）、PIL。無ければ飛ばす（終わりの状態 0）。
隔離: 偽の HOME・別の TMUX_TMPDIR・別のソケット名（hdshots）・Xvfb の仮の画面。本物の tmux には触らない。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS, ROWS = 180, 46
KEYS = {"cg": b"\x07", "tab": b"\t", "enter": b"\r", "esc": b"\x1b", "i": b"i",
        "memo": "# メモ\n- 10.10.11.5 は DC\n- svc_sql の資格情報を試す".encode()}
# 手順（キーの名前と s:<画面の名前>＝撮る）。メモのタブを出す設定で、コマンド → 変数 → 資格情報 → 環境 → メモ → 案件 → 設定
STEPS = "cg s:cmd enter s:var esc tab s:creds tab tab i memo esc s:memo tab s:case tab enter s:themes"
NAMES = ["cmd", "var", "creds", "memo", "case", "themes"]


def outer(out, names):
    probe = subprocess.run([sys.executable, "-I", "-c", "import gi; gi.require_version('Vte', '2.91'); "
                            "from gi.repository import Vte; import PIL"], capture_output=True)
    if not shutil.which("xvfb-run") or probe.returncode:
        print("飛ばした（要るものが無い: xvfb-run・python3-gi・VTE・PIL）")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        t = Path(tempfile.mkdtemp(prefix="hackdeck-shots."))
        env = {k: v for k, v in os.environ.items()
               if k not in ("TMUX", "TMUX_PANE", "ZDOTDIR", "HACK_ROOT", "WAYLAND_DISPLAY", "DISPLAY")
               and not k.startswith("XDG_") and not k.startswith("HACKDECK_")}
        env.update(HOME=str(t / "home"), TMUX_TMPDIR=str(t / "tmux"), HACKDECK_TMUX_SOCKET="hdshots", LANG="C.UTF-8",
                   GDK_BACKEND="x11", NO_AT_BRIDGE="1", MESA_SHADER_CACHE_DISABLE="true", MESA_GLSL_CACHE_DISABLE="true",
                   SHOTS_OUT=str(out), SHOTS_NAME=name)
        try:
            for d in ("home", "tmux"):
                (t / d).mkdir()
            subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                            f"from hackdeck import settings; settings.save(theme={name!r}, memo=True, template='', work_dir='work', state_dir='work/.hack', log_file='logs/session.log')"], env=env, check=True)
            (t / "home" / ".zshrc").write_text("PROMPT='$ '\n")
            subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "make", "demo"], env=env, check=True,
                           capture_output=True)
            state = t / "home" / "cases" / "demo" / "work" / ".hack"
            state.mkdir(parents=True, exist_ok=True)
            (state / "creds").write_text("alice:Passw0rd!:test.local\nAdministrator:0123456789abcdef0123456789abcdef:SRV01\n",
                                         encoding="utf-8")
            (state / "env").write_text("export TARGET=10.10.10.5\nexport DOMAIN=test.local\n", encoding="utf-8")
            r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 2560x1440x24", sys.executable, "-I", __file__,
                                "--inner"], env=env, capture_output=True, text=True, timeout=240)
            if r.returncode:
                print(r.stderr[-1500:])
        finally:
            subprocess.run(["tmux", "-L", "hdshots", "kill-server"], env=env, capture_output=True)
            shutil.rmtree(t, ignore_errors=True)
        sheet(out, name)
    return 0


def sheet(out, name):
    """撮った画面を、窓のあたりを切り出して 2×3 に並べる（<配色>.png）"""
    from PIL import Image
    shots = [out / f"{name}-{n}.png" for n in NAMES]
    if not all(p.exists() for p in shots):
        print(f"{name}: 撮れなかった画面がある")
        return
    ims = [Image.open(p).convert("RGB") for p in shots]
    w, h = ims[0].size
    ims = [im.crop((60, 30, w - 75, h - 80)) for im in ims]
    cw, ch = int(ims[0].size[0] * 0.62), int(ims[0].size[1] * 0.62)
    board = Image.new("RGB", (cw * 2 + 10, ch * 3 + 20), (40, 40, 40))
    for i, im in enumerate(ims):
        board.paste(im.resize((cw, ch), Image.LANCZOS), ((i % 2) * (cw + 10), (i // 2) * (ch + 10)))
    board.save(out / f"{name}.png")
    print(out / f"{name}.png")


def inner():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import GLib, Gdk, Gtk, Pango, Vte
    out, name = os.environ["SHOTS_OUT"], os.environ["SHOTS_NAME"]
    win, term = Gtk.Window(), Vte.Terminal()
    term.set_font(Pango.FontDescription("Monospace 10"))
    term.set_size(COLS, ROWS)
    win.add(term)
    win.show_all()
    term.spawn_async(Vte.PtyFlags.DEFAULT, os.environ["HOME"], ["/usr/bin/zsh", "-i"],
                     [f"{k}={v}" for k, v in os.environ.items() if k not in ("DISPLAY", "XAUTHORITY")],
                     GLib.SpawnFlags.DEFAULT, None, None, -1, None, None, None)

    def snap(screen):
        w = win.get_window()
        Gdk.pixbuf_get_from_window(w, 0, 0, w.get_width(), w.get_height()).savev(f"{out}/{name}-{screen}.png", "png", [], [])

    steps, t = [(1500, lambda: term.feed_child(f"{ROOT}/bin/hackdeck case attach demo\r".encode()))], 5000
    for tok in STEPS.split():
        if tok.startswith("s:"):
            steps.append((t, lambda n=tok[2:]: snap(n)))
            t += 300
        else:
            steps.append((t, lambda d=KEYS[tok]: term.feed_child(d)))
            t += 1500
    steps.append((t + 300, Gtk.main_quit))
    for ms, fn in steps:
        GLib.timeout_add(ms, lambda fn=fn: (fn(), False)[1])
    Gtk.main()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inner"]:
        inner()
    elif len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    else:
        sys.exit(outer(Path(sys.argv[1]).expanduser().resolve(), sys.argv[2:]))
