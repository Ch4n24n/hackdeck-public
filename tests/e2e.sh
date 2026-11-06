#!/usr/bin/env bash
# hackdeck の通しの試し。案件を作って専用の tmux に入り、シェルの部分（環境変数・ログ・実行の時刻・戻るコマンド）、窓のキー
# （zsh の入力行にも、ほかのプログラムにも貼る）、prefix+F、窓の配色（枠の色・題）、マウスのクリック（1回はカーソル、2回は Enter）、
# 一覧の見え方（端の行のクリック・描き直し）、検索欄（打つと絞る・行の Enter で書き換え・Ctrl+W は空白と記号で止まる）、
# メモのタブ（vim）、案件のタブでの切り替え、終えた案件の並びの復元、案件の名前を
# 変える（Ctrl+E・hackdeck の外で mv しても引き継ぐ）、設定の読み直し、
# tmux の外の端末の Ctrl+G（待合の上に窓・止まっている案件に入っても固まらない）、案件の外も tmux で（設定の outside。
# プログラムが動いていても Ctrl+G・案件から離れると戻る・端末を閉じると片づく）を試す。
#
#   bash tests/e2e.sh          全部流して、OK・NG と最後に数を出す（NG があれば終わりの状態 1）
#   KEEP=1 bash tests/e2e.sh   終わっても tmux と一時フォルダを残す（中を見るとき。片づけ方を最後に出す）
#
# 隔離: 偽の HOME・別の TMUX_TMPDIR・別のソケット名（hdtest・outer）。本物の tmux サーバー・ペイン・案件には触らない。
# 端末は script(1) で作り、外側の tmux（ふだんの tmux の代わり）につなぐ。キーは外側の tmux のペインに送る（その中で
# 専用の tmux につないだ端末が受けるので、窓のキー・窓の中の操作が本物と同じに通る）。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HD="$ROOT/bin/hackdeck"
T=$(mktemp -d /tmp/hackdeck-e2e.XXXXXX)
export HOME=$T/home TMUX_TMPDIR=$T/tmux HACKDECK_TMUX_SOCKET=hdtest LANG=C.UTF-8
unset TMUX TMUX_PANE ZDOTDIR HACK_ROOT XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME
mkdir -p "$HOME" "$TMUX_TMPDIR"
# 設定を書く（キー 値（JSON））。専用の tmux の設定は settings.json のとおりに作られる（環境変数では変わらない）
setting() { python3 -I -c "import sys; sys.path.insert(0, '$ROOT'); import json; from hackdeck import settings; settings.save(**{sys.argv[1]: json.loads(sys.argv[2])})" "$1" "$2"; }
conf() { python3 -I -c "import sys; sys.path.insert(0, '$ROOT'); from hackdeck.session import write_conf; write_conf()"; }
setting home_cmd '"hk"'
# 箱でない形（雛形は空・work・logs/session.log）で試す。既定は付属の雛形の箱の形（2026-11-02。tests/snapshot.py の GENERIC と同じ）
setting template '""'; setting work_dir '"work"'; setting state_dir '"work/.hack"'; setting log_file '"logs/session.log"'
# 自分の ~/.tmux.conf の代わり（tmux-sensible と同じく R に読み直しを割り当てている。hackdeck が外すか見る）
printf 'bind R display-message user-R\n' >"$HOME/.tmux.conf"
# 自分の ~/.zshrc の代わり。Kali の既定と同じく precmd() 関数で文字を出す（実行の時刻がその前に出るかを見る）
# HD_INIT があるシェル（tmux の外の端末の代わり）は、hackdeck shell-init の1行も読む
cat >"$HOME/.zshrc" <<'RC'
PROMPT='$ '
precmd() { print -r -- "<user-precmd ──>" }
[[ -n $HD_INIT ]] && eval "$($HD_INIT shell-init zsh)"
RC
O() { tmux -L outer "$@"; }
H() { tmux -L hdtest "$@"; }
pass=0 fail=0
ok() { if eval "$2"; then echo "[OK] $1"; pass=$((pass + 1)); else echo "[NG] $1"; fail=$((fail + 1)); fi; }
screen() { O capture-pane -p -t main | grep -v '^ *$'; }
pane() { H capture-pane -p -t "$1" | grep -v '^ *$'; }
cleanup() {
  if [ -n "${KEEP:-}" ]; then
    echo "残した: $T（片づけ: TMUX_TMPDIR=$T/tmux tmux -L hdtest kill-server; TMUX_TMPDIR=$T/tmux tmux -L outer kill-server; rm -rf $T）"
    return
  fi
  H kill-server 2>/dev/null; O kill-server 2>/dev/null
  for p in $(pgrep -f "[s]cript -qfc stty cols 160 rows 45; TERM=xterm-256color tmux -L outer"); do kill "$p" 2>/dev/null; done
  rm -rf "$T"
}
trap cleanup EXIT

