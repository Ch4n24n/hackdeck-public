"""設定のタブ。画面は settings.SETTINGS から作る（項目を足すときは SETTINGS に1つ足すだけで、ここは触らない。新しい種類を
足すときだけ、ここに見せ方を足す）。

画面は2段: 項目の一覧（v なし）と、項目を開いた画面（v に項目のキー）。開いた画面は項目の種類で決まる:
  choice     候補から選ぶ（配色。選ぶとすぐ変わる）
  bool       開かない。一覧で Enter を押すたびに、する・しないが変わる
  dir・text  いまの値を検索欄に出し、直して Enter で保存（打つたびに、値の問題を settings.problem で一言出す）
  list       一覧を書く（＋の行で Enter 足す・ほかの行で Enter 書き換え・Ctrl+D 外す）。settings.json の配列
  common     よく使うユーザー・パスワード（list と同じ操作。中身は paths.COMMON_CREDS）"""
import os
import shlex
from pathlib import Path

from .paths import COMMON_CREDS, SETTINGS_FILE
from .text import fit, short_home
from .settings import BY_KEY, SETTINGS
from . import settings
from .theme import C_RESET, GROUPS, THEMES, THEME_ORDER, _fzf_theme_color_opt, apply_theme, save_theme_name, swatch
from .creds import common_items, common_lines, common_parse, common_shown, common_write, parse_cred_line
from .env import env_defaults_items, env_reserved
from .session import write_conf
from .fzfcall import filter_grouped, filter_rows
from .ui import (CLOSE_KEYS, UP_KEY, foot_args, foot_lines, fzf_run, grouped, item_preview, keep_place, nav_hint, nav_key,
    note_args, rows_now, tab_hit, twice, work_file, work_subdir)
from . import theme
from . import ui

TMUX_KEYS = ("key", "user_tmux_conf", "stamps", "home_cmd", "theme")   # 変えたら、専用の tmux の設定を作り直す（write_conf）
EMPTY_MEANS = {"template": "空なら、作業フォルダとログの置き場所だけを作る", "log_file": "空なら、ログを残さない"}
# 一時的に変えるときの例（説明欄の「一時的に」。bool は 1 する・0 しない）
EXAMPLES = {"theme": "matrix", "cases_dir": "~/ctf", "template": "~/templates/case", "work_dir": ".", "state_dir": ".hack",
            "log_file": "logs/run.log", "stamps": "0", "home_cmd": "hk", "key": "M-g", "user_tmux_conf": "0", "memo": "1", "outside": "1"}
# 開いた画面の注意書き（変えても、すでにあるものは動かない、など）
NOTES = {"work_dir": "変えても、もとからある案件のファイルは動かさない（前の場所のものは手で移す）",
         "state_dir": "変えても、もとからある案件のデータは動かさない（前の場所のものは手で移す）",
         "log_file": "変えても、もとからある案件のログは動かさない。動いているセッションは、新しく開いたペインから",
         "key": "動いている案件のセッションにも、すぐ効く"}


def shown_value(s):
    """項目の一覧に出す、いまの値"""
    v = settings.get(s.key)
    if s.kind == "choice":
        return THEMES[theme.CURRENT_THEME]["label"]
    if s.kind == "bool":
        return "する" if v else "しない"
    if s.kind == "dir":
        return short_home(Path(v).expanduser())
    if s.kind == "list":
        return "・".join(x.partition(":")[0] if s.key == "env_defaults" else x for x in v) or "（無し）"
    if s.kind == "common":
        return "・".join(common_shown(c, s.key) for c in common_items(s.key)) or "（無し）"
    return v or f"（空。{EMPTY_MEANS.get(s.key, '')}）".replace("。）", "）")


def list_items(key):
    """一覧を書く項目の行 [(印, 見せる文字, 探す文字（列の幅で切り詰める前）)]（ファイル・設定の順）"""
    if key == "env_defaults":
        return [(f"it:{i}", f"{fit(n, 14)}  {d}", f"{n}  {d}") for i, (n, d) in enumerate(env_defaults_items())]
    if key in ("common_users", "common_passwords"):
        rows = []
        for c in common_items(key):
            d = "・".join(x for x in (f"{c['user']} と組" if key == "common_passwords" and c["user"] else "", c["desc"]) if x)
            rows.append((f"cm:{c['line']}", fit(common_shown(c, key), 24) + "  " + d, f"{common_shown(c, key)}  {d}"))
        return rows
    rows = []
    for i, x in enumerate(settings.get(key)):
        text = x + ("" if Path(x).expanduser().is_dir() else "  （無いフォルダ）")
        rows.append((f"it:{i}", text, text))
    return rows


