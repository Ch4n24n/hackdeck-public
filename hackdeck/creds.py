"""資格情報（案件のデータの creds）と、よく使うユーザー・パスワード（案件をまたぐ。paths.COMMON_CREDS）の
読み書き・見せ方。"""
import os
import re

from .paths import COMMON_CREDS
from .text import LMNT, NT, display_width, fit
from .case import keep_out_of_git, state_file
from .ui import twice


COMMON_SEED = ["admin:", "root:", "guest:", "hacker:", ":admin", ":password", ":Welcome1", ":Password123!"]


def creds_file():
    """資格情報のファイル（案件のデータの creds。案件の外は None）。1行に user:secret:説明。自動では足さない
    （本人の指摘「自動で保存するとゴミみたいな情報が集まる」。足すのは資格情報のタブと、netexec の画面で選んだものだけ）"""
    return state_file("creds")


def parse_cred_line(line, common=False):
    """資格情報の1行（user:secret:説明。説明は省略可。secret に : があれば最後の : の後ろが説明。LM:NT の形はそのまま
    secret）を分ける。読まない行（# で始まる・形が違う）は None。common: よく使う方の書き方（片方が空でもよい。
    パスワードが空なら kind は user）"""
    user, sep, rest = line.partition(":")
    user = user.strip()
    if not sep or user.startswith("#") or not (user or common):
        return None
    secret, desc = (rest.rsplit(":", 1) if ":" in rest and not LMNT.fullmatch(rest.strip()) else (rest, ""))
    if not secret and not (common and user):
        return None
    m = NT.match(secret.strip())
    kind, secret = ("nt", m.group(1)) if m else ("pass" if secret else "user", secret)
    desc = desc.strip()
    return {"user": user, "secret": secret, "kind": kind, "label": desc, "desc": desc, "src": desc or "説明なし"}


def own_creds(f=None, common=False):
    """資格情報のファイル（既定は creds_file()）の組。line は0始まりの行番号（資格情報の画面で消すときに使う）"""
    f = f or creds_file()
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f else []
    except OSError:
        return []
    rows = []
    for n, line in enumerate(lines):
        c = parse_cred_line(line, common)
        if c:
            rows.append({**c, "line": n})
    return rows


def same_cred(text, f=None, by_scope=False):
    """足そうとしている行と同じものがあれば (行の組, 中身まで同じか)。ユーザーと説明が同じなら同じもの
    （上書きするか確かめる。2026-10-30、本人の指摘「同じものは上書き。上書きの前に確認」）。by_scope: 説明ではなく範囲
    （説明の頭）で見る（netexec の画面。説明の（）に見つけた日時などが入り、毎回違うため。ユーザーの大文字小文字も見ない）"""
    new = parse_cred_line(text)
    if not new:
        return None, False
    for c in own_creds(f):
        if ((c["user"].lower() == new["user"].lower() and cred_host(c).lower() == cred_host(new).lower()) if by_scope
                else (c["user"] == new["user"] and c["desc"] == new["desc"])):
            return c, c["secret"] == new["secret"]
    return None, False


def creds():
    """認証に使える組（いまの案件の資格情報だけ）"""
    return own_creds()