echo "== 案件を作る"
"$HD" case make demo >/dev/null
ok "作業フォルダとログの置き場所" "[ -d $HOME/cases/demo/work ] && [ -d $HOME/cases/demo/logs ]"

echo "== ほかの tmux の中から案件に入る（入れ子にせず、その端末が専用の tmux に切り替わる）"
O -f /dev/null new-session -d -s main -x 160 -y 45 "env SHELL=/usr/bin/zsh zsh -f"
(TERM=xterm-256color script -qfc "stty cols 160 rows 45; TERM=xterm-256color tmux -L outer attach -t main" /dev/null >/dev/null 2>&1 &)
sleep 1.5
O send-keys -t main "$HD case attach demo" Enter
sleep 3
ok "端末が専用の tmux の demo に" "[ \"\$(H list-clients -F '#{client_session}')\" = demo ]"
ok "外側の tmux から離れた" "[ -z \"\$(O list-clients)\" ]"
ok "セッションの環境（HACK_ROOT・NXC_PATH）" "H show-environment -t demo HACK_ROOT | grep -q cases/demo && H show-environment -t demo NXC_PATH | grep -q .hack/nxc"
sleep 1
ok "シェルの部分が入った（@hack_shell）" "[ \"\$(H show-options -pqv -t demo @hack_shell)\" = 1 ]"

echo "== シェルの部分"
printf 'export TARGET=10.10.10.99\n' >"$HOME/cases/demo/work/.hack/env"
H send-keys -t demo 'echo "TARGET=$TARGET dir=${nameddirs[hack]}"' Enter
sleep 1
ok "環境変数のファイルが次のコマンドで効く" "pane demo | grep -q 'TARGET=10.10.10.99'"
ok "~hack が作業フォルダ" "pane demo | grep -q 'dir=$HOME/cases/demo/work'"
H send-keys -t demo 'export LHOST=10.10.14.7' Enter
sleep 1.5
ok "export を書き戻す" "grep -q 'export LHOST=10.10.14.7' $HOME/cases/demo/work/.hack/env"
ok "実行の時刻（前と後）" "pane demo | grep -q '────.*\[[0-9.]*s\]'"
ok "終わりの時刻が自分の precmd より先" "pane demo | grep -A1 '\[[0-9.]*s\]' | grep -q '<user-precmd'"
ok "自分の precmd の文字が化けない（罫線）" "pane demo | grep -q '<user-precmd ──>'"
ok "コマンドごとのログ" "grep -q 'TARGET=10.10.10.99' $HOME/cases/demo/logs/session.log"
ok "ログの頭に空行が無い" "[ -n \"\$(head -1 $HOME/cases/demo/logs/session.log)\" ]"
ok "並びの自動保存（プロンプトのたび。15分に1回）" "[ -e $HOME/.local/state/hackdeck/autosave ]"
H send-keys -t demo 'cd / && hk && echo "here=$PWD"' Enter
sleep 1
ok "作業フォルダへ戻るコマンド（設定の home_cmd）" "pane demo | grep -q 'here=$HOME/cases/demo/work'"
ok "prefix+C-r は hackdeck の設定ごと読み直す・prefix+R は何もしない（~/.tmux.conf の R も外す）" \
  "H list-keys -T prefix | grep -qE '^bind-key +-T prefix +C-r +source-file' && ! H list-keys -T prefix | grep -qE '^bind-key +-T prefix +R '"
ok "prefix+C-s は何もしない" "! H list-keys -T prefix | grep -q ' C-s '"
setting home_cmd '"hk2"'; conf
H send-keys -t demo 'cd / && hk2 && echo "here2=$PWD"; whence hk || echo hk-gone' Enter
sleep 1.5
ok "戻るコマンドを変えると、開いているペインでも次に打つコマンドから効く（前の名前は消える）" "pane demo | grep -q 'here2=$HOME/cases/demo/work' && pane demo | grep -q '^hk-gone'"
ok "窓の枠の色が配色に合う（ocean の見出しの色）" "H list-keys -T root | grep -q 'fg=#56d4dd'"

echo "== 案件から離れると、元の tmux に戻る"
H detach-client
sleep 2
ok "外側の tmux の main に戻った" "[ \"\$(O list-clients -F '#{client_session}')\" = main ]"

