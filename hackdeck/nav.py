"""通った画面の列（戻る・進む・上へ）と、その保存。"""
import datetime
import hashlib
import json
import os
from pathlib import Path

from .paths import NAV_DIR
from .settings import BY_KEY
from .case import case_scope
from .flow import flow_nodes
from .ui import tab_of


HISTORY_STALE_DAYS = 90  # この日数触っていない案件の、開き直す画面の列（nav）は片づける


def tab_entry(nav, tab):
    """タブへ移るときの行き先。そのタブで最後に開いていた画面（書き換えの途中の画面は除く）。無ければそのタブの最初の画面"""
    for e in reversed(nav["entries"][:nav["index"] + 1]):
        if tab_of(e) == tab and e.get("e") is None:   # 設定の開いていた項目（配色の一覧など）にも戻る（2026-11-01、本人の指摘）
            return dict(e)
    if tab == "cmd":
        return {"s": "picker", "q": "", "f": None}
    if tab == "creds":
        return {"s": "creds", "tab": tab, "q": "", "f": None, "e": None}
    return {"s": tab, "q": "", "f": None, "e": None}   # 設定は項目の一覧から


NAV_KEEP = 300   # 列に残す数（本人の指定）


_HERE = object()   # nav_file・nav_save の scope の既定（いまの案件）


def nav_file(scope=_HERE):
    """案件ごとの列のファイル（案件の外は1つ）。開き直すための画面の列で、案件の情報ではないので案件の中には置かない
    （キャッシュの nav/。履歴は案件の中）。scope: 案件の範囲（case_scope の形。None は案件の外。既定はいまの案件）"""
    scope = (case_scope() if scope is _HERE else scope) or ""
    return NAV_DIR / f"{hashlib.sha1(scope.encode()).hexdigest()[:16]}.json"


def nav_adopt(root):
    """前の形（案件の場所ごと）の列のファイルがあれば、案件の目印ごとのファイルへ移す（2026-11-01、案件の目印で見分けるように
    してから。前に開いていた画面が消えないように）。root: 案件のフォルダ（None なら何もしない）"""
    if root is None:
        return
    new = nav_file(case_scope(Path(root)))
    if new.exists():
        return
    for old in (nav_file(str(root)), nav_file(str(Path(root).resolve()))):
        if old.exists() and old != new:
            os.replace(old, new)
            return


def nav_load(f=None):
    """残した列。読めない・形が違うときは捨てて、空から始める（壊れたファイルで開けなくならないように）。f: 列のファイル
    （既定はいまの案件の）"""
    try:
        nav = json.loads((f or nav_file()).read_text(encoding="utf-8"))
        if (nav.get("v") == 1 and isinstance(nav.get("builds"), dict)
                and 0 <= nav.get("index", -1) < len(nav.get("entries", []))
                and all(e.get("s") != "var" or ("b" in e and "v" in e) for e in nav["entries"])
                and all(e.get("s") != "settings" or e.get("v") in (None, *BY_KEY) for e in nav["entries"])):
            return nav
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return {"v": 1, "entries": [], "index": -1, "builds": {}, "last": ""}


