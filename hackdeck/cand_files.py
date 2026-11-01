"""変数の候補: ファイル・フォルダ・一覧ファイル（.user・.pass・.hash）・チケット。"""
import json
import os
import re
import shlex
import struct
import subprocess
from pathlib import Path

from .paths import COMMON_LISTS, MAGIC_CACHE
from .text import display_width, fit, fit_desc, fit_values, out, path_safe, short_home, term_cols
from .case import case_root, expand_named, list_place, lists_dir, named_dirs
from .creds import common_creds, creds
from .fzfcall import HEADING, mark_match, match_at
from .ui import grouped


# ファイルの種類ごとの名前の型
FILE_KINDS = {
    "any": ["*"],
    "user": ["*user*", "*.txt"],
    "pass": ["*pass*", "*.txt"],
    "hash": ["*.hash", "*hash*", "*.txt"],
    "req": ["*.req", "*.txt"],
    "url": ["*vhost*", "*url*", "*host*", "*.txt"],
    "pfx": ["*.pfx"],
    "sam": ["*sam*", "*SAM*"],
    "security": ["*security*", "*SECURITY*"],
    "system": ["*system*", "*SYSTEM*"],
    "ovpn": ["*.ovpn"],
    "dir": [],   # フォルダだけを出す（files_rows）
}

# 一覧ファイル（2026-10-30、本人の指摘「netexec の -u・-p はファイルも取れる。資格情報を一覧ファイルにして、選択肢に入れる
# 機能があってもいい」。NT ハッシュと、よく使うユーザー・パスワードの一覧も本人の希望）。拡張子で種類を見分け（.user・.pass・
# .hash。本人の案）、決まった置き場所（lists_dir）にあるものを候補の先頭（画面ではいちばん下）に出す。手で置いた一覧も出る。
# 資格情報とよく使うものからは、下の名前で作る（いまいる場所に作るとぐちゃぐちゃになる、との指摘で置き場所を決めた）。
# 資格情報の分は案件のホーム、よく使う分は共通の置き場所に、コマンドで使うときだけ作る（本人の指摘「その時必要になったものだけ」）
LIST_EXTS = ("user", "pass", "hash")
LIST_KIND_LABEL = {"user": "ユーザー", "pass": "パスワード", "hash": "NT ハッシュ"}
LIST_FILES = {"user": ("creds.user", "資格情報のユーザー", "人"),
              "pass": ("creds.pass", "資格情報のパスワード", "つ"),
              "hash": ("creds.hash", "資格情報の NT ハッシュ", "つ"),
              "common-user": ("common.user", "よく使うユーザー", "人"),
              "common-pass": ("common.pass", "よく使うパスワード", "つ"),
              "common-hash": ("common.hash", "よく使う NT ハッシュ", "つ")}


def cred_list_values(kind):
    """作る一覧の中身（資格情報・よく使うものの順、重複なし）。NT ハッシュは NT の部分だけ（LM:NT の LM は落とす）"""
    rows = common_creds() if kind.startswith("common-") else creds()
    ext = kind.rsplit("-", 1)[-1]
    if ext == "user":
        return list(dict.fromkeys(c["user"] for c in rows if c["user"]))
    want = "nt" if ext == "hash" else "pass"
    return list(dict.fromkeys(c["secret"] for c in rows if c["kind"] == want))


def write_used_lists(cmd):
    """組み立てたコマンドが使う「作る一覧」（LIST_FILES）だけを、置き場所に書き直す（中身が同じなら触らない）。
    コマンドを出すときに呼ぶ（履歴から出し直したときも、その時点の資格情報・よく使うもので書き直す）"""
    for kind, (name, _, _) in LIST_FILES.items():
        if not re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", cmd):
            continue
        d, text = list_place(kind), "".join(v + "\n" for v in cred_list_values(kind))
        if d is None:
            continue
        try:
            if (d / name).read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f".{name}.{os.getpid()}"
            with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, d / name)
        except OSError:
            pass   # 書けない場所なら、コマンドの方で見つからないと分かる


def takes_cred_files():
    """組み立てているコマンドが、-u・-p・-H にファイルも取る道具か（netexec だけ。evil-winrm などは取らない）。
    var_screen が候補のコマンドに HACKDECK_TPL（コマンド帳の1行）を渡す"""
    tpl = os.environ.get("HACKDECK_TPL", "").split()
    return bool(tpl) and tpl[0] in ("netexec", "nxc")