echo "== 外側のペインの中で専用の tmux につなぐ（ここからキーを送る）"
O send-keys -t main 'unset TMUX TMUX_PANE; tmux -L hdtest attach -t demo' Enter
sleep 2
printf '2026-10-31T09:00:00\techo hello-from-history\n' >"$HOME/cases/demo/work/.hack/history"
H send-keys -t demo 'clear' Enter
sleep 1
O send-keys -t main C-g
sleep 3
ok "zsh のプロンプトで窓のキー: 窓が開く" "screen | grep -q '│コマンド  資格情報'"
O send-keys -t main C-r
sleep 2.5
O send-keys -t main Enter
sleep 2.5
ok "選んだコマンドが入力行に貼られる（実行はしない）" "pane demo | grep -q '^\\$ echo hello-from-history\$'"
H send-keys -t demo C-u 'cat' Enter
sleep 1
O send-keys -t main C-g
sleep 3
O send-keys -t main C-r
sleep 2.5
O send-keys -t main Enter
sleep 2.5
ok "zsh でないプログラム（cat）の中: 窓から貼る" "pane demo | tail -3 | grep -q '^echo hello-from-history'"
O send-keys -t main Enter
sleep 0.5
O send-keys -t main C-b F
sleep 2
ok "prefix+F ですぐログに残す" "tail -3 $HOME/cases/demo/logs/session.log | grep -q 'echo hello-from-history'"
H send-keys -t demo C-d
sleep 1

echo "== 窓の中で配色を選ぶと、開いている窓の枠の色もすぐ変わる"
O send-keys -t main C-g
sleep 3
for _ in 1 2 3 4; do O send-keys -t main Tab; sleep 1.2; done
O send-keys -t main Enter
sleep 2
O send-keys -t main Down
sleep 0.8
O send-keys -t main Enter
sleep 2
ok "枠が Amber の見出しの色（ff9e64）になった" "O capture-pane -e -p -t main | grep -E '38;2;255;158;100m[┌╭]' >/dev/null"
ok "配色を変えても、窓の題（hackdeck）は消えない" "O capture-pane -p -t main | grep -E '[┌╭┏╔+][─━═-] hackdeck ' >/dev/null"
O send-keys -t main -l 'kyo'
sleep 1.5
O send-keys -t main Enter
sleep 2
ok "配色は文字で絞って選べる（kyo → 京紫）" "grep -q '\"theme\": \"kyo\"' $HOME/.config/hackdeck/settings.json"
O send-keys -t main Tab
sleep 1.5
O send-keys -t main BTab
sleep 2
# 入力欄の頭の字は配色で変わる（いまは京紫）
PR=$(python3 -I -c "import sys; sys.path.insert(0, '$ROOT'); from hackdeck.theme import THEMES; print((THEMES['kyo'].get('prompt') or '> ').strip())")
ok "タブを移って戻ると、配色の一覧のまま（打った文字も）" "O capture-pane -p -t main | grep -q '絞り方' && O capture-pane -p -t main | grep -qF '$PR kyo'"
O send-keys -t main C-u
sleep 0.5
O send-keys -t main -l 'kyo'   # 京紫（和）と Tokyo Night（背景ごと変える）の2行。間に見出しと空行
sleep 1.5
ok "絞ると、当たった行のあるまとまりだけが見出しつきで残る" \
  "screen | grep -q '◆ 和（京の色）' && screen | grep -q '◆ 背景ごと変える' && ! screen | grep -q '◆ ハッカー'"
O send-keys -t main Up
sleep 1
O send-keys -t main Enter
sleep 2
ok "見出しと空行にはカーソルが止まらない（京紫から上へ1つで Tokyo Night）" "grep -q '\"theme\": \"tokyo\"' $HOME/.config/hackdeck/settings.json"
O send-keys -t main C-u
sleep 0.5
O send-keys -t main -l 'ocean'
sleep 1.5
O send-keys -t main Enter
sleep 1.5
O send-keys -t main Tab   # コマンドのタブに戻してから閉じる（次に開くと、閉じる直前の画面から）
sleep 1.5
O send-keys -t main C-g
sleep 1.5

echo "== マウス: 1回のクリックはカーソルを動かすだけ、2回のクリックは Enter と同じ"
# 端末がクリックのときに送る文字列（SGR の形の押す・離す）を、外側のペインに流す（中の専用の tmux が、窓の中の fzf に渡す）。
# at <文字>...: 外側の画面で、下の行から探して最初に見つかった文字の位置（1始まりの 列 行。全角は2マス）
at() { O capture-pane -p -t main | python3 -I -c '
import sys, unicodedata
lines = sys.stdin.read().split("\n")
for want in sys.argv[1:]:
    for y in range(len(lines) - 1, -1, -1):
        i = lines[y].find(want)
        if i >= 0:
            print(sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in lines[y][:i]) + 1, y + 1, want)
            sys.exit()' "$@"; }
click() { O send-keys -t main -l "$(printf '\033[<0;%s;%sM\033[<0;%s;%sm' "$1" "$2" "$1" "$2")"; }
dclick() { O send-keys -t main -l "$(printf '\033[<0;%s;%sM\033[<0;%s;%sm\033[<0;%s;%sM\033[<0;%s;%sm' "$1" "$2" "$1" "$2" "$1" "$2" "$1" "$2")"; }
O send-keys -t main C-g
sleep 3
read -r X Y W < <(at 'showmount' 'smbclient' 'enum4linux')
click "$X" "$Y"
sleep 1.5
ok "コマンドの行を1回クリック: 窓は開いたまま、カーソルだけ動く（説明の箱がその行の $W に）" \
  "screen | grep -q '│コマンド' && ! screen | grep -q 'ここでは Tab は補完' && screen | grep -q '\[探索, $W\]'"