def where_lines(x):
    """その項目の、保存先と一時的な変え方（説明欄の行）。[(見出し, 中身)]。いま環境変数で上書きされていれば注意書きも"""
    if x.kind == "common":
        lines = [("保存先", f"{short_home(COMMON_CREDS)}（よく使うユーザーとパスワードで1つのファイル。手で直してもよい）")]
    else:
        lines = [("保存先", f"{short_home(SETTINGS_FILE)} の「{x.key}」（この画面で変えると書き換わる。手で直してもよい）")]
    name = settings.env_name(x.key)
    if name:
        ex = EXAMPLES.get(x.key, "値")
        lines.append(("一時的に", f"{name}={ex} hackdeck のように付けて起動すると、その回だけその値を使う（保存先は変わらない）"))
        now = settings.overridden(x.key)
        if now is not None:
            lines.append(("注意", f"いまは {name}={now} が効いている。ここで変えても、その間は使われない"))
    elif x.key in settings.SERVER_KEYS:
        lines.append(("一時的に", "案件のセッションの tmux とシェルに効く項目なので、一時的には変えられない（ここで変える）"))
    else:
        lines.append(("一時的に", "一覧の項目なので、一時的には変えられない"))
    return lines


def item_problem(key, text):
    """一覧に足す・書き換える1行の問題（無ければ None）"""
    if key in ("common_users", "common_passwords"):
        return None if common_parse(text, key) else "形が違う"
    if key == "env_defaults" and env_reserved(text.partition(":")[0].strip()):
        return "その名前はシェルが使う（既定にできない）"
    return settings.problem(key, text)


def c_settingrows(query=""):
    """設定のタブの候補。HACKDECK_SETTINGS_VIEW は開いている項目（空なら項目の一覧）、HACKDECK_EDITING は書き換えている
    行の印。1列目は選んだときの印。項目の一覧・配色・一覧を書く項目は、ほかのタブと同じく打った文字で絞る（一覧を書く項目は、
    いちばん下の足す行は残る）。値を書く項目と書き換えは、打った文字が値（保存の1行だけ）"""
    key = os.environ.get("HACKDECK_SETTINGS_VIEW", "")
    s = BY_KEY.get(key)
    if s is None:
        rows = []
        for x in reversed(SETTINGS):   # 画面は下から上へ並ぶので、SETTINGS の順に上から出すには逆に
            over = "  （環境変数で上書き中）" if settings.overridden(x.key) is not None else ""
            v = shown_value(x)
            rows.append((x.key, f"{fit(x.label, 26)}  {v}{over}", f"{x.label}  {v}{over}"))
        for line in filter_rows(rows, query.strip()):
            print(line)
        return
    if s.kind == "choice":
        # まとまり（GROUPS）ごとに見出し。画面は下から上へ並ぶので、まとまりも中身も逆に渡す（ui.grouped）。打った文字で絞ると、
        # 当たった行のあるまとまりだけを見出しつきで残す（変数の画面と同じ。2026-11-01、本人の指摘「見出しは選択肢に入れない
        # 方針」。前は fzf に絞らせていて、見出しも1つの行として打った文字に当たり、中身の無い見出しだけが残ることがあった）
        groups = []
        for g, title in reversed(GROUPS):
            rows = [(f"theme:{n}", f"{swatch(n)}  {THEMES[n]['label']}  {theme.C_HINT}{n}{C_RESET}"
                     + (f"  {theme.C_TAG}← いま{C_RESET}" if n == theme.CURRENT_THEME else ""))
                    for n in reversed(THEME_ORDER) if THEMES[n]["group"] == g]
            groups.append((title, rows))
        for line in filter_grouped([f"{v}\t{shown}" for v, shown in grouped(groups)], query.strip()):
            print(line)
        return
    if s.kind in ("dir", "text"):
        v = query.strip()
        why = settings.problem(key, v)
        hint = why or (f"Enter で空にする（{EMPTY_MEANS[key]}）" if not v and key in EMPTY_MEANS else
                       f"Enter で{s.label}をこれにする")
        print(f"save\t{fit('＋ 保存', 10)}  {fit(query, 56)}  {hint}")
        return
    if os.environ.get("HACKDECK_EDITING"):
        print(f"save\t{fit('＋ 保存', 10)}  {fit(query, 40)}  {item_problem(key, query) or 'Enter で書き換える'}（{s.hint}）")
        return
    hint = (f"{s.hint} を打って Enter" if not query.strip() else item_problem(key, query) or "Enter で足す")
    print(f"add\t{fit('＋ 追加', 10)}  {fit(query, 40)}  {hint}")   # 名前は資格情報・環境のタブと同じ
    for line in filter_rows(list(reversed(list_items(key))), query.strip()):
        print(line)


