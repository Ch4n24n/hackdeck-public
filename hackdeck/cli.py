"""コマンドラインの入口（hackdeck <サブコマンド>）。何も付けなければ窓を開く（launch）。

モジュールは、サブコマンドごとに要るものだけを、呼ぶときに読む（2026-11-01、本人の希望「反応速度がはやくなると嬉しい」。fzf
から打つたび・画面を出すたびに hackdeck が起き直すので、前のように全部を読むと、それだけで 1回 0.05 秒ほどかかっていた）。"""
import os
import sys


USAGE = """使い方: hackdeck [サブコマンド] [引数]
  （なし）                          窓を開く。案件のセッションの中は、いまのペインの上に（組み立てたコマンドをそのペインに
                                    貼る）。ほかの tmux の中は、その上に。tmux の外は、この端末で。案件のセッションの外は、
                                    案件と設定のタブだけ
  ui [--lobby クライアント]           この端末で開く（組み立てたコマンドは標準出力へ。--lobby は待合の窓から呼ばれる）
  shell-init zsh                    ~/.zshrc に書く1行のための中身: eval "$(hackdeck shell-init zsh)" で、案件のセッションの
                                    外でも、窓のキー（設定の key）で開く。案件のセッションの中は書かなくても開く
  popup <ペイン>                     専用の tmux の窓のキーから呼ばれる
  outside [gc]                      この端末を案件の外のセッションにつなぐ（設定の outside。shell-init の1行から）。gc は、
                                    端末を閉じた案件の外のセッションを終える（専用の tmux が、端末が離れたときに呼ぶ）
  leave <クライアント>               案件から離れる（専用の tmux の prefix+d。案件の外のセッションから来た端末は、そこへ戻る）
  log flush <ペイン>                 ペインの、前に残した所から今までを、案件のログに足す（専用の tmux の prefix+F）
  case <ls|attach|new|make|kill|save|autosave> ...   案件のセッション（hackdeck case だけで使い方）
  check                             コマンド帳を点検する（書き足したら流す）
候補（コマンド帳の $ の行が呼ぶ）:
  hosts / fqdns / domains / lhost / ifaces / cidrs / users / passwords / hashes / ccache / hostips / hostnames / urls / dcs
  auth <nxc|winrm|certipy|bh> [ドメイン] [ホスト]
  authforms <brute> [proto]         認証の形（値に <userfile> などを含み、選ぶと続けてそれを聞く）
  authcreds <nxc|winrm|dump|imp|mssql|impn|bloody|smb|rdp|e4l> [行き先]   資格情報を先に選ぶ画面の候補（行き先は
                                    netexec ならプロトコル、impacket・bloodyAD なら相手か DC）
  users [self]                      ユーザー（self なら、組み立てに使う資格情報のユーザーをいちばん下に）
  adtarget <dacl|owner>             dacledit・owneredit の対象（名前・DN・SID で -target・-target-dn・-target-sid）
  domaindn                          ドメインの DN（資格情報のドメインから）
  authhow nxc                       資格情報のあとの認証のしかた（netexec の1番）
  users-for <pass|nt>               認証の形の中のユーザー（その種類の資格情報があるユーザーが先）
  secrets-for <pass|nt> <ユーザー>   認証の形の中のパスワード・NT ハッシュ（そのユーザーの分が先）
  files [--dir 場所] [--query 打った文字] <種類|glob>...   種類: any user pass hash req pfx sam security system ovpn
  opts <一覧の名前>
  value <値>...                     決まった値を候補にする
  complete <打った文字> <選んでいる行> <候補のファイル>   変数の画面の fzf（Tab）から呼ばれる
  findpos <値> <候補のファイル> [0]   変数・資格情報の画面の fzf（戻ってきたとき）から呼ばれる
  findidx <行番号> <候補のファイル>   コマンド選びの画面の fzf（戻ってからやり直すとき）から呼ばれる
  typed <打った文字>                 変数の画面の fzf（reload）から呼ばれる
  flowclick <対応表>                 変数の画面の流れの図のクリック（fzf の click-footer）から呼ばれる
  credsrows [打った文字]             資格情報の画面の fzf（reload）から呼ばれる
  nxcfound                           netexec が見つけた資格情報のうち、まだ足していないもの（資格情報のタブの Ctrl+N と同じ）
  nxc-stamp                          netexec の DB の、まだ日時の無い資格情報に見つけた日時を付け、足したあとの説明の
                                    （netexec …）を DB の中身で書き直す（shell/hack.zsh から呼ばれる）
  envrows [打った文字]               環境の画面の fzf（reload）から呼ばれる
  caserows [打った文字]              案件の画面の fzf（reload）から呼ばれる
  casepos [打った文字]               案件の画面の fzf（load）から呼ばれる
  rubout <打った文字>                どの画面の fzf（Ctrl+W）からも呼ばれる（カーソルの手前の1語を消す。空白と記号で止まる）
  settingrows [打った文字]           設定の画面の fzf（reload）から呼ばれる
  footclick <対応表|->               足もと（流れの図）のクリック（fzf の click-footer）から呼ばれる
  env-capture <set|unset> <名前> <値> ...   シェルで export・unset した変数を書き戻す（shell/hack.zsh から呼ばれる）
  history                            いまの案件の履歴をそのまま見る（新しい順）"""