def list_arg(p):
    """一覧ファイルをコマンドに入れるときの書き方（2026-10-30、本人の指摘「../ だとコマンドが長くなる。~/ のように定義して
    使えないか」）。案件の作業フォルダは ~hack/、案件をまたぐ置き場所は ~cmn/ を、いまいる場所に関係なく付ける（同日、本人の
    指摘「常に ~ を付ければいい」）。zsh の名前付きディレクトリで、案件のセッションのシェルに shell/hack.zsh が定義する。
    ほかは相対パス"""
    name = shlex.quote(p.name)
    if case_root() and p.parent == lists_dir():
        return f"~hack/{name}"
    if p.parent == COMMON_LISTS:
        return f"~cmn/{name}"
    if p.parent == Path.cwd():
        return name
    rel = os.path.relpath(p, Path.cwd())
    if not rel.startswith(os.pardir + os.sep + os.pardir):
        return shlex.quote(rel)
    home, s = str(Path.home()), str(p)
    return "~/" + shlex.quote(s[len(home) + 1:]) if s.startswith(home + "/") else shlex.quote(s)


def list_peek(p):
    """手で置いた一覧の行数と先頭の行（説明に並べる分。画面の1行に入る数より多めに）。大きいファイルは数えずに大きさだけ"""
    try:
        size = p.stat().st_size
        if size > 5_000_000:
            return f"{size // 1_000_000}MB", []
        lines = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        return f"{len(lines)}行", lines[:200]
    except OSError:
        return "読めない", []


def list_rows(ext):
    """一覧ファイルの候補（ext: user・pass・hash）。作る一覧（資格情報の分・よく使う分。ファイルがまだ無くても出し、
    コマンドを出すときに作る）と、手で置いた *.<ext>（案件のホームと、共通の置き場所）を、名前の A→Z（画面では上から）で出す。
    （[(値, 説明)], その一覧のパス）を返す。説明には中身を、画面の幅に入るだけ並べる（2026-10-30、本人の指摘「横幅に達するまで、できる限り値を」。
    前は先頭の3つで、ユーザーの一覧だけだった）。説明は値のすぐ後ろから始まるとみなして詰め、ほかの候補の値が長いときは
    並べる側（pad_candidate_line・print_aligned）がさらに詰める"""
    home_dir, rows = lists_dir(), []
    made = [k for k in LIST_FILES if k.rsplit("-", 1)[-1] == ext and list_place(k)]
    for k in made:
        vals = cred_list_values(k)
        if vals:
            _, label, unit = LIST_FILES[k]
            rows.append((list_place(k) / LIST_FILES[k][0], f"{label}（{len(vals)}{unit}", vals))
    names = {LIST_FILES[k][0] for k in LIST_FILES}   # 作る一覧と同じ名前の、手で置いたものは出さない（作る一覧の方に出る）
    for d in dict.fromkeys(x for x in (home_dir, COMMON_LISTS) if x):
        try:
            files = [p for p in d.glob(f"*.{ext}") if p.is_file() and p.name not in names]
        except OSError:
            continue
        for p in files:
            count, head = list_peek(p)
            rows.append((p, f"{'一覧' if d == home_dir else '共通の一覧'}（{count}", head))
    cols = term_cols()
    return ([(list_arg(p), fit_values(head, vals, cols - display_width(list_arg(p)) - 6))
             for p, head, vals in sorted(rows, key=lambda r: (r[0].name.lower(), str(r[0])), reverse=True)],
            {p.resolve() for p, _, _ in rows})

def write_cred_list(kind):
    """作る一覧を1つ、いまの場所に書き出す（資格情報の画面の Ctrl+O）。書いた件数を返す"""
    vals = cred_list_values(kind)
    Path(LIST_FILES[kind][0]).write_text("".join(v + "\n" for v in vals), encoding="utf-8")
    return len(vals)


def c_credlists(kinds=None):
    """資格情報の画面の Ctrl+O（fzf の transform から呼ばれ、画面は閉じない）。資格情報にある分の一覧ファイルを、
    コマンドを組まずに、いまの場所へ書き出す（2026-10-30、本人の指摘「ファイル単体も出せたほうが嬉しい」。一覧は
    いつも置き場所にあるが、いまの場所にも写したいときのために、本人の希望で残した）。
    開いている画面の分だけ（資格情報なら creds.*、設定のよく使うユーザー・パスワードなら common.*。本人の指摘「タブ
    ごとに」）。何を書き出したかを、検索ボックスの上（header）に1行出す"""
    kinds = kinds or ("user", "pass", "hash")
    made = [f"{LIST_FILES[k][0]}（{write_cred_list(k)}{LIST_FILES[k][2]}）" for k in kinds if cred_list_values(k)]
    home, here = str(Path.home()), str(Path.cwd())
    where = "~" + here[len(home):] if here.startswith(home + "/") else here
    print(f"change-header:書き出した: {'・'.join(made)} → {where}" if made else "change-header:書き出すものがまだ無い")


