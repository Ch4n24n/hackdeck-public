# hackdeck: 案件のセッションの zsh に入る部分。専用の tmux サーバー（tmux -L hackdeck）のシェルだけが、自分の設定（~/.zshrc
# など）を読んだあとの最初のプロンプトで読む（ZDOTDIR の .zshenv を hackdeck が作り、専用のサーバーがそこへ向ける。
# ~/.zshrc には何も書かない）。
#   - ~hack・~cmn: 案件の作業フォルダ（~hack と打って Enter で戻る。setopt autocd のとき。cd ~hack でも）と、案件をまたぐ
#     置き場所（よく使うものの一覧）
#   - 環境変数: 案件の env を、コマンドを打つたびに読み直す。シェルの export・unset も書き戻す（環境のタブと同じファイル）
#   - ログ: コマンドごとに、画面に出たもの（プロンプト・コマンド・出力）を案件のログに足す。prefix+F ですぐ残す
#   - 実行の時刻: コマンドの前と後に、時刻とかかった秒数を出す（設定の stamps）
#   - netexec: 見つけた資格情報に、見つけた日時を付ける（資格情報のタブの Ctrl+N）
# 案件の場所は、セッションの環境（HACK_ROOT・HACK_HOME・HACK_STATE・HACK_LOG・NXC_PATH。hackdeck が入れる）で決まる。
# いまいる場所（cwd）は見ない
[[ -n $HACK_ROOT && -n $TMUX && -n $TMUX_PANE ]] || return 0
autoload -Uz add-zsh-hook
zmodload zsh/datetime 2>/dev/null
typeset -g _hack_tool=${HACK_TOOL:-hackdeck}

# --- 場所 ---------------------------------------------------------------------------------
# 作業フォルダにいるとき、プロンプトとタブの題（%~）は ~hack に縮む。~hack と打って Enter で作業フォルダへ（setopt autocd の
# とき。cd ~hack でも）。設定の「作業フォルダへ戻るコマンド」があれば、その名前でも戻る（前の tmux-op の op。下の _hack_conf）
hash -d hack=$HACK_HOME
[[ -n $HACK_COMMON ]] && hash -d cmn=$HACK_COMMON

# --- 設定（コマンドの前後の時刻・戻るコマンド）-------------------------------------------------
# hackdeck が設定を保存すると書き換わるファイル（HACK_SHELL_CONF。1行に 名前=値）を、プロンプトのたびに見る（中身が変わった
# ときだけ読み直す。$(<…) なので、ほかのプロセスは起こさない）。開いているペインにも、次に打つコマンドから効く（preexec でも見る）
typeset -g _hack_conf_seen="" _hack_stamps=0 _hack_home_cmd=""
_hack_conf() {
  local body line stamps=0 home=""
  [[ -r $HACK_SHELL_CONF ]] && body="$(<$HACK_SHELL_CONF)"
  [[ $body == "$_hack_conf_seen" ]] && return 0
  _hack_conf_seen=$body
  for line in ${(f)body}; do
    case ${line%%=*} in
      stamps)   stamps=${line#*=} ;;
      home_cmd) home=${line#*=} ;;
    esac
  done
  _hack_stamps=$stamps
  if [[ $home != "$_hack_home_cmd" ]]; then
    # 前に作った戻るコマンドを消し（hackdeck が作ったものだけ）、新しい名前で作る
    [[ -n $_hack_home_cmd ]] && (( $+functions[$_hack_home_cmd] )) && unfunction $_hack_home_cmd
    [[ $home =~ '^[A-Za-z_][A-Za-z0-9_-]*$' ]] && functions[$home]='cd -- "$HACK_HOME"'
    _hack_home_cmd=$home
  fi
  return 0
}


# --- 環境変数 -------------------------------------------------------------------------------
# 読み直し: コマンドを打つたび（preexec）とプロンプトを出すたび（precmd）に、ファイルの中身が前に読んだときと違えば source
# する。前に読んだのにファイルから消えた名前は unset する（シェルや案件のセッションが壊れる名前は外す。env.py の
# ENV_RESERVED と同じ）。これで動いているペインにも、次に打つコマンドから届く。zsh が前にいないペイン（ssh・リバース
# シェル・vim）には届かない（zsh に戻れば、次のコマンドから）
typeset -g _hack_env_seen=""
typeset -ga _hack_env_loaded _hack_env_pending

