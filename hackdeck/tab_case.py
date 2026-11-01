"""案件のタブ（案件の一覧・入る・作る・終える）。"""
import datetime
import os
import re
import shlex
import subprocess
import termios
import tty as ttymod

from .text import copy_text, display_width, fit, short_home
from .theme import C_RESET, _fzf_theme_color_opt
from .case import CASE_NAME_RE, case_path, cases_dir, is_case_dir, last_case, to_trash
from .session import (TOOL, case_kill, case_open, case_rename, case_rows, in_server, leave, template_kind, tmux,
                      tmux_sessions)
from .ui import (CLOSE_KEYS, foot_args, foot_lines, fzf_run, keep_place, nav_hint, nav_key, note_args, rows_now,
    tab_hit, twice, work_file)
from .nav import nav_handoff
from .fzfcall import filter_rows
from . import theme


MAKE_HOW = {"git": "雛形を clone する", "dir": "雛形を写す", "": "作業フォルダだけを作る"}   # 雛形の種類ごとの、作り方


def c_caserows(query=""):
    """案件のタブの候補（打つたびに作り直す）。1列目は選んだときの印（new・detach・case:名前）。いちばん下（先頭）は新しい
    案件の行（2026-10-30、本人の指摘「新しい案件は一番下に」）。何も打っていなければ、その上に案件から離れる行（案件の
    セッションの中だけ）と案件（作った順。新しいものほど下）。打つと、ほかのタブと同じく、打った文字を含む案件だけになる
    （fzfcall.filter_rows。名前と日付。本人の理解「既存は候補に出るので選んで Enter、新規は＋新しい案件だけが残る」。カーソルは、
    合う案件があればそちらへ。c_casepos）"""
    cur, typed = os.environ.get("HACKDECK_CUR_SESSION", ""), query.strip()
    old = os.environ.get("HACKDECK_RENAME", "")
    if old:   # 名前を変えている間（Ctrl+E）は、その1行だけ
        if not typed:
            hint = "新しい名前を打って Enter"
        elif typed == old:
            hint = "同じ名前（直してから Enter）"
        elif not CASE_NAME_RE.match(typed):
            hint = "名前に使えるのは英数字と - _ + だけ"
        elif case_path(typed).exists():
            hint = "その名前はもうある"
        else:
            hint = "Enter で名前を変える"
        print(f"rename\t✎ 名前を変える  {old} → {fit(typed, 36)}  {hint}")
        return
    rows = case_rows()
    nw = min(max([display_width(r["name"]) for r in rows] + [16]), 36)   # 絞っても列の位置は変えない
    if not typed:
        hint = f"名前を打って Enter（Ctrl+T で今日の日付を頭に。{MAKE_HOW[template_kind()]}）"
    elif not CASE_NAME_RE.match(typed):
        hint = "名前に使えるのは英数字と - _ + だけ"
    elif case_path(typed).exists():
        hint = "その名前はもうある（上の行を選ぶ）"
    else:
        hint = f"Enter で作る（{MAKE_HOW[template_kind()]}）"
    print(f"new\t{fit('＋ 新しい案件', nw + 2)}  {(fit(typed, 30) + '  ') if typed else ''}{hint}")
    if not typed and cur:   # 操作の行なので、打っている間は出さない（打った文字の先の Enter で離れないように）
        print(f"detach\t{fit('↩ 案件から離れる', nw + 2)}  元の端末へ（セッションは動いたまま。prefix+d と同じ）")
    day = lambda t: datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else "—"
    lines = []
    for r in rows:
        # 状態は丸の色で分かるので文にしない（本人の指摘「説明の文は要るか？上にまとめて説明されている」）。窓の数もやめ、
        # 作成日と更新日（2026-10-30、本人の指摘「窓数はいらない」「作成日と更新日を書いて」）
        mark = (f"{theme.CASE_CUR}●{C_RESET}" if r["name"] == cur else f"{theme.CASE_ON}●{C_RESET}") if r["running"] \
            else f"{theme.C_HINT}○{C_RESET}"
        dates = f"作成 {day(r['born'])}  更新 {day(r['updated'])}"
        lines.append((f"case:{r['name']}", f"{mark} {fit(r['name'], nw)}  {dates}", f"{r['name']}  {dates}"))
    for line in filter_rows(lines, typed):
        print(line)


