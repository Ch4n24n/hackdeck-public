"""変数の枝分かれと、画面の流れの図（聞く順の木）・組み立て中のコマンドの見せ方。"""
import re
import shlex

from .text import ANSI_RE, DOLLAR_RE, VAR_RE, clip, display_width
from .theme import B_ON, C_LINE, C_RESET, DIM, U_ON
from .cand_auth import AUTHCREDS_SHAPE, AUTH_FORMS, auth_now, dn_of
from .candidates import opts_lines
from .cheatbook import compute_var_order, var_deps, var_names_in
from . import theme


# --- 分岐と流れの図（2026-10-29 追加） -----------------------------------------
# 選んだ値の中にさらに <var> があれば、続けてそれを聞く（認証の形の「パスワード」= -u <pw_user> -p <pw_pass>）。
# 聞く順は値が決まるたびに作り直し、画面の下に木の形で出す（本人の指摘「フローチャートを出して、
# クリックしたらそこの設定に飛べるといい。proto を変えたら後半も変わるように」）

def nested_vars(value, defs):
    """値の中の <var>（定義のあるものだけ）。定義の無い <…> は打った文字の一部とみなして聞かない"""
    return [n for n in var_names_in(value) if n in defs]


def flow_nodes(template, defs, values, confirmed):
    """いまの値で枝を開いた、聞く順の一覧 [(名前, 深さ, 親)]。依存（定義の中で使う変数）を先に並べるのは
    compute_var_order と同じ。Enter で決めた値の中に変数があれば、その直後に1段深く並べる"""
    nodes, done, visiting = [], set(), set()

    def visit(name, depth, parent):
        if name in done:
            return
        if name in visiting:
            raise RuntimeError(f"変数の依存が循環している: {name}")
        visiting.add(name)
        for d in var_deps(defs.get(name, ("", "", ""))[0]):
            if d != name:
                visit(d, depth, parent)
        visiting.discard(name)
        done.add(name)
        nodes.append((name, depth, parent))
        if name in confirmed:
            for child in nested_vars(values.get(name, ""), defs):
                visit(child, depth + 1, name)

    for name in var_names_in(template):
        visit(name, 0, None)
    return nodes


def flow_colors(template, defs, nodes):
    """変数ごとの色。コマンドに直接ある変数（と依存）は compute_var_order の順で今までどおり、
    枝の中の変数はその後ろの色を出てきた順に使う（枝を開いても、外側の変数の色は変わらない）"""
    colors = {}
    for name in compute_var_order(template, defs) + [n for n, _, _ in nodes]:
        if name not in colors:
            colors[name] = theme.VAR_COLORS[len(colors) % len(theme.VAR_COLORS)]
    return colors


def expand(text, values, depth=0):
    """<var> を値で置き換える。値の中の <var>（枝の中の変数）も続けて置き換える"""
    if depth > 8:
        return text
    return VAR_RE.sub(lambda m: expand(values[m.group(1)], values, depth + 1)
                      if m.group(1) in values else m.group(0), text)


def quoted_in_tpl(tpl, name):
    """コマンド帳の行で、<name> が '…' か "…" の中にあるか（あれば、打った文字を囲まずにそのまま入れる。c_typed）"""
    i = tpl.find(f"<{name}>")
    quote = None
    for ch in tpl[:max(i, 0)]:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
    return i >= 0 and quote is not None


def var_quoted(tpl, values, name):
    """<name> が '…' か "…" の中にあるか（quoted_in_tpl）。コマンド帳の行に無い変数（枝の値の中の変数。bloodyAD の組の
    '<target_user>'・'<group>'）は、それを中に持つ決めた枝の値で見る（2026-10-31。行だけを見ていると、枝の値の中で引用符に
    入った変数に打った値が二重に囲まれ、Backup Operators のような空白のある名前が2つの引数に割れた）"""
    if f"<{name}>" in tpl:
        return quoted_in_tpl(tpl, name)
    return any(quoted_in_tpl(v, name) for v in values.values() if isinstance(v, str) and f"<{name}>" in v)


def drop_empty(text, values):
    """値が空の変数は、前の空白ごと外す（認証のしかたの NTLM 認証は何も足さない。コマンドに空白が2つ並ばないように。
    2026-10-30）"""
    return re.sub(r" ?<([A-Za-z0-9_]+)>", lambda m: "" if values.get(m.group(1)) == "" else m.group(0), text)


