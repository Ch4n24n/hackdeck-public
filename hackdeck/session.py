"""案件の tmux セッション。専用の tmux サーバー（tmux -L hackdeck）に、案件ごとに1つ作る。

ふだんの tmux（~/.tmux.conf・ふだんのサーバー）には書かない。サーバーの設定（窓のキー・シェルへの注入・並びの保存）は、
設定から毎回 paths.TMUX_CONF に作って読ませる（write_conf）。セッションには案件の環境（case.case_env の HACK_ROOT など）を
入れるので、その中のシェルと窓は、どこに cd しても同じ案件になる。止まっている案件は、残した並び（窓・ペイン・場所・
画面の中身。案件のデータの session/）から戻す。"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .paths import AUTOSAVE_STAMP, CASE_LAST, COMMON_LISTS, RESURRECT_DIR, ROOT, SHELL_CONF, SHELL_DIR, TMUX_CONF, ZDOTDIR
from .text import ANSI_RE
from .case import (CASE_NAME_RE, case_dirs, case_env, case_file, case_path, ensure_state, is_case_dir, last_case,
                   last_case_set, log_of, work_of)
from . import settings
from . import theme

SOCKET = os.environ.get("HACKDECK_TMUX_SOCKET") or "hackdeck"   # 試すときは別の名前（隔離した tmux）
# 案件の外の待合。tmux の外で窓を開くとき、窓の下に敷くセッション（端末だけでは tmux の窓を描けないため）。名前の頭が英数字で
# ないので、案件の名前にはならない（案件の一覧にも出ない）
LOBBY = "_hackdeck"
LOBBY_CMD = "printf '\\033[2J\\033[H\\n  hackdeck（案件の外）\\n'; exec sleep infinity"
# 案件の外のセッション（設定の outside。2026-11-01、本人の指摘「案件外で Ctrl+G を押す際に、nosleep とかが起動していると反応
# しない。案件内のように、ターミナルの状況に依存しない動きにしたい」）。VTE の端末で開いた zsh を、はじめから専用の tmux の中で
# 動かす（窓のキーを tmux が受けるので、どのプログラムが動いていても効く）。端末ごとに1つ（名前は端末の番号。頭が英数字で
# ないので、案件の名前にはならない）。印は @hack_outside、持ち主の端末は @hack_owner（端末を閉じたら outside_gc が終える）
OUTSIDE_PREFIX = "_out-"
SESSION_KEEP_LINES = 2000   # 画面の中身を残す行数（ペインごと。全部はログにある）
AUTOSAVE_EVERY = 15 * 60    # 並びを自動で残す間隔（秒）
TOOL = ROOT / "bin" / "hackdeck"


def tmux(*args, start=False):
    """専用の tmux サーバーを1回呼んで、標準出力を返す（失敗したとき・サーバーが動いていないときは None）。
    start: サーバーを起こすかもしれない呼び出し（設定のファイルを渡す）"""
    cmd = ["tmux", "-L", SOCKET, *(["-f", str(TMUX_CONF)] if start else []), *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def in_server():
    """いま専用の tmux サーバーの中か（$TMUX のソケットの名前で見る）"""
    return Path(os.environ.get("TMUX", "").split(",")[0]).name == SOCKET


def tmux_sessions():
    """動いているセッション {名前: {id, windows, used, attached}}。操作は ID で指す"""
    out = tmux("list-sessions", "-F",
               "#{session_id}\t#{session_windows}\t#{session_activity}\t#{session_attached}\t#{session_name}") or ""
    res = {}
    for line in out.splitlines():
        sid, wins, used, att, name = line.split("\t", 4)
        res[name] = {"id": sid, "windows": int(wins or 0), "used": int(used or 0), "attached": int(att or 0)}
    return res


# --- サーバーの設定 ---------------------------------------------------------------------------------

def _user_zdotdir():
    """もとの ZDOTDIR（案件のセッションの中から作り直すときは、注入の前の値）。ホームと同じなら空（zsh には同じ）"""
    v = (os.environ.get("HACK_USER_ZDOTDIR", "") if os.environ.get("ZDOTDIR") == str(ZDOTDIR)
         else os.environ.get("ZDOTDIR", ""))
    return "" if v.rstrip("/") in ("", str(Path.home())) else v


def zle_key(key):
    """tmux のキーの書き方を、zsh の bindkey の書き方に（C-g → ^g、M-g → ^[g）。書けないキー（F5 など）は None"""
    m = re.fullmatch(r"((?:[CM]-)*)([A-Za-z0-9])", key)
    if not m:
        return None
    s = "^" + m.group(2).lower() if "C-" in m.group(1) else m.group(2)
    return "^[" + s if "M-" in m.group(1) else s


def _tq(v):
    """tmux の設定に書く '…'（' を含む値は書かない）"""
    v = str(v)
    if "'" in v:
        raise ValueError(f"' を含む値は tmux の設定に書けない: {v}")
    return f"'{v}'"


def conf_text():
    tool, key = str(TOOL), settings.get("key")
    style = " ".join(f"'{a}'" for a in theme.popup_style(settings.get("theme", env_ok=False)))   # 窓の題・地・枠（配色に合わせる）
    popup = (f"display-popup -E -w 90% -h 85% {style} -e HACKDECK_POPUP=1 -d '#{{pane_current_path}}' "
             f"'{tool} popup #{{pane_id}}'")
    # どのプログラムの中でも同じ: 窓を開き、組み立てたコマンドを元のペインに貼る（zsh の入力行にも、リバースシェルにも。
    # 2026-10-31、本人の指摘で、zsh のプロンプトだけ打ちかけの行を検索語にして行を置き換える動きはやめた）
    opener = f'run-shell -C "{popup}"'
    lines = [f"# key {key}",
             "# hackdeck の専用の tmux サーバー（tmux -L hackdeck）の設定。hackdeck が設定から毎回作る（手で直さない）。",
             "# ふだんの tmux（~/.tmux.conf・ふだんのサーバー）には書かない",
             "# ~/.tmux.conf の tmux-resurrect・tmux-continuum が、ふだんの tmux の保存を上書きしたり、ふだんのセッションを",
             "# ここへ戻したりしないように（並びは hackdeck が案件ごとに残す）。~/.tmux.conf を読む前と後の両方で入れる",
             f"set -g @resurrect-dir {_tq(RESURRECT_DIR)}",
             "set -g @continuum-restore 'off'"]
    if settings.get("user_tmux_conf"):
        lines += ["source-file -q ~/.tmux.conf",
                  f"set -g @resurrect-dir {_tq(RESURRECT_DIR)}",
                  "set -g @continuum-restore 'off'",
                  "set -g @continuum-save-interval '0'",
                  "set -gu @resurrect-hook-post-save-all"]
    lines += [
        "# 案件のセッションの zsh に hackdeck の部分（shell/hack.zsh）を入れる。ZDOTDIR をここに向け、自分の設定を読んだあとで読む",
        f"set-environment -g ZDOTDIR {_tq(ZDOTDIR)}",
        f"set-environment -g HACK_USER_ZDOTDIR {_tq(_user_zdotdir())}",
        f"set-environment -g HACK_TOOL {_tq(tool)}",
        f"set-environment -g HACK_COMMON {_tq(COMMON_LISTS)}",
        f"set-environment -g HACK_AUTOSAVE {_tq(AUTOSAVE_STAMP)}",
        f"set-environment -g HACK_SHELL_CONF {_tq(SHELL_CONF)}",
        "# 窓（コマンドの組み立て・資格情報・環境・案件・設定）。組み立てたコマンドは、元のペインに貼る（実行はしない）",
        f"bind -n {key} {opener}",
        f'bind -N "コマンドを組み立てて、このペインに貼る (hackdeck)" {key} {opener}',
        "# 設定を読み直す（prefix+C-r。~/.tmux.conf の読み直しは ~/.tmux.conf だけを読むので、hackdeck の分ごと読むものに替える）。"
        "prefix+R（tmux-sensible や ~/.tmux.conf の読み直し）と prefix+C-s（tmux-resurrect の手動の保存）は押しても何もしない"
        "（2026-11-01、本人の指摘「使わないから押せないように」「prefix+C-r の方が押しやすい」「R と被っている。R の方を消して」）",
        f'bind -N "設定を読み直す（~/.tmux.conf と hackdeck の分）" C-r source-file {_tq(TMUX_CONF)} \\; '
        'display-message "設定を読み直した（~/.tmux.conf と hackdeck の分）"',
        "unbind R",
        "unbind C-s",
        "# ログ: このペインの、前に残した所から今までを、すぐ残す（リバースシェルの中など、プロンプトに戻らないとき）",
        f"bind -N \"このペインをログに残す (hackdeck)\" F run-shell \"{tool} log flush '#{{pane_id}}'\"",
        "# 並びを残す: 離れたとき（ここ）と、15分に1回まで（シェルのプロンプトのたび。shell/hack.zsh）。番号を決めておき、",
        "# 読み直しても増やさない",
        "# 案件の外のセッション（設定の outside）も、離れたとき（端末を閉じたとき）に、持ち主の端末が無くなったものを終える。",
        "# prefix+d は、案件の外のセッションから来た端末なら、そこへ戻る（無ければ、ふつうに離れる）",
        f"set-hook -g client-detached[73] \"run-shell -b '{tool} outside gc; {tool} case save'\"",
        # hackdeck が動かなくても離れられるように（prefix+d は逃げ道）
        f'bind -N "案件から離れる（案件の外のセッションから来た端末は、そこへ戻る）" d run-shell -b '
        f'"{tool} leave \'#{{client_name}}\' || tmux -L {SOCKET} detach-client -t \'#{{client_name}}\'"',
    ]
    return "\n".join(lines) + "\n"


ZSHENV = """# hackdeck: 案件のセッションの zsh が最初に読む（専用の tmux サーバーが ZDOTDIR をここに向けている）。hackdeck が作る。
# ZDOTDIR を元に戻して自分の .zshenv を読み、自分の .zshrc などを読んだあとの最初のプロンプトで、hackdeck の部分を読む。
# 対話でない zsh（zsh -c。並びを戻したペインの「画面を出してからシェルになる」コマンドなど）は、ZDOTDIR をここに戻す
# （そこから始める対話の zsh にも、hackdeck の部分が入るように）
_hack_zd=$ZDOTDIR
ZDOTDIR=${HACK_USER_ZDOTDIR:-$HOME}
[[ -r $ZDOTDIR/.zshenv ]] && source $ZDOTDIR/.zshenv
if [[ -o interactive ]]; then
  _hack_init() { precmd_functions=(${precmd_functions:#_hack_init}); source %s }
  precmd_functions+=(_hack_init)
else
  ZDOTDIR=$_hack_zd
fi
unset _hack_zd
"""


def shell_conf():
    """案件のシェルが、プロンプトのたびに見る設定（shell/hack.zsh の _hack_conf）。ここに書いた値は、開いているペインにも
    次のプロンプトから効く（2026-11-01、本人の指摘「hk を設定して prefix+R したけど、hk で戻れない」。前は tmux の環境変数で
    渡していて、新しく開いたペインにしか届かなかった）"""
    return f"stamps={1 if settings.get('stamps') else 0}\nhome_cmd={settings.get('home_cmd').strip()}\n"


def write_conf():
    """専用のサーバーの設定と、zsh への注入のファイルを作る（中身が同じなら書かない）。サーバーが動いていれば読み直させる
    （窓のキーを変えたときは、前のキーを外してから）"""
    for f, text in ((TMUX_CONF, conf_text()), (ZDOTDIR / ".zshenv", ZSHENV % shlex.quote(str(SHELL_DIR / "hack.zsh"))),
                    (SHELL_CONF, shell_conf())):
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            old = f.read_text(encoding="utf-8")
        except OSError:
            old = ""
        if old == text:
            continue
        f.write_text(text, encoding="utf-8")
        if f == TMUX_CONF and tmux("list-sessions") is not None:
            was = old.split("\n", 1)[0][len("# key "):] if old.startswith("# key ") else ""
            if was and was != settings.get("key"):
                tmux("unbind", "-n", was)
                tmux("unbind", was)
            tmux("source-file", str(TMUX_CONF))


def outside_sessions():
    """案件の外のセッション [(ID, 持ち主の端末)]"""
    out = tmux("list-sessions", "-F", "#{session_id}\t#{@hack_outside}\t#{@hack_owner}") or ""
    return [(f[0], f[2]) for f in (line.split("\t") for line in out.splitlines()) if len(f) == 3 and f[1] == "1"]


def outside_gc():
    """持ち主の端末がもう無い、案件の外のセッションを終える（端末を閉じたとき。client-detached のフックから）。持ち主が
    案件のセッションに切り替えているあいだは、つないだままなので終えない（案件から離れると、そこへ戻る）"""
    ttys = set((tmux("list-clients", "-F", "#{client_tty}") or "").split())
    for sid, owner in outside_sessions():
        if owner not in ttys:
            tmux("kill-session", "-t", sid)
    return 0


def outside_start():
    """この端末を、専用の tmux の案件の外のセッションにつなぐ（shell-init の1行から。設定の outside）。セッションが終わったら
    0（呼んだシェルも終わり、端末が閉じる）。つなげなかった・離れたときは 1（呼んだシェルのまま。離れたセッションは終える）"""
    try:
        tty = os.ttyname(0)
    except OSError:
        return 1
    write_conf()
    outside_gc()
    name = OUTSIDE_PREFIX + Path(tty).name   # /dev/pts/7 → _out-7
    if tmux("has-session", "-t", f"={name}") is not None:
        tmux("kill-session", "-t", f"={name}")   # 前に同じ番号の端末が使っていたもの
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    try:
        r = subprocess.run(["tmux", "-L", SOCKET, "-f", str(TMUX_CONF), "new-session", "-s", name, "-c", os.getcwd(),
                            ";", "set-option", "-t", f"={name}:", "@hack_outside", "1",
                            ";", "set-option", "-t", f"={name}:", "@hack_owner", tty], env=env)
    except OSError:
        return 1
    if r.returncode != 0:
        return 1
    if tmux("has-session", "-t", f"={name}") is None:
        return 0
    tmux("kill-session", "-t", f"={name}")
    return 1


def leave(client):
    """案件から離れる（prefix+d・案件のタブの「案件から離れる」）。その端末の案件の外のセッションがあれば、そこへ戻る。無ければ
    離れる（元の端末へ）。案件の外のセッションそのものでは何もしない（離れる先が無い。閉じるなら exit か端末を閉じる）"""
    info = (tmux("display-message", "-p", "-c", client, "#{@hack_outside}\t#{client_tty}") or "").rstrip("\n").split("\t")
    if len(info) != 2:
        return 1
    outside, tty = info
    if outside == "1":
        tmux("display-message", "-c", client, "案件の外のセッション（離れる先は無い。閉じるなら exit か端末を閉じる）")
        return 0
    own = next((sid for sid, owner in outside_sessions() if owner == tty), None)
    if own:
        tmux("switch-client", "-c", client, "-t", own)
    else:
        tmux("detach-client", "-t", client)
    return 0


def lobby_ensure():
    """待合を用意する（無ければ作る。状態の行は出さない）"""
    write_conf()
    if tmux("has-session", "-t", f"={LOBBY}") is None:
        tmux("new-session", "-d", "-s", LOBBY, LOBBY_CMD, start=True)
        tmux("set", "-t", f"={LOBBY}:", "status", "off")   # set の -t は「=名前:」（「=名前」だとセッションが見つからない）


# --- 案件の一覧 ---------------------------------------------------------------------------------------

def moved_from(roots, d):
    """前の案件の場所（roots。そのままの形と、リンクをたどった形）の中の場所を、いまの場所 d の中へ読み替える関数"""
    pairs = [(a, b) for a, b in zip(roots, (str(d), str(Path(d).resolve()))) if a and a != b]

    def moved(p):
        for a, b in pairs:
            if p == a or p.startswith(a + "/"):
                return b + p[len(a):]
        return p
    return moved


def case_saved(d):
    """残した並び。([窓], [ペイン])。窓は (番号, 前に出ていたか, 拡大, 名前を自動で変えるか, 並び, 名前)、
    ペインは (窓の番号, 番号, 前に出ていたか, 場所)。残したあとに案件の場所が変わっていれば（hackdeck の外で名前を変えた・
    動かした）、ペインの場所を今の場所の中へ読み替える（r の行に、残したときの案件の場所がある）"""
    try:
        lines = (case_file(d, "session") / "layout.tsv").read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], []
    wins, panes, roots = [], [], []
    for line in lines:
        f = line.split("\t")
        if f[0] == "r":
            roots = f[1:3]
        elif f[0] == "w" and len(f) >= 7:
            wins.append(f[1:6] + ["\t".join(f[6:])])
        elif f[0] == "p" and len(f) >= 5:
            panes.append(f[1:4] + ["\t".join(f[4:])])
    if roots:
        moved = moved_from(roots, d)
        panes = [p[:3] + [moved(p[3])] for p in panes]
    return wins, panes