def c_casecopy(key):
    """案件のタブの Ctrl+Y（fzf の transform から呼ばれ、画面は閉じない）。案件名をコピーする（2026-10-30、本人の指摘）"""
    if key.startswith("case:"):
        copy_text(key[5:])
        print(f"change-header:案件名 {key[5:]} をコピーした")


def c_dateprefix(query=""):
    """案件の名前の頭に今日の日付（20261030-）を入れる。もう日付が頭にあれば、今日の日付に替える"""
    today = datetime.date.today().strftime("%Y%m%d")
    print(today + "-" + (query[9:] if re.match(r"^\d{8}-", query) else query))


def run_screen(title, cmd, ok, ng):
    """別の画面でコマンドを走らせ、コマンドと出力をそのまま見せる。終わったら、成功は緑・失敗は赤で最後の行に書き、キーの
    ヒント（Enter 戻る・Ctrl+Y ログをコピー）を出して待つ（2026-10-30、本人の指摘「新しい案件は Ctrl+G の中で作る。別の画面に
    コマンドとログを出し、成功なら緑、失敗なら赤。ログのコピーのヒントも。Enter で元の画面に戻る」）。戻り値は終わりの状態"""
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return subprocess.run(cmd).returncode

    def w(x):
        os.write(fd, x.encode("utf-8") if isinstance(x, str) else x)
    w(theme.based(f"\x1b[2J\x1b[H{theme.C_COMMENT}{title}{C_RESET}\n\n{theme.C_SNIPPET}$ {shlex.join(cmd)}{C_RESET}\n"))
    log = bytearray()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while chunk := os.read(p.stdout.fileno(), 4096):
            log += chunk
            w(chunk)
        rc = p.wait()
    except OSError as ex:
        rc = 127
        log += f"{ex}\n".encode()
        w(f"{ex}\n")
    # コピーする中身は、進み具合の上書き（\r）を畳んだもの
    text = "\n".join(l.rsplit("\r", 1)[-1] for l in log.decode("utf-8", "replace").split("\n")).strip("\n")
    w("\n" + (f"\x1b[1;32m✔ {ok}\x1b[0m" if rc == 0 else f"\x1b[1;31m✘ {ng}（終わりの状態 {rc}）\x1b[0m") + "\n")
    hint = f"{theme.C_HINT}Enter 戻る  Ctrl+Y ログをコピー{C_RESET}"
    w(hint)
    old = termios.tcgetattr(fd)
    try:
        ttymod.setraw(fd)
        while (ch := os.read(fd, 1)) not in (b"\r", b"\n", b"\x07", b"\x03", b""):
            if ch == b"\x19":   # Ctrl+Y
                copy_text(f"$ {shlex.join(cmd)}\n{text}\n")
                w(f"\r\x1b[2K{hint}  コピーした")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        os.close(fd)
    return rc


