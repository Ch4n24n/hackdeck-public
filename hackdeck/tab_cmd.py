"""コマンドのタブ: コマンド選び・履歴・変数の画面。"""
import ipaddress
import re

from .paths import WPSCAN_TOKEN
from .text import short_home, term_cols
from .theme import callout
from .history import history_file, history_rows, inputs_record, relative_ago
from .cand_auth import PLAIN_PROTOS
from .cheatbook import VAR_DESCS, substitute, var_deps
from .flow import default_focus, drop_empty, expand, flow_colors, flow_footer, flow_nodes, render_command, var_quoted
from .ui import UP_KEY, VAR_HEADINGS, entry_label, foot_lines, nav_hint, nav_key
from .prompt import pick_entry, prompt_var
from .nav import build_names, entry_key
from . import ui


def picker_screen(nav, e, entries, defs, can_back, can_fwd):
    """コマンド選び（最初の画面）。Esc は検索語を消し、カーソルを一覧の先頭へ戻す（開いたときと同じ初期状態。
    画面は閉じず、fzf の中で動く。2026-10-29、本人の指摘「コマンド一覧画面で Esc を押したら、初期状態に戻して
    ほしい」。その前は「初期画面で再度 Esc を押しても変化なし」の指摘どおり、何もしなかった）。
    Enter でそのコマンドの組み立てを新しく始める。戻り値は var_screen と同じ"""
    n = len(history_rows())
    hint = ["Enter 選ぶ", f"Ctrl+R 履歴（{n}件）" if n else "Ctrl+R 履歴（まだ無い）"] \
        + nav_hint(can_back, can_fwd, esc="初期状態へ")
    keys = ["ctrl-r", "tab", "btab"] + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else [])
    focus = next((i for i, r in enumerate(entries) if entry_key(r) == e.get("f")), None)
    key, query, idx = pick_entry(entries, e.get("q", ""), focus, keys, hint, defs, esc="clear-query+first", place=e)
    e["q"] = query
    if idx is not None:
        e["f"] = entry_key(entries[idx])
    if key == "ctrl-r":
        return ("push", {"s": "history", "q": "", "f": None})
    if key != "enter":
        return nav_key(key, "cmd")
    if idx is None:
        return ("stay",)
    r = entries[idx]
    b = {"key": entry_key(r), "tag": r["tag"], "comment": r["comment"], "tpl": r["command"],
         "values": {}, "confirmed": [], "stale": [], "labels": {}, "view": {}}
    names = build_names(b, defs)
    if not names:
        return ("done", r["command"])   # 変数の無いコマンド
    bid = str(max((int(k) for k in nav["builds"]), default=0) + 1)
    nav["builds"][bid] = b
    return ("push", {"s": "var", "b": bid, "v": names[0]})


def history_foot():
    """履歴の画面の説明欄（ほかのタブと同じ決まり）。履歴は案件ごとのファイル（2026-10-30、本人の指摘）"""
    f = history_file()
    return foot_lines([(f.name, "この案件で組み立てたコマンド。1行に 時刻 と コマンド"), ("置き場所", short_home(f))])