def settings_screen(e, can_back, can_fwd):
    """設定の画面（大きいタブの「設定」）。項目の一覧を出し、Enter か2回のクリックで開いて選ぶ・書く（2026-10-30、本人の指摘
    「設定タブは項目にし、クリックした後に選べるように」。はじめは1回のクリックで開いていたが、2026-11-01、どの画面もクリックの
    決まりをそろえるときに本人が「2回で決める」を選んだ。ui.fzf_run）。配色は選ぶとすぐ色が変わり、その画面のまま（本人の指摘「配色を変えても
    前のタブに移らなくていい」）。値を書く項目は、いまの値を検索欄に出し、直して Enter で保存して一覧に戻る（Alt+← でやめる）。
    一覧を書く項目は、＋の行で Enter 足す・ほかの行で Enter 書き換え・Ctrl+D 外す、Esc で項目の一覧に戻る（よく使うものは、
    はじめは大きいタブの「よく使う」で書いていたが、2026-10-30、本人の指摘「ユーザーとパスワードは別々の設定項目に」でここへ移した）。
    e: 列の1つ（v 開いている項目・q 検索語・f カーソルの行・e 書いている行・t 書き換える前の行）。戻り値は var_screen と同じ"""
    key, editing = e.get("v") or "", e.get("e")
    s = BY_KEY.get(key)
    listing = s is not None and s.kind in ("list", "common")
    rows_dir = None
    if s is None:
        hint = ["Enter 開く（する・しないは、その場で切り替わる）"] + nav_hint(can_back, can_fwd)
        # 説明の箱と足もとは、カーソルのある項目のもの（項目ごとのファイルを、fzf の preview と focus の transform-footer が
        # 出す。2026-10-31、本人の指摘「置き場所・試すとき が何を示しているのか分からない。項目ごとにどの環境変数を使えばいいのかも」）
        rows_dir = work_subdir("settings")
        for x in SETTINGS:
            (rows_dir / x.key).write_text(
                f"{theme.C_COMMENT}{x.label}{C_RESET} {theme.C_TAG}[{theme.CURRENT_THEME}]{C_RESET}\n"
                f"{theme.C_HINT}{x.help}{C_RESET}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}", encoding="utf-8")
            lines = foot_lines(where_lines(x))
            (rows_dir / f"{x.key}.foot").write_text(
                "\n".join(lines + [" "] * (ui.FOOT_ROWS - len(lines))), encoding="utf-8")
        (rows_dir / "none.foot").write_text("\n".join([" "] * max(ui.FOOT_ROWS, 1)), encoding="utf-8")   # 当たる項目が無いとき
        first = BY_KEY.get(e.get("f") or "") or SETTINGS[0]
        srcs = where_lines(first)
        line2 = ""
    elif s.kind == "choice":
        hint = ["Enter 選ぶ（すぐ変わる）"] + nav_hint(can_back, can_fwd)
        line2 = f"いま {THEMES[theme.CURRENT_THEME]['label']}"
        srcs = [(s.label, "選ぶとすぐ色が変わり、この画面のまま。戻るのは Alt+←"),
                ("絞り方", "名前（京紫・Matrix など）か、右の英字の名前（kyo・matrix）を打つ")]
    elif s.kind in ("dir", "text") or editing is not None:
        hint = ["Enter 保存"] + (["Alt+← やめる"] if can_back else []) + nav_hint(False, can_fwd)
        line2 = f"いま {shown_value(s)}" if editing is None else "直して Enter で保存"
        srcs = [("書き方", s.hint), *where_lines(s)]
    else:
        hint = ["Enter 追加・書き換え", "Ctrl+D 外す（2回）"] \
            + (["Ctrl+O いまの場所に一覧を書き出す"] if s.kind == "common" else []) + nav_hint(can_back, can_fwd)
        line2 = s.help
        srcs = [("書き方", f"{s.hint} を打って Enter で足す"), *where_lines(s)]
    if s is not None and key in NOTES:
        srcs.append(("注意", NOTES[key]))
    preview = (f"{theme.C_COMMENT}{s.label if s else '設定'}{C_RESET} {theme.C_TAG}[{theme.CURRENT_THEME}]{C_RESET}\n"
               f"{theme.C_HINT}{line2}{C_RESET}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
    foot = foot_lines(srcs)
    keys = ["enter", "esc", *CLOSE_KEYS] + ([UP_KEY] if ui.NAV_UP else []) + (["tab", "btab"] if editing is None else []) \
        + (["ctrl-d"] if listing and editing is None else []) \
        + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else [])
    # どの一覧も、絞るのは hackdeck 側（c_settingrows。配色の一覧は見出しを残すため）。打ったら、いちばん下の行へ（load:first。
    # ほかのタブと同じ）
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--disabled", "--no-sort",
            "--no-clear", "--color", _fzf_theme_color_opt(),
            "--preview-window", "up,3,border-rounded,noinfo",
            *foot_args("settings", foot),
            "--delimiter", "\t", "--with-nth=2", "--print-query", "--query", e.get("q", ""),
            f"--expect={','.join(keys)}", "--bind", "change:reload(hackdeck settingrows {q})", "--bind", "load:first"]
    if rows_dir:
        rows = shlex.quote(str(rows_dir))
        args += item_preview(f"cat {rows}/{{1}}", "項目", f"{theme.C_HINT}{'  '.join(hint)}{C_RESET}")
        args += ["--bind", f"focus:transform-footer:cat {rows}/{{1}}.foot 2>/dev/null || cat {rows}/none.foot"]
    else:
        args += ["--preview", f"cat {shlex.quote(str(work_file('preview.txt', preview)))}"]
    if s is not None and s.kind == "common" and editing is None:   # 一覧ファイルの書き出し（前の「よく使う」のタブの Ctrl+O）
        args += ["--bind", "ctrl-o:transform:hackdeck credlists "
                 + ("common-user" if key == "common_users" else "common-pass common-hash")]
    focus = e.get("f") or (f"theme:{theme.CURRENT_THEME}" if s is not None and s.kind == "choice" else
                           SETTINGS[0].key if s is None else "")
    if focus:
        # 開いたときだけカーソルを合わせる（findpos が unbind(result) も出す。配色を打って絞るたびに、いまの配色へ戻さない）
        args += ["--sync", "--bind", f"result:transform:hackdeck findpos {shlex.quote(focus)} {{*f}}"]
    args += note_args(e)
    scr_env = {"HACKDECK_SETTINGS_VIEW": key, "HACKDECK_EDITING": editing or ""}
    r = fzf_run(args, "settings", input=rows_now(c_settingrows, e.get("q", ""), scr_env), capture_output=True,
                text=True, env={**os.environ, **scr_env}, place=e)
    parts = r.stdout.splitlines()
    pending = e.pop("confirm", None)
    if not parts:
        return ("close",)
    typed, key_pressed = parts[0], parts[1] if len(parts) > 1 else ""
    # 打った文字は残す（タブを移って戻っても、一言を出し直しても。ほかのタブと同じ。前は残さず、形の違う値を Enter すると、
    # 直していた値がもとに戻った）
    e["q"] = typed
    if tab_hit(parts[1:]):
        return ("tab", tab_hit(parts[1:]))   # タブの並びのクリック
    sel = parts[2].split("\t", 1)[0] if len(parts) > 2 else ""
    if sel:
        e["f"] = sel
    if listing:
        return list_action(e, s, pending, typed, key_pressed, sel, editing)
    if key_pressed not in ("enter", ""):
        return nav_key(key_pressed, "settings")
    if s is None:
        x = BY_KEY.get(sel)
        if x is None:
            return ("stay",)
        if x.kind == "bool":
            settings.save(**{x.key: not settings.get(x.key)})
            if x.key in TMUX_KEYS:
                write_conf()
            e["msg"] = f"{x.label}: {shown_value(x)}"
            return ("stay",)
        if x.kind in ("dir", "text"):
            now = settings.get(x.key)
            return ("push", {"s": "settings", "v": x.key, "q": short_home(Path(now).expanduser()) if x.kind == "dir" else now,
                             "f": "save", "e": x.key})
        return ("push", {"s": "settings", "v": x.key, "q": "", "f": None})
    if s.kind == "choice":
        if sel.startswith("theme:") and sel[6:] in THEMES:
            save_theme_name(sel[6:])
            apply_theme(sel[6:])
            write_conf()   # 次に開く窓の色も
            theme.restyle_popup()   # いま開いている窓の地と枠も、すぐに
            # 画面は消さない（2026-11-01、本人の指摘「全体としてチカチカするのは止めてほしい」。前は地を塗り直すために全部を
            # 消していて、次の画面を描くまで 0.1 秒ほど空白になった）。地は、次の画面の fzf が受け持つ所（余白の行も）を全部、
            # タブの並びは fzf_run が塗り直す。どちらも塗らない所は窓の地（restyle_popup）
            e["msg"] = f"配色を {THEMES[sel[6:]]['label']} にした"
        return ("stay",)
    value = typed.strip()
    why = settings.problem(key, value)
    if why:
        e["msg"] = why
        return ("stay",)
    settings.save(**{key: value})
    if key in TMUX_KEYS:
        write_conf()
    return ("saved", key)