def file_magics(paths, max_w=50):
    """file -b の出力一覧（paths と同じ順番、長ければ max_w で切り詰める）。1つも無ければ []。
    1ファイルずつ呼ぶと file の起動コストがかさむので、まとめて1回で呼ぶ
    （2026-10-28、本人の指摘「ファイルの説明はサイズよりマジックの方がいい」で追加。
    実機で、43ファイルをまとめて1回 0.04秒・1ファイルずつ0.25秒と確認し、まとめる方を選んだ）。
    結果は、場所・大きさ・更新時刻ごとにキャッシュ（MAGIC_CACHE）に残し、変わったファイルだけ調べる（打つたびに候補を作り直す
    ので、そのたびに全部を調べ直していた。2026-11-01、本人の希望「反応速度がはやく」）。残すのは直前に出した場所の分だけ"""
    if not paths:
        return []
    keys = []
    for p in paths:
        try:
            st = p.stat()
            keys.append(f"{p}\t{st.st_size}\t{st.st_mtime_ns}")
        except OSError:
            keys.append("")
    try:
        cache = json.loads(MAGIC_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    need = [p for p, k in zip(paths, keys) if k not in cache]
    if need:
        try:
            r = subprocess.run(["file", "-b"] + [str(p) for p in need], capture_output=True, text=True, timeout=2)
            lines = r.stdout.splitlines()
        except Exception:
            lines = []
        if len(lines) != len(need):
            return ["" for _ in paths]  # file 側の行数が合わない異常ケースは諦める
        got = dict(zip(need, lines))
        cache = {k: got[p] if p in got else cache[k] for p, k in zip(paths, keys) if k}
        try:
            MAGIC_CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = MAGIC_CACHE.with_name(f"{MAGIC_CACHE.name}.{os.getpid()}")
            tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, MAGIC_CACHE)
        except OSError:
            pass
    lines = [cache.get(k, "") for k in keys]
    return [fit(m, max_w).rstrip() if display_width(m) > max_w else m for m in lines]


def c_files(args):
    """ファイルの候補。型に合うファイルを新しい順に出し、残りのファイル、フォルダ（名前/）の順に後ろへ足す
    （ハッシュのファイルは mssqladm_tgs・watch.sqli.pass のように名前がそろわないので、型で隠さない）。
    --query は打つたびに渡される。打った文字に / があれば、その場所の中身を打った形のまま前に付けて出す。
    説明は、ファイルは file -b の判定結果（マジック）、フォルダは無し（2026-10-28、本人の指摘「ディレクトリ
    は末尾の / で分かる。ファイルもサイズよりマジックを教えてほしい」で、サイズ／固定文言から変更）"""
    d, query, pats, kinds, typed = Path.cwd(), None, [], [], False
    while args:
        a, args = args[0], args[1:]
        if a == "--dir" and args:
            d, args = Path(os.path.expanduser(args[0])), args[1:]
        elif a == "--query" and args:
            query, args = args[0], args[1:]
        elif a == "--typed":
            typed = True   # 先頭に「打った値をそのまま使う」行（列をそろえるため、ほかの行と一緒に出す）
        else:
            kinds.append(a)
            pats += FILE_KINDS.get(a, [a])
    term = (query or "")[(query or "").rfind("/") + 1:]   # 絞るのは最後の / の後ろ（前は、どこの中を見るか）
    print_aligned(files_rows(d, query, pats, kinds, term), (path_safe(query or ""), "そのまま使う") if typed else None, term)


