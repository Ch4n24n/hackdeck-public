"""変数の候補の入口: hackdeck <種類> の振り分け（CANDIDATE_CMDS）と、決まった値・opts（打った値の行は fzfcall.c_typed）。"""
import os
import re

from .text import VAR_RE, display_width, fit, out
from .cand_net import (c_cidrs, c_connect, c_dcs, c_domains, c_fqdns, c_hostips, c_hostnames, c_hosts, c_ifaces,
    c_lhost, c_urls)
from .cand_auth import (c_adtarget, c_auth, c_authcreds, c_authforms, c_authhow, c_domaindn, c_hashes, c_passwords,
    c_secrets_for, c_users, c_users_for)
from .cand_files import c_ccache, c_files
from .cheatbook import opts_file


_OPTS_ROWS = {}   # (ファイル, 更新時刻) → 行（流れの図のために、窓を開くたびに同じ一覧を何度も読んでいた）


def opts_lines(name):
    f = opts_file(name)
    if not f:
        return []  # 一覧が無ければ候補なし（その場で打つ）
    try:
        key = (f, f.stat().st_mtime_ns)
    except OSError:
        return []
    if key not in _OPTS_ROWS:
        rows = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        # 数字を選ぶ一覧（モード・ポートなど）は数字順。値が空の行（付けない）は先頭
        if all(re.fullmatch(r"[\d,]*", r.split("\t")[0]) for r in rows):
            rows.sort(key=lambda r: [int(x) for x in r.split("\t")[0].split(",") if x] or [-1])
        _OPTS_ROWS[key] = rows
    return list(_OPTS_ROWS[key])


def c_opts(name):
    # 組み立てているコマンドに既にあるオプションは出さない（スプレーは --continue-on-success がいつも付く。2026-10-30）
    have = set(os.environ.get("HACKDECK_TPL", "").split())
    lines = [l for l in opts_lines(name) if l.split("\t")[0] not in have]
    # 値・名前・例の3列（hashcat のモード）は、名前の列をそろえてから例を続け、2列（値・説明）にして返す（2026-10-30、本人の
    # 指摘「モードの例が見にくい。列を揃えて」。fit は端末の見た目の幅で詰めるので、全角の名前でも例の開始位置がそろう）
    # 枝分かれの値（中に <変数> がある。win-persist）の3列は、値・表示名・説明のまま返す（入る値は長いので、画面と図には表示名を
    # 出す。2026-10-31）。枝の行がある一覧（fw-rule）は、枝でない3列の行（定番セット）も表示名のまま（値と表示名がまざると、
    # 長い値に合わせて表示名の列が崩れる。2026-10-31）
    named = any(l.count("\t") >= 2 and VAR_RE.search(l.split("\t")[0]) for l in lines)
    nw = max((display_width(l.split("\t", 2)[1]) for l in lines
              if l.count("\t") >= 2 and not VAR_RE.search(l.split("\t")[0])), default=0)
    for line in lines:
        p = line.split("\t", 2)
        if len(p) >= 3 and (named or VAR_RE.search(p[0])):
            print(line)
        else:
            print(f"{p[0]}\t{fit(p[1], nw)}  {p[2]}" if len(p) >= 3 else line)


def c_value(args):
    """決まった値を候補にする"""
    for v in args:
        out(v)


CANDIDATE_CMDS = {
    "hosts": c_hosts, "fqdns": c_fqdns, "domains": c_domains, "lhost": c_lhost, "hostips": c_hostips, "hostnames": c_hostnames,
    "ifaces": c_ifaces, "cidrs": c_cidrs, "users": c_users, "passwords": c_passwords,
    "hashes": c_hashes, "ccache": c_ccache, "urls": c_urls, "dcs": c_dcs, "connect": c_connect,
}


def run_candidate_cmd(cmd, args):
    """$ 行の候補コマンド（hackdeck <種類> ...）を直接呼ぶときの分岐。cheats/opts/check が使う"""
    if cmd == "users":
        c_users(*args[:1])
    elif cmd in CANDIDATE_CMDS:
        CANDIDATE_CMDS[cmd]()
    elif cmd == "adtarget":
        c_adtarget(*args[:1])
    elif cmd == "domaindn":
        c_domaindn()
    elif cmd == "auth" and args:
        c_auth(*args[:3])
    elif cmd == "authforms" and args:
        c_authforms(*args[:2])
    elif cmd == "authcreds" and args:
        c_authcreds(*args[:2])
    elif cmd == "authhow" and args:
        c_authhow(*args[:2])
    elif cmd == "users-for" and args:
        c_users_for(args[0])
    elif cmd == "secrets-for" and args:
        c_secrets_for(args[0], args[1] if len(args) > 1 else "")
    elif cmd == "files":
        c_files(args)
    elif cmd == "opts" and args:
        c_opts(args[0])
    elif cmd == "value":
        c_value(args)
    else:
        return False
    return True