dclick "$X" "$Y"
sleep 2.5
ok "コマンドの行を2回クリック: Enter と同じ（変数の画面へ。前は窓が閉じていた）" "screen | grep -q 'ここでは Tab は補完'"
O send-keys -t main Escape   # コマンド選びの初めの画面へ
sleep 2
for _ in 1 2 3 4; do O send-keys -t main Tab; sleep 1.2; done   # 設定のタブ（配色の一覧のまま）
O send-keys -t main C-u   # 前に打った文字（ocean）が残っている
sleep 0.5
O send-keys -t main -l 'matrix'
sleep 1.5
read -r X Y W < <(at 'Matrix（')
click "$X" "$Y"
sleep 1.5
ok "配色の行を1回クリック: 選ばない（ocean のまま）" "grep -q '\"theme\": \"ocean\"' $HOME/.config/hackdeck/settings.json"
dclick "$X" "$Y"
sleep 2
ok "配色の行を2回クリック: 選ぶ（Matrix）" "grep -q '\"theme\": \"matrix\"' $HOME/.config/hackdeck/settings.json"

echo "== 一覧の見え方を保つ（端の行をクリックしてもずれない・選んで描き直しても同じ所が見える）"
# themes: 見えている配色の行の「名前 列 行」（配色の行は、行の右に英字の名前がある。そのあとは窓の枠かスクロールバー。枠の字は
# 配色で変わる）
themes() { O capture-pane -p -t main | python3 -I -c '
import re, sys, unicodedata
for y, line in enumerate(sys.stdin.read().split("\n"), 1):
    m = re.search(r"\s([a-z][a-z0-9_-]+)\s*(← いま)?\s*[│║┃|]", line)
    if m and "（" in line:
        print(m.group(1), sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line[:m.start(1)]) + 1, y)'; }
O send-keys -t main C-u   # 絞り込みを消して、配色の一覧の全部へ
sleep 1.5
read -r _ X Y < <(themes | sed -n '3p')
# ホイールで一覧のいちばん下まで行ってから、上へ20行（一覧の端ではない中ほどを出す。端ではもともとずれない）
for _ in $(seq 1 60); do O send-keys -t main -l "$(printf '\033[<65;%s;%sM' "$X" "$Y")"; sleep 0.03; done
for _ in $(seq 1 20); do O send-keys -t main -l "$(printf '\033[<64;%s;%sM' "$X" "$Y")"; sleep 0.05; done
sleep 1
themes >"$T/view1"
read -r NAME X Y < <(head -1 "$T/view1")   # いちばん上に見えている配色
click "$X" "$Y"
sleep 1.5
themes >"$T/view2"
ok "一覧のいちばん上の行をクリックしても、一覧はずれない（$NAME）" "[ -n '$NAME' ] && diff -q $T/view1 $T/view2 >/dev/null"
# カーソルを一覧の中ほどへ（起動し直したときに fzf が置く所＝端とは違う所）。そこで選んで、描き直したあとも同じ所が見えるか
for _ in 1 2 3 4; do O send-keys -t main Down; sleep 0.3; done
sleep 1
themes >"$T/view3"
O send-keys -t main Enter
sleep 2.5
themes >"$T/view4"
ok "一覧の中ほどの配色を選んで描き直しても、一覧の同じ所が見える" \
  "[ -s $T/view3 ] && diff -q <(cut -d' ' -f1,3 $T/view3) <(cut -d' ' -f1,3 $T/view4) >/dev/null"
O send-keys -t main Tab   # コマンドのタブに戻してから閉じる
sleep 1.5
O send-keys -t main C-g
sleep 1.5
setting theme '"ocean"'   # このあとの節は既定の配色で（上で選んだ配色は、一覧の行の並びで変わる。窓の枠の字も変わる）