POPUP = ["display-popup", "-E", "-w", "90%", "-h", "85%", "-e", "HACKDECK_POPUP=1"]   # 題・枠・地は theme.popup_style


def popup_args():
    """窓を開く引数。hackdeck を起動したシェルの HACKDECK_*（設定を一時的に変える環境変数）を、窓の中にも渡す（窓の中は
    tmux のサーバーの環境で動くため。' を含む値は渡さない）"""
    from . import theme
    env = [a for k, v in sorted(os.environ.items()) if k.startswith("HACKDECK_") and "'" not in v for a in ("-e", f"{k}={v}")]
    return [*POPUP, *theme.popup_style(), *env]


def launch():
    """窓を開く。案件のセッションの中は、いまのペインの上に（専用の tmux の窓のキーと同じ）。ほかの tmux の中は、その tmux の
    窓で（案件と設定。案件に入ると、その端末が案件のセッションに切り替わる）。tmux の外は、専用の tmux の待合（LOBBY）に
    つないで、その上に窓を開く（2026-10-31、本人の指摘「案件の外で Ctrl+G を打っても、案件の中と同じ窓で」。端末だけでは
    tmux の窓を描けないので、待合を下に敷く。窓の後ろは、元の端末の画面ではなく待合の空の画面になる）"""
    import shlex
    import subprocess
    from .session import LOBBY, SOCKET, TOOL, in_server, lobby_ensure, tty_rw
    tool = shlex.quote(str(TOOL))
    if in_server():
        return subprocess.run(["tmux", *popup_args(), f"{tool} popup {os.environ.get('TMUX_PANE', '')}"]).returncode
    if os.environ.get("TMUX"):
        return subprocess.run(["tmux", *popup_args(), f"{tool} ui"]).returncode
    lobby_ensure()
    tty_rw()
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    popup = " ".join(shlex.quote(a) for a in popup_args())
    os.execvpe("tmux", ["tmux", "-L", SOCKET, "attach-session", "-t", f"={LOBBY}", ";", "run-shell", "-C",
                        f"{popup} '{TOOL} ui --lobby #{{client_name}}'"], env)


def ui(args=()):
    """この端末で開く。--lobby <クライアント>: 待合の窓から呼ばれたとき。案件を選ばずに閉じたら、待合から離れて元の端末へ
    （案件を選んだときは、その案件のセッションへ切り替わっている）"""
    from .builder import run_builder
    from .env import env_vars
    from .session import LOBBY, tmux
    lobby = args[1] if args[:1] == ["--lobby"] and len(args) > 1 else None
    cmd = run_builder({**os.environ, **dict(env_vars())})
    if lobby:
        if (tmux("display-message", "-p", "-c", lobby, "#{client_session}") or "").strip() == LOBBY:
            tmux("detach-client", "-t", lobby)
    elif cmd:
        print(cmd)
    return 0


def shell_init(shell):
    """自分の ~/.zshrc の eval に渡す中身（案件のセッションの外の、窓のキー）"""
    import shlex
    from .session import TOOL, zle_key
    from . import settings
    if shell != "zsh":
        print(f"[!] いまは zsh だけ（{shell} は無い）", file=sys.stderr)
        return 2
    key = zle_key(settings.get("key"))
    if not key:
        print(f"# hackdeck: 窓のキー {settings.get('key')} は zsh で書けない（設定のタブで C-g・M-g などに）")
        return 0
    # コメントは出さない（setopt interactivecomments の無い zsh では、eval した # の行がコマンドになって壊れる）
    tool = shlex.quote(str(TOOL))
    print(f"""_hackdeck_open() {{ zle -I; {tool} <$TTY >$TTY 2>&1; zle reset-prompt }}
zle -N _hackdeck_open
bindkey {shlex.quote(key)} _hackdeck_open""")
    if settings.get("outside"):
        # 案件の外も tmux で（設定の outside）。VTE の端末（GNOME Terminal など）の対話の zsh だけ。tmux の中・ssh・Orca・VS Code
        # の端末は入れない（Orca や VS Code は自分で端末を扱う）。セッションが終わったら、この zsh も終える（端末が閉じる）
        print(f"""if [[ -z $TMUX && -n $VTE_VERSION && -z $SSH_TTY && -z $ORCA_APP_VERSION && $TERM_PROGRAM != vscode && -o interactive && -t 0 && -t 1 ]]; then {tool} outside && exit; fi""")
    return 0


