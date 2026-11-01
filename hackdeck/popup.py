"""窓（専用の tmux サーバーで、窓のキーを押したとき）の中身。元のペインのセッションの案件で開き、組み立てたコマンドを
そのペインに貼る（実行はしない。zsh の入力行にも、リバースシェルのプロンプトにも、打ったのと同じに入る）。"""
import os
from pathlib import Path

from .case import case_env, is_case_dir
from .env import env_vars
from .session import tmux, write_conf
from .builder import run_builder


def pane_case(pane):
    """ペインのセッションの案件（セッションの環境の HACK_ROOT。session.case_create が入れる）。案件でなければ None"""
    out = (tmux("show-environment", "-t", pane, "HACK_ROOT") or "").strip()
    v = out.partition("=")[2] if out.startswith("HACK_ROOT=") else ""
    return Path(v) if v and is_case_dir(Path(v)) else None


def c_popup(args):
    """hackdeck popup <ペイン>"""
    if not args:
        return 2
    pane = args[0]
    write_conf()   # hackdeck を直したあとも、次の窓から専用の tmux の設定が新しくなる（中身が同じなら何もしない）
    # 窓は、元のペインのセッションの案件で開く（2026-10-31、本人の指摘「案件に入ったあと Ctrl+G で、直前の案件にフォーカスして
    # いることがある」。そのころは、ペインのいまの場所で案件を決めていた）
    d = pane_case(pane)
    for k in [k for k in os.environ if k.startswith("HACK_")]:
        os.environ.pop(k)
    if d:
        os.environ.update(case_env(d))
    cmd = run_builder({**os.environ, **dict(env_vars())})
    if cmd:
        # 貼るだけで実行はしない（改行を付けない）。バッファは残すので prefix + = で貼り直せる
        tmux("set-buffer", "-b", "hackdeck", "--", cmd)
        tmux("paste-buffer", "-b", "hackdeck", "-t", pane)
    return 0