def list_screen(e, can_back, can_fwd):
    """履歴（Ctrl+R）の画面。開いたキーをもう一度押しても戻る（2026-10-28、「Ctrl+G, T をもう一度押したら戻るように」との
    指摘）。Enter でそのコマンドを入れて閉じる。配色は設定のタブへ移した（2026-10-30。前はこの画面で選んでいた）。
    戻り値は var_screen と同じ"""
    rows = [{"tag": "履歴", "comment": f"履歴: {relative_ago(r['ts'])}", "command": r["cmd"]}
            for r in history_rows()] or [{"tag": "履歴", "comment": "まだ履歴はありません", "command": ""}]
    keys = ["esc", "ctrl-r", "tab", "btab"] + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else []) \
        + ([UP_KEY] if ui.NAV_UP else [])
    focus_idx = next((i for i, r in enumerate(rows) if r["command"] == e.get("f")), None)
    key, query, idx = pick_entry(rows, e.get("q", ""), focus_idx, keys,
                                 ["Enter 選ぶ", "Ctrl+R コマンド選びへ"] + nav_hint(can_back, can_fwd), tab="cmd",
                                 # 置き場所は説明欄に（2026-10-30、本人の指摘「どこに保存されているか、説明欄に」）
                                 foot=history_foot(), place=e, what="履歴")
    e["q"] = query
    if idx is not None:
        e["f"] = rows[idx]["command"]
    if key == "ctrl-r":
        # 開いたコマンド選びへ（2026-10-30、本人の指摘「Ctrl+R で戻ろうとすると設定のタブに移る」。前は通った画面の1つ前へ
        # 戻していたので、タブを行き来して履歴を開き直していると、1つ前が別のタブの画面だった）
        return ("home",)
    if key != "enter":
        return nav_key(key, "cmd")
    if idx is None:
        return ("stay",)
    if not rows[idx]["command"]:
        return ("home",)   # 「まだ履歴はありません」の行
    return ("done", rows[idx]["command"])