def main(argv):
    # 候補の行（fzf の reload・コマンド帳の $ の行）は hackdeck を名前で呼ぶので、PATH に無くても動くように足す
    bindir = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + "/bin"
    if bindir not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = f"{bindir}:{os.environ.get('PATH', '')}"
    if not argv:
        return launch()
    cmd, args = argv[0], argv[1:]
    a0 = args[0] if args else ""
    # fzf から、打つたび・カーソルが動くたび・画面を出すたびに呼ばれるもの（いちばん軽く。fzfcall は text だけを読む）
    if cmd in ("findpos", "findidx", "complete", "typed", "pick", "casepos", "rubout"):
        from . import fzfcall
        if cmd == "findpos" and len(args) in (2, 3):
            fzfcall.c_findpos(*args)
        elif cmd == "findidx" and len(args) == 2:
            fzfcall.c_findidx(*args)
        elif cmd == "complete" and len(args) == 3:
            fzfcall.c_complete(*args)
        elif cmd == "typed":
            fzfcall.c_typed(a0)
        elif cmd == "pick" and len(args) == 2:
            fzfcall.c_pick(*args)
        elif cmd == "casepos":
            fzfcall.c_casepos(a0)
        elif cmd == "rubout":
            fzfcall.c_rubout(a0)
        else:
            print(USAGE, file=sys.stderr)
            return 2
        return 0
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
    elif cmd == "ui":
        return ui(args)
    elif cmd == "shell-init":
        return shell_init(a0 or "zsh")
    elif cmd == "popup" and args:
        from .popup import c_popup
        return c_popup(args)
    elif cmd == "outside":
        from .session import outside_gc, outside_start
        return outside_gc() if a0 == "gc" else outside_start()
    elif cmd == "leave" and args:
        from .session import leave
        return leave(a0)
    elif cmd == "log" and a0 == "flush" and len(args) > 1:
        from .panelog import log_flush
        return log_flush(args[1])
    elif cmd == "flowclick" and args:
        from .prompt import c_flowclick
        c_flowclick(a0)
    elif cmd == "footclick":
        from .prompt import c_footclick
        c_footclick(*(args[:2] or ["-"]))
    elif cmd == "credsrows":
        from .tab_creds import c_credsrows
        c_credsrows(a0)
    elif cmd == "credcopy" and args:
        from .tab_creds import c_credcopy
        c_credcopy(a0)
    elif cmd == "credlists":
        from .cand_files import c_credlists
        c_credlists(args or None)
    elif cmd in ("nxcfound", "nxc-stamp"):
        from .nxc import c_nxcrows, nxc_entries, nxc_refresh
        if cmd == "nxcfound":
            c_nxcrows()
        else:
            nxc_entries()   # 新しく見つけた行に日時を付け、扱う300件を決め直す（nxc_seen）
            nxc_refresh()   # 足したあとの説明の（netexec …）も、いまの DB の中身で書き直す
    elif cmd == "envrows":
        from .tab_env import c_envrows
        c_envrows(a0)
    elif cmd == "envcopy" and args:
        from .tab_env import c_envcopy
        c_envcopy(a0)
    elif cmd == "env-capture":
        from .env import c_envcapture
        c_envcapture(args)
    elif cmd in ("caserows", "dateprefix"):
        from .tab_case import c_caserows, c_dateprefix
        (c_caserows if cmd == "caserows" else c_dateprefix)(a0)
    elif cmd == "casecopy" and args:
        from .tab_case import c_casecopy
        c_casecopy(a0)
    elif cmd == "settingrows":
        from .tab_settings import c_settingrows
        c_settingrows(a0)
    elif cmd == "case":
        from .session import c_case
        return c_case(args)
    elif cmd == "history":
        from .history import c_history
        c_history()
    elif cmd == "check":
        from .check import check
        return check()
    else:
        from .candidates import run_candidate_cmd
        if not run_candidate_cmd(cmd, args):
            print(USAGE, file=sys.stderr)
            return 2
    return 0