echo "== 検索欄は、どの画面も打つと一覧を絞る（足せる画面は、いちばん下の足す行が残る）。行の Enter で書き換え・Ctrl+W は空白と記号で止まる"
# 行の数は一覧の右下の数（絞った行の数/全部の数）で見る（窓の左右には下のペインの字が見えるので、無い字は探さない）
printf 'alice:Passw0rd!:test.local\nbob:Secret1:corp.local\n' >"$HOME/cases/demo/work/.hack/creds"
O send-keys -t main C-g
sleep 3
O send-keys -t main -l 'zzqq'
sleep 1.5
ok "コマンド選び: 当たる行が無くても、上の枠を空にしない" "screen | grep -q '当たるコマンドは無い'"
O send-keys -t main Escape   # 初期状態へ
sleep 1.5
O send-keys -t main Tab   # 資格情報
sleep 1.5
O send-keys -t main -l 'corp'
sleep 1.5
# パスワードは引用符つきで出る（text.q）
ok "資格情報: 打った文字を含む行（bob）と、足す行だけ" "screen | grep -q 'bob  *.Secret1.' && screen | grep -q '＋ 追加  *corp' && screen | grep -q ' 2/2 '"
# 行を選んで Enter で書き換え（2026-11-07。前は Ctrl+E）。Ctrl+W は空白と記号（: . など）で止まる。保存すると一覧の検索欄は空、
# Alt+← でやめると、書き換えに入る前に打っていた文字のまま
O send-keys -t main Up
sleep 1
O send-keys -t main Enter
sleep 2
ok "資格情報: 行で Enter で書き換え（その行が検索欄に入る）" "screen | grep -q '＋ 保存  *bob:Secret1:corp.local'"
O send-keys -t main C-w
sleep 1.5
ok "Ctrl+W は . で止まる（corp.local の local だけ消える）" "screen | grep -q '＋ 保存  *bob:Secret1:corp\.  '"
O send-keys -t main C-w
sleep 1.5
ok "もう一度 Ctrl+W で、: の手前まで（説明が消える）" "screen | grep -q '＋ 保存  *bob:Secret1:  '"
O send-keys -t main -l 'corp.htb'; O send-keys -t main Enter
sleep 2
ok "書き換えを Enter で保存して一覧へ（検索欄は空）" \
  "grep -qx 'bob:Secret1:corp.htb' $HOME/cases/demo/work/.hack/creds && screen | grep -q '＋ 追加  *user:pass:説明 を打って Enter'"
O send-keys -t main -l 'alice'
sleep 1.5
O send-keys -t main Up
sleep 1
O send-keys -t main Enter
sleep 2
O send-keys -t main M-Left
sleep 2
ok "書き換えを Alt+← でやめると、打っていた文字（alice）のままの一覧へ" \
  "screen | grep -q '＋ 追加  *alice ' && screen | grep -q ' 2/2 ' && grep -qx 'alice:Passw0rd!:test.local' $HOME/cases/demo/work/.hack/creds"
O send-keys -t main C-u
sleep 1
O send-keys -t main Tab   # 環境
sleep 1.5
O send-keys -t main -l '10.10.14'
sleep 1.5
ok "環境: 値でも絞る（10.10.14 → LHOST と足す行だけ）" "screen | grep -q 'LHOST  *10\.10\.14\.7' && screen | grep -q ' 2/2 '"
O send-keys -t main C-u
sleep 1
# 値に : がある変数を行の Enter で書き換え、そのまま保存しても値が変わらない（最後の : の後ろは説明なので、: を足して出す。
# 前は http://web01:8080/ の 8080/ を説明と読み、値が http://web01 になった）
O send-keys -t main -l 'URL=http://web01:8080/'; O send-keys -t main Enter
sleep 2
O send-keys -t main -l 'web01'
sleep 1.5
O send-keys -t main Up
sleep 1
O send-keys -t main Enter
sleep 2
ok "環境: 行で Enter で書き換え（値に : があれば最後に : を足して出す）" "screen | grep -q '＋ 保存  *URL:http://web01:8080/:'"
O send-keys -t main Enter
sleep 2
ok "そのまま保存しても、値は変わらない" "grep -qx 'export URL=http://web01:8080/' $HOME/cases/demo/work/.hack/env"
for _ in 1 2; do O send-keys -t main Tab; sleep 1.5; done   # 案件 → 設定（配色の一覧が開いている）
O send-keys -t main Escape   # 設定の項目の一覧へ
sleep 1.5
O send-keys -t main -l 'ログの'
sleep 1.5
ok "設定の項目の一覧: 打った文字で絞る（前は何も起きなかった）" "screen | grep -q 'ログのファイル  *logs/session.log' && screen | grep -q ' 2/2 '"
O send-keys -t main -l 'zzz'
sleep 1.5
ok "設定の項目の一覧: 当たる行が無くても、上の枠を空にしない" "screen | grep -q '当たる項目は無い'"
O send-keys -t main C-u; O send-keys -t main -l '並ぶ環境変数'
sleep 1.5
O send-keys -t main Enter   # どの案件にも並ぶ環境変数（一覧を書く項目）
sleep 2
O send-keys -t main -l 'KRB'
sleep 1.5
ok "設定の一覧を書く項目: 打った文字で絞り、足す行は残る" "screen | grep -q 'KRB5_CONFIG' && screen | grep -q '＋ 追加  *KRB' && screen | grep -q ' 3/3 '"
O send-keys -t main Up
sleep 1
O send-keys -t main Enter
sleep 2
ok "設定の一覧を書く項目: 行で Enter で書き換え（足さない。資格情報・環境のタブと同じ）" \
  "screen | grep -q '＋ 保存  *KRB5' && ! grep -q '\"KRB\"' $HOME/.config/hackdeck/settings.json"
