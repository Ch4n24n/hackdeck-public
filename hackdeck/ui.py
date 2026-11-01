"""fzf を呼ぶ共通の部品（タブの並び・足もと・見出し・キーの意味・2回押しの確かめ）と、画面の行き来の状態。"""
import contextlib
import io
import os
import shlex
import shutil
import subprocess

from .text import ANSI_RE, display_width, fit, fit_desc, out, term_cols
from .fzfcall import HEADING
from .case import case_root
from .paths import RUN_DIR
from .theme import B_ON, C_LINE, C_RESET, U_ON
from . import settings
from . import theme


# --- 窓の作業の置き場所 --------------------------------------------------------

def work_dir():
    """この窓の作業の置き場所 ~/.cache/hackdeck/run/<この窓のプロセスの番号>/（上の枠の中身・変数の候補・流れの図の対応表・
    カーソルの動き・fzf の一時ファイル）。画面ごとに同じ名前を上書きして使い回す（2026-11-01、本人の指摘「一時ファイルは、再利用
    するものはどこかに保存しておいて。そうすれば /tmp の中身を削除できる」。前は画面ごとに /tmp に作って消していて、窓ごと止め
    られると残っていった）。窓を閉じると run_builder が消し、止められて残ったものは、次に窓を開いたときに消す（work_clean）。
    中身に資格情報が入ることもあるので、自分だけが読める"""
    d = RUN_DIR / str(os.getpid())
    if not d.is_dir():
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def work_file(name, text=None):
    """作業の置き場所のファイル（text を渡すと、それを書く）"""
    p = work_dir() / name
    if text is not None:
        p.write_text(text, encoding="utf-8")
    return p


def work_subdir(name):
    """作業の置き場所の中のフォルダ（行ごとのファイルを置く。前の画面のものを消して、空にして返す）"""
    d = work_dir() / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    return d