def render_command(text, values, confirmed, colors, current, base="", depth=0):
    """プレビューに出すコマンドの行。Enter で決めた値はその変数の色で埋め（値の中の変数はその変数の色、
    残りは外側の変数の色に戻す）、まだの変数といま聞いている変数は <名前> のまま。それまでは常に <名前>
    のままで、値は下の一覧にだけ出していた（2026-10-29、組み立て中のコマンドの形が見えるように変更）"""
    def lit(s):
        return f"{base}{s}{C_RESET}" if base and s else s
    if depth > 8:
        return lit(text)
    parts, pos = [], 0
    for m in VAR_RE.finditer(text):
        parts.append(lit(text[pos:m.start()]))
        name, col = m.group(1), colors.get(m.group(1), "")
        if name in confirmed and name != current and name in values:
            parts.append(render_command(values[name], values, confirmed, colors, current, col, depth + 1))
        else:
            parts.append(f"{col}{m.group(0)}{C_RESET}" if col else lit(m.group(0)))
        pos = m.end()
    parts.append(lit(text[pos:]))
    return "".join(parts)


def flow_footer(nodes, values, confirmed, labels, colors, current, cols):
    """変数の画面の下（fzf の --footer）に出す流れの図。戻り値: (行の一覧, 各行の (変数名, クリックで飛べるか))。
    飛べるのは一度 Enter で決めた変数だけ（Alt+→ と同じ決まり）で、名前に下線を引く。いま聞いている変数は
    太字と「◀ いま」、まだ決めていない変数は行ごと薄く出す。値は図に出す名前（labels。認証の形なら
    「パスワード」）があればそちら"""
    kids = {}
    for name, _depth, parent in nodes:
        kids.setdefault(parent, []).append(name)
    # まだ決めていない変数のうち図でいちばん前のもの。下線なし・薄くしない字で出し、クリックで飛べる（それより前は
    # 全部決まっているので、候補の一覧が崩れない）。それより後のまだの変数は薄い字で、飛べない（2026-10-29、本人の
    # 指摘「下線は決定済み、下線なしは直近の未決定、グレーアウトは飛べない直近ではない未決定」）
    first_open = next((n for n, _, _ in nodes if n not in confirmed), None)
    lines, mapping = [], []

    def walk(parent, lead):
        sibs = kids.get(parent, [])
        w = max((display_width(s) for s in sibs), default=0)
        for k, name in enumerate(sibs):
            last = k == len(sibs) - 1
            if parent is None:
                head, sub = "", "  "  # fzf が footer の行頭に2桁の余白を足すので、自分では足さない
            else:
                head = f"{lead}{C_LINE}{'└' if last else '├'}{C_RESET} "
                sub = lead + ("  " if last else f"{C_LINE}│{C_RESET} ")
            col = colors.get(name, "")
            conn = "─" * (w - display_width(name) + 1)
            is_cur, done = name == current, name in confirmed
            value = (labels.get(name) or values.get(name, "")) if done else ""
            room = cols - display_width(ANSI_RE.sub("", head)) - w - 6 - (9 if is_cur else 0)
            value = clip(value, max(room, 8))
            if is_cur:
                line = (f"{head}{B_ON}{col}{name}{C_RESET} {C_LINE}{conn}{C_RESET} {value}"
                        f"{'  ' if value else ''}{theme.C_TAG}{B_ON}◀ いま{C_RESET}")
            elif done:
                line = f"{head}{U_ON}{col}{name}{C_RESET} {C_LINE}{conn}{C_RESET} {value}"
            elif name == first_open:
                line = f"{head}{col}{name}{C_RESET} {C_LINE}{conn}{C_RESET}"
            else:
                line = f"{DIM}{ANSI_RE.sub('', head)}{col}{name} {C_LINE}{conn}{C_RESET}"
            lines.append(line)
            mapping.append((name, (done or name == first_open) and not is_cur))
            walk(name, sub)

    walk(None, "")
    return lines, mapping


_STATIC_CHOICES = {}


def static_lines(name, defs):
    """定義が「hackdeck opts <名前>」（変数を含まない）なら、その一覧の行。それ以外は空"""
    try:
        argv = shlex.split(defs.get(name, ("", "", ""))[0])
    except ValueError:
        return []
    if argv[:2] == ["hackdeck", "opts"] and len(argv) > 2 and "$" not in argv[2]:
        return opts_lines(argv[2])
    return []


