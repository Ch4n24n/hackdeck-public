"""コマンド帳の点検（hackdeck check）。定義の漏れ・依存の輪・opts の有無・候補のコマンドが動くか。自分のコマンド帳
（設定の books）も一緒に見る。"""
import os
import re
import shutil
import subprocess

from .paths import ROOT
from .cand_auth import AUTHCREDS_SHAPE, AUTH_FORMS
from .cheatbook import VAR_DESCS, book_label, compute_var_order, opts_files, parse_cheat_files, var_names_in


# --- 点検 -------------------------------------------------------------------

SAMPLE = {"domain": "corp.htb", "host": "$TARGET", "user": "john", "target_file": "x"}


def check_line(cmd, where):
    """$ の行の決まり: 候補は hackdeck から出す（決まった値も hackdeck value で）"""
    if not cmd.startswith("hackdeck "):
        print(f"[NG] {where}: 候補は hackdeck から出す（決まった値は hackdeck value）")
        return 1
    return 0


def check():
    """cheats を読み、変数の候補の定義と、候補を出すコマンドが動くかを確かめる"""
    entries, defs = parse_cheat_files()
    used = {}
    for r in entries:
        for v in var_names_in(r["command"]):
            used.setdefault(v, r["where"])
    problems = 0
    for name, (cmd, where, _example) in defs.items():
        problems += check_line(cmd, where)
    free = sorted(set(used) - set(defs))
    print(f"コマンドの変数 {len(used)} 個 / 候補の定義 {len(defs)} 個")
    for v in free:
        print(f"[NG] {used[v]} <{v}>: 候補の定義が無い（その場で打つものも `$ {v}: hackdeck value` を書く）")
        problems += 1
    # 候補の値の中の <var>（枝の中の変数。認証の形・opts の -M <nxc_mod> など）にも定義が要る（2026-10-29 追加）
    branch = {}
    for fmt, forms in AUTH_FORMS.items():
        for value, _shown in forms:
            for v in var_names_in(value):
                branch.setdefault(v, f"AUTH_FORMS[{fmt}]")
    for fmt, shape in AUTHCREDS_SHAPE.items():
        for _shown, kids in shape:
            for v in kids:
                branch.setdefault(v, f"AUTHCREDS_SHAPE[{fmt}]")
    opts = opts_files()
    for f in opts.values():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                for v in var_names_in(line.split("\t")[0]):
                    lab = book_label(f)
                    branch.setdefault(v, lab if "/" in lab else f"opts/{lab}")
    for v, where in sorted(branch.items()):
        if v not in defs:
            print(f"[NG] {where} <{v}>: 候補の定義が無い（枝の中の変数も `$ {v}: …` を書く）")
            problems += 1
    nodesc = sorted(v for v in set(used) | set(branch) if v in defs and not VAR_DESCS.get(v))
    if nodesc:
        print("説明（? の行）の無い変数: " + ", ".join(nodesc))
    unused = sorted(set(defs) - set(used) - set(branch)
                    - {v for c, _where, _example in defs.values() for v in var_names_in(c)})
    if unused:
        print("使われていない定義: " + ", ".join(unused))
    # 依存の輪（循環）が無いか。各定義を単体の template として order を計算してみる
    for name, (cmd, where, _example) in defs.items():
        try:
            compute_var_order(f"<{name}>", defs)
        except RuntimeError as e:
            print(f"[NG] {where} {name}: {e}")
            problems += 1
    protos = [l.split("\t")[0] for l in opts["nxc-proto"].read_text().splitlines() if l and not l.startswith("#")]
    for name, (cmd, where, _example) in sorted(defs.items()):
        body = re.sub(r"<([A-Za-z0-9_]+)>", lambda m: SAMPLE.get(m.group(1), "x"), cmd)
        for ref in re.findall(r'opts\s+"?([A-Za-z0-9_$-]+)', body):
            names = [ref.replace("$proto", p) for p in protos] if "$proto" in ref else [ref]
            if not any(x in opts for x in names):
                print(f"[NG] {where} {name}: opts/{ref}.tsv が無い")
                problems += 1
        env = dict(os.environ, proto="smb", PATH=f"{ROOT / 'bin'}:{os.environ.get('PATH', '')}")
        r = subprocess.run(["bash", "-c", body], env=env, capture_output=True, text=True)
        if r.returncode != 0 or r.stderr.strip():
            print(f"[NG] {where} {name}: {r.stderr.strip()[:200] or 'exit ' + str(r.returncode)}")
            problems += 1
    if not shutil.which("fzf"):
        print("[NG] fzf が無い: sudo apt install fzf")
        problems += 1
    print("問題なし" if not problems else f"問題 {problems} 件")
    return 1 if problems else 0
