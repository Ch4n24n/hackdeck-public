"""資格情報のタブと、netexec が見つけた資格情報の一覧（Ctrl+N）。"""
import os
import shlex
from pathlib import Path

from .paths import COPY_STATE
from .text import copy_text, fit, q, short_home
from .theme import C_RESET, _fzf_theme_color_opt
from .case import case_root
from .creds import CRED_ADD_RE, cred_save, creds_file, delete_cred, own_creds, same_cred
from .nxc import c_nxcrows, nxc_desc, nxc_found, nxc_home, nxc_key, nxc_refresh, nxc_workspace_dir
from .fzfcall import filter_rows
from .ui import (CLOSE_KEYS, UP_KEY, foot_args, foot_lines, fzf_run, keep_place, nav_hint, nav_key, note_args, rows_now,
    tab_hit, twice, work_file)
from . import theme
from . import ui


def c_credcopy(key):
    """資格情報の画面の Ctrl+Y（fzf の transform から呼ばれ、画面は閉じない）。同じ行で1回目はユーザー、続けて
    2回目はパスワード（ハッシュ）をコピーする（2026-10-29、本人の指摘「同じキーでユーザーとパスワードを」）。
    何をコピーしたかを、検索ボックスの上（header）に1行出す"""
    if not key.startswith("op:"):
        return
    line_no = int(key[3:])
    c = next((c for c in own_creds() if c["line"] == line_no), None)
    if not c:
        return
    try:
        last = COPY_STATE.read_text(encoding="utf-8")
    except OSError:
        last = ""
    field = "secret" if last == f"{line_no}\tuser" else "user"
    copy_secret(line_no, field)
    COPY_STATE.parent.mkdir(parents=True, exist_ok=True)
    COPY_STATE.write_text(f"{line_no}\t{field}", encoding="utf-8")
    msg = (f"{c['user']} のパスワードをコピーした" if field == "secret"
           else f"ユーザー {c['user']} をコピーした。もう一度 Ctrl+Y でパスワード")
    print(f"change-header:{msg}")


def copy_secret(line_no, field="secret"):
    """資格情報の画面の Ctrl+Y。その行のパスワード（ハッシュ）をクリップボードに入れる（2026-10-29、本人の指摘。
    CopyQ を使っているとその履歴にも残る）。Wayland は wl-copy、それ以外は xclip"""
    c = next((c for c in own_creds() if c["line"] == line_no), None)
    if c:
        copy_text(c[field])   # field: secret / user


def c_credsrows(query=""):
    """資格情報の画面の候補（打つたびに作り直す）。1列目は選んだときの印（add・op:行番号・ro）。
    先頭は、打った user:pass を足す行。その上の資格情報は、ほかのタブと同じく打った文字で絞る（fzfcall.filter_rows。
    ユーザー・パスワード（ハッシュ）・説明）"""
    f = creds_file()
    if CRED_ADD_RE.match(query):
        same, dup = same_cred(query, f)
        hint = ("同じものがもうある" if dup else f"Enter で上書き（2回。いまの {same['user']} の行）" if same
                else f"Enter で {f.name} に足す")
    else:
        hint = "user:pass:説明 の形で打つ" if query else "user:pass:説明 を打って Enter（説明は省略可）"
    editing = os.environ.get("HACKDECK_EDITING", "")
    if editing:
        hint = f"Enter で {int(editing) + 1} 行目を書き換える" if CRED_ADD_RE.match(query) else hint
    print(f"add\t{fit('＋ 保存' if editing else '＋ 追加', 15)}  {fit(query, 36)}  {hint}")
    if editing:
        return  # 書き換え中は「保存」の行だけ（カーソルが他の行へ動かないように。2026-10-29、本人の指摘）
    rows = []
    for c in own_creds():
        secret = f"NT {c['secret']}" if c["kind"] == "nt" else q(c["secret"]) if c["secret"] else "—"
        rows.append((f"op:{c['line']}", f"{fit(c['user'] or '—', 15)}  {fit(secret, 36)}  {c['desc']}",
                     f"{c['user'] or '—'}  {secret}  {c['desc']}"))
    for line in filter_rows(rows, query.strip()):
        print(line)