def work_clean(mine=False):
    """持ち主の窓（プロセス）がもういない作業の置き場所を消す。mine: この窓のものも（閉じるとき）"""
    for d in (RUN_DIR.iterdir() if RUN_DIR.is_dir() else []):
        if not d.name.isdigit():
            continue
        if int(d.name) == os.getpid():
            if mine:
                shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            os.kill(int(d.name), 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass   # ほかのユーザーのプロセス（番号が使い回された）。残す


# --- 画面（fzf を自分で呼ぶ） -------------------------------------------------

JUMP_PREFIX = "hackdeck-jump:"  # 流れの図をクリックしたとき、fzf の print() で返ってくる行の頭（後ろに変数名）
TAB_PREFIX = "hackdeck-tab:"    # タブの並びをクリックしたとき、同じく返ってくる行の頭（後ろにタブの名前）
CLICK_MARK = "hackdeck-click"   # 2回のクリックで決めたとき、fzf の print() で返ってくる行（fzf_run が Enter に読み替えて消す）


def heading_text(title):
    """候補の見出しの表示（テーマのタグの色で、先頭に印、名前は太字。2026-10-30、本人の指摘「見出しは色を使って綺麗に」「線は
    幅がそろわずバランスが悪い。先頭にアイコンのようなものを置いて、線はなくす」）"""
    return f"{theme.C_TAG}{theme.ICON}{C_RESET} {B_ON}{theme.C_TAG}{title}{C_RESET}"


def grouped(groups):
    """候補をまとまりごとに見出しで分けた行に（2026-10-30、本人の指摘「見出しをつけて分けて」「空行を入れて見やすく」）。
    groups: [(見出し, [(値, 説明)])] を画面の下から上の順に。空のまとまりは出さない。見出しはまとまりの上、まとまりの間に空行
    （下から上へ並ぶ画面なので、行のあとに見出し、その次に空行を出す）"""
    groups = [(t, rows) for t, rows in groups if rows]
    flat = []
    for i, (title, rows) in enumerate(groups):
        flat += rows + [(HEADING, heading_text(title))]
        if i + 1 < len(groups):
            flat.append((HEADING, " "))
    return flat


# 候補が1つのまとまりの変数の見出し（2026-10-30、本人の指摘「見た目をそろえるため、オプションを選ぶ画面にはすべて見出しを」）。
# まとまりが分かれる候補（ユーザー・ファイル・ホストなど）は、候補の側で見出しを付ける。ここに無い変数は変数名のまま
VAR_HEADINGS = {
    "fqdn": "/etc/hosts", "realm": "レルム", "upn": "UPN", "iface": "ネットワーク", "cidr": "ネットワークの範囲",
    "sweep": "ホストの探し方", "sweep_ports": "ポート", "impersonate": "なりすます相手", "group": "グループ", "new_pass": "新しいパスワード",
    "brute_how": "認証のしかた", "auth_nxc": "資格情報", "auth_nxc_smb": "資格情報", "auth_e4l": "資格情報", "pattern": "探すパターン",
    "share_opt": "オプション", "tty": "TTY にするしかた", "fw_rule": "開けるポート", "fw_port": "ポート",
    "wget_os": "相手の OS", "ligolo_agent": "相手の OS", "deleted_act": "やること", "spn_act": "やること", "group_act": "やること", "nxc_how": "認証のしかた", "krb_how": "認証のしかた", "mssql_how": "認証のしかた",
    "ccache": "Kerberos のチケット", "proto": "プロトコル",
    "nxc_opt": "オプション", "dump_opt": "オプション", "nxc_mod": "モジュール", "exec": "実行のしかた", "mode": "ハッシュの種類", "x2john": "変換の道具",
    "wl_dir": "単語リスト", "wl_vhost": "単語リスト", "wl_lfi": "単語リスト", "wl_pass": "単語リスト", "ffuf_ext": "拡張子", "fs": "除く大きさ",
    "login_path": "ログインのパス", "post_data": "送るデータ", "sqlmap_act": "やること", "hydra_svc": "サービス",
    "http_port": "ポート", "http_dir": "配るフォルダ", "listen_port": "ポート", "envname": "環境変数の名前",
    "wl_ext": "単語リスト", "wl_param": "単語リスト", "wl_bypass": "単語リスト", "hydra_user": "ユーザー", "hydra_form": "送り方",
    "user_param": "ユーザー名のパラメータ", "pass_param": "パスワードのパラメータ", "http_method": "メソッド",
    "sqlmap_lvl": "念入りさ（--level・--risk）", "fail_text": "失敗したときの文", "form_extra": "そのほかのパラメータ",
    "sqlmap_db": "データベース", "sqlmap_table": "テーブル", "sid": "SID", "domain_dn": "ドメインの DN",
    "krb5_conf": "krb5.conf の置き場所", "dc_fqdn": "/etc/hosts", "remote_dir": "相手のフォルダ",
    "remote_file": "相手のファイル", "share": "共有", "new_user": "作るアカウント", "win_persist": "アカウントの種類",
}


def out_grouped(groups):
    for v, d in grouped(groups):
        out(v, d)
# どの画面でも「閉じる」として受け取るキー。Ctrl+G は開くキーと同じ（本人の指摘「Ctrl+G でツールを開閉」）。
# Ctrl+C も閉じる。どちらも、いまの画面・検索語・カーソルを残して閉じる（2026-10-29。それまでは Esc で閉じていた）
CLOSE_KEYS = ("ctrl-g", "ctrl-c")
# 1つ上の画面へ（up_entry。ファイルエクスプローラーの「上へ」。2026-10-30、本人の指摘「ファイルエクスプローラーの↑のような、
# タブの初期画面へ1つずつ戻るボタンがほしい」に、戻り方を整理したページで本人が案 A を選んだ: Alt+← → と Esc はそのまま、
# Alt+↑ を足す）。NAV_UP はいまの画面に1つ上があるか（run_builder が画面を出す前に決め、キーとヒントに使う）
UP_KEY = "alt-up"
NAV_UP = False
# 足もと（説明欄・流れの図）の高さ。どの画面も、コマンド選びの流れの図のいちばん高いものにそろえる（run_builder が決める。
# 2026-10-30、本人の指摘「説明欄の縦の幅がタブによってばらばら。そろえたほうがいい」。タブを移っても一覧の始まりが動かない）
FOOT_ROWS = 0
KEY_LABEL = {"ctrl-r": "Ctrl+R"}
# 大きいタブ（2026-10-30、tmux-op の合流で。本人の指摘「コマンドの組み立て、資格情報の管理、環境変数の管理、配色と別々の機能が
# あるので、それぞれタブで移動できるように」）。Ctrl+Tab で次のタブへ（GNOME Terminal は Ctrl+Tab を Tab と同じに送るので、
# 受けるのは Tab）。変数の画面だけは Tab が補完なので、そこからは Ctrl+Shift+Tab と ←・→ で移る。タブの並びは画面のいちばん上の
# 行に出す（2026-10-30、本人の指摘「タブは一番上のほうがいい。クリックできなくていい」）。案件のセッションの外は、案件と設定
# だけ（コマンドの組み立て・資格情報・環境は、案件のもの）
ALL_TABS = [("cmd", "コマンド"), ("creds", "資格情報"), ("env", "環境"), ("memo", "メモ"), ("case", "案件"), ("settings", "設定")]
OUTSIDE_TABS = ("case", "settings")


def tabs():
    """いま出すタブ [(名前, 見出し)]。メモのタブは設定で出す（2026-11-01、本人の提案。案件の中だけ）"""
    if not case_root():
        return [t for t in ALL_TABS if t[0] in OUTSIDE_TABS]
    return [t for t in ALL_TABS if t[0] != "memo" or settings.get("memo")]


def tab_of(e):
    """列の1つが、どのタブの画面か（コマンド選び・変数・履歴はコマンドのタブ。netexec が見つけた分は資格情報のタブ）"""
    if e["s"] == "creds":
        return e.get("tab", "creds")
    if e["s"] == "nxc":
        return "creds"
    if e["s"] == "settings":
        return "settings"
    return e["s"] if e["s"] in ("env", "memo", "case") else "cmd"


def tab_line(cur, clickonly=False):
    """タブの並び（開いているタブを太字・下線・色付きで、ほかを薄く）。clickonly: 変数の画面（Tab は補完）"""
    names = "  ".join(f"{B_ON}{U_ON}{theme.C_COMMENT}{n}{C_RESET}" if k == cur else f"{theme.C_HINT}{n}{C_RESET}"
                      for k, n in tabs())
    how = ("タブの移動 Ctrl+Shift+Tab（前）  ここでは Tab は補完" if clickonly
           else "タブの移動 Ctrl+Tab（次）・Ctrl+Shift+Tab（前）")
    # 移り方の説明は右端に寄せ、縦線で区切る（タブの名前のすぐ後ろに同じ色で並べると、タブの1つに見えた。2026-10-30、本人の指摘）
    hint = f"{C_LINE}│{C_RESET} {theme.C_HINT}{how}{C_RESET}"
    room = term_cols() - 1
    pad = room - display_width(ANSI_RE.sub("", names)) - display_width(ANSI_RE.sub("", hint))
    return f"{names}{' ' * max(pad, 4)}{hint}"


def foot_lines(srcs):
    """説明欄の行（どのタブも同じ形: 名前 ──── 中身。名前の列の幅をそろえる。名前に色が付いていてもよい）。名前が「注意」の行は
    注意書きの帯（theme.callout。幅をそろえるのには数えない）"""
    width = lambda n: display_width(ANSI_RE.sub("", n))
    w = max([width(n) for n, _ in srcs if n != "注意"] + [0])
    return [theme.callout(d) if n == "注意" else f"{n} {C_LINE}{'─' * (w - width(n) + 1)}{C_RESET} {d}" for n, d in srcs]


def foot_args(cur, lines=(), clickonly=False, flowmap=None):
    """足もと（fzf の footer）の引数。lines を FOOT_ROWS の高さにそろえて出す。クリックは hackdeck footclick が受ける
    （流れの図の行）"""
    lines = list(lines) + [" "] * (FOOT_ROWS - len(lines))   # 高さをそろえる（足りない分は空白1つの行）
    if not lines:
        return []
    return ["--footer", "\n".join(lines), "--footer-border=line",
            "--bind", f"click-footer:transform:hackdeck footclick {shlex.quote(flowmap) if flowmap else '-'} 0"]


def item_preview(cmd, what, hint):
    """カーソルの行ごとに変わる上の枠（コマンド選び・履歴・設定の項目の一覧）の fzf の引数。cmd: 行の印（{1}）から枠の中身を出す
    コマンド。打った文字に当たる行が無いときは「当たる<what>は無い」とキーのヒント（hint。色つきの1行）の枠にする（fzf は、
    カーソルの行が無いと枠を空にし、題もキーも消えていた。打ち直すと、行ごとの枠に戻す）"""
    none = work_file("none.txt", f"{theme.C_COMMENT}当たる{what}は無い{C_RESET}\n"
                                 f"{theme.C_HINT}打った文字を消すと、全部に戻る{C_RESET}\n{hint}")
    return ["--preview", cmd, "--bind", f"zero:change-preview(cat {shlex.quote(str(none))})",
            "--bind", f"change:+change-preview({cmd})"]


def turns(ps, keep=40):
    """カーソルの位置の並びから、動きの向きが変わった所と最後だけを残す（fzf の一覧のずらし方は、これで決まる）"""
    out = []
    for p in ps:
        if out and p == out[-1]:
            continue
        if len(out) >= 2 and (out[-2] < out[-1]) == (out[-1] < p):
            out[-1] = p   # 同じ向きに進んだ: 端を伸ばす
        else:
            out.append(p)
    return out[-keep:]


def fzf_run(args, tab, clickonly=False, place=None, **kw):
    """fzf を1回走らせる。run_builder が入った代わりの画面の中に、--height=-1 で上から描かせる（fzf が起動のたびに代わりの
    画面へ入り直して画面を消すのをやめ、画面やタブを移るときのチカチカを無くす。2026-10-30、本人の指摘「タブが移動する
    たびに画面が一回閉じる。目がチカチカする」）。1行目にタブの並びを描き、2行目から fzf。
    place: その画面の状態（列の1つ）。一覧の見え方（カーソルの動き。o・oq）を覚え、次に同じ画面を出すときに戻す"""
    try:
        with open("/dev/tty", "w") as tty:
            # 背景を変えるテーマは、自分で描く行も地の色で（行の残りも \x1b[K で地の色に塗る）
            tty.write(f"\x1b[1;1H{theme.based(tab_line(tab, clickonly))}\x1b[K{C_RESET}\x1b[2;1H")
    except OSError:
        pass
    if True:
        # fzf は起動の途中で、受け持つ最初の行を消し（ESC[K）、同期描画を区切って端末に位置を問い合わせ、返事を待ってから描く。
        # その間に消えた行が映るので、最初の行が上の枠の上辺だと、タブを移るたびに上辺が一瞬消えた（2026-10-30、本人の指摘
        # 「タブの下の四角い枠の上辺がチカチカ消える」。端末への出力を記録して確かめた）。最初の1行を空けて（--margin）、消されても
        # 見た目が変わらないようにする
        args = [args[0], "--margin=1,0,0,0", *args[1:]]
    # 一覧の端の近くの行をクリックしても、一覧をずらさない（fzf の既定は、カーソルを一覧の端から3行離す。クリックした行が端から
    # 3行以内だと、その場で一覧がずれ、2回のクリックの2回目が別の行に当たることもあった。2026-11-01、本人の指摘「何かを決定
    # したりすると、画面がクリックした直前の状態と変わる」）
    args = [args[0], "--scroll-off=0", *args[1:]]
    # カーソルは、前の fzf が終わってから次の fzf が最初の画面を描くまで、受け持つ最初の行の左端に出ていた（fzf は終わるときに
    # カーソルを出し、起動の途中の位置の問い合わせでも出したまま返事を待つ。タブを移るたびに 20〜110ms。2026-10-30、本人の指摘
    # 「Ctrl+Tab をすると、タブの下の左隅にカーソルが一瞬出る」。端末への出力を時刻つきで記録して確かめた）。--no-input で起動中は
    # 隠し、start で入力欄を出す（最初の画面から入力欄は入っている）。終わったらすぐ隠し、run_builder が閉じるときに戻す
    args = [args[0], "--no-input", "--bind", "start:show-input", *args[1:]]
    # 配色の形（枠の線・選んでいる行の印・入力欄の頭・線。2026-11-01、本人の指摘「全く異なる系の配色を何パターンも」）
    args = [args[0], *theme.fzf_shape_args(),
            *(a.replace("border-rounded", f"border-{theme.FRAME}") if a.startswith("up,") else a for a in args[1:])]
    # 左右のキーでもタブを移る（2026-10-31、本人の指摘「左右ボタンでもできるように。画面上でそのことを示す必要はない」＝ヒントには
    # 出さない）。検索欄が空のときだけ（空なら ←・→ はもともと何もしない。打ちかけの文字を直すときのカーソル移動は奪わない）。
    # キーボードでタブを移れる画面（--expect に btab がある。書き換えの途中は外れている）だけ。移り方はタブの並びのクリックと同じ
    # （print → accept。各画面が tab_hit で受ける）
    order = [k for k, _ in tabs()]
    expect = next((a.split("=", 1)[1].split(",") for a in args if a.startswith("--expect=")), [])
    # 戻る・進む・上へ（Alt+←・→・↑）は、その画面で受けないときは何もしない（fzf の既定の「1語の左右」などにさせない。
    # 2026-10-29。前は画面ごとに書いていた）
    args = args + [a for k in ("alt-left", "alt-right", UP_KEY) if k not in expect for a in ("--bind", f"{k}:ignore")]
    if tab in order and "btab" in expect:
        i = order.index(tab)
        for key, to, move in (("left", order[i - 1], "backward-char"), ("right", order[(i + 1) % len(order)], "forward-char")):
            args = args + ["--bind", f"{key}:transform:[ -z {{q}} ] && echo 'print({TAB_PREFIX}{to})+accept' || echo {move}"]
    # 前の画面の全角の字の地の色（注意書きの黄色い帯・選んでいた行の地）が、字の右半分だけ1マスおきに残っていた（2026-11-01、
    # 本人の報告「直前の画面に出た忠告文が次の画面でも残骸が残る」）。tmux 3.7c の窓（display-popup）では、全角の字の左半分を
    # 半角で上書きすると、tmux は右半分を地の色の無い空白とみなし、続けて fzf がそこへ地の色の無い空白を書いても「変わらない」
    # として端末へ送らない。GNOME Terminal（VTE）は右半分に元の地の色を残すので、それが見える（ペインなら tmux が行ごと描き
    # 直すので起きない。tmux の開発版では直っている）。新しい画面を描いた直後（キーを押す前の focus。fzf は画面を書き出して
    # から focus の動作をする）に、tmux に窓ごと描き直させる（その場で上書きするので、画面は消えない）。focus が画面を書き出す
    # 前に来たときのために、少しあとにもう1回。VTE で再現して確かめた（tests/vte.py）
    focus = []
    if os.environ.get("HACKDECK_POPUP") and os.environ.get("TMUX"):
        focus.append('[ -n "$FZF_KEY" ] || (tmux refresh-client; sleep 0.2; tmux refresh-client) >/dev/null 2>&1 &')
    # 起動し直しても、一覧の見え方を前と同じにする（2026-11-01、本人の指摘「配色を選ぶと画面が若干上にスクロールされる。設定を
    # 変えたり何かを決定したりすると、画面がクリックした直前の状態と変わる」）。配色を選ぶときなど、画面は fzf を起動し直して
    # 描く。fzf は一覧のずらし方を外に出さず、起動し直すと「カーソルの行が見える最小のずらし方」になって、前と違う所が見えた。
    # ずらし方はカーソルの動きで決まるので、動きの向きが変わった所を覚えておき（place の o。検索語 oq のときのもの）、次に
    # 同じ画面を出すときに同じ順にカーソルを動かす（findpos・findidx が、最初の画面を描く前に pos(…) を続けて出す）
    # 動きは決まった1つのファイルに書く（/tmp に毎回作ると、窓ごと止められたときに残っていった）
    hist = None
    if place is not None:
        hist = work_file("scroll", "")
        focus.insert(0, f"printf '%s\\t%s\\n' \"$FZF_QUERY\" \"$FZF_POS\" >>{shlex.quote(str(hist))}")
        kw["env"] = {**(kw.get("env") or os.environ), "HACKDECK_REPLAY": " ".join(map(str, place.get("o") or []))}
    # 見出し・空行（1列目が HEADING の行）には、カーソルを止めない（2026-10-30、本人の指摘「改行や見出しにはフォーカスしない
    # ように」。はじめは変数の画面だけで、配色の一覧では見出しにもカーソルが止まった。2026-11-01、本人の指摘「見出しは選択肢に
    # 入れない方針」で、どの画面も同じにした）。移った向き（直前の位置と比べる）にもう1つ進む。いちばん上の見出しなら、一覧を
    # 1行ずらして見出しを見せてから1つ戻す（ずらさないと、一覧が長いとき、いちばん上の見出しは隠れたままだった。戻してから
    # ずらすと、一覧が短いときにカーソルが見出しに戻った）。位置は一覧の何番目か（FZF_POS。{n} は入力の何行目かで、fzf に
    # 絞らせると一覧の位置と違う）。毎回 Python を起こすと矢印キーが重くなるので、シェルだけで。候補の1列目をタブで区切る画面
    # だけ（コマンド選び・履歴の行に見出しは無い）
    if any(a == "--delimiter" and b == "\t" for a, b in zip(args, args[1:])):
        last = shlex.quote(str(work_file("focus", "0")))
        focus.insert(0, f'if [ {{1}} = {HEADING} ]; then read -r p 2>/dev/null <{last}; '   # 先頭に（裏で描き直す & の後ろに ; を続けない）
                        f'if [ "$FZF_POS" -lt "${{p:-0}}" ]; then echo down; elif [ "$FZF_POS" -lt "$FZF_MATCH_COUNT" ]; '
                        f'then echo up; else echo offset-up+down; fi; fi; echo "$FZF_POS" >{last}')
    if focus:
        # transform: 見出しを飛ばす動き（up・down）だけを返す。ほかは何も出さない（記録はファイルへ、描き直しは裏で）
        args = args + ["--bind", "focus:+transform:" + "; ".join(focus)]
    # マウス: 1回のクリックはカーソルを動かすだけ（fzf の既定。その行の説明が見られる）、2回のクリックは Enter と同じ（2026-11-01、
    # 本人の指摘「コマンドなどはクリックすると窓を閉じてしまう」。どの画面も同じにし、本人が「2回で決める」を選んだ）。fzf の2回の
    # クリックの既定は accept で、押したキー（--expect）の行が空になり、画面は中断とみなして窓を閉じていた。印を print して、
    # 下で Enter に読み替える。画面の側で left-click を割り当てない（1回で決めると、2回目のクリックが次の画面に届く）
    keyed = any(a.startswith("--expect") for a in args)
    if keyed:
        args = args + ["--bind", f"double-click:print({CLICK_MARK})+accept"]
    # fzf の一時ファイル（{*f} など）も作業の置き場所に（止められても /tmp に残さない）
    kw["env"] = {**(kw.get("env") or os.environ), "TMPDIR": str(work_dir())}
    r = subprocess.run(args, **kw)
    k = 1 if "--print-query" in args else 0   # 押したキーの行（検索語の行の次）
    out = r.stdout.splitlines() if keyed and isinstance(r.stdout, str) else []
    if CLICK_MARK in out[k + 1:]:
        del out[out.index(CLICK_MARK, k + 1)]
        out[k] = "enter"
        r.stdout = "\n".join(out) + "\n"
    if hist:
        try:
            recs = [l.split("\t", 1) for l in hist.read_text(encoding="utf-8").splitlines() if "\t" in l]
        except OSError:
            recs = []
        lines = r.stdout.splitlines() if isinstance(r.stdout, str) else []
        query = lines[0] if "--print-query" in args and lines else (recs[-1][0] if recs else place.get("oq", ""))
        moves = []   # 終わりの検索語のときの動き（検索語が変わると一覧が変わるので、その前の動きは使えない）
        for q, p in reversed(recs):
            if q != query:
                break
            if p.isdigit() and p != "0":
                moves.insert(0, int(p))
        same = place.get("oq") == query and all(q == query for q, _ in recs)   # この画面の間、検索語が変わらなかった
        place["o"], place["oq"] = turns(((place.get("o") or []) if same else []) + moves), query
    try:
        with open("/dev/tty", "w") as tty:
            tty.write("\x1b[?25l")
    except OSError:
        pass
    return r


def tab_hit(lines):
    """fzf の出力に、タブの並びのクリックの印があれば、そのタブ"""
    return next((l[len(TAB_PREFIX):] for l in lines if l.startswith(TAB_PREFIX)), None)


def candidate_val_width(lines):
    """「値\t説明」または「値」だけの行一覧から、値のうちいちばん長い見た目の幅を返す（0 なら整形不要）。
    opts/*.tsv をそのまま候補にしていたため、値の長さが行ごとに違うとタブの位置（＝説明の開始位置）
    がそろわず「値と説明がバラバラで見にくい」状態になっていた（2026-10-28、本人の指摘）。
    説明の無い行（nxc-proto.tsv 等、値だけの1列）も対象にする。外していたため、そのような候補だけの
    変数（proto 等）は val_w が常に0になり、pad_candidate_line が1列のまま返していた。prompt_var は
    --with-nth=2（2列目だけ表示）で候補を出すため、1列しかない行は2列目が無く画面が空白になっていた
    （2026-10-29、「オプションに何も表示されない」との報告で実機確認して特定）"""
    return max((display_width(cand_fields(l)[1]) for l in lines if not l.startswith(HEADING)), default=0)


def cand_fields(line):
    """候補の1行を (値, 表示名, 説明) に分ける。「値」「値\\t説明」「値\\t表示名\\t説明」の3つの形を受け付ける
    （3列の形は 2026-10-29 追加。認証の形のように、入る値（-u <pw_user> -p <pw_pass>）と画面で見せる名前
    （パスワード）が違う候補のため）"""
    parts = line.split("\t", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[0], parts[1]
    return parts[0], parts[0], ""


def pad_candidate_line(line, val_w, desc_w=0):
    """候補の1行を「値\t(表示名をそろえた表示)\t表示名」に変換する。
    1列目（選んだときに返す実際の値）はそのまま、2列目（表示用）だけ表示名をそろえて説明を続ける。
    説明の無い行（opts の1列だけのファイルなど）も、2列目に整形済みの値をそのまま入れて2列化する
    （値のまま1列で返すと、--with-nth=2 で表示する画面でその行が空白になるため。2026-10-29 修正）。
    3列目の表示名は、選んだあと流れの図に出すために持ち帰る（2026-10-29 追加）。desc_w: 説明に使える幅（0 なら切らない。
    一覧の中身のような「・」で並べた説明は、値の区切りで詰める）"""
    val, shown, desc = cand_fields(line)
    if val == HEADING:
        return f"{HEADING}\t{desc}\t"   # 見出し・空行は、値の列に入れずにそのまま
    if desc and desc_w:
        desc = fit_desc(desc, desc_w)
    return f"{val}\t{fit(shown, val_w)}  {desc}\t{shown}" if desc else f"{val}\t{fit(shown, val_w)}\t{shown}"


def entry_label(r):
    """プレビューの1行目に出す「コメント [タグ]」（navi 時代と同じ形式・同じ色）"""
    return f"{theme.C_COMMENT}{r['comment']}{C_RESET} {theme.C_TAG}[{r['tag']}]{C_RESET}"


def twice(e, pending, kind, target, note):
    """2回押しの確かめ（消す・上書き・終える。2026-10-30、本人の指摘「操作は共通にしたほうが覚えやすい」で、資格情報・
    よく使う・環境・案件のタブでそろえた）。直前に同じ相手へ同じ操作をしていれば True。でなければ印と、画面に出す一言
    （note）を付けて False。ほかのキーを押すと印は消える（画面が fzf から戻るたびに pending として取り出すため）"""
    if pending and pending[:2] == [kind, target]:
        return True
    e["confirm"] = [kind, target, note]
    return False


def rows_now(fn, query, scr_env):
    """候補の行（画面ごとの ...rows を、この中で呼んだ出力）。fzf に最初から渡す。start:reload で後から入れると、起動の
    たびに一覧が空の画面が一瞬出て、目がチカチカした（2026-10-30、本人の指摘「エントリーを消したら画面が一回暗くなる」）"""
    old = {k: os.environ.get(k) for k in scr_env}
    os.environ.update(scr_env)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(query)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return buf.getvalue()


def keep_place(e, sel, fn, query, scr_env, act):
    """消したあともカーソルを同じ位置に（同じ位置に来る行へ）。前は消した行を探して見つからず、カーソルが先頭へ飛んでいた
    （本人の指摘「エントリーを消したら、フォーカスしているエントリーが変わる」）"""
    keys = lambda: [l.split("\t", 1)[0] for l in rows_now(fn, query, scr_env).splitlines()]
    before = keys()
    i = before.index(sel) if sel in before else 0
    act()
    after = keys()
    e["f"] = after[min(i, len(after) - 1)] if after else None


def note_args(e):
    """画面の一言（確かめの「もう一度…」か、やったことの知らせ）を検索ボックスの上に出す fzf の引数。知らせは1回だけ"""
    note = e.pop("msg", None)
    if e.get("confirm"):
        return ["--header", e["confirm"][2], "--color", "header:#ffcf6b:bold"]
    # 何も無いときも空の1行をとっておく（一言が出るたびに一覧が1行上にずれて、チカチカした。2026-10-30、本人の指摘）
    return ["--header", note or " "]


def nav_hint(can_back, can_fwd, back_key=None, esc="初期画面へ"):
    """キーのヒントの後ろ半分（どの画面でも同じキー）。esc: Esc の説明（コマンド選びは「初期状態へ」）"""
    h = []
    if can_back:
        h.append(f"Alt+←/{KEY_LABEL[back_key]} 戻る" if back_key else "Alt+← 戻る")
    if can_fwd:
        h.append("Alt+→ 進む")
    if NAV_UP:
        h.append("Alt+↑ 上へ")
    if esc:
        h.append(f"Esc {esc}")
    return h + ["Ctrl+G 閉じる"]


def nav_key(key, cur=None):
    """どの画面でも同じ意味のキー。cur: いまの画面のタブ（Ctrl+Tab＝Tab で次のタブへ。tab:名前 はタブの並びのクリック）"""
    if key.startswith("tab:"):
        return ("tab", key[4:])
    if cur and key in ("tab", "btab"):
        # Ctrl+Tab（＝Tab）で次、Ctrl+Shift+Tab（GNOME Terminal は Shift+Tab と同じ ESC [Z で送る）で前のタブ
        # （2026-10-30、本人の指摘「Ctrl+Shift+Tab で逆順に」）
        order = [k for k, _ in tabs()]
        if cur not in order:
            return ("tab", order[0])
        return ("tab", order[(order.index(cur) + (1 if key == "tab" else -1)) % len(order)])
    if key == "alt-left":
        return ("back",)
    if key == "alt-right":
        return ("forward",)
    if key == UP_KEY:
        return ("up",)
    if key == "esc":
        # そのタブの初期画面へ（2026-10-30、本人の指摘「Esc を押すと各タブの初期画面に戻るように」。前はどのタブからでも
        # コマンド選びへ戻っていた）。書き換えの途中ならやめて、そのタブの一覧へ
        return ("tabhome", cur) if cur and cur != "cmd" else ("home",)
    if key in CLOSE_KEYS or not key:
        return ("close",)   # 空: fzf が何も返さなかった（Ctrl+Q 等の既定の中断）
    return ("stay",)
