#!/usr/bin/env bash
# hackdeck を入れる。手元の環境で変えるのは ~/.local/bin/hackdeck の symlink 1つだけ（無くても bin/hackdeck を直接呼べば
# 動く）。~/.zshrc・~/.tmux.conf は書き換えない: 案件のセッションは専用の tmux サーバー（tmux -L hackdeck）で動き、その設定は
# hackdeck が ~/.cache/hackdeck/ に作る。要るものが足りなければ、入れ方を出して止まる（sudo は使わない）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"

ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]; }   # $1 が $2 以上
ok=1
need() {   # 名前 いまの版 要る版 入れ方
  if [ -z "$2" ]; then
    echo "[!] $1 が無い（$3 以上が要る）: $4"; ok=0
  elif ver_ge "$2" "$3"; then
    echo "[=] $1 $2"
  else
    echo "[!] $1 が古い（いま $2。$3 以上が要る）: $4"; ok=0
  fi
}
need tmux "$(tmux -V 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)" 3.3 "sudo apt install tmux"
need fzf "$(fzf --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+(\.[0-9]+)?' || true)" 0.65 \
  "https://github.com/junegunn/fzf/releases（apt の版が古いとき）"
need python3 "$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)" 3.8 "sudo apt install python3"
command -v zsh >/dev/null || echo "[?] zsh が無い: 画面は動く。案件のシェルの部分（ログ・実行の時刻・環境変数の読み直し・~hack・打ちかけの行の検索）は zsh のときだけ"
command -v flock >/dev/null || echo "[?] flock が無い（util-linux）: 案件のログを残せない"
[ "$ok" = 1 ] || exit 1

mkdir -p "$BIN"
ln -sfn "$HERE/bin/hackdeck" "$BIN/hackdeck"
echo "[+] $BIN/hackdeck -> $HERE/bin/hackdeck"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "[?] $BIN が PATH に無い（hackdeck と打つなら PATH に足す。$HERE/bin/hackdeck を直接呼んでもよい）" ;;
esac

cat <<'USAGE'

使い方:
  hackdeck        案件と設定の画面を開く（案件を選ぶと、その案件のセッションに入る。tmux の中なら、その上の窓で）
  案件のセッションの中は Ctrl+G（設定のタブで変えられる）で、コマンドの組み立て・資格情報・環境・案件・設定を開く

案件のセッションの外でも Ctrl+G で開くなら、~/.zshrc に次の1行を足す（足さなくても、hackdeck と打てば開く）:
  eval "$(hackdeck shell-init zsh)"

点検: hackdeck check
USAGE