def nav_save(nav, f=None, scope=_HERE):
    """選んだパスワードも入るので 600 で書く。HISTORY_STALE_DAYS 日触っていない案件の列は片づける。f・scope: 書く先の
    列のファイルと案件の範囲（既定はいまの案件。nav_handoff が行き先の案件の列に書く）"""
    f = f or nav_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    nav["scope"] = case_scope() if scope is _HERE else scope
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(nav, fh, ensure_ascii=False)
    os.replace(tmp, f)
    cutoff = datetime.datetime.now().timestamp() - HISTORY_STALE_DAYS * 86400
    for old in NAV_DIR.glob("*.json"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass


def nav_handoff(root, entry):
    """案件を移るとき（案件のタブで入る・tmux から離れる）、行き先の列にも entry（案件のタブ・カーソルは入った案件）を積む
    （2026-10-31、本人の指摘「案件タブから案件に入ると、Ctrl+G のフォーカスやタブが初期状態に戻る。以前の位置を常に覚えて
    おいて」。列は案件ごとのファイルなので、積まないと行き先で開き直したとき、その案件で前に開いていた画面（無ければ最初の
    画面）から始まっていた。行き先の前の画面は Alt+← で戻れる）。root: 行き先の案件のルート（None は案件の外）。いまと同じ
    範囲なら何もしない（閉じるときにいまの列を書くので）"""
    nav_adopt(root)
    scopes = {None} if root is None else {case_scope(Path(root))}   # 行き先の案件の目印
    for scope in scopes - {case_scope()}:
        f = nav_file(scope)
        nav = nav_load(f)
        nav_push(nav, dict(entry))
        nav_save(nav, f, scope)


def nav_only(nav, tabs):
    """列を、そのタブの画面だけにする（案件のセッションの外は案件と設定だけ）。いまの画面が外れたら、残った最後の画面へ"""
    cur = nav["entries"][nav["index"]] if nav["entries"] else None
    nav["entries"] = [e for e in nav["entries"] if tab_of(e) in tabs]
    # いまの画面は、中身の等しい画面ではなく、その画面そのものを探す（前は index で等しい最初の画面を拾い、同じコマンド選びの
    # 画面が前にもあると、そこまで巻き戻って、あとで開いた画面（設定の配色の一覧など）を見失っていた。2026-11-01）
    nav["index"] = next((i for i, e in enumerate(nav["entries"]) if e is cur), len(nav["entries"]) - 1)


def nav_push(nav, entry):
    """新しい画面へ。いまより後ろ（Alt+← で戻ってきた先）は捨てる（ブラウザと同じ）"""
    nav["entries"] = (nav["entries"][:nav["index"] + 1] + [entry])[-NAV_KEEP:]
    nav["index"] = len(nav["entries"]) - 1
    used = {e["b"] for e in nav["entries"] if e["s"] == "var"}
    nav["builds"] = {k: b for k, b in nav["builds"].items() if k in used}


def nav_step(nav, step, defs):
    """Alt+←（-1）/ Alt+→（+1）の行き先の番号。もう出せない画面（枝を変えて図から消えた変数）は飛ばす。無ければ None"""
    i = nav["index"] + step
    while 0 <= i < len(nav["entries"]):
        e = nav["entries"][i]
        if e["s"] != "var" or e["v"] in build_names(nav["builds"].get(e["b"]), defs):
            return i
        i += step
    return None


def nav_saved(nav, focus):
    """書き換え（資格情報・環境・設定の一覧）を保存したとき。書き換えの画面（と後ろ）を列から外し、その前の同じ画面に戻す"""
    i = nav["index"]
    cur = nav["entries"][i]
    nav["entries"], nav["index"] = nav["entries"][:i], i - 1
    prev = nav["entries"][-1] if nav["entries"] else None
    if prev and tab_of(prev) == tab_of(cur) and prev.get("e") is None:
        prev.update(q="", f=focus)
    else:
        nav_push(nav, {**{k: cur[k] for k in ("s", "tab") if k in cur}, "q": "", "f": focus, "e": None})


def home_entry(nav, focus=None):
    """Esc の行き先のコマンド選び。いちばん近いコマンド選びの検索語を引き継ぎ、カーソルは組み立てていたコマンドへ"""
    for e in reversed(nav["entries"][:nav["index"] + 1]):
        if e["s"] == "picker":
            return {"s": "picker", "q": e.get("q", ""), "f": focus or e.get("f")}
    return {"s": "picker", "q": "", "f": focus}


def up_entry(nav, e, defs):
    """Alt+↑ の行き先。そのタブの画面の並びで1つ上（いちばん上の画面なら None）。来た道をたどる Alt+← と違い、途中で
    別のタブを開いていても、タブの中の並びで上がる。変数の画面は流れの図で1つ前の変数（最初の変数ならコマンド選び）、
    履歴はコマンド選び、netexec が見つけた分は資格情報の一覧（いちばん近くで開いていた検索語・カーソルのまま）、
    書き換えの途中はその一覧、設定の項目を開いた画面は項目の一覧"""
    s = e["s"]
    if s == "var":
        b = nav["builds"].get(e["b"])
        names = build_names(b, defs)
        i = names.index(e["v"]) if e["v"] in names else 0
        return {"s": "var", "b": e["b"], "v": names[i - 1]} if i > 0 else home_entry(nav, b["key"] if b else None)
    if s == "history":
        return home_entry(nav)
    if s == "nxc":
        for x in reversed(nav["entries"][:nav["index"] + 1]):
            if x["s"] == "creds" and x.get("e") is None:
                return dict(x)
        return {"s": "creds", "tab": "creds", "q": "", "f": None, "e": None}
    if s == "creds" and e.get("e") is not None:
        return {"s": "creds", "tab": "creds", "q": "", "f": f"op:{e['e']}", "e": None}
    if s == "env" and e.get("e") is not None:
        return {"s": "env", "q": "", "f": f"env:{e['e']}", "e": None}
    if s == "settings" and e.get("v"):
        v = e["v"]
        if e.get("e") is not None and BY_KEY[v].kind in ("list", "common"):
            return {"s": "settings", "v": v, "q": "", "f": e["e"], "e": None}   # 一覧の1行の書き換えは、その一覧へ
        return {"s": "settings", "q": "", "f": v, "e": None}
    return None


def entry_key(r):
    """コマンド帳の1行を見分ける文字列（閉じて開き直しても同じ行を指す）"""
    return f"{r['tag']}\x1f{r['comment']}\x1f{r['command']}"


def build_names(b, defs):
    """組み立て1回分の、いまの値で枝を開いた聞く順の変数名"""
    if not b:
        return []
    try:
        return [n for n, _, _ in flow_nodes(b["tpl"], defs, b["values"], set(b["confirmed"]))]
    except RuntimeError:
        return []