def common_creds():
    """よく使うユーザー・パスワード（COMMON_CREDS）の組。無ければ COMMON_SEED で作る（600）"""
    if not COMMON_CREDS.exists():
        COMMON_CREDS.parent.mkdir(parents=True, exist_ok=True)
        try:
            with os.fdopen(os.open(COMMON_CREDS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as fh:
                fh.write("".join(l + "\n" for l in COMMON_SEED))
        except FileExistsError:
            pass
    return own_creds(COMMON_CREDS, common=True)


def common_items(view):
    """設定の「よく使うユーザー」（view が common_users）か「よく使うパスワード」（common_passwords。NT ハッシュも）に出す
    行。ユーザーとパスワードの組の行は、パスワードの方に出す"""
    return [c for c in common_creds() if (c["kind"] == "user") == (view == "common_users")]


def common_shown(c, view):
    """一覧に出す値（NT ハッシュは頭に NT）"""
    return c["user"] if view == "common_users" else f"NT {c['secret']}" if c["kind"] == "nt" else c["secret"]


def common_parse(text, view):
    """設定の「よく使う…」で打った 値:説明 を、ファイルの1行に（形が違えば None）。パスワードは資格情報と同じく、
    最後の : の後ろが説明（パスワードに : があるときは最後に : を足す。P:ss: ）"""
    text = text.strip()
    if view == "common_users":
        v, _, d = text.partition(":")
        v, d = v.strip(), d.strip()
        return (f"{v}::{d}" if d else f"{v}:") if v and not v.startswith("#") else None
    v, d = text.rsplit(":", 1) if ":" in text and not LMNT.fullmatch(text) else (text, "")
    v, d = v.strip(), d.strip()
    return ":" + v + (f":{d}" if d or ":" in v else "") if v else None


def common_lines():
    common_creds()   # 無ければ作る（600）
    return COMMON_CREDS.read_text(encoding="utf-8").splitlines()


def common_write(lines):
    COMMON_CREDS.write_text("".join(l + "\n" for l in lines), encoding="utf-8")   # 前からあるファイルなので 600 のまま


def add_cred(text, f=None):
    """「user:secret」を f（既定は creds_file()）の末尾に1行足す（作るときから 600）。形が違えば False"""
    user, sep, secret = text.partition(":")
    f = f or creds_file()
    if not CRED_ADD_RE.match(text) or not f:
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        head = f.read_bytes()
    except OSError:
        head = b""
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(("\n" if head and not head.endswith(b"\n") else "") + f"{user.strip()}:{secret}\n")
    os.chmod(f, 0o600)
    keep_out_of_git(f)
    return True


def delete_cred(line_no, f=None):
    f = f or creds_file()
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if 0 <= line_no < len(lines):
        del lines[line_no]
        f.write_text("".join(lines), encoding="utf-8")


def cred_save(e, pending, text, f, by_scope=False):
    """「user:secret:説明」を f に足す（資格情報のタブと、netexec の画面の Enter）。ユーザーと説明が同じ行がもうあれば、
    確かめてから上書き（2回。2026-10-30、本人の指摘「同じものは上書き。上書きの前に確認」）。中身まで同じなら何もしない。
    by_scope: 同じものを、ユーザーと範囲で見る（same_cred）。
    足したら "add"、上書きしたら "over"、どちらでもなければ ""（確かめの1回目・同じもの・形が違う）"""
    same, dup = same_cred(text, f, by_scope)
    if dup:
        e["msg"] = "同じものがもうある"
    elif same and twice(e, pending, "over", text,
                        f"もう一度 Enter で上書き: {same['user']} の {same['secret']} → {parse_cred_line(text)['secret']}"):
        lines = f.read_text(encoding="utf-8").splitlines()
        lines[same["line"]] = text
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "over"
    elif not same and add_cred(text, f):
        return "add"
    return ""


# ユーザー・パスワードの候補の並び（2026-10-30、本人の指摘）。画面の上から、よく使うもの（A→Z）、資格情報（ホストごとに
# まとめ、その中で名前の A→Z）、一覧ファイル（名前の A→Z）。下から上へ並ぶ画面なので、逆の順に出す。資格情報は1つを1行にし
# （同じ Administrator でも DC01 と SVC01 は別の行。本人の指摘「まとめないで」）、説明はホスト・紐づく値（ユーザーの画面なら
# パスワード、パスワードの画面ならユーザー）・残りの説明の列にそろえる（本人の指摘「ユーザー名には紐づくパスワード、パスワード
# には紐づくユーザー名を」「ホストごとにまとまりがほしい。列を足すか」）。違う置き場所に同じ値があっても、まとめない

def cred_host(c):
    """資格情報のホスト（説明の頭の英数字の語。DC01（確認用）なら DC01。無ければ空）。本人の決まり「同じ Administrator を
    DC01・SVC01 のように説明で見分ける」（2026-10-29）を、まとまりと列に使う"""
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", c["desc"].strip())
    return m.group(0) if m else ""


def cred_sorted(rows):
    """資格情報を、使える範囲ごと（ドメイン全体のもの（範囲に . がある）を先に、次に端末ごと、範囲の無いものは最後）、その中で
    名前の A→Z に（2026-10-30、本人の指定「ドメインのまとまりを端末のまとまりより上に」）"""
    return sorted(rows, key=lambda c: (not cred_host(c), "." not in cred_host(c), cred_host(c).lower(), c["user"].lower(),
                                       c["secret"]))


def cred_domain(c, domain):
    """その資格情報で名乗るドメイン。範囲（説明の頭）がドメイン名ならそれ、端末名ならその端末（ローカルのアカウント。impacket の
    SVC01/administrator・smbclient の SVC01/administrator%…）、範囲が無ければ選んだドメイン（2026-10-30、本人の指定「範囲が
    端末名のときは、ローカルの書き方を自動で」。前はどの資格情報にも選んだドメインを付けていて、ローカルの管理者だと通らなかった）"""
    return cred_host(c) or domain


def secret_shown(c):
    return f"NT {c['secret']}" if c["kind"] == "nt" else c["secret"]


def cred_columns(rows, other):
    """資格情報の行の説明（ホスト・紐づく値・残りの説明の列）。other: 紐づく値を出す関数"""
    hw = max([display_width(cred_host(c)) for c in rows] + [1])
    ow = min(max([display_width(other(c)) for c in rows] + [1]), 36)
    return [f"{fit(cred_host(c) or '—', hw)}  {fit(other(c), ow)}  {c['desc'].strip()[len(cred_host(c)):].strip()}".rstrip()
            for c in rows]


def common_users():
    """よく使うユーザー {名前: [説明]}（同じ名前は1つに）"""
    users = {}
    for c in common_creds():
        if c["user"]:
            users.setdefault(c["user"], []).append(c["desc"])
    return users


def common_user_rows(q_user=lambda u: u, fixed=()):
    """よく使うユーザーの行（A→Z。出す順は逆）。fixed: 足す決まった名前（よく使うユーザーに無ければ）"""
    users = common_users()
    for u in fixed:
        users.setdefault(u, ["決まった名前"])
    rows = []
    for u, descs in sorted(users.items(), key=lambda x: x[0].lower(), reverse=True):
        d = "・".join(dict.fromkeys(x for x in descs if x))
        rows.append((q_user(u), f"よく使うユーザー（{d}）" if d else "よく使うユーザー"))
    return rows


def cred_rows(rows, value, other):
    """資格情報の行（ホストごと・名前の A→Z。出す順は逆）。value: 入る値、other: 説明に出す紐づく値"""
    rows = cred_sorted(rows)
    return list(reversed([(value(c), d) for c, d in zip(rows, cred_columns(rows, other))]))


def cred_is_local(c):
    """範囲（説明の頭）が端末名＝ローカルのアカウント（ドメイン名には . がある）"""
    h = cred_host(c)
    return bool(h) and "." not in h


CRED_ADD_RE = re.compile(r"^[^:#\s][^:]*:.+")