_hack_env_reload() {
  local f=$HACK_STATE/env body line name
  local -a now gone
  [[ -r $f ]] && body="$(<$f)"
  [[ $body == "$_hack_env_seen" ]] && return 0
  _hack_env_seen=$body
  for line in ${(f)body}; do
    [[ $line == 'export '*=* ]] || continue
    name=${${line#export }%%=*}
    [[ $name =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]] && now+=($name)
  done
  gone=(${_hack_env_loaded:|now})
  gone=(${gone:#(PATH|HOME|SHELL|USER|LOGNAME|TERM|PWD|OLDPWD|LANG|ZDOTDIR|TMUX|TMUX_PANE|NXC_PATH|HACK_*)})
  (( $#gone )) && unset $gone
  [[ -n $body ]] && source $f
  _hack_env_loaded=($now)
  return 0
}

# 書き戻し: export・unset した名前を preexec で控え、precmd で実行後の値を hackdeck env-capture に渡す（書き戻す名前だけ
# 書く。unset は名前に関係なく消す）。書くのは評価済みの値なので、export TARGET="$(...)" でも読み直しで再実行されない。
# ${(z)} はシェルと同じ単語分け。コマンドの位置の export・typeset・declare・unset だけを見る
_hack_env_names() {   # reply に set:名前・unset:名前
  local w mode="" cmdpos=1
  reply=()
  for w in ${(z)1}; do
    case "$w" in
      ';'|'&&'|'||'|'|'|'&'|'{'|'('|'then'|'do'|'else'|'!') cmdpos=1; mode=""; continue ;;
    esac
    if (( cmdpos )); then
      cmdpos=0
      case "$w" in
        export|typeset|declare) mode=set;   continue ;;
        unset)                  mode=unset; continue ;;
        *)                      mode="" ;;
      esac
    fi
    [[ -z "$mode" ]] && continue
    [[ "$w" == -* ]] && continue          # export -g のようなフラグ
    # set 側は代入（NAME=…）だけを拾う。typeset -p TARGET のような「表示するだけ」のコマンドを設定と取り違えない
    if [[ "$mode" == unset ]]; then
      if [[ "$w" =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]]; then reply+=("unset:$w"); else mode=""; fi
    elif [[ "$w" == *=* && "${w%%=*}" =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]]; then
      reply+=("set:${w%%=*}")
    else
      mode=""                             # 変数の代入でない語が来たら、そこで切る
    fi
  done
}

_hack_env_capture() {
  local p n
  local -a a seen
  for p in $_hack_env_pending; do
    n=${p#*:}
    (( ${seen[(Ie)$n]} )) && continue
    seen+=($n)
    # 同じコマンドで export も unset もしたときは、実行後に残っているかで決める
    if (( ${_hack_env_pending[(Ie)set:$n]} && ${+parameters[$n]} )); then
      a+=(set $n "${(P)n}")
    else
      a+=(unset $n '')
    fi
  done
  _hack_env_pending=()
  (( $#a )) && command $_hack_tool env-capture "${a[@]}" 2>/dev/null
  return 0
}

# --- ログ -----------------------------------------------------------------------------------
# 画面に出たもの（tmux の capture-pane。見たままの文字）を、コマンドごとに案件のログ（HACK_LOG）に足す。前に残した所は
# ペインの @hack_last（履歴の行数＋カーソルの行）で、prefix+F（hackdeck log flush。panelog.py）と同じ値を使う（同じ所を
# 2回残さない）。書くときはファイルに鍵をかける（ほかのペインのブロックと混ざらない）。リバースシェルの中など、zsh が前に
# いない間はプロンプトに戻らないので、戻ったときに全体を1つのブロックで残す（途中で残すときは prefix+F）
typeset -g _hack_ran="" _hack_skip=""

_hack_log_pos() {   # REPLY に「履歴の行数 カーソルの行」
  REPLY=$(tmux display-message -p -t $TMUX_PANE '#{history_size} #{cursor_y}' 2>/dev/null)
  [[ $REPLY == <->' '<-> ]]
}

_hack_log_mark() {   # いまの位置を基準にする（これより前の画面は残さない）
  _hack_log_pos || return 0
  tmux set-option -p -t $TMUX_PANE @hack_last $(( ${REPLY% *} + ${REPLY#* } )) 2>/dev/null
  return 0
}

_hack_log_preexec() {
  _hack_ran=1
  # ログを画面に出すコマンド（cat ログ など）は残さない（画面に出たログを次に拾い、見るたびに倍々に増えるため）
  [[ -n $HACK_LOG && ( $1 == *${HACK_LOG:t}* || $1 == *${HACK_LOG:h:t}/* ) ]] && _hack_skip=1
  return 0
}

_hack_log() {
  [[ -n $_hack_ran ]] || return 0
  _hack_ran=""
  local skip=$_hack_skip
  _hack_skip=""
  [[ -n $HACK_LOG ]] || return 0
  local last hs cy now blk
  last=$(tmux show-options -pqv -t $TMUX_PANE @hack_last 2>/dev/null)
  _hack_log_pos || return 0
  hs=${REPLY% *} cy=${REPLY#* }
  now=$(( hs + cy ))
  # 基準の無いペインは、基準を張るだけで書かない（画面に残っている前のスクロールバックを丸ごと拾わない）
  if [[ $last != <-> ]]; then
    tmux set-option -p -t $TMUX_PANE @hack_last $now 2>/dev/null
    return 0
  fi
  if [[ -z $skip ]] && (( now > last )); then
    # 行末の空白と、頭の空行は落とす
    blk=$(tmux capture-pane -p -J -t $TMUX_PANE -S $(( last - hs )) -E $(( cy - 1 )) 2>/dev/null |
          sed -e 's/[[:space:]]*$//' -e '/./,$!d')
    if [[ -n $blk ]]; then
      mkdir -p ${HACK_LOG:h} 2>/dev/null
      # コマンドとコマンドの間に空行2つ（見やすく）
      { flock -w 5 3 && printf '%s\n\n\n' "$blk" >&3 } 3>>$HACK_LOG 2>/dev/null
    fi
  fi
  # 残さなかったときも位置は進める（画面に出たログを、次のコマンドのブロックとして拾わない）
  tmux set-option -p -t $TMUX_PANE @hack_last $now 2>/dev/null
  return 0
}

# --- 実行の時刻 -----------------------------------------------------------------------------
# コマンドの前に時刻、後に時刻とかかった秒数（設定の stamps。_hack_conf が読む）
typeset -g _hack_t0=""

_hack_stamp_start() {
  [[ $_hack_stamps == 1 ]] || return 0
  _hack_t0=$EPOCHREALTIME
  print -P "%F{240}──── %F{cyan}%D{%Y/%m/%d %H:%M:%S} %F{240}────%f"
}

_hack_stamp_end() {
  [[ -n $_hack_t0 ]] || return 0
  local el
  printf -v el %.3f $(( EPOCHREALTIME - _hack_t0 ))
  _hack_t0=""
  print -P "%F{240}──── %F{cyan}%D{%Y/%m/%d %H:%M:%S} %F{240}[%F{cyan}${el}s%F{240}] ────%f"
}

# 自分の precmd 関数（~/.zshrc の precmd()。Kali の既定はプロンプトの前に空行を出す）より先に、終わりの時刻を出す（zsh は
# precmd 関数を precmd_functions より先に呼ぶので、そのままだと空行のあとに時刻が出る）。この中だけの入れ替えで、~/.zshrc は
# 触らない。~/.zshrc を読み直して precmd が作り直されたときも、precmd_functions の _hack_precmd が出す（2回は出さない）
# 写すのは functions -c（functions[名前]=$functions[precmd] で写すと、中の日本語や罫線の文字が化ける。zsh の中での文字の
# 持ち方が二重にかかるため。2026-10-31、本人の .zshrc の時刻の罫線で確かめた）
if (( $+functions[precmd] )) && [[ $functions[precmd] != *_hack_stamp_end* ]]; then
  functions -c precmd _hack_user_precmd
  precmd() { local st=$?; _hack_stamp_end; () { return $st }; _hack_user_precmd "$@" }
fi

# --- netexec ---------------------------------------------------------------------------------
# netexec が見つけた資格情報の、見つけた日時を残す（netexec の DB には時刻が無い）。DB がその記録（hackdeck-seen.tsv）より
# 新しくなったときだけ、裏で hackdeck nxc-stamp を呼ぶ（netexec を打ったあとの最初のプロンプト。ふだんのプロンプトは、
# ファイルの時刻を比べるだけ）。NXC_PATH は案件のセッションの環境（案件のデータの nxc）
_hack_nxc_stamp() {
  local -a db=($NXC_PATH/workspaces/*/*.db(N.om[1]))
  if (( $#db )) && [[ $db[1] -nt $NXC_PATH/hackdeck-seen.tsv ]]; then
    command $_hack_tool nxc-stamp >/dev/null 2>&1 &!
  fi
  return 0
}

# --- フック -----------------------------------------------------------------------------------
_hack_preexec() {
  _hack_conf          # 設定を変えた直後のコマンドにも効くように（戻るコマンドはここで作れば、このコマンドから使える）
  _hack_env_names "$1"
  _hack_env_pending+=($reply)
  _hack_env_reload
  _hack_log_preexec "$1"
  _hack_stamp_start
}

# --- 並びを残す ---------------------------------------------------------------------------
# 案件のセッションの窓・ペイン・画面を、15分に1回まで残す（離れたときは tmux が残す）。ふだんのプロンプトは、時刻の
# ファイル（HACK_AUTOSAVE）の更新時刻を見るだけ
_hack_autosave() {
  [[ -n $HACK_AUTOSAVE ]] || return 0
  local -a fresh=($HACK_AUTOSAVE(N.mm-15))
  (( $#fresh )) || command $_hack_tool case autosave >/dev/null 2>&1 &!
  return 0
}

_hack_precmd() {
  local st=$?                              # プロンプトの %? を壊さない
  _hack_stamp_end
  _hack_conf
  _hack_log
  _hack_env_capture
  _hack_env_reload
  _hack_nxc_stamp
  _hack_autosave
  return $st
}

# 読み直したときに二重にしない。どちらも先頭に置く（ほかのフックが出す文字より先に、時刻を出す）
add-zsh-hook -D preexec '_hack_*' 2>/dev/null
add-zsh-hook -D precmd  '_hack_*' 2>/dev/null
preexec_functions=(_hack_preexec $preexec_functions)
precmd_functions=(_hack_precmd $precmd_functions)

# --- 始めに -----------------------------------------------------------------------------------
_hack_log_mark      # このシェルより前の画面は残さない
_hack_conf
_hack_env_reload
tmux set-option -p -t $TMUX_PANE @hack_shell 1 2>/dev/null   # このペインのシェルに hackdeck の部分が入った（確かめる目印）
