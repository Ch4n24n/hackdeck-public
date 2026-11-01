"""環境のタブ（案件の環境変数）。"""
import os
import shlex

from .text import copy_text, display_width, fit, short_home
from .theme import C_RESET, _fzf_theme_color_opt
from .case import case_root
from .fzfcall import filter_rows
from .env import (env_reserved, env_defaults, env_defaults_items, env_extra_names, env_file, env_keep,
    env_keep_write, env_name_lines, env_names_file, env_parse, env_update, env_vars)
from .ui import (CLOSE_KEYS, UP_KEY, foot_args, foot_lines, fzf_run, keep_place, nav_hint, nav_key, note_args, rows_now,
    tab_hit, twice, work_file)
from . import theme
from . import ui


def c_envrows(query=""):
    """環境の画面の候補（打つたびに作り直す）。1列目は選んだときの印（add・env:名前）。先頭は打った 名前:値 を書く行、次に
    ファイルにある変数と、書き戻す名前のうちまだ値の無いもの（未設定）。ほかのタブと同じく、打った文字を含む行だけに絞る
    （fzfcall.filter_rows。名前・値・説明。前は = の前の名前だけで絞っていて、名前:値 の形で打つと全部の行が消えていた）"""
    editing = os.environ.get("HACKDECK_EDITING", "")
    vals, keep, descs = dict(env_vars()), env_keep(), env_name_lines()
    pr = env_parse(query) if query.strip() else None
    if pr and env_reserved(pr[0]):
        hint = f"{pr[0]} はここでは変えない（シェルが壊れるため）"
    elif pr:
        n, v, d = pr
        if editing and n != editing:
            hint = f"Enter で {editing} を {n} に変えて保存する" + (f"（2回。いまの {n} は上書き）" if n in vals else "")
        elif editing:
            hint = f"Enter で {n} を保存する"
        elif v is None:
            hint = (f"Enter で {n} の説明を「{d}」にする" if d is not None else f"{n} はもう書き戻す名前" if n in keep
                    else f"Enter で {n} を、この場所の書き戻す名前に足す（値はあとで）")
        elif n in vals and vals[n] == v and d is None:
            hint = f"{n} はもうこの値"
        elif n in vals and vals[n] != v:
            hint = f"Enter で上書き（2回。いまは {vals[n] or '空'}）"
        else:
            hint = f"Enter で {n} を足す" + ("" if n in keep else "（シェルの export でも書き戻すようにする）")
    else:
        hint = "名前:値:説明 の形で打つ" if query else "名前:値:説明 を打って Enter（値・説明は省けて、名前だけでも足せる。例 DC01:10.10.11.5:DC）。書き換えは Ctrl+E"
    w = max([display_width(n) for n in [*vals, *keep]] + [12])
    print(f"add\t{fit('＋ 保存' if editing else '＋ 追加', w)}  {fit(query, 36)}  {hint}")
    if editing:
        return   # 書き換え中は「保存」の行だけ（資格情報の画面と同じ）
    # アルファベット順（画面では上から A→Z）。値が入っても未設定でも位置が変わらない（2026-10-30、本人の指摘「更新順だと、
    # 前の場所と変わって分かりづらい」。前はファイルの順＝更新の順、そのあとに未設定の名前だった）
    dd, rows = dict(env_defaults_items()), []
    for n in sorted({*vals, *keep}, key=str.lower, reverse=True):
        d = "・".join(x for x in (("既定" + (f"（{dd[n]}）" if dd.get(n) else "")) if n in dd else "", descs.get(n, "")) if x)
        v = (vals[n] or "（空）") if n in vals else "（未設定）"
        rows.append((f"env:{n}", f"{fit(n, w)}  {fit(v, 30)}  {d}", f"{n}  {v}  {d}"))
    for line in filter_rows(rows, query.strip()):
        print(line)


