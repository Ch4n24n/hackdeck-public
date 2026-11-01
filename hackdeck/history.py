"""組み立てたコマンドの履歴と、変数ごとに打った値の履歴（どちらも案件のデータの history・inputs。案件の外は無い）。"""
import datetime
import os
import re

from .text import out, q, shell_safe
from .case import state_file


INPUTS_KEEP = 10
# 履歴は、残すのも一覧に出すのも新しいほうから300件（2026-10-30、本人の指摘「履歴は300件ほど残して」。前は20件）。書くたびに
# 古い分を消す（2026-10-31、本人の指摘「見える方も管理する数も300に」。同日に一度「全部残して出すのを300件」にしたのは、
# 本人の意図の逆だった）。netexec の画面（Ctrl+N）も同じ数（NXC_SHOW）
HISTORY_KEEP = 300
HISTORY_SHOW = HISTORY_KEEP


def history_file():
    """履歴のファイル（コマンドのタブの「履歴」。案件の外は None）"""
    return state_file("history")


def _history_load(f):
    """1行に「時刻<TAB>コマンド」（手で直してもよい。時刻の読めない行は飛ばす）"""
    try:
        text = f.read_text(encoding="utf-8", errors="replace") if f else ""
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        ts, sep, cmd = line.partition("\t")
        try:
            datetime.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if sep and cmd.strip():
            rows.append({"ts": ts, "cmd": cmd})
    return rows


def _history_save(f, rows):
    """選んだパスワードも入るので 600 で書く"""
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{r['ts']}\t{r['cmd']}\n" for r in rows))


# 打った値を残さない変数（ファイルは手元から選ぶ。資格情報・パスワードは資格情報のタブで足す。本人の指摘「自動で保存すると
# ゴミみたいな情報が集まる」）
NO_INPUT_LOG = re.compile(r"hackdeck (?:files|auth|authforms|authcreds|authhow|users-for|secrets-for|passwords|hashes)\b")


def inputs_file():
    """打った値の履歴のファイル（上の「打った値」。案件の外は None）"""
    return state_file("inputs")


def inputs_load(f):
    """[(変数名, 値)]（古い順）"""
    try:
        text = f.read_text(encoding="utf-8", errors="replace") if f else ""
    except OSError:
        return []
    return [tuple(l.split("\t", 1)) for l in text.splitlines() if "\t" in l and l.split("\t", 1)[1].strip()]


def inputs_recent(name):
    """その変数の打った値（新しい順、INPUTS_KEEP 個まで）"""
    return [v for n, v in reversed(inputs_load(inputs_file())) if n == name][:INPUTS_KEEP]


def inputs_record(b, names, defs):
    """組み終えたコマンドで、打った値（「そのまま使う」の行で決めた、空でない値）を変数ごとに残す。同じ値は新しい方へ寄せ、
    変数ごとに新しい INPUTS_KEEP 個まで。選んだパスワードが入ることもあるので 600 で書く"""
    pairs, values = [], b.get("values", {})
    for n in names:
        if NO_INPUT_LOG.search(defs.get(n, ("", "", ""))[0]):
            continue
        v = b.get("view", {}).get(n, {})
        q = " ".join((v.get("q") or "").split())
        if v.get("t") and q:
            pairs.append((n, q))
        else:   # 前に打った値を選び直したら、それも新しい方へ（よく使う値が10個の中に残るように）
            hit = next((r for r in inputs_recent(n) if values.get(n) in (r, shell_safe(r))), None)
            if hit:
                pairs.append((n, hit))
    f = inputs_file()
    if not pairs or not f:
        return
    rows = inputs_load(f)
    for n, q in pairs:
        rows = [r for r in rows if r != (n, q)] + [(n, q)]
    kept, count = [], {}
    for n, q in reversed(rows):
        if count.get(n, 0) < INPUTS_KEEP:
            count[n] = count.get(n, 0) + 1
            kept.append((n, q))
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{n}\t{q}\n" for n, q in reversed(kept)))


def relative_ago(ts):
    d = datetime.datetime.now() - datetime.datetime.fromisoformat(ts)
    s = d.total_seconds()
    if s < 60:
        return "たった今"
    if s < 3600:
        return f"{int(s // 60)}分前"
    if s < 86400:
        return f"{int(s // 3600)}時間前"
    if s < 7 * 86400:
        return f"{int(s // 86400)}日前"
    return datetime.datetime.fromisoformat(ts).strftime("%m/%d")


def history_append(cmd):
    """いまの案件の履歴に積む。直前と同じコマンドなら増やさない。直近 HISTORY_KEEP 件まで"""
    f = history_file()
    if not f:
        return
    rows = _history_load(f)
    if not rows or rows[-1]["cmd"] != cmd:
        rows.append({"ts": datetime.datetime.now().isoformat(timespec="seconds"), "cmd": cmd})
    _history_save(f, rows[-HISTORY_KEEP:])


def history_rows():
    """いまの案件の履歴を、重複を除いて新しい順に最大 HISTORY_SHOW 件"""
    seen, uniq = set(), []
    for r in reversed(_history_load(history_file())):
        if r["cmd"] not in seen:
            seen.add(r["cmd"])
            uniq.append(r)
        if len(uniq) >= HISTORY_SHOW:
            break
    return uniq


def c_history():
    """点検・確認用に、いまの案件の履歴をそのまま見る（新しい順）"""
    for r in history_rows():
        out(r["cmd"], relative_ago(r["ts"]))