def case_born(dirs):
    """案件のフォルダを作った時刻 {フォルダ: 時刻}。ファイルシステムの作成時刻（stat の %W）、取れなければ
    .git/description（clone のときに書かれて変わらない）、それも無ければフォルダの更新時刻"""
    born = {}
    if dirs:
        r = subprocess.run(["stat", "-c", "%W\t%n", "--", *map(str, dirs)], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            t, _, name = line.partition("\t")
            if t.isdigit() and int(t) > 0:
                born[name] = int(t)
    for d in dirs:
        if str(d) not in born:
            for p in (d / ".git" / "description", d):
                try:
                    born[str(d)] = int(p.stat().st_mtime)
                    break
                except OSError:
                    pass
    return {Path(k): v for k, v in born.items()}


def case_updated(d):
    """案件を最後に触った時刻（案件・作業フォルダ・ログの更新時刻のいちばん新しいもの。中まで全部は見ない）"""
    log = log_of(d)
    ts = []
    for p in (d, work_of(d), *((log.parent, log) if log else ())):
        try:
            ts.append(p.stat().st_mtime)
        except OSError:
            pass
    return int(max(ts)) if ts else 0


def case_rows():
    """案件の一覧（作った順、新しいものが先）。動いていなければ、残した窓の数"""
    sessions, rows = tmux_sessions(), []
    dirs = case_dirs()
    born = case_born(dirs)
    for d in dirs:
        s = sessions.get(d.name)
        wins = [] if s else case_saved(d)[0]
        rows.append({"name": d.name, "running": bool(s), "windows": s["windows"] if s else len(wins),
                     "saved": bool(wins), "born": born.get(d, 0), "updated": case_updated(d)})
    return sorted(rows, key=lambda r: (-r["born"], r["name"]))


# --- 並びを残す・戻す ---------------------------------------------------------------------------------

def _capture(t):
    """ペインの画面の中身（全画面の道具が出ていれば、その裏の元の画面）"""
    cap = ("capture-pane", "-p", "-e", "-J", "-t", t)
    alt, _, hist = (tmux("display-message", "-p", "-t", t, "#{alternate_on}\t#{history_size}") or "").strip().partition("\t")
    if alt == "1":
        # Ctrl+G の窓や vim が出ている。出ている画面を残すと、戻したときにそれが焼き付くので、裏の元の画面（履歴と -a）を残す
        return (((tmux(*cap, "-S", f"-{SESSION_KEEP_LINES}", "-E", "-1") or "") if hist.isdigit() and int(hist) else "")
                + (tmux(*cap, "-a", "-q") or ""))
    return tmux(*cap, "-S", f"-{SESSION_KEEP_LINES}") or ""


def case_save(names=None):
    """動いている案件のセッションの並び（窓・ペイン・場所）と画面の中身を、案件の session/ に書く（離れたとき・15分ごと・
    終える前）。案件のフォルダが無いセッションは書かない"""
    for name, s in tmux_sessions().items():
        d = case_path(name)
        if (names and name not in names) or not is_case_dir(d):
            continue
        wins = tmux("list-windows", "-t", s["id"], "-F", "#{window_index}\t#{window_active}\t#{window_zoomed_flag}"
                    "\t#{automatic-rename}\t#{window_layout}\t#{window_name}")
        panes = tmux("list-panes", "-s", "-t", s["id"], "-F",
                     "#{window_index}\t#{pane_index}\t#{pane_active}\t#{pane_current_path}")
        if not wins or not panes:
            continue
        dest = case_file(d, "session")
        ensure_state(d)
        tmp = dest.with_name(f"session.{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(mode=0o700)
        (tmp / "layout.tsv").write_text(f"r\t{d}\t{d.resolve()}\n"   # 残したときの案件の場所（case_saved が読み替える）
                                        + "".join(f"w\t{l}\n" for l in wins.splitlines())
                                        + "".join(f"p\t{l}\n" for l in panes.splitlines()), encoding="utf-8")
        for line in panes.splitlines():
            w, p = line.split("\t")[:2]
            lines = _capture(f"{s['id']}:{w}.{p}").splitlines()
            while lines and not ANSI_RE.sub("", lines[-1]).strip():
                lines.pop()
            if lines:   # 画面にパスワードが出ていることもあるので 600
                with os.fdopen(os.open(tmp / f"{w}.{p}.txt", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                               encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\x1b[0m\n")
        old = dest.with_name(f"session.old{os.getpid()}")
        if dest.exists():
            os.replace(dest, old)
        os.replace(tmp, dest)
        shutil.rmtree(old, ignore_errors=True)


def case_autosave():
    """15分に1回まで、並びを残す（案件のセッションのシェルが、プロンプトのたびに見る。shell/hack.zsh。何も出さない）"""
    try:
        last = AUTOSAVE_STAMP.stat().st_mtime
    except OSError:
        last = 0
    if time.time() - last < AUTOSAVE_EVERY:
        return
    AUTOSAVE_STAMP.parent.mkdir(parents=True, exist_ok=True)
    AUTOSAVE_STAMP.touch()
    case_save()


def case_create(name):
    """案件のセッションを動かす（動いていればそのまま）。残した並びがあれば、窓・ペイン・場所・画面の中身を戻す
    （動いていたプログラムは戻らない）。セッションの ID を返す"""
    s = tmux_sessions().get(name)
    if s:
        return s["id"]
    from .nxc import nxc_home_prepare   # 案件の netexec の置き場所（NXC_PATH）を先に作る
    d = case_path(name)
    ensure_state(d)
    nxc_home_prepare(case_file(d, "nxc"))
    write_conf()
    env = [a for k, v in case_env(d).items() for a in ("-e", f"{k}={v}")]
    wins, panes = case_saved(d)
    if not wins:
        return (tmux("new-session", "-d", "-P", "-F", "#{session_id}", "-s", name, "-c", str(work_of(d)), *env,
                     start=True) or "").strip() or None
    shell = (tmux("show", "-gv", "default-shell") or "").strip() or os.environ.get("SHELL") or "/bin/sh"

    def start(w, p):   # ペインの場所と、残した画面を出してからシェルになるコマンド
        cwd = p[3] if Path(p[3]).is_dir() else str(work_of(d))
        f = case_file(d, "session") / f"{w}.{p[1]}.txt"
        return ["-c", cwd] + ([f"cat {shlex.quote(str(f))}; exec -l {shlex.quote(shell)}"] if f.is_file() else [])
    m = re.match(r"^[0-9a-f]+,(\d+)x(\d+),", wins[0][4])
    size = ["-x", m.group(1), "-y", m.group(2)] if m else []
    base = (tmux("show", "-gv", "base-index") or "0").strip()
    sid = None
    for idx, active, zoomed, auto, layout, wname in sorted(wins, key=lambda w: int(w[0])):
        wp = sorted((p for p in panes if p[0] == idx), key=lambda p: int(p[1]))
        if not wp:
            continue
        named = ["-n", wname] if auto in ("0", "off") else []
        if sid is None:
            sid = (tmux("new-session", "-d", "-P", "-F", "#{session_id}", "-s", name, *size, *named, *env,
                        *start(idx, wp[0]), start=True) or "").strip()
            if not sid:
                return None
            if m:
                tmux("set", "-t", sid, "default-size", f"{m.group(1)}x{m.group(2)}")   # 後から作る窓も同じ大きさに
            if idx != base:
                tmux("move-window", "-s", f"{sid}:{base}", "-t", f"{sid}:{idx}")
            last = (tmux("display-message", "-p", "-t", f"{sid}:{idx}", "#{pane_id}") or "").strip()
        else:
            last = (tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", f"{sid}:{idx}", *named,
                         *start(idx, wp[0])) or "").strip()
        for p in wp[1:]:
            # 直前に作ったペインを分ける（tmux は分けたペインのすぐ後ろに足すので、こうすると番号が残した順になる）
            last = (tmux("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", last, *start(idx, p)) or last).strip()
        tmux("select-layout", "-t", f"{sid}:{idx}", layout)
        act = next((p[1] for p in wp if p[2] == "1"), wp[0][1])
        tmux("select-pane", "-t", f"{sid}:{idx}.{act}")
        if zoomed == "1":
            tmux("resize-pane", "-Z", "-t", f"{sid}:{idx}.{act}")
    actw = next((w[0] for w in wins if w[1] == "1"), None)
    if sid and actw:
        tmux("select-window", "-t", f"{sid}:{actw}")
    return sid


def case_open(name):
    """案件のセッションへ（動いていなければ、残した並びで戻すか新しく作る）。専用のサーバーの中は切り替える。ほかの tmux の
    中は、その tmux から離れて、同じ端末を専用のサーバーにつなぐ（入れ子にしない。案件から離れると、元の tmux のセッションに
    戻る）。tmux の外は、このプロセスを tmux に置き換えてつなぐ"""
    if not is_case_dir(case_path(name)):
        print(f"[!] 案件が無い: {case_path(name)}", file=sys.stderr)
        return 1
    sid = case_create(name)
    if not sid:
        print(f"[!] セッションを作れなかった: {name}", file=sys.stderr)
        return 1
    last_case_set(case_path(name))
    if in_server():
        tmux("switch-client", "-t", sid)
        return 0
    attach = f"tmux -L {shlex.quote(SOCKET)} attach-session -t {shlex.quote(sid)}"
    tty_rw()
    if os.environ.get("TMUX"):
        outer = os.environ["TMUX"].split(",")[0]
        try:   # ほかの tmux のいまのセッション（$TMUX のサーバー）
            back = subprocess.run(["tmux", "display-message", "-p", "#{session_id}"], capture_output=True,
                                  text=True).stdout.strip()
        except OSError:
            back = ""
        again = f"exec tmux -S {shlex.quote(outer)} attach-session" + (f" -t {shlex.quote(back)}" if back else "")
        return subprocess.run(["tmux", "detach-client", "-E", f"{attach}; {again}"]).returncode
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    os.execvpe("tmux", ["tmux", "-L", SOCKET, "attach-session", "-t", sid], env)


def template_kind(tpl=None):
    """雛形（設定の template）の種類: "" 空・"dir" 手元のフォルダ（git でない）・"git" git の URL か手元の git"""
    tpl = (settings.get("template") if tpl is None else tpl).strip()
    if not tpl:
        return ""
    local = Path(tpl).expanduser()
    return "dir" if local.is_dir() and not (local / ".git").exists() else "git"


def case_make(name):
    """案件のフォルダを雛形から作る（始めはしない）。git なら clone（進み具合を出す）、手元のフォルダなら写す、空なら作業
    フォルダだけ。作業フォルダとログの置き場所は、雛形に無ければ作る。うまくいけば 0"""
    if not CASE_NAME_RE.match(name):
        print("[!] 名前に使えるのは英数字と - _ + だけ（頭は英数字）", file=sys.stderr)
        return 1
    d = case_path(name)
    if d.exists():
        print(f"[!] もうある: {d}（案件のタブで選んで入る）", file=sys.stderr)
        return 1
    d.parent.mkdir(parents=True, exist_ok=True)
    tpl, kind = settings.get("template").strip(), template_kind()
    if kind == "dir":
        print(f"[*] 雛形を写す {tpl} → {d}", flush=True)
        shutil.copytree(Path(tpl).expanduser(), d, symlinks=True)
    elif kind == "git":
        local = Path(tpl).expanduser()
        src = str(local) if local.is_dir() else tpl
        print(f"[*] 雛形を clone {tpl} → {d}", flush=True)
        if subprocess.run(["git", "clone", "--progress", src, str(d)]).returncode != 0:
            print("[!] clone できなかった", file=sys.stderr)
            shutil.rmtree(d, ignore_errors=True)
            return 1
    else:
        print(f"[*] 案件のフォルダを作る → {d}", flush=True)
    work_of(d).mkdir(parents=True, exist_ok=True)
    log = log_of(d)
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
    return 0


def tty_rw():
    """tmux につなぐ前に、標準入力をいまの端末を読み書きで開き直したものにし、標準出力を捨てる。
    tmux はつなぐ端末（標準入力）をサーバーに渡し、サーバーはそれで画面を描く。zsh のウィジェットから `<$TTY` で呼ばれると
    読むだけで開いてあるので、つないでもキーは届くのに画面が描かれなかった（固まって見えた。2026-10-31、本人の報告「Ctrl+G の
    案件のタブで止まっている案件を Enter すると固まる」）。標準出力には、離れたときに tmux が「[detached (from session …)]」と
    改行を出し、案件の外の Ctrl+G を押すたびにプロンプトの行が1つずつ増えていた（2026-11-01、本人の報告）ので捨てる（画面は
    標準入力で描くので困らない）"""
    try:
        fd = os.open(os.ttyname(0), os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return
    os.dup2(fd, 0)
    os.dup2(fd, 2)
    if fd > 2:
        os.close(fd)
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.close(null)


def case_new(name):
    """案件を作って始める"""
    rc = case_make(name)
    if rc:
        return rc
    print(f"[*] セッション {name} を作って{'切り替える' if in_server() else '入る'}")
    return case_open(name)


def case_kill(name):
    """セッションを終える。並びは先に残す（次に開いたとき戻せるように）"""
    s = tmux_sessions().get(name)
    if not s:
        return 1
    case_save([name])
    tmux("kill-session", "-t", s["id"])
    return 0


def case_rename(old, new):
    """止まっている案件の名前を変える（2026-11-01、本人の指摘「案件のフォルダの名前を変えられるように」）。フォルダの名前と、
    それに合わせて、残した並びの中のペインの場所（前のフォルダの中なら新しいフォルダの中へ）・直前の案件（前の形の覚え方）。
    窓の画面の列は案件の目印で見分けるので、そのまま続く（前の形のファイルなら、目印ごとへ移してから変える）。資格情報・環境・
    履歴・メモ・ログ・残した並びはフォルダの中なので、そのまま使える。動いている案件は
    変えない（セッションとシェルの環境が前の場所を指したままになり、ログは前の名前のフォルダを作り直してそこへ書き、窓は
    案件の外の扱いになる。試して確かめた）。(できたか, 一言)"""
    src, dst, sessions = case_path(old), case_path(new), tmux_sessions()
    if not is_case_dir(src):
        return False, f"{old} が無い"
    if old in sessions:
        return False, f"{old} は動いている（名前を変えるのは終えてから。案件のタブの Ctrl+D か hackdeck case kill。窓の並びは残る）"
    if new == old:
        return False, "同じ名前"
    if not CASE_NAME_RE.match(new):
        return False, "名前に使えるのは英数字と - _ + だけ"
    if dst.exists() or new in sessions:
        return False, f"{new} はもうある"
    from .nav import nav_adopt   # nav は ui を通して読むので、ここでだけ
    nav_adopt(src)   # 前の形（案件の場所ごと）の窓の画面の列を、目印ごとへ移しておく（名前を変えたあとも同じ列）
    roots = [str(src), str(src.resolve())]   # ペインの場所は、tmux がリンクをたどった本当の場所で残している
    try:
        os.rename(src, dst)
    except OSError as ex:
        return False, f"変えられなかった: {ex.strerror}"
    moved = moved_from(roots, dst)
    lay = case_file(dst, "session") / "layout.tsv"
    try:
        lines = lay.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if lines:   # 前の形（r の行が無い）でも戻るように、ペインの場所も書き替える
        out = []
        for line in lines:
            f = line.split("\t")
            if f[0] == "p" and len(f) >= 5:
                line = "\t".join(f[:4] + [moved("\t".join(f[4:]))])
            elif f[0] == "r":
                line = f"r\t{dst}\t{dst.resolve()}"
            out.append(line)
        lay.write_text("".join(l + "\n" for l in out), encoding="utf-8")
    try:
        last = CASE_LAST.read_text(encoding="utf-8").partition("\t")[0].strip()
    except OSError:
        last = ""
    if last == old:
        last_case_set(dst)
    return True, f"{old} を {new} に変えた"


CASE_USAGE = """使い方: hackdeck case <コマンド>（案件のタブが使う。AI が使うときもこれ）
  ls                 案件の一覧（作った順。動いているか・窓の数・作った日）
  attach [名前]      案件のセッションへ（動いていなければ、残した並びで戻す。名前を省くと直前の案件）
  new <名前>         雛形から作って始める
  make <名前>        雛形から作るだけ（始めない。案件のタブが使う）
  kill <名前>        セッションを終える（並びは残す）
  rename <名前> <新しい名前>   名前を変える（止まっている案件だけ。残した並び・窓の画面の列も合わせる）
  save [名前...]     並びと画面の中身を案件のデータ（session/）に残す（専用の tmux が離れたときに呼ぶ）
  autosave           15分に1回まで save（案件のセッションのシェルが呼ぶ）"""


def c_case(args):
    sub, rest = (args[0] if args else ""), args[1:]
    if sub in ("attach", "a"):
        name = rest[0] if rest else last_case()   # 名前を変えていても、目印で今の名前を探す
        if not name:
            print("[!] 直前の案件が見つからない（hackdeck case ls で確かめる）", file=sys.stderr)
            return 1
        return case_open(name)
    if sub == "new" and rest:
        return case_new(rest[0])
    if sub == "make" and rest:
        return case_make(rest[0])
    if sub == "kill" and rest:
        return case_kill(rest[0])
    if sub == "rename" and len(rest) == 2:
        ok, msg = case_rename(*rest)
        print(msg if ok else f"[!] {msg}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if sub == "save":
        case_save(rest or None)
        return 0
    if sub == "autosave":
        case_autosave()
        return 0
    if sub == "ls":
        import datetime
        for r in case_rows():
            day = datetime.datetime.fromtimestamp(r["born"]).strftime("%Y-%m-%d") if r["born"] else "-"
            st = "動いている" if r["running"] else "止まっている（並びあり）" if r["saved"] else "止まっている"
            print(f"{r['name']}\t{st}\t窓 {r['windows']}\t{day}")
        return 0
    print(CASE_USAGE, file=sys.stderr)
    return 2