def c_envcopy(key):
    """環境の画面の Ctrl+Y（fzf の transform から呼ばれ、画面は閉じない）。その変数の値をクリップボードへ"""
    if not key.startswith("env:"):
        return
    copy_text(f"${key[4:]}")   # 値ではなく $名前（コマンドに貼る形。2026-10-30、本人の指摘）
    print(f"change-header:${key[4:]} をコピーした")


def env_screen(e, can_back, can_fwd):
    """環境の画面（大きいタブの「環境」。2026-10-30、tmux-op の op-env を合流）。案件の環境変数のファイル（env）の
    変数を出し、打った 名前=値 を Enter で書く（もうある名前は、確かめてから上書き）。Ctrl+E で書き換え、Ctrl+D を2回で
    消す（値の無い行なら、シェルの export で書き戻す名前から外す）、Ctrl+Y で値をコピー。操作は資格情報のタブと同じ
    （2026-10-30、本人の指摘「操作感は資格情報タブと同じに。共通にしたほうが覚えやすい」。はじめは行を選んで Enter でも
    書き換えていた）。書いた値は、開いているどのペインも次に打つコマンドから効く（shell/hack.zsh が読み直す）。
    打った文字は、一覧を絞り（ほかのタブと同じ。絞るのは c_envrows）、そのままいちばん下の行で書く値にもなる。
    e: 列の1つ（q 検索語・f カーソルの行・e 書き換えている変数の名前）。戻り値は var_screen と同じ"""
    f, root, editing = env_file(), case_root(), e.get("e")
    if editing is None:
        hint = ["Enter 追加", "Ctrl+E 書き換え", "Ctrl+Y $名前をコピー", "Ctrl+D 消す（2回）"] + nav_hint(can_back, can_fwd)
    else:
        hint = ["Enter 保存"] + (["Alt+← 書き換えをやめる"] if can_back else []) + nav_hint(False, can_fwd)
    preview = (f"{theme.C_COMMENT}環境{C_RESET} {theme.C_TAG}[{root.name}]{C_RESET}\n"
               f"{theme.C_HINT}置き場所{C_RESET} {short_home(f)}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
    # 説明欄は、初めて見ても分かる言葉で（creds_screen と同じ決まり。2026-10-30、本人の指摘「初見の人間にはさっぱり」）
    srcs = [(f.name, "この案件の環境変数。1行に export 名前=値。どのペインでも次のコマンドから使える"),
            (env_names_file().name, "一覧に並べる名前と説明（名前だけでも足せる）。どの案件にも並ぶ名前は設定のタブで決める"),
            ("export・unset", f"一覧にある名前なら、シェルで変えても {f.name} に保存される")]
    foot = foot_lines(srcs)
    keys = ["enter", "esc", *CLOSE_KEYS] + ([UP_KEY] if ui.NAV_UP else []) \
        + (["ctrl-d", "ctrl-e", "tab", "btab"] if editing is None else []) \
        + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else [])
    pv = work_file("preview.txt", preview)
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--disabled", "--no-sort", "--no-clear",
            "--color", _fzf_theme_color_opt(),
            "--preview", f"cat {shlex.quote(str(pv))}", "--preview-window", "up,3,border-rounded,noinfo",
            *foot_args("env", foot),
            "--delimiter", "\t", "--with-nth=2", "--print-query", "--query", e.get("q", ""),
            f"--expect={','.join(keys)}",
            "--bind", "ctrl-y:transform:hackdeck envcopy {1}",
            "--bind", "change:reload(hackdeck envrows {q})",
            # 打って候補が変わったら、カーソルを先頭（画面ではいちばん下）へ。前の位置のままだと、減った候補の別の行に
            # 残ることがあった（2026-10-30、案件のタブで Bravo と打つと「＋ 新しい案件」の行に残った）
            "--bind", "load:first"]
    if editing is not None:
        args += ["--bind", "ctrl-d:delete-char"]  # 既定の delete-char/eof は、検索語が空だと fzf ごと閉じる
    if e.get("f"):
        args += ["--sync", "--bind", f"result:transform:hackdeck findpos {shlex.quote(e['f'])} {{*f}}"]
    args += note_args(e)
    scr_env = {"HACKDECK_EDITING": editing or ""}
    r = fzf_run(args, "env", input=rows_now(c_envrows, e.get("q", ""), scr_env), capture_output=True, text=True,
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
    vals = dict(env_vars(f))
    if key == "ctrl-d" and sel.startswith("env:"):
        n = sel[4:]
        if n in vals:
            stays = ("既定の名前なので行は残る" if n in env_defaults() else
                     "名前は残り、未設定になった行でもう一度押すと名前も外れる" if n in env_extra_names() else "")
            if twice(e, pending, "del", sel, f"もう一度 Ctrl+D で {n} の値を消す: {n}={vals[n]}（開いているどのペインからも"
                     f"外れる{'。' + stays if stays else ''}）"):
                keep_place(e, sel, c_envrows, typed, {"HACKDECK_EDITING": ""}, lambda: env_update([(n, None)], f))
        elif n in env_defaults():
            e["msg"] = f"{n} は既定の名前なので外せない"
        elif twice(e, pending, "del", sel, f"もう一度 Ctrl+D で、書き戻す名前から {n} を外す"):
            keep_place(e, sel, c_envrows, typed, {"HACKDECK_EDITING": ""},
                       lambda: env_keep_write([k for k in env_extra_names() if k != n]))
        return ("stay",)
    if key == "ctrl-e" and sel.startswith("env:") and editing is None:
        # 書き換え: 名前=いまの値 を検索ボックスに出し、Enter（保存の行）で書く（資格情報の画面の Ctrl+E と同じ）
        d = env_name_lines().get(sel[4:], "")
        return ("push", {"s": "env", "q": f"{sel[4:]}:{vals.get(sel[4:], '')}" + (f":{d}" if d else ""), "f": "add",
                         "e": sel[4:]})
    if key != "enter":
        return nav_key(key, "env")
    if sel.startswith("env:"):
        e["msg"] = "書き換えは Ctrl+E（Enter は一番下の行で足す）"
        return ("stay",)
    pr = env_parse(typed) if sel == "add" else None
    if not pr or env_reserved(pr[0]):
        return ("stay",)
    name, val, desc = pr
    if desc is not None:
        env_keep_write([*env_extra_names(), *([name] if name not in env_keep() else [])], {name: desc})
    if val is None:   # 名前だけ（説明だけ）: 書き戻す名前に足す・説明を変える
        if editing is not None and editing != name:
            env_update([(editing, None)], f)
        if name not in env_keep():
            env_keep_write([*env_extra_names(), name])
            e["msg"] = f"{name} を書き戻す名前に足した（値は 名前:値 か、シェルの export で）"
        if editing is not None:
            return ("saved", f"env:{name}")
        e["q"] = ""   # 打つ行に留まる（2026-10-31、本人の指摘「操作のあとにカーソルの位置が変わる」。前は足した行へ飛んだ）
        return ("stay",)
    if editing is None and vals.get(name) == val:
        e["msg"] = f"{name} はもうこの値" if desc is None else f"{name} の説明を変えた"
        e["q"] = "" if desc is not None else e["q"]
        return ("stay",)
    if name in vals and name != editing and not twice(
            e, pending, "over", typed, f"もう一度 Enter で上書き: {name} {vals[name] or '（空）'} → {val}"
            + (f"（{editing} は消える）" if editing else "")):
        return ("stay",)
    env_update(([(editing, None)] if editing and editing != name else []) + [(name, val)], f)
    if name not in env_keep():
        env_keep_write([*env_extra_names(), name])   # 画面で足した名前は、シェルの export でも書き戻す
    if editing is None:
        e["q"] = ""
        return ("stay",)
    return ("saved", f"env:{name}")