def static_choices(name, defs):
    """コマンド選びの画面の図で、この変数を枝分かれとして描く材料。候補を手元で決めている定義
    （hackdeck authforms・hackdeck opts）だけを見る（ホストやユーザーのようにその場で作る候補は見ない）。
    戻り値: None（枝なし）/ (全部の形を出すか, 依存の変数名, [(表示名, 中の変数), ...])。
    認証の形は全部の形を出す。opts は中に変数を持つ行（-M <nxc_mod>）だけを出し、残りは
    「proto ごとのオプション」の1行にまとめる"""
    if name in _STATIC_CHOICES:
        return _STATIC_CHOICES[name]
    try:
        argv = shlex.split(defs.get(name, ("", "", ""))[0])
    except ValueError:
        argv = []
    res = None
    sub = argv[2] if len(argv) > 2 else ""
    if argv[:2] == ["hackdeck", "authforms"] and AUTH_FORMS.get(sub):
        res = (True, [], [(shown, nested_vars(value, defs)) for value, shown in AUTH_FORMS[sub]])
    elif argv[:2] == ["hackdeck", "authcreds"] and AUTHCREDS_SHAPE.get(sub):
        # チケットの形が無い道具（rdp）は AUTHCREDS_SHAPE にキーが無く、枝を出さない（res は None のまま）
        res = (True, [], [(shown, [k for k in kids if k in defs]) for shown, kids in AUTHCREDS_SHAPE[sub]])
    elif argv[:2] == ["hackdeck", "opts"] and len(argv) > 2:
        deps = DOLLAR_RE.findall(argv[2])
        names = [argv[2]]
        for d in deps:
            vals = [l.split("\t")[0] for l in static_lines(d, defs)]
            names = [n.replace(f"${d}", v) for n in names for v in vals]
        items, every = {}, True
        for n in names:
            lines = opts_lines(n)
            # 枝の行がある3列の一覧（fw-rule）は、枝でない3列の行（定番セット）も表示名で図に出す（c_opts と同じ。2026-10-31）
            named = any(len(l.split("\t")) >= 3 and nested_vars(l.split("\t")[0], defs) for l in lines)
            for line in lines:
                p = line.split("\t")
                kids = nested_vars(p[0], defs)
                if kids or (named and len(p) >= 3):
                    # 3列（値・表示名・説明）なら表示名で（win-persist。2026-10-31）。2列は値から変数を抜いた形（空白は1つに。
                    # --spider <share> --pattern <pattern> → --spider --pattern）
                    items.setdefault(p[1] if len(p) >= 3 else " ".join(VAR_RE.sub("", p[0]).split()) or p[0], kids)
                else:
                    every = False
        if items:
            res = (every, deps, list(items.items()))   # 全部の行が枝なら「そのほかの候補」の行は出さない
    _STATIC_CHOICES[name] = res
    return res


def default_focus(name, defs, values=None):
    """まだ決めていない変数の、最初のカーソルの値。認証のしかた（authhow）は NTLM 認証の空の値、認証の形（authforms）は先頭の
    形、フォルダ（files dir）はいまの場所、自分（users self）・ドメインの DN（domaindn）は決めた資格情報（values）から。ほかは
    None（いつもどおり「そのまま使う」の行から）"""
    try:
        argv = shlex.split(defs.get(name, ("", "", ""))[0])
    except ValueError:
        return None
    values = values or {}   # 候補のコマンドに渡す環境（決めた値と、案件の環境変数）
    if argv[:2] == ["hackdeck", "authhow"]:
        if (argv[2:3] or [""])[0] == "mssql":
            # Windows 認証/SQL のログインの初期カーソルは、選んだ資格情報の形から（ドメイン前置か NT ハッシュ＝Windows 認証、
            # sa のような前置なし＝SQL のログイン）。選び直せる（2026-10-31）
            am = values.get("auth_mssql", "")
            return "-windows-auth" if ("-hashes" in am or "/" in am.split("@")[0].split(":")[0]) else ""
        return ""   # nxc・krb は NTLM（何も足さない）から
    if argv[:3] == ["hackdeck", "users", "self"]:
        return auth_now(values)[1] or None
    if argv[:2] == ["hackdeck", "domaindn"]:
        dom = auth_now(values)[0]
        dom = dom if "." in dom else values.get("DOMAIN", "")
        return dn_of(dom) if dom else None
    if argv[:3] == ["hackdeck", "files", "dir"]:
        return "./"   # 「そのまま使う」の空の行で Enter すると、cd だけになる
    if argv[:2] == ["hackdeck", "authforms"] and len(argv) > 2 and AUTH_FORMS.get(argv[2]):
        return AUTH_FORMS[argv[2]][0][0]
    return None