def list_action(e, s, pending, typed, key_pressed, sel, editing):
    """一覧を書く項目（list・common）の操作"""
    key, items = s.key, {m: t for m, t, _ in list_items(s.key)}
    view_env = {"HACKDECK_SETTINGS_VIEW": key, "HACKDECK_EDITING": ""}
    if key_pressed == "ctrl-d" and sel in items:
        if twice(e, pending, "del", sel, f"もう一度 Ctrl+D で外す: {items[sel].split('  ')[0].strip()}"):
            keep_place(e, sel, c_settingrows, typed, view_env, lambda: list_remove(key, sel))
        return ("stay",)
    if key_pressed not in ("enter", ""):
        return nav_key(key_pressed, "settings")
    if sel in items:
        # 書き換え（資格情報・環境のタブと同じく、行を選んで Enter で。2026-11-07 から。前は Ctrl+E で、Enter は「書き換えは
        # Ctrl+E」と出すだけ。その前は、どの行で Enter しても打った文字を足していた）。一覧の検索欄はそのまま（資格情報のタブと同じ）
        q0, old = list_text(key, sel)
        return ("push", {"s": "settings", "v": key, "q": q0, "f": "save", "e": sel, "t": old})
    text = typed.strip()
    why = item_problem(key, text)
    if why or not text:
        e["msg"] = why or f"{s.hint} の形で"
        return ("stay",)
    if s.kind == "common":
        return common_save(e, key, text, editing)
    vals = settings.get(key)
    old = vals[int(editing[3:])] if editing and int(editing[3:]) < len(vals) else None
    if key == "env_defaults":
        n, _, d = text.partition(":")
        text = n.strip() + (f":{d.strip()}" if d.strip() else "")
        same = [i for i, x in enumerate(vals) if x.partition(":")[0] in (n.strip(), (old or "").partition(":")[0])]
    else:
        same = [i for i, x in enumerate(vals) if x in (text, old)]
    pos = same[0] if same else len(vals)
    vals = [x for i, x in enumerate(vals) if i not in same]
    vals.insert(min(pos, len(vals)), text)
    settings.save(**{key: vals})
    if editing:
        return ("saved", f"it:{vals.index(text)}")
    e["q"] = ""   # 打つ行に留まる（2026-10-31、本人の指摘「操作のあとにカーソルの位置が変わる」。前は足した行へ飛んだ）
    return ("stay",)


