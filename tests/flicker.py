#!/usr/bin/env python3
"""画面を移るときのチカチカを、GNOME Terminal と同じ VTE（libvte-2.91）で確かめる。tmux の窓（display-popup）の中で画面を移る
瞬間の画面の文字を、数ミリ秒ごとに VTE から読み、移る前にも移ったあとにも字のある行が、途中で一瞬だけ字を失ったか（空白に
なったか）を見る（2026-11-01、本人の指摘「メモタブに移動すると、チカチカする」「全体としてチカチカするのは止めてほしい」で作った）。

  python3 -I tests/flicker.py                 流して、移り方ごとに OK・NG を出す（NG があれば終わりの状態 1）
  python3 -I tests/flicker.py --root <場所>    ほかの置き場所の hackdeck（直す前の本人の実物など）を同じ手順で試す

NG: 移る前にもあとにもある枠の線（上の枠の上下・説明欄の下の線）が一瞬でも消えた移り方（画面を全部消してから描いている）か、
中身の行が 40 ミリ秒以上空白になった移り方（中身が遅れて出ている）。fzf は描き始めに一覧と上の枠の中をいったん空白で埋める
ので、それより短い中身の描きかけは「短い描きかけ」として出すだけ（fzf の同期描画に VTE 0.84 が対応しておらず、tmux も端末も
隠せない）。見るのは VTE の中の文字なので、消してからすぐ描き直すもの（vim の起動など）は、間が短いと読み取りの合間に収まって
見逃すことがある（数回流すか、tests/pane_record.py で画面を消す制御を数える）。
要るもの: xvfb-run、python3-gi と VTE（gir1.2-vte-2.91）。無ければ飛ばす（終わりの状態 0）。
隔離: 偽の HOME・別の TMUX_TMPDIR・別のソケット名（hdflicker）・Xvfb の仮の画面。本物の tmux には触らない。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLS, ROWS = 160, 45
KEYS = {"cg": b"\x07", "tab": b"\t", "btab": b"\x1b[Z", "down": b"\x1b[B", "enter": b"\r", "esc": b"\x1b"}
# 移り方（名前=キー）。名前の無いキーは、移る前の準備（撮らない）
STEPS = ("cg to-creds=tab to-env=tab to-memo=tab memo-to-case=tab to-settings=tab open-theme=enter down pick-theme=enter "
         "back-list=esc to-cmd=tab to-var=enter to-var2=enter var-esc=esc back-settings=btab back-case=btab back-memo=btab "
         "memo-to-env=btab")
LONG_MS = 40   # 中身の行がこれ以上空白なら NG
DROP = 6       # 前とあとの少ないほうより、これだけ字が減ったら空白とみなす
FRAME = set("─━═╌┄┈╶╭╮╰╯┌┐└┘┏┓┗┛╔╗╚╝▛▜▙▟▀▄▔▁")   # 枠の線の字（この字が 30 以上ある行は枠の線）


def outer(root):
    probe = subprocess.run([sys.executable, "-I", "-c", "import gi; gi.require_version('Vte', '2.91'); "
                            "from gi.repository import Vte"], capture_output=True)
    if not shutil.which("xvfb-run") or probe.returncode:
        print("飛ばした（要るものが無い: xvfb-run・python3-gi・VTE）")
        return 0
    t = Path(tempfile.mkdtemp(prefix="hackdeck-flicker."))
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "ZDOTDIR", "HACK_ROOT", "WAYLAND_DISPLAY", "DISPLAY")
           and not k.startswith("XDG_") and not k.startswith("HACKDECK_")}
    env.update(HOME=str(t / "home"), TMUX_TMPDIR=str(t / "tmux"), HACKDECK_TMUX_SOCKET="hdflicker", LANG="C.UTF-8",
               GDK_BACKEND="x11", NO_AT_BRIDGE="1", MESA_SHADER_CACHE_DISABLE="true", MESA_GLSL_CACHE_DISABLE="true",
               FLICKER_ROOT=str(root), FLICKER_OUT=str(t / "frames.json"))
    try:
        for d in ("home", "tmux"):
            (t / d).mkdir()
        subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root)!r}); "
                        "from hackdeck import settings; settings.save(memo=True, template='', work_dir='work', state_dir='work/.hack', log_file='logs/session.log')"], env=env, check=True)
        (t / "home" / ".zshrc").write_text("PROMPT='$ '\n")
        subprocess.run([str(root / "bin" / "hackdeck"), "case", "make", "demo"], env=env, check=True, capture_output=True)
        memo = t / "home" / "cases" / "demo" / "work" / ".hack" / "memo.md"
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.write_text("# メモ\n- 10.10.11.5 は DC\n", encoding="utf-8")
        r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 2560x1440x24", sys.executable, "-I", __file__, "--inner"],
                           env=env, capture_output=True, text=True, timeout=300)
        try:
            frames = json.loads((t / "frames.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"撮れなかった\n{r.stderr[-1500:]}")
            return 1
        return report(frames)
    finally:
        subprocess.run(["tmux", "-L", "hdflicker", "kill-server"], env=env, capture_output=True)
        shutil.rmtree(t, ignore_errors=True)


def report(frames):
    """移り方ごとに、枠の線が消えたか、前にもあとにも字のある行が途中で空白になった長さを出す。rows は行ごとの
    [空白でない字の数, 枠の線の字の数]"""
    by = {}
    for name, ms, rows in frames:
        by.setdefault(name, []).append((ms, rows))
    npass = nfail = 0
    for name in [n for n in by if not n.endswith("-before") and n + "-before" in by]:
        before, seq = by[name + "-before"][-1][1], by[name]
        after = seq[-1][1]
        lost, worst = [], []
        for r in range(len(after)):
            if before[r][1] >= 30 and after[r][1] >= 30 and any(rows[r][1] < 10 for _, rows in seq):
                lost.append(r + 3)   # 前にもあとにもある枠の線が消えた
                continue
            floor = min(before[r][0], after[r][0])
            if floor < DROP:
                continue
            blank = [ms for ms, rows in seq if rows[r][0] <= floor - DROP]
            if blank:
                # 空白だった長さ（空白のサンプルの最初から、字が戻った最初のサンプルまで）
                back = next((ms for ms, rows in seq if ms > blank[-1] and rows[r][0] > floor - DROP), seq[-1][0])
                worst.append((back - blank[0], r + 3))
        long = [w for w in worst if w[0] >= LONG_MS]
        good = not lost and not long
        npass, nfail = npass + good, nfail + (not good)
        what = []
        if lost:
            what.append(f"枠の線が消えた（{'・'.join(map(str, lost))} 行目）")
        if long:
            what.append(f"{len(long)} 行の中身が空白（いちばん長い {max(long)[0]} ミリ秒。{max(long)[1]} 行目）")
        if not what and worst:
            what.append(f"短い描きかけ（{max(worst)[0]} ミリ秒以下）")
        print(f"[{'OK' if good else 'NG'}] {name}" + (f"（{'・'.join(what)}）" if what else ""))
    print(f"\nOK {npass} / NG {nfail}")
    return 1 if nfail else 0


def inner():
    import time
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Vte", "2.91")
    from gi.repository import GLib, Gtk, Pango, Vte
    root = os.environ["FLICKER_ROOT"]
    win, term = Gtk.Window(), Vte.Terminal()
    term.set_font(Pango.FontDescription("Monospace 10"))
    term.set_size(COLS, ROWS)
    win.add(term)
    win.show_all()
    term.spawn_async(Vte.PtyFlags.DEFAULT, os.environ["HOME"], ["/usr/bin/zsh", "-i"],
                     [f"{k}={v}" for k, v in os.environ.items() if k not in ("DISPLAY", "XAUTHORITY")],
                     GLib.SpawnFlags.DEFAULT, None, None, -1, None, None, None)

    def ink():
        """各行の [空白でない字の数, 枠の線の字の数]（VTE がいま持っている画面の文字。窓の枠の外は数えない）"""
        lines = (term.get_text_format(Vte.Format.TEXT) or "").split("\n")[:ROWS]
        return [[sum(1 for c in l[9:COLS - 9] if not c.isspace()), sum(1 for c in l[9:COLS - 9] if c in FRAME)]
                for l in (lines[2:ROWS - 1] + [""] * ROWS)[:ROWS - 3]]

    frames, state = [], {"name": None, "t0": 0.0, "until": 0.0}

    def tick():
        now = time.monotonic()
        if state["name"] and now < state["until"]:
            frames.append((state["name"], round((now - state["t0"]) * 1000), ink()))
        return True

    def watch(name, secs):
        state.update(name=name, t0=time.monotonic(), until=time.monotonic() + secs)

    steps, t = [(1500, lambda: term.feed_child(f"{root}/bin/hackdeck case attach demo\r".encode()))], 5000
    for tok in STEPS.split():
        name, _, key = tok.rpartition("=")
        if name:
            steps.append((t - 200, lambda n=name: watch(n + "-before", 0.15)))
            steps.append((t, lambda n=name, k=key: (watch(n, 0.9), term.feed_child(KEYS[k]))))
        else:
            steps.append((t, lambda k=key: term.feed_child(KEYS[k])))
        t += 1500

    def done():
        Path(os.environ["FLICKER_OUT"]).write_text(json.dumps(frames), encoding="utf-8")
        Gtk.main_quit()
    steps.append((t + 300, done))
    for ms, fn in steps:
        GLib.timeout_add(ms, lambda fn=fn: (fn(), False)[1])
    GLib.timeout_add(3, tick)
    Gtk.main()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inner"]:
        inner()
    else:
        sys.exit(outer(Path(sys.argv[2]).resolve() if sys.argv[1:2] == ["--root"] and len(sys.argv) > 2 else ROOT))