def print_aligned(rows, first=None, term=""):
    """候補を「値\t値の幅をそろえた表示  説明」で出す（ファイルの候補。説明の列をそろえる。2026-10-30、本人の指摘「説明の列が
    揃っていない」。前は値の後ろをタブで区切っていたので、説明が8桁ごとの位置から始まり、値の長さで開始位置が変わった）"""
    if first and rows:
        rows = [(HEADING, " ")] + rows   # 「そのまま使う」の上に空行
    rows = ([first] if first else []) + rows
    cols = term_cols()
    w = min(max((display_width(v) for v, _ in rows if v != HEADING), default=0), cols * 45 // 100)
    for i, (v, desc) in enumerate(rows):
        if v == HEADING:
            print(f"{v}\t{desc}")
        else:
            shown = f"{fit(v, w)}  {fit_desc(desc, cols - w - 6)}" if desc else fit(v, w)
            print(f"{v}\t{mark_match(shown, term) if term and not (first and i == 0) else shown}")


def files_rows(d, query, pats, kinds, term=""):
    """ファイルの候補の行 [(値, 説明)]（出す順。画面では下から上）。いまの場所のファイルと一覧ファイルは、見出しの行で分ける
    （2026-10-30、本人の指摘「選択肢に見出しをつけて分けて。いまのディレクトリの値と、決めたユーザーリストの一覧を」）"""
    rows = []
    prefix = ""
    if query and "/" in query:
        prefix = query[:query.rindex("/") + 1]
        # 絶対パス・~ ならそのまま、相対ならいまの場所（--dir）から。~hack/・~cmn/ は zsh の名前付きディレクトリ（2026-10-30、
        # 本人の指摘「~op・~cmn と打っても候補が出てこない」。前は ~ と ~user だけ見ていた）
        d = d / expand_named(prefix)
        if not d.is_dir():
            return rows  # 無い場所: 候補なし（Ctrl+T か、何も無ければ Enter で打った文字がそのまま入る）
    show_hidden = bool(query) and query[len(prefix):].startswith(".")
    try:
        entries = [p for p in d.iterdir() if show_hidden or not p.name.startswith(".")]
    except OSError:
        return rows
    # 一覧ファイル（list_rows）を先頭（画面ではいちばん下）に。同じファイルがいまの場所にあれば、そちらにも出す（2026-10-30、
    # 本人の指摘「いまの場所のファイルとユーザーの一覧に同じファイルがあっても、そのままでいい」。前は一覧の方だけに出していた）
    groups = []
    for k in ([] if prefix or d != Path.cwd() else kinds):
        if k in LIST_EXTS:
            groups.append((f"{LIST_KIND_LABEL[k]}の一覧（資格情報・よく使うもの・置いた一覧）", list_rows(k)[0]))
    dirs = [(prefix + p.name + "/", "") for p in sorted(p for p in entries if p.is_dir())]
    if "dir" in kinds:
        # フォルダを選ぶ変数（secretsdump の実行場所。2026-10-30）。ファイルは出さず、先頭（画面ではいちばん下）にその場所そのもの
        groups.append((f"{prefix} の中" if prefix else "いまの場所", [(prefix or "./", short_home(d.resolve()))] + dirs))
    else:
        files = {p: p.stat().st_mtime for p in entries if p.is_file()}
        hit = {p for pat in pats or ["*"] for p in d.glob(pat) if p in files}
        newest = sorted(files, key=files.get, reverse=True)
        ordered = [p for p in newest if p in hit] + [p for p in newest if p not in hit]
        groups.append((f"{prefix} の中" if prefix else "いまの場所のファイル",
                       [(prefix + p.name, magic) for p, magic in zip(ordered, file_magics(ordered))] + dirs))
    if not prefix and (query or "").startswith("~"):
        # ~hack/・~cmn/ は、~ を打ったときだけ（打ちかけの ~hack・~cmn から Tab で中へ。いつもは出さない。2026-10-30、本人の
        # 指摘「選択肢に ~cmn・~op はいらない」）
        groups.append(("置き場所", [(f"~{name}/", "案件の作業フォルダ" if name == "hack"
                                     else "案件をまたぐ置き場所（よく使うものの一覧）") for name in named_dirs()]))
    if term:   # 打った文字で絞る（当たった行のあるまとまりだけ見出しつきで）
        groups = [(t, [(v, dsc) for v, dsc in g if match_at(f"{v}  {dsc}", term) >= 0]) for t, g in groups]
    return rows + grouped(groups)


def c_ccache():
    found = {}
    root = case_root()
    for d in [Path("/var/tmp"), Path.cwd()] + ([root] if root else []):
        for p in d.glob("*.ccache"):
            found[p] = p.stat().st_mtime
    for p in sorted(found, key=found.get, reverse=True):
        out(str(p), p.stem)


def ccache_principal(path):
    """ccache（v3・v4）の持ち主 (レルム, 名前)。読めなければ None。/var/tmp の19個で impacket の CCache と同じ値になるのを
    確かめた（2026-10-30。PNT-SVRBPA$ のようなマシンアカウントも）"""
    try:
        b = Path(path[5:] if path.startswith("FILE:") else path).read_bytes()
        ver, off = struct.unpack_from(">H", b)[0], 2
        if ver == 0x0504:
            off += 2 + struct.unpack_from(">H", b, off)[0]   # v4 は見出しを飛ばす
        elif ver != 0x0503:
            return None
        n, off = struct.unpack_from(">I", b, off + 4)[0], off + 8   # 名前の種類（4バイト）の次が、名前の部分の数
        parts = []
        for _ in range(n + 1):   # レルム、名前の部分
            size = struct.unpack_from(">I", b, off)[0]
            parts.append(b[off + 4:off + 4 + size].decode("utf-8", "replace"))
            off += 4 + size
        return (parts[0], "/".join(parts[1:])) if n else None
    except (OSError, struct.error):
        return None