def var_screen(nav, e, defs, base_env, can_back, can_fwd):
    """変数を1つ聞く画面。Enter で決めたら図の次の変数へ（決めてあっても行き、前の検索語とカーソルのまま出す。
    Enter を押し続ければ前の値のまま、まだ決めていない変数まで進める。2026-10-29、本人の指摘）。
    選んだ値の中にさらに変数があれば（認証の形の「パスワード」= -u <pw_user> -p <pw_pass>）、図に枝が開いて続けて
    それを聞く（本人の指摘「資格情報がパスワードかハッシュかチケットかの違いだけなので、エントリーを分けずに分岐が
    できるように作り直す」）。値は変数名で覚える（パスワードと Kerberos は同じ pw_user・pw_pass を使うので、形だけ
    変えればユーザーとパスワードは聞き直さない）。値を変えたら、その値を使う変数（nxc_opt は $proto を使う）は
    決め直しにし、前の値が新しい一覧に無ければ、まだ決めていない変数として空から聞く。図で決めた変数（とまだ決めて
    いない最初の変数）をクリックすると、その画面へ飛ぶ。
    戻り値（run_builder が列を動かす）: ("push", 列の1つ) / ("back",) / ("forward",) / ("home", カーソルを合わせる
    コマンド) / ("done", 組み立てた文字列) / ("close",) / ("stay",)"""
    b = nav["builds"].get(e["b"])
    names = build_names(b, defs)
    if not names:
        return ("home",)   # 組み立てが列から消えた・コマンド帳を直して変数が無くなった
    values, labels, view = b["values"], b["labels"], b["view"]
    confirmed, stale = set(b["confirmed"]), set(b["stale"])
    if e["v"] not in names:   # コマンド帳を直して、いた変数が図から消えた
        e["v"] = next((n for n in names if n not in confirmed), names[0])
    name = e["v"]
    cmd, _, example = defs.get(name, (None, None, ""))
    if cmd is None:
        return ("home",)   # 定義が無い（check で見つかるはずの不整合）
    nodes = flow_nodes(b["tpl"], defs, values, confirmed)
    done_vals = [(n, values[n]) for n in names if n in confirmed and n != name]
    env = dict(base_env)
    env.update(done_vals)
    env["HACKDECK_TPL"] = b["tpl"]   # 候補のコマンドが、組み立てているコマンドを見られるように（一覧ファイル・nxc_opt）
    # 検索語とカーソルは、この画面を前に離れたときのまま（2026-10-29、本人の指摘「戻ったとき、前に打った検索語と
    # カーソルの位置がそのまま残っていてほしい」。閉じて開き直したときも同じ）
    v = view.get(name, {})
    focus = v.get("f")
    if focus is None and (name in confirmed or name in stale):
        focus = values.get(name)
    colors = flow_colors(b["tpl"], defs, nodes)
    shown_vals = {n: values[n] for n in confirmed if n in values and n != name}   # 空の値は前の空白ごと外して見せる
    cmd_line = render_command(drop_empty(b["tpl"], shown_vals), {n: drop_empty(v, shown_vals) for n, v in values.items()},
                              confirmed, colors, name)
    preview = f"{entry_label(b)}\n{cmd_line}"
    built = expand(b["tpl"], values)
    notes = []
    # チケット（KRB5CCNAME）を使う形か。-k でも、パスワード・ハッシュを渡す netexec はチケットを自分で取るので要らない。
    # evil-winrm は -r で Kerberos（2026-10-30、1番の作り直しと3・4番をまとめたときに分けた）
    uses_ticket = bool(re.search(r"(?:^|\s)(?:--use-kcache|-no-pass)(?:\s|$)|--use-krb5-ccache", built)
                       or (re.search(r"(?:^|\s)-k(?:\s|$)", built)
                           and not re.search(r"(?:^|\s)(?:-p|-H|-hashes|--hashes|-aesKey|--aesKey)\s", built))
                       or (built.startswith("evil-winrm") and " -r " in f" {built} "))
    # 資格情報を選ぶ画面（xfreerdp はチケットの形が無いので外す）
    # KRB5CCNAME のチケットを事前の行で選べる変数（netexec の1番・SMB の共有・evil-winrm・secretsdump・enum4linux-ng）だけ、空のとき知らせる。
    # impacket 実行系・bloodyAD の -k（krb_how）は、パスワード・ハッシュから TGT を取れるので KRB5CCNAME は要らない（uses_ticket に
    # 入らない）。2026-10-31、でっち上げのチケット行を消したのに合わせて、警告もこの3つに絞った
    picks_ccache = name in ("auth_nxc", "auth_nxc_smb", "auth_winrm", "auth_dump", "auth_e4l") \
        and not (name == "auth_nxc" and values.get("proto", "") in PLAIN_PROTOS)
    if not env.get("KRB5CCNAME") and (picks_ccache or "<realm>" in b["tpl"] or uses_ticket):
        # Kerberos を使う（使える）のに、チケットが無い（2026-10-30、棚卸しの4番・5番。流れの図の下に。本人の指摘「縦に並んだ
        # 設定値の下に、コールアウトのような見た目で」）
        notes.append(callout("KRB5CCNAME が空。チケットで入るには、先に環境のタブ（または export）で KRB5CCNAME にチケットを入れてから"))
    if "wpscan-api-token" in b["tpl"] and not WPSCAN_TOKEN.is_file():
        # 秘密はコマンド帳に書かず ~/.config に置く（2026-10-30。本人の決まり「秘密はリポジトリに入れない」）
        notes.append(callout(f"WPScan の API トークンが無い。{short_home(WPSCAN_TOKEN)} に1行で置く（chmod 600）"))
    if b["tpl"].startswith("evil-winrm") and (name == "auth_winrm" or " -r " in f" {built} "):
        # evil-winrm のチケット（Kerberos）は、行き先を名前（FQDN）で。行き先が IP なら知らせる（2026-10-30、行き先を
        # 先に聞く形にしたとき。本人の指摘「host → creds だろ」）
        h = values.get("host", "")
        try:
            ipaddress.ip_address(env.get(h.strip("${}"), "") if h.startswith("$") else h)
            notes.append(callout("チケットで入るときは、行き先を名前（FQDN）にする。いまの行き先は IP"))
        except ValueError:
            pass
    if re.search(r"(?:^|\s)-k(?:\s|$)", built) and (b["tpl"].startswith(("impacket-", "bloodyAD")) or " <exec>" in b["tpl"] or b["tpl"].startswith("impacket-<exec>")):
        # impacket 実行系・bloodyAD で Kerberos（-k）を選んだのに、行き先が IP（SPN が引けず失敗する）。host・dc を見る
        tgt = values.get("host") or values.get("dc") or ""
        try:
            ipaddress.ip_address(env.get(tgt.strip("${}"), "") if tgt.startswith("$") else tgt)
            notes.append(callout("Kerberos（-k）は行き先を名前（FQDN）に。いまの行き先は IP（KRB5CCNAME も要る）"))
        except ValueError:
            pass
    footer, footer_map = flow_footer(nodes, values, confirmed, labels, colors, name, term_cols())
    if notes:
        footer = footer + [""] + notes   # 流れの図の行の番号（クリック）は変わらない
    # 今入力している変数に「例」があれば、検索ボックスのゴースト文字（--ghost）として出す（2026-10-28）
    # 入力欄の薄い字は「何を入れるか（例：…）」（2026-10-30、本人の指摘。前は「名前 の例: …」だけ）
    desc = VAR_DESCS.get(name, "")
    example_label = (f"{desc}（例：{example}）" if desc and example else desc
                     or (f"{name} の例: {example}" if example else ""))
    if var_quoted(b["tpl"], values, name):
        env["HACKDECK_TYPED_RAW"] = "1"   # 引用符の中の変数（c_typed。枝の値の中の変数も）
    cursor_typed = v.get("t", True)
    if focus is None and default_focus(name, defs, env) is not None:
        # 認証のしかた・認証の形は、まだ決めていなければ先頭の形（NTLM 認証）の行から。「そのまま使う」の行（空の値）にいると、
        # そのまま Enter で壊れたコマンドになる（2026-10-30。1番の認証のしかたは「そのまま使う」も値が空なので合わせない）。
        # 自分（member）・ドメインの DN は、決めた資格情報から（2026-10-31）
        focus, cursor_typed = default_focus(name, defs, env), False
    place = {k: v[k] for k in ("o", "oq") if k in v}   # 一覧の見え方（ui.fzf_run が覚える）
    res = prompt_var(substitute(cmd, done_vals), env, preview, query=v.get("q", ""), cursor_value=focus,
                     example_label=example_label, can_back=can_back, can_fwd=can_fwd,
                     footer=footer, footer_map=footer_map, old_must_exist=name in stale,
                     cursor_typed=cursor_typed, title=VAR_HEADINGS.get(name, name), var_name=name, place=place)
    if not res["key"] and not res["jump"]:
        return ("close",)   # fzf が何も返さなかった。この画面の検索語・カーソルは前のまま残す
    view[name] = {"q": res["query"], "f": res["focus"], "t": res["typed"], **place}
    if res["jump"]:
        target = res["jump"]
        first_open = next((n for n in names if n not in confirmed), None)
        if target in names and target != name and (target in confirmed or target == first_open):
            return ("push", {"s": "var", "b": e["b"], "v": target})
        return ("stay",)
    if res["key"] == "esc":
        return ("home", b["key"])
    if res["key"] != "enter":
        return nav_key(res["key"], "cmd")
    value = res["value"]
    changed = name in values and values[name] != value
    values[name] = value
    labels[name] = res["shown"] or value
    confirmed.add(name)   # Enter で確定した（候補から選んだ・打った値をそのまま使った、どちらも）
    stale.discard(name)
    if changed:
        # この変数の値を使う変数（定義に <名前> か $名前 がある）は決め直し。proto を ldap にしたら、
        # smb の一覧から選んだ nxc_opt を選び直す（本人の指摘「proto が変わったら後半も変わる」）
        for other, (ocmd, _w, _e) in defs.items():
            if other != name and other in confirmed and name in var_deps(ocmd):
                confirmed.discard(other)
                stale.add(other)
    b["confirmed"], b["stale"] = sorted(confirmed), sorted(stale)
    # 次は図の次の変数。枝を変えたときは、新しく開いた枝の変数が次になる。最後の変数なら、まだ決めていない最初の変数へ
    names = build_names(b, defs)
    i = names.index(name)
    nxt = names[i + 1] if i + 1 < len(names) else next((n for n in names if n not in confirmed), None)
    if nxt is None:
        # 最後の変数が空（nxc_opt の「オプションなし」など）だと末尾に空白が残るので落とす（2026-10-30）
        vals = {n: values[n] for n in names}
        inputs_record(b, names, defs)   # 打った値を、変数ごとに残す
        return ("done", expand(drop_empty(b["tpl"], vals), {n: drop_empty(v, vals) for n, v in vals.items()}).rstrip())
    return ("push", {"s": "var", "b": e["b"], "v": nxt})