def list_text(key, mark):
    """書き換えるときに検索欄に出す文字と、書き換える前の行"""
    if key in ("common_users", "common_passwords"):
        c = next(c for c in common_items(key) if f"cm:{c['line']}" == mark)
        t = common_lines()[c["line"]]
        return (c["user"] + (f":{c['desc']}" if c["desc"] else "") if key == "common_users" else t.partition(":")[2]), t
    v = settings.get(key)[int(mark[3:])]
    return v, v


def list_remove(key, mark):
    if key in ("common_users", "common_passwords"):
        n = int(mark[3:])
        common_write([l for i, l in enumerate(common_lines()) if i != n])
    else:
        n = int(mark[3:])
        settings.save(**{key: [x for i, x in enumerate(settings.get(key)) if i != n]})


def common_save(e, key, text, editing):
    """よく使うユーザー・パスワードの1行を足す・書き換える"""
    line = common_parse(text, key)
    lines = common_lines()
    if editing:
        old, i = e.get("t", ""), int(editing[3:])
        if not (0 <= i < len(lines) and lines[i] == old):
            i = lines.index(old) if old in lines else None   # 開いている間に行が動いた
        if i is not None:
            lines[i] = old.partition(":")[0] + line if key == "common_passwords" else line   # 組の行はユーザーを残す
            common_write(lines)
        return ("saved", f"cm:{i}" if i is not None else None)
    shown = common_shown(parse_cred_line(line, True), key)
    if any(common_shown(c, key) == shown for c in common_items(key)):
        e["msg"] = f"{shown} はもうある（説明を変えるなら、その行で Enter）"
        return ("stay",)
    common_write(lines + [line])
    e["q"] = ""   # 打つ行に留まる
    return ("stay",)