def case_screen(e, can_back, can_fwd):
    """案件の画面（大きいタブの「案件」。2026-10-30、tmux-op の new・attach・kill・ls を合流）。案件を選んで Enter で、
    案件のセッションの中ならその場で切り替え（止まっていれば残した並びで戻す）、外ならその端末で案件のセッションに入る
    （session.case_open）。名前を打つと案件が絞られ、無い名前なら「＋ 新しい案件」で Enter を押すと、この中の別の画面で
    雛形から作る（run_screen。同日、本人の指摘で、入力行に入れる形から変えた）。Ctrl+D を2回でセッションを終える（本人が
    選んだ）。「案件から離れる」はセッションを止めずに元の端末へ戻る（prefix+d と同じ。本人の問い「案件外に抜けたいときは」）。
    e: 列の1つ（q 検索語・f カーソルの行）。戻り値は var_screen と同じ"""
    inside = in_server()
    cur = (tmux("display-message", "-p", "#{session_name}") or "").strip() if inside else ""
    if not CASE_NAME_RE.match(cur):   # 待合（tmux の外で開いた窓の下）と、案件の外のセッション（設定の outside）は案件の外
        cur = ""
    if e.get("f") is None:
        # 開いたときのカーソルは直前の案件（セッションの中は1つ前のセッション、外は「直前」のファイル）
        prev = (tmux("display-message", "-p", "#{client_last_session}") or "").strip() if inside else ""
        if not prev or prev == cur:
            prev = last_case()   # 名前を変えていても、目印で今の名前を探す
        if prev and prev != cur and is_case_dir(case_path(prev)):
            e["f"] = f"case:{prev}"
    where = short_home(cases_dir())
    # Ctrl+E で名前を変えている案件（2026-11-01、本人の指摘）。その間は、名前を直す1行だけを出す
    renaming = e.get("e")
    if renaming:
        hint = ["直して Enter で名前を変える", "Ctrl+T 日付を頭に", "Esc・Alt+← やめる"]
    else:
        hint = ["Enter " + ("切り替える" if inside else "入る"), "Ctrl+T 日付を頭に", "Ctrl+Y 案件名をコピー",
                "Ctrl+E 名前を変える", "Ctrl+D 終える（2回）", "Ctrl+X 消す（2回。ゴミ箱へ）"] + nav_hint(can_back, can_fwd)
    title = f"案件の名前を変える{C_RESET} {theme.C_TAG}[{renaming}]" if renaming else f"案件{C_RESET} {theme.C_TAG}[{cur or '案件の外'}]"
    preview = (f"{theme.C_COMMENT}{title}{C_RESET}\n"
               f"{theme.C_HINT}置き場所{C_RESET} {where}\n"
               f"{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
    # 説明欄は、初めて見ても分かる言葉で（creds_screen と同じ決まり。2026-10-30、本人の指摘「初見の人間にはさっぱり」）。印ごとに
    # 1行にして、左の列の幅をほかのタブにそろえた。案件は、置き場所の下のフォルダ1つと、同じ名前の tmux のセッション
    srcs = ([(f"{theme.CASE_CUR}●{C_RESET} いま入っている", "この画面を開いたセッションの案件")] if cur else []) \
        + [(f"{theme.CASE_ON}●{C_RESET} 動いている", "セッションがある案件。入ると、そのセッションに移る"),
           ("○ 止まっている", "セッションが無い案件。入ると作り直し、終えたときの窓の並びと画面があれば戻す")]
    if renaming:
        srcs = [("変わるもの", "案件のフォルダの名前。中の資格情報・環境・履歴・メモ・ログ・残した窓の並びは、そのまま使える"),
                ("使える名前", "英数字と - _ +。まだ無い名前")]
    foot = foot_lines(srcs)
    if renaming:
        keys = ["enter", "esc", *CLOSE_KEYS, "alt-left"]
    else:
        keys = ["enter", "esc", *CLOSE_KEYS, "ctrl-d", "ctrl-x", "ctrl-e", "tab", "btab"] + (["alt-left"] if can_back else []) \
            + (["alt-right"] if can_fwd else [])
    pv = work_file("preview.txt", preview)
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--disabled", "--no-sort", "--no-clear",
            "--color", _fzf_theme_color_opt(),
            "--preview", f"cat {shlex.quote(str(pv))}", "--preview-window", "up,3,border-rounded,noinfo",
            *foot_args("case", foot),
            "--delimiter", "\t", "--with-nth=2", "--print-query", "--query", e.get("q", ""),
            f"--expect={','.join(keys)}",
            "--bind", "change:reload(hackdeck caserows {q})",
            # --sync: 最初の画面を描くのは、この位置合わせ（Python）が終わってから（2026-11-01、本人の指摘「チカチカする」。無いと、
            # 枠だけ先に描かれ、終わるまでの 0.06 秒ほど、上の枠の中身が空になっていた）
            "--sync", "--bind", "load:transform:hackdeck casepos {q}",
            # 新しい案件の名前の頭に今日の日付（本人の指摘「よく接頭辞に日付を使うから、日付を入れるショートカットを」）
            "--bind", "ctrl-t:transform-query:hackdeck dateprefix {q}",
            "--bind", "ctrl-y:transform:hackdeck casecopy {1}"]
    if e.get("f"):
        args += ["--sync", "--bind", f"result:transform:hackdeck findpos {shlex.quote(e['f'])} {{*f}}"]
    args += note_args(e)
    scr_env = {"HACKDECK_CUR_SESSION": cur, "HACKDECK_RENAME": renaming or ""}
    r = fzf_run(args, "case", input=rows_now(c_caserows, e.get("q", ""), scr_env), capture_output=True, text=True,
                env={**os.environ, **scr_env})
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
    if renaming:
        if key == "enter":
            ok, msg = case_rename(renaming, typed.strip())
            e["msg"] = msg
            if ok:
                e.update(e=None, q="", f=f"case:{typed.strip()}")
            return ("stay",)
        e.update(e=None, q="", f=f"case:{renaming}")   # Esc・Alt+← はやめる。窓を閉じても、次は一覧から
        return ("stay",) if key in ("esc", "alt-left") else nav_key(key, "case")
    if key == "ctrl-e":
        # 名前を変える（2026-11-01、本人の指摘）。動いている案件は変えない（session.case_rename の説明）
        name = sel[5:] if sel.startswith("case:") else ""
        if not name:
            e["msg"] = "名前を変える案件の行で Ctrl+E"
        elif tmux_sessions().get(name):
            e["msg"] = f"{name} は動いている（名前を変えるのは、Ctrl+D で終えてから。窓の並びは残る）"
        else:
            e.update(e=name, q=name)
        return ("stay",)
    if key == "ctrl-x":
        # 案件のフォルダをゴミ箱へ（2026-10-30、本人の指摘「Ctrl+G からディレクトリを削除できるように」。消さずにゴミ箱へ移すので、
        # ゴミ箱から戻せる。動いている案件は先に終える）
        name = sel[5:] if sel.startswith("case:") else ""
        if name and tmux_sessions().get(name):
            e["msg"] = f"{name} は動いている（先に Ctrl+D で終える）"
        elif name and twice(e, pending, "trash", sel, f"もう一度 Ctrl+X で {name} をゴミ箱へ（案件のフォルダごと。ゴミ箱から戻せる）"):
            done = {}
            # 消したあともカーソルを同じ位置に（2026-10-31、本人の指摘「案件を消すと、消したあとのフォーカスの位置が変わる」。
            # 前はカーソルを空にしていて、開いたときと同じ「直前の案件」に飛んでいた）
            keep_place(e, sel, c_caserows, typed, scr_env, lambda: done.update(r=to_trash(case_path(name))))
            ok, why = done["r"]
            e["msg"] = f"{name} をゴミ箱へ移した" if ok else f"ゴミ箱へ移せなかった: {why}"
        return ("stay",)
    if key == "ctrl-d":
        name = sel[5:] if sel.startswith("case:") else ""
        s = tmux_sessions().get(name) if name else None
        if name and not s:
            e["msg"] = f"{name} は止まっている（終えるものが無い）"
        elif s:
            n = len((tmux("list-panes", "-s", "-t", s["id"], "-F", "x") or "").splitlines())
            if twice(e, pending, "kill", sel, f"もう一度 Ctrl+D で {name} を終える（窓 {s['windows']}・ペイン {n}。"
                                             "中のシェルとリバースシェルも切れる。窓の並びは残す）"):
                case_kill(name)   # いまのセッションなら、この画面ごと閉じる（tmux が端末へ戻す）
                e["msg"] = f"{name} を終えた（窓の並びは残した。選ぶと戻る）"
        return ("stay",)
    if key != "enter":
        return nav_key(key, "case")
    if sel == "new":
        name = typed.strip()
        if not name:
            e["msg"] = "名前を打ってから Enter"
            return ("stay",)
        if not CASE_NAME_RE.match(name) or case_path(name).exists():
            e["msg"] = "その名前では作れない（英数字と - _ + だけ・まだ無い名前）"
            return ("stay",)
        rc = run_screen(f"新しい案件を作る: {name}", [str(TOOL), "case", "make", name],
                        f"作った: {where}/{name}（Enter で戻って、選ぶと入る）", "作れなかった")
        if rc == 0:
            e.update(q="", f=f"case:{name}")
            e["msg"] = f"{name} を作った（Enter で入る）"
        return ("stay",)
    if sel == "detach":
        if cur:
            nav_handoff(None, {"s": "case", "q": "", "f": f"case:{cur}", "e": None})   # 案件の外で開くと、いまの案件の行
        # 案件の外のセッションから来た端末は、そこへ戻る（prefix+d と同じ。session.leave）
        leave((tmux("display-message", "-p", "#{client_name}") or "").strip())
        return ("close",)
    if sel.startswith("case:"):
        name = sel[5:]
        if name != cur:
            nav_handoff(case_path(name), {"s": "case", "q": "", "f": sel, "e": None})   # 入った先で開くと、案件のタブのこの行
        if not inside:
            # 閉じたその場で、案件のセッションに入る（本人の指摘「コマンドは打ちたくない。Enter した時点でセッションに入って
            # いてほしい」）。画面を元に戻してから入るので、run_builder に任せる
            return ("attach", name)
        if name != cur:
            case_open(name)
        return ("close",)
    return ("stay",)