O send-keys -t main M-Left
sleep 2
ok "Alt+← でやめると、打っていた文字（KRB）のままの一覧へ" "screen | grep -q '＋ 追加  *KRB ' && screen | grep -q ' 3/3 '"
O send-keys -t main Escape   # 項目の一覧へ
sleep 1.5
O send-keys -t main Tab   # コマンドのタブに戻してから閉じる
sleep 1.5
O send-keys -t main C-g
sleep 1.5

echo "== メモのタブ（設定で出す。本物の vim で書き、データの置き場所の memo.md に残す）"
MEMO=$HOME/cases/demo/work/.hack/memo.md
VIMTOP='ここではノーマルモードで'   # メモのタブ（vim）のいちばん上の行（タブの並びの右端）
setting memo true
O send-keys -t main C-g
sleep 3
ok "設定で出すと、タブの並びの環境と案件の間にメモ" "screen | grep -q '環境  メモ  案件'"
for _ in 1 2 3; do O send-keys -t main Tab; sleep 1.5; done   # コマンド → 資格情報 → 環境 → メモ
ok "メモのタブで vim が開く（いちばん上にタブの並び）" "screen | grep -q '$VIMTOP'"
# below_tabs: 窓の中で、タブの並びの次の行が空か（窓の枠の内側だけ。窓の左右には下のペインの字が見える）
below_tabs() { O capture-pane -p -t main | python3 -I -c '
import sys, unicodedata
w = lambda c: 2 if unicodedata.east_asian_width(c) in "WF" else 1
def cells(line):   # 1マスずつの字（全角は2マス目を空に）
    out = []
    for c in line:
        out += [c] + [""] * (w(c) - 1)
    return out
lines = sys.stdin.read().split("\n")
i = next(i for i, l in enumerate(lines) if "コマンド  資格情報" in l)
top = cells(lines[i])
left, right = top.index("│"), len(top) - 1 - top[::-1].index("│")   # 窓の左右の枠
sys.exit(0 if not "".join(cells(lines[i + 1])[left + 1:right]).strip() else 1)'; }
ok "メモのタブも、タブの並びの下を1行あけ、上の枠（題・置き場所）と説明欄がほかのタブと同じ形" \
  "below_tabs && screen | grep -q 'メモ \[demo\]' && screen | grep -q '置き場所 ~/cases/demo/work/.hack/memo.md' && screen | grep -q 'memo.md ─ この案件の軽いメモ'"
O send-keys -t main i; O send-keys -t main -l 'hello-memo'; O send-keys -t main Escape
sleep 1.5
O send-keys -t main Tab   # ノーマルモードの Tab で次のタブ（案件）へ
sleep 2
ok "Tab で次のタブ（案件）へ移り、メモは保存される" "grep -q '^hello-memo\$' $MEMO && screen | grep -q 'Ctrl+T 日付を頭に'"
O send-keys -t main BTab
sleep 2
ok "Shift+Tab でメモへ戻ると、書いた中身がある" "screen | grep -q '$VIMTOP' && screen | grep -q 'hello-memo'"
O send-keys -t main -l 'Go'; O send-keys -t main -l 'second-line'; O send-keys -t main Escape
sleep 1.5
O send-keys -t main C-g
sleep 2
ok "Ctrl+G で窓を閉じても保存される" "grep -q '^second-line\$' $MEMO && ! screen | grep -q '$VIMTOP'"
O send-keys -t main C-g
sleep 3
ok "次に開くと、メモのタブから（中身も）" "screen | grep -q '$VIMTOP' && screen | grep -q 'second-line'"
O send-keys -t main -l ':q'; O send-keys -t main Enter
sleep 2
ok ":q で窓を閉じる" "! screen | grep -q '$VIMTOP'"
O send-keys -t main C-g   # 次の節のために、コマンドのタブに戻してから閉じる（メモ → 案件 → 設定 → コマンド）
sleep 3
for _ in 1 2 3; do O send-keys -t main Tab; sleep 1.5; done
O send-keys -t main C-g
sleep 1.5
setting memo false   # このあとの節は、メモのタブの無い並びで試す

echo "== 窓の案件のタブで切り替える"
"$HD" case make demo2 >/dev/null
O send-keys -t main C-g
sleep 3
for _ in 1 2 3; do O send-keys -t main Tab; sleep 1.5; done
O send-keys -t main -l 'demo2'
sleep 2
O send-keys -t main Enter
sleep 4
ok "demo2 に切り替わった" "[ \"\$(H list-clients -F '#{client_session}')\" = demo2 ]"

echo "== 終えた案件の並びを残して戻す"
H new-window -t demo2 -n second -c "$HOME/cases/demo2/work"
H split-window -t demo2:second -c "$HOME/cases/demo2/work"
sleep 2
H send-keys -t demo2:second.0 'echo in-second-window' Enter
sleep 1
H switch-client -t demo
sleep 1
"$HD" case kill demo2
ok "終えた" "! H has-session -t demo2 2>/dev/null"
ok "並びと画面を残した" "[ -f $HOME/cases/demo2/work/.hack/session/layout.tsv ] && grep -q in-second-window $HOME/cases/demo2/work/.hack/session/1.0.txt"
H send-keys -t demo "$HD case attach demo2" Enter
sleep 4
ok "戻した（窓2つ・2つ目はペイン2つ）" "[ \"\$(H list-windows -t demo2 -F '#{window_panes}' | tr '\n' ' ')\" = '1 2 ' ]"
ok "戻した画面に前の中身" "pane demo2:second.0 | grep -q in-second-window"
ok "戻したペインにもシェルの部分が入る" "[ \"\$(H show-options -pqv -t demo2:second.1 @hack_shell)\" = 1 ]"
ok "zsh の初めての設定の画面が出ていない" "! pane demo2:second.1 | grep -q 'zsh-newuser-install\|Type one of the keys'"

echo "== 案件の名前を変える（案件のタブの Ctrl+E。止まっている案件だけ）"
"$HD" case make ren1 >/dev/null
mkdir -p "$HOME/cases/ren1/work/sub"
H new-session -d -s ren1 -c "$HOME/cases/ren1/work/sub"
sleep 1
"$HD" case kill ren1   # 並びを残して終える（ペインはサブフォルダ）
# to_tab <そのタブにだけ出る文字>: そのタブまで Tab で移る（窓がどのタブから開くかに頼らない。demo2 には案件のタブから入ったので、
# 窓は案件のタブから開く）
to_tab() { for _ in 1 2 3 4 5 6; do screen | grep -q "$1" && return 0; O send-keys -t main Tab; sleep 1.5; done; }
O send-keys -t main C-g
sleep 3
to_tab 'Ctrl+T 日付を頭に'   # 案件のタブ
O send-keys -t main -l 'ren1'
sleep 2
O send-keys -t main C-e
sleep 2
ok "Ctrl+E で、名前を直す1行になる" "screen | grep -q '✎ 名前を変える  ren1 →'"
O send-keys -t main C-u; O send-keys -t main -l 'ren1-new'
sleep 1.5
O send-keys -t main Enter
sleep 2.5
ok "Enter で名前が変わる（フォルダ・残した並びの中の場所）" \
  "[ -d $HOME/cases/ren1-new ] && [ ! -e $HOME/cases/ren1 ] && grep -q 'ren1-new/work/sub' $HOME/cases/ren1-new/work/.hack/session/layout.tsv && screen | grep -q 'ren1 を ren1-new に変えた'"
O send-keys -t main C-u; O send-keys -t main -l 'demo2'   # いま入っている（動いている）案件
sleep 2
O send-keys -t main C-e
sleep 2
ok "動いている案件は変えない（Ctrl+D で終えてから）" "screen | grep -q 'demo2 は動いている' && [ -d $HOME/cases/demo2 ]"
O send-keys -t main C-u
sleep 1.5
to_tab 'Ctrl+R 履歴'   # コマンドのタブに戻してから閉じる
O send-keys -t main C-g
sleep 1.5
ok "コマンドでも変えられる（hackdeck case rename）" "'$HD' case rename ren1-new ren1-cli >/dev/null && [ -d $HOME/cases/ren1-cli ]"

echo "== hackdeck の外で名前を変えても（止まっている案件。直前の案件・並び・窓の画面は、案件の目印で引き継ぐ）"
H send-keys -t demo2:0.0 "$HD case attach ren1-cli" Enter   # 入る（直前の案件になる。専用の tmux の中は切り替え）
sleep 4
ok "（準備）ren1-cli に入った" "[ \"\$(H list-clients -F '#{client_session}')\" = ren1-cli ]"
O send-keys -t main C-g
sleep 3
to_tab 'Enter 開く（する・しないは'   # 窓で設定のタブを開いて閉じる（次に開くとここから）
O send-keys -t main C-g
sleep 1.5
H switch-client -t demo2
sleep 1
"$HD" case kill ren1-cli   # 並びを残して終える
mv "$HOME/cases/ren1-cli" "$HOME/cases/ren1-mv"   # hackdeck の外で名前を変える
H send-keys -t demo2:0.0 "$HD case attach" Enter   # 名前を省く（直前の案件）
sleep 4
ok "名前を省いた hackdeck case attach で、名前を変えた案件（ren1-mv）に入る" "[ \"\$(H list-clients -F '#{client_session}')\" = ren1-mv ]"
ok "サブフォルダにいたペインは、新しい名前のフォルダの同じ場所に戻る" \
  "[ \"\$(H display -p -t ren1-mv:0.0 '#{pane_current_path}')\" = $HOME/cases/ren1-mv/work/sub ]"
O send-keys -t main C-g
sleep 3
ok "窓は、名前を変える前に開いていた画面（設定のタブ）から開く" "screen | grep -q 'Enter 開く（する・しないは'"
O send-keys -t main C-g
sleep 1.5
H switch-client -t demo2
sleep 1

echo "== 設定を読み直しても増えない・窓のキーを変える"
for _ in 1 2; do setting stamps false; conf; setting stamps true; conf; done
ok "離れたときのフックは1つ" "[ \"\$(H show-hooks -g | grep -c client-detached)\" = 1 ]"
ok "状態の行（status-right）に足していない" "! H show -gv status-right | grep -q hackdeck"
setting key '"M-g"'; conf
ok "前のキー C-g を外し、M-g にした" "! H list-keys -T root | grep -q ' C-g ' && H list-keys -T root | grep -q ' M-g '"
setting key '"C-g"'; conf
ok "C-g に戻した" "H list-keys -T root | grep -q ' C-g ' && ! H list-keys -T root | grep -q ' M-g '"

echo "== tmux の外の端末で Ctrl+G（待合の上に窓）"
"$HD" case make demo3 >/dev/null
O new-session -d -s plain -x 160 -y 45 "env -u TMUX -u TMUX_PANE HD_INIT=$HD SHELL=/usr/bin/zsh zsh -i"
sleep 2
O send-keys -t plain C-g
sleep 3.5
ok "待合につながり、その上に窓が開く" "[ \"\$(H list-clients -F '#{client_session}' | grep -c _hackdeck)\" = 1 ] && O capture-pane -p -t plain | grep -q '│案件  設定'"
O send-keys -t plain C-g
sleep 2
ok "選ばずに閉じると、待合から離れて端末に戻る" "! H list-clients -F '#{client_session}' | grep -q _hackdeck && [ \"\$(O display -p -t plain '#{pane_current_command}')\" = zsh ]"
O send-keys -t plain C-g
sleep 3.5
O send-keys -t plain -l 'demo3'
sleep 2
O send-keys -t plain Enter
sleep 4
ok "止まっている案件で Enter → 入る" "H list-clients -F '#{client_session}' | grep -q '^demo3\$'"
O send-keys -t plain 'echo drawn-$((6 * 7))' Enter
sleep 2
ok "入ったあとも画面が描かれる（固まらない）" "O capture-pane -p -t plain | grep -q '^drawn-42'"
O send-keys -t plain C-b d
sleep 2
ok "prefix+d で端末に戻る" "! H list-clients -F '#{client_session}' | grep -q '^demo3\$' && [ \"\$(O display -p -t plain '#{pane_current_command}')\" = zsh ]"
ok "離れても tmux の [detached …] と改行が端末に出ない（プロンプトの行が増えない）" "! O capture-pane -p -t plain | grep -q 'detached'"

echo "== 案件の外も tmux で（設定の outside。VTE の端末で開いた zsh を、はじめから専用の tmux の案件の外のセッションで）"
setting outside true
# VTE の端末の代わり（VTE_VERSION を付ける。この試しを動かしている Orca や VS Code の目印は外す）
O new-session -d -s vte -x 160 -y 45 "env -u TMUX -u TMUX_PANE -u ORCA_APP_VERSION -u TERM_PROGRAM -u SSH_TTY VTE_VERSION=7600 HD_INIT=$HD SHELL=/usr/bin/zsh zsh -i"
sleep 4
OUT=$(H list-sessions -F '#{session_name} #{@hack_outside}' | awk '$2 == 1 {print $1}')
ok "開いた端末が、案件の外のセッション（$OUT）に入る" "[ -n '$OUT' ] && H list-clients -F '#{client_session}' | grep -qx '$OUT'"
O send-keys -t vte 'sleep 300' Enter
sleep 1.5
O send-keys -t vte C-g
sleep 3.5
ok "プログラム（sleep）が動いていても、Ctrl+G で窓が開く（案件と設定のタブ）" "O capture-pane -p -t vte | grep -q '│案件  設定'"
O send-keys -t vte C-u   # 待合の節で打った demo3 が、案件の外の画面に残っている（閉じる直前の画面から開く）
sleep 0.5
O send-keys -t vte -l 'demo3'
sleep 2
O send-keys -t vte Enter
sleep 4
ok "案件を選ぶと、その端末が案件のセッションへ" "H list-clients -F '#{client_session}' | grep -qx demo3"
O send-keys -t vte C-b d
sleep 3
ok "prefix+d で、案件の外のセッションへ戻る（動いていた sleep もそのまま）" \
  "H list-clients -F '#{client_session}' | grep -qx '$OUT' && [ \"\$(H display -p -t '=$OUT:' '#{pane_current_command}')\" = sleep ]"
O send-keys -t vte C-b d
sleep 2.5
ok "案件の外のセッションで prefix+d: 離れない（離れる先が無い）" "H list-clients -F '#{client_session}' | grep -qx '$OUT'"
O kill-session -t vte   # 端末を閉じる
sleep 3
ok "端末を閉じると、案件の外のセッションも終わる" "! H list-sessions -F '#{@hack_outside}' | grep -qx 1"
setting outside false

echo
echo "OK $pass / NG $fail"
[ "$fail" = 0 ]
