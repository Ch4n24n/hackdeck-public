"""案件のモデル: 案件の置き場所と、1つの案件の中の場所（作業フォルダ・データの置き場所・ログ）と、いまの案件。

どの場所も設定で決まる（cases_dir・work_dir・state_dir・log_file。settings.py）。いまの案件は、案件のセッションの環境
（HACK_ROOT。session.py がセッションに入れ、窓は popup.py がペインのセッションから入れる）だけで決め、いまいる場所
（cwd）は見ない。セッションの外は「案件の外」で、画面は案件のタブと設定のタブだけになる。"""
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .paths import CASE_LAST, COMMON_LISTS
from . import settings

CASE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+-]*$")   # tmux のセッション名にもなる（: . は使えない）


def cases_dir():
    return Path(settings.get("cases_dir")).expanduser()


def case_path(name):
    return cases_dir() / name


def work_of(root):
    """作業フォルダ（~hack・$HACK_HOME）"""
    w = settings.get("work_dir").strip() or "."
    return root if w in (".", "./") else root / w


def state_of(root):
    """案件のデータの置き場所（資格情報・環境変数・履歴・メモ・窓の並び・netexec の DB・案件の目印）。案件のフォルダからの場所（設定の state_dir）"""
    return root / (settings.get("state_dir").strip() or settings.BY_KEY["state_dir"].default)


def log_of(root):
    """ログのファイル（設定が空なら None）"""
    v = settings.get("log_file").strip()
    return root / v if v else None


def is_case_dir(d):
    """案件のフォルダか（隠しフォルダでなく、作業フォルダがある）"""
    return d.is_dir() and not d.name.startswith(".") and work_of(d).is_dir()


def case_dirs():
    try:
        return sorted(d for d in cases_dir().iterdir() if is_case_dir(d))
    except OSError:
        return []


def case_root():
    """いまの案件のフォルダ（案件のセッションの外は None）"""
    v = os.environ.get("HACK_ROOT")
    return Path(v) if v and is_case_dir(Path(v)) else None


def case_file(root, name):
    """案件のデータのファイル（env・env-names・creds・history・inputs・session・nxc）"""
    return state_of(root) / name


def state_file(name):
    """いまの案件のデータのファイル（案件の外は None）"""
    root = case_root()
    return case_file(root, name) if root else None


def case_env(root):
    """案件のセッションに入れる環境変数（session.py が tmux のセッションに、popup.py が窓に入れる）"""
    env = {"HACK_ROOT": str(root), "HACK_CASE": root.name, "HACK_HOME": str(work_of(root)),
           "HACK_STATE": str(state_of(root)), "NXC_PATH": str(case_file(root, "nxc"))}
    log = log_of(root)
    env["HACK_LOG"] = str(log) if log else ""
    return env


def lists_dir():
    """一覧ファイルを作る場所（いまの案件の作業フォルダ。シェルでは ~hack）"""
    root = case_root()
    return work_of(root) if root else None


def list_place(kind):
    """作る一覧の置き場所。資格情報の分は案件の作業フォルダ、よく使う分は案件をまたぐ置き場所"""
    return COMMON_LISTS if kind.startswith("common-") else lists_dir()


def named_dirs():
    """zsh の名前付きディレクトリ（shell/hack.zsh が定義する）{名前: 場所}"""
    root = case_root()
    return {**({"hack": work_of(root)} if root else {}), "cmn": COMMON_LISTS}


def expand_named(path):
    """~hack/…・~cmn/… を本当の場所に（~/… と ~user/… は os.path.expanduser と同じ）"""
    head, sep, rest = path.partition("/")
    d = named_dirs().get(head[1:]) if head.startswith("~") else None
    return str(d) + sep + rest if d else os.path.expanduser(path)


def case_id(root, create=True):
    """案件の目印（データの置き場所の id）。名前を変えても・動かしても同じなので、案件の外で覚えるもの（窓の画面の列・
    直前の案件）は、名前や場所ではなくこれで見分ける（2026-11-01、本人の指摘「名前を変えたあとも、どうにかできるでしょ」。
    hackdeck の外で mv しても、止まっている案件ならそのまま使えるように）。無ければ作る（create）。作れなければ空"""
    f = state_of(root) / "id"
    try:
        v = f.read_text(encoding="utf-8").strip()
        if v:
            return v
    except OSError:
        pass
    if not create or not is_case_dir(root):
        return ""
    ensure_state(root)
    v = uuid.uuid4().hex
    try:
        with os.fdopen(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as fh:
            fh.write(v + "\n")
    except FileExistsError:   # 同じ案件の別の窓が、同時に作った
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return v


def case_by_id(cid):
    """目印 cid の案件のフォルダ（無ければ None）"""
    return next((d for d in case_dirs() if cid and case_id(d, create=False) == cid), None)


def case_scope(root=None):
    """閉じたときの画面の列（nav）を案件ごとに分ける文字列（案件の外は None）。案件の目印なので、名前を変えても同じ列。
    目印を作れないとき（書けない場所）は案件の場所。root: 案件のフォルダ（既定はいまの案件）"""
    root = root or case_root()
    if not root:
        return None
    cid = case_id(root)
    return f"id:{cid}" if cid else str(root)


def last_case():
    """直前に入った案件の名前（hackdeck case attach の名前を省いたとき・案件のタブの最初のカーソル）。名前を変えていたら
    （hackdeck の外で mv しても）、目印で今の名前を探す。見つからなければ空"""
    try:
        name, _, cid = CASE_LAST.read_text(encoding="utf-8").strip().partition("\t")
    except OSError:
        return ""
    d = case_path(name) if name else None
    if d and is_case_dir(d):
        have = case_id(d, create=False)
        if not cid or not have or have == cid:
            return name   # 同じ名前の案件（前の形の覚え方・目印がまだ無い案件も）
    d = case_by_id(cid)
    return d.name if d else ""


def last_case_set(root):
    """直前に入った案件を覚える（名前と目印）"""
    CASE_LAST.parent.mkdir(parents=True, exist_ok=True)
    CASE_LAST.write_text(f"{root.name}\t{case_id(root)}\n", encoding="utf-8")


def keep_out_of_git(f):
    """f が git の作業ツリーの中にあって無視されていなければ、.git/info/exclude に足す（資格情報などをコミットしないため）"""
    def git(*a):
        return subprocess.run(["git", "-C", str(f.parent), *a], capture_output=True, text=True)
    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode != 0 or git("check-ignore", "-q", f.name).returncode == 0:
            return
        exclude = Path(git("rev-parse", "--git-path", "info/exclude").stdout.strip())
    except OSError:
        return
    if not exclude.is_absolute():
        exclude = f.parent / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    rel = f.resolve().relative_to(Path(top.stdout.strip()).resolve())
    with open(exclude, "a", encoding="utf-8") as fh:
        fh.write(f"/{rel}\n")


def to_trash(path):
    """ゴミ箱へ移す（gio か trash-put。どちらも無ければ移さない）。(できたか, 一言)"""
    for cmd in (["gio", "trash"], ["trash-put"]):
        if shutil.which(cmd[0]):
            r = subprocess.run([*cmd, str(path)], capture_output=True, text=True)
            return r.returncode == 0, r.stderr.strip()[:60]
    return False, "ゴミ箱へ移す道具が無い（gio か trash-cli を入れる）"


def ensure_state(root):
    """データの置き場所を作る（700。git の中なら追わない）"""
    d = state_of(root)
    if not d.is_dir():
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        keep_out_of_git(d)
    return d