def creds_screen(e, can_back, can_fwd):
    """資格情報の画面（Ctrl+S。コマンド選び・変数の画面のどちらからも開ける）。打った user:pass:説明 を Enter で
    足し、Ctrl+D で消す（2026-10-29、本人の指摘「資格情報は自動で保存するとゴミが集まるので、Ctrl+G で入った画面の
    どこかで設定できたらいい」で追加）。打った文字は、一覧を絞り（ほかのタブと同じ。絞るのは c_credsrows）、そのまま
    いちばん下の行で足す値にもなる。
    行を選んで Enter で書き換え（保存の1行だけの画面を列に足す。Enter で保存、Alt+← で書き換えをやめる。2026-11-07 から。前は
    Ctrl+E）、Ctrl+Y でユーザー・パスワードをクリップボードへ（2026-10-29、本人の指摘で追加）。
    e: 列の1つ（q 検索語・f カーソルの行・e 書き換えている行の番号・t その行の書き換え前の中身・tab 大きいタブ（creds。
    同じ画面で開いていた「よく使う」は、2026-10-30 に設定のタブの2項目へ移した））。
    戻り値は var_screen と同じ。書き換えを保存したときだけ ("saved", カーソルを合わせる行)"""
    tab, root = "creds", case_root()
    f = creds_file()
    editing = e.get("e")
    if editing is None:
        nxc_refresh(f)   # netexec のあとで増えた Pwn3d! を、足した行の説明の（netexec …）にも出す
    if editing is not None:
        # 書き換えている行が、閉じている間や別の行を消したあとに動いていないか（書き換え前の中身で探し直す）
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        if not (0 <= editing < len(lines) and lines[editing] == e.get("t")):
            editing = e["e"] = lines.index(e["t"]) if e.get("t") in lines else None
    home = str(Path.home())
    where = "~" + str(f)[len(home):] if str(f).startswith(home + "/") else str(f)
    if editing is None:
        n = len(nxc_found()[0])
        hint = ["Enter 追加・書き換え", f"Ctrl+N netexec（{n}件）",
                "Ctrl+Y コピー（1回目ユーザー・2回目パスワード）", "Ctrl+D 消す（2回）"] \
            + ["Ctrl+O いまの場所に一覧を書き出す"] + nav_hint(can_back, can_fwd)
    else:
        hint = ["Enter 保存"] + (["Alt+← 書き換えをやめる"] if can_back else []) + nav_hint(False, can_fwd)
    title, scope = "資格情報", root.name
    preview = (f"{theme.C_COMMENT}{title}{C_RESET} {theme.C_TAG}[{scope}]{C_RESET}\n"
               f"{theme.C_HINT}置き場所{C_RESET} {where}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
    # 説明欄は、初めて見ても分かる言葉で（2026-10-30、本人の指摘「初見の人間にはさっぱり」。どのタブも同じ決まり: 1行目は
    # ファイルと中身、2行目からは書き方と見分け方。キーの操作は上の枠に、仕組み・経緯・数は書かない。置き場所は上の枠）
    srcs = [(f.name, "この案件で見つけた資格情報。1行に user:pass:説明（説明は省ける）"),
            ("範囲", "説明の頭にドメイン名か端末名（例 test.local・SVC01）。端末名ならローカルのアカウント"),
            ("見分け方", "32桁の16進（LM:NT の形も）は NT ハッシュ、それ以外はパスワード")]
    foot = foot_lines(srcs)
    keys = ["enter", "esc", *CLOSE_KEYS] + ([UP_KEY] if ui.NAV_UP else []) \
        + (["ctrl-d", "ctrl-n", "tab", "btab"] if editing is None else []) \
        + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else [])
    pv = work_file("preview.txt", preview)
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--disabled", "--no-sort", "--no-clear",
            "--color", _fzf_theme_color_opt(),
            "--preview", f"cat {shlex.quote(str(pv))}", "--preview-window", "up,3,border-rounded,noinfo",
            *foot_args(tab, foot),
            "--delimiter", "\t", "--with-nth=2", "--print-query", "--query", e.get("q", ""),
            f"--expect={','.join(keys)}",
            # コピーは画面を閉じずにその場で（カーソルが先頭に戻らないように。2026-10-29、本人の指摘）
            "--bind", "ctrl-y:transform:hackdeck credcopy {1}",
            "--bind", "change:reload(hackdeck credsrows {q})",
            # 打って候補が変わったら、カーソルを先頭（画面ではいちばん下）へ。前の位置のままだと、減った候補の別の行に
            # 残ることがあった（2026-10-30、案件のタブで Bravo と打つと「＋ 新しい案件」の行に残った）
            "--bind", "load:first"]
    if editing is not None:
        args += ["--bind", "ctrl-d:delete-char"]  # 既定の delete-char/eof は、検索語が空だと fzf ごと閉じる
    else:
        args += ["--bind", "ctrl-o:transform:hackdeck credlists"]  # 一覧ファイルの書き出し（コピーと同じく画面は閉じない）
    if e.get("f"):
        args += ["--sync", "--bind", f"result:transform:hackdeck findpos {shlex.quote(e['f'])} {{*f}}"]
    args += note_args(e)
    scr_env = {"HACKDECK_EDITING": "" if editing is None else str(editing)}
    r = fzf_run(args, tab, input=rows_now(c_credsrows, e.get("q", ""), scr_env), capture_output=True, text=True,
                env={**os.environ, **scr_env}, place=e)
    parts = r.stdout.splitlines()
    pending = e.pop("confirm", None)
    if not parts:
        return ("close",)
    typed, key = parts[0], parts[1] if len(parts) > 1 else ""
    if tab_hit(parts[1:]):
        e["q"] = typed
        return ("tab", tab_hit(parts[1:]))   # タブの並びのクリック
    sel = parts[2].split("\t", 1)[0] if len(parts) > 2 else ""
    e["q"] = typed
    if sel:
        e["f"] = sel
    rows = {f"op:{c['line']}": c for c in own_creds(f)}
    if key == "ctrl-d" and sel in rows:
        c = rows[sel]
        if twice(e, pending, "del", sel, f"もう一度 Ctrl+D で消す: {c['user'] or '—'} {c['secret'] or ''} {c['desc']}".rstrip()):
            keep_place(e, sel, c_credsrows, typed, {"HACKDECK_EDITING": ""},
                       lambda: delete_cred(int(sel[3:]), f))
        return ("stay",)
    if key == "ctrl-n":
        return ("push", {"s": "nxc", "tab": tab, "q": "", "f": None})   # netexec が見つけた分（nxc_screen）
    if key != "enter":
        return nav_key(key, tab)
    if sel in rows:
        # 書き換え: その行を検索欄に出し、Enter（保存の行）でその行に上書きする（2026-10-29、本人の指摘）。2026-11-07 から、行を
        # 選んで Enter で（本人「既存の項目を選んで Enter したら編集モードに入り、再度 Enter したら設定のほうが直感的」。前は
        # Ctrl+E で、Enter は「書き換えは Ctrl+E」と出すだけだった）。一覧の検索欄はそのまま（Alt+← でやめると、打っていた文字の
        # まま戻る。同日いったん空にしたが、本人「一回戻って、再度入り直したときに、以前の記入を残すか？って話ね。なら残しておいて」）
        n = int(sel[3:])
        line = f.read_text(encoding="utf-8").splitlines()[n]
        return ("push", {"s": "creds", "tab": tab, "q": line, "f": "add", "e": n, "t": line})
    if sel == "add" and CRED_ADD_RE.match(typed):
        if editing is None:
            # 同じもの（資格情報はユーザーと説明が同じ）があれば、確かめてから上書き。中身まで同じなら何もしない
            if cred_save(e, pending, typed, f):
                e["q"] = ""   # 打つ行に留まる（2026-10-31、本人の指摘「操作のあとにカーソルの位置が変わる」。前は足した行へ飛んだ）
            return ("stay",)
        lines = f.read_text(encoding="utf-8").splitlines()
        if 0 <= editing < len(lines):
            lines[editing] = typed
            f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ("saved", f"op:{editing}")
    return ("stay",)


