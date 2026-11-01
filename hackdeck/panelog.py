"""ペインの画面のログ（案件のログ HACK_LOG。tmux-op の自動ログを移した）。コマンドごとに残すのは shell/hack.zsh の precmd、
すぐ残すのは prefix+F（hackdeck log flush。リバースシェルの中など、プロンプトに戻らないとき）。どちらも、ペインの @hack_last
（前に残した所。履歴の行数＋カーソルの行）から今までの画面を、見たままの文字で足す（ファイル自身に鍵をかけ、ほかのペインと
混ざらないように）。同じ値を見るので、prefix+F のあとでプロンプトに戻っても、同じ所を2回残さない。"""
import fcntl
from pathlib import Path

from .session import tmux


def pane_env(pane, name):
    """ペインのセッションの環境変数（無ければ空）"""
    out = (tmux("show-environment", "-t", pane, name) or "").strip()
    return out.partition("=")[2] if out.startswith(name + "=") else ""


def log_flush(pane):
    def say(msg):
        tmux("display-message", "-t", pane, f"hackdeck: {msg}")
    log = pane_env(pane, "HACK_LOG")
    if not log:
        say("このセッションはログを残さない（設定のログが空か、案件のセッションでない）")
        return 0
    pos = (tmux("display-message", "-p", "-t", pane, "#{history_size} #{cursor_y}") or "").split()
    if len(pos) != 2 or not all(x.isdigit() for x in pos):
        return 0
    hs, cy = int(pos[0]), int(pos[1])
    now = hs + cy
    last = (tmux("show-options", "-pqv", "-t", pane, "@hack_last") or "").strip()
    if not last.isdigit():   # zsh でないペインなど、まだ基準が無い。ここより前の画面は残さない
        tmux("set-option", "-p", "-t", pane, "@hack_last", str(now))
        say("ここから残す（前の画面は残さない。もう一度 prefix+F で、ここまでを残す）")
        return 0
    if now <= int(last):
        say("新しい出力なし")
        return 0
    blk = tmux("capture-pane", "-p", "-J", "-t", pane, "-S", str(int(last) - hs), "-E", str(cy - 1)) or ""
    blk = "\n".join(l.rstrip() for l in blk.split("\n")).strip("\n")   # 行末の空白と、頭と終わりの空行は落とす
    if blk:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(blk + "\n\n\n")   # コマンドとコマンドの間に空行2つ（zsh の側と同じ）
    tmux("set-option", "-p", "-t", pane, "@hack_last", str(now))
    say("ここまでをログに残した" if blk else "新しい出力なし")
    return 0