def flow_rows_max(template, defs):
    """変数の画面の流れの図が、いちばん長くなるときの行数（変数ごとに、中の変数がいちばん多い枝を開いたとき。中の変数が使う
    変数（realm の domain など）も数える）"""
    try:
        top = compute_var_order(template, defs)
    except RuntimeError:
        return 0
    n = 0
    for name in top:
        ch = static_choices(name, defs)
        widest = 0
        for _shown, kids in (ch[2] if ch else []):
            names = {k for k in kids if k not in top}   # もう聞いた変数（win-persist の <new_user>）は枝に開かない
            for kid in kids:
                names.update(d for d in var_deps(defs.get(kid, ("", "", ""))[0]) if d not in top)
            widest = max(widest, len(names))
        n += 1 + widest
    return n


_OVERVIEW = {"defs": None, "theme": None, "rows": {}}   # 変数の定義と配色ごとに覚えた流れの図


def flow_overview(template, defs):
    """コマンド選びの画面の下に出す、選んでいるコマンドの流れ（聞く順と枝分かれ）。見るだけ（クリックで
    飛ぶのは変数の画面の図）。戻り値: (行の一覧, 変数ごとの色)。枝の中の変数の色は、形ごとに同じ位置なら
    同じ色（pw_user と nt_user は同じ色）。窓を開くとき、説明欄の高さ（run_builder）とコマンド選びの画面で同じものを2回
    計算していたので、変数の定義（同じもの）と配色ごとに覚える（2026-11-01）"""
    if _OVERVIEW["defs"] is not defs or _OVERVIEW["theme"] != theme.CURRENT_THEME:
        _OVERVIEW.update(defs=defs, theme=theme.CURRENT_THEME, rows={})
    if template not in _OVERVIEW["rows"]:
        _OVERVIEW["rows"][template] = _flow_overview(template, defs)
    lines, colors = _OVERVIEW["rows"][template]
    return list(lines), dict(colors)


def _flow_overview(template, defs):
    try:
        top = compute_var_order(template, defs)
    except RuntimeError:
        return [], {}
    colors = {n: theme.VAR_COLORS[i % len(theme.VAR_COLORS)] for i, n in enumerate(top)}
    nxt = len(top)
    w = max((display_width(n) for n in top), default=0)
    lines = []
    for name in top:
        col = colors[name]
        ch = static_choices(name, defs)
        if not ch:
            lines.append(f"{col}{name}{C_RESET}")  # 行頭の余白は fzf が足す（2桁）
            continue
        all_forms, deps, items = ch
        items = [(s, [k for k in kids if k not in top]) for s, kids in items]   # もう聞いた変数は枝に出さない
        rows = list(items) if all_forms else \
            [(f"{'・'.join(deps)} ごとのオプション" if deps else "そのほかの候補", [])] + list(items)
        for _, k in rows:
            for pos, kid in enumerate(k):
                colors.setdefault(kid, theme.VAR_COLORS[(nxt + pos) % len(theme.VAR_COLORS)])
        nxt += max((len(k) for _, k in rows), default=0)
        alt_w = max((display_width(s) for s, k in rows if k), default=0)
        for i, (shown, k) in enumerate(rows):
            if i == 0:
                head = (f"{col}{name}{C_RESET} {C_LINE}{'─' * (w - display_width(name) + 1)}"
                        f"{'┬' if len(rows) > 1 else '─'}{C_RESET} ")
            else:
                head = " " * (w + 2) + f"{C_LINE}{'└' if i == len(rows) - 1 else '├'}{C_RESET} "
            body = shown
            if k:
                body = (f"{shown} {C_LINE}{'─' * (alt_w - display_width(shown) + 2)}{C_RESET} "
                        + f" {C_LINE}─{C_RESET} ".join(f"{colors[c]}{c}{C_RESET}" for c in k))
            lines.append(head + body)
    return lines, colors