def nxc_screen(e, can_back, can_fwd):
    """netexec が見つけた資格情報の画面（資格情報のタブの Ctrl+N。2026-10-31、本人が選んだ案 B）。まだ資格情報の
    ファイルに無いものを並べ、Enter でその1つを足す（user:pass:範囲（netexec ホスト 権限）。nxc_desc。
    ユーザーと範囲が同じ行がもうあれば、資格情報のタブと同じく Enter を2回で上書き）。足したあとも、この画面に留まる
    （続けて足せる。足した行は一覧から消える）。Ctrl+N をもう一度で資格情報のタブへ（履歴の Ctrl+R と同じ）。打った文字で絞る。
    e: 列の1つ（q 検索語・f カーソルの行）。戻り値は var_screen と同じ"""
    tab, root, f = "creds", case_root(), creds_file()
    hint = ["Enter 資格情報に足す", "Ctrl+N 資格情報へ戻る"] + nav_hint(can_back, can_fwd)
    preview = (f"{theme.C_COMMENT}netexec が見つけた資格情報{C_RESET} {theme.C_TAG}[{root.name}]{C_RESET}\n"
               f"{theme.C_HINT}置き場所{C_RESET} {short_home(nxc_workspace_dir(nxc_home()))}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
    # 説明欄は、初めて見ても分かる言葉で（creds_screen と同じ決まり）
    srcs = [("netexec の DB", "この案件で netexec がログインできた・抜いた資格情報のうち、"
                             f"まだ {f.name} に無いもの"),
            ("足すとき", "説明の頭に範囲（ドメイン名か端末名）、（）にコマンド・ホスト・権限。あとで Pwn3d! が増えたら（）も書き足す"),
            ("右の列", "見つけた日時（初めて見つけたとき）・コマンド・ホストと権限（Pwn3d! は全部、強い順。無ければログインできた・抜いたホスト）"),
            ("権限", "smb は管理者。ほかはそのサービスだけ（winrm は WinRM に入れる、mssql は SQL の sysadmin、ssh は root か sudo）。"
                     "ldap・rdp は netexec が DB に残さない")]
    foot = foot_lines(srcs)
    keys = ["enter", "esc", "ctrl-n", "tab", "btab", *CLOSE_KEYS] + ([UP_KEY] if ui.NAV_UP else []) \
        + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else [])
    pv = work_file("preview.txt", preview)
    # 絞り込みは、変数の画面と同じく打った文字そのまま（パスワードの ! や ' を fzf の記号として読まない）
    args = ["fzf", "--layout=default", "--height=-1", "--no-sort", "--no-clear", "--no-extended", "--exact",
            "--color", _fzf_theme_color_opt(),
            "--preview", f"cat {shlex.quote(str(pv))}", "--preview-window", "up,3,border-rounded,noinfo",
            *foot_args(tab, foot),
            "--delimiter", "\t", "--with-nth=2", "--print-query", "--query", e.get("q", ""),
            f"--expect={','.join(keys)}"]
    if e.get("f"):
        args += ["--sync", "--bind", f"result:transform:hackdeck findpos {shlex.quote(e['f'])} {{*f}}"]
    args += note_args(e)
    r = fzf_run(args, tab, input=rows_now(c_nxcrows, "", {}), capture_output=True, text=True, place=e)
    parts = r.stdout.splitlines()
    pending = e.pop("confirm", None)
    if not parts:
        return ("close",)
    typed, key = parts[0], parts[1] if len(parts) > 1 else ""
    if tab_hit(parts[1:]):
        e["q"] = typed
        return ("tab", tab_hit(parts[1:]))   # タブの並びのクリック
    sel = parts[2].split("\t", 1)[0] if len(parts) > 2 else ""
    e["q"] = typed
    if sel:
        e["f"] = sel
    if key == "ctrl-n":
        return ("up",)   # 資格情報のタブへ（開いたキーをもう一度）
    if key != "enter":
        return nav_key(key, tab)
    c = next((c for c in nxc_found()[0] if nxc_key(c) == sel), None)
    if c is None:
        return ("stay",)   # 「まだ記録が無い」などの行
    # 説明はいつも付く（パスワードに : があっても、最後の : の後ろを説明と読み違えない。parse_cred_line）
    text = f"{c['user']}:{c['secret']}:{nxc_desc(c)}"

    def save():
        done = cred_save(e, pending, text, f, by_scope=True)
        if done:
            e["msg"] = f"{'足した' if done == 'add' else '上書きした'}: {c['user']}（{c['scope'] or '範囲なし'}）"
    keep_place(e, sel, c_nxcrows, "", {}, save)
    return ("stay",)
