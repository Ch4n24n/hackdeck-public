#!/usr/bin/python3 -I
"""hackdeck の CLI の出力を、試しの案件で丸ごと記録し、あとで比べる（作り替えの前後で、挙動が変わっていないかを見る）。

  python3 -I tests/snapshot.py record <出力.json>     いまの bin/hackdeck で記録する
  python3 -I tests/snapshot.py compare <記録.json>    いまの bin/hackdeck で走らせ、記録と違う所を出す

偽の HOME（一時フォルダ）に試しの案件・資格情報・netexec の DB を作り、tmux も別の置き場所にする（本物のサーバー・
ファイルには触らない）。コマンド帳の $ の行は全部、変数を試しの値に置き換えて bash で走らせる（check と同じやり方）。
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

# $ の行の <変数> に入れる試しの値
SAMPLE = {"domain": "test.local", "host": "$TARGET", "dc": "10.10.10.5", "user": "alice", "pw_user": "alice",
          "nt_user": "Administrator", "target_file": "x", "group": "Domain Admins"}
# 試しで使う、箱でない形の設定（既定は付属の雛形の箱の形。tests/e2e.sh・撮る道具も同じ値を書く）
GENERIC = {"template": "", "work_dir": "work", "state_dir": "work/.hack", "log_file": "logs/session.log"}
PROTOS = ["smb", "ldap", "winrm", "mssql", "ssh", "rdp", "wmi", "ftp", "vnc", "nfs"]


def build(t):
    """試しの環境を t の下に作る（案件は ~/cases。雛形は空・作業フォルダは work・データの置き場所は work/.hack・ログは
    logs/session.log を設定に書く＝箱でない形。既定は付属の雛形の箱の形だが、試しは箱の中身に頼らない。2026-11-02）。
    戻り値は (環境変数, 案件の作業フォルダ)"""
    home = t / "home"
    case = home / "cases" / "20261031-snap"
    work = case / "work"
    state = work / ".hack"
    (case / "logs").mkdir(parents=True)
    state.mkdir(parents=True)
    (state / "env").write_text("export TARGET=10.10.10.5\nexport DOMAIN=test.local\nexport DC01=10.10.10.5\n"
                               "export SRV01=10.10.10.6\nexport LHOST=10.10.14.2\n", encoding="utf-8")
    (state / "env-names").write_text("DC01:DC\nSRV01\n", encoding="utf-8")
    creds = ["alice:Passw0rd!:test.local", "bob:pa:ss:test.local（確認用）",
             "Administrator:0123456789abcdef0123456789abcdef:SRV01", "svc_sql:Sql2026!",
             "carol:C1:test.local（netexec SRV01 管理者、WS01 winrm）"]
    (state / "creds").write_text("".join(c + "\n" for c in creds), encoding="utf-8")
    (state / "history").write_text("2026-10-01T10:00:00\tnetexec smb $TARGET -u 'alice' -p 'Passw0rd!'\n"
                                   "2026-10-02T11:00:00\tevil-winrm -i $TARGET -u 'alice' -p 'Passw0rd!'\n",
                                   encoding="utf-8")
    (state / "inputs").write_text("domain\tcorp.htb\nuser\tdave\n", encoding="utf-8")
    (work / "users.user").write_text("alice\nbob\n", encoding="utf-8")
    (work / "pw.pass").write_text("Passw0rd!\n", encoding="utf-8")
    (work / "h.hash").write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    (work / "notes.txt").write_text("hello\n", encoding="utf-8")
    (work / "sub").mkdir()
    # netexec の DB（hackdeck が読む列だけ）
    ws = state / "nxc" / "workspaces" / "default"
    ws.mkdir(parents=True)
    c = sqlite3.connect(ws / "smb.db")
    c.executescript("""
        create table hosts (id integer primary key, ip text, hostname text, domain text, os text, dc boolean);
        create table users (id integer primary key, domain text, username text, password text, credtype text,
                            pillaged_from_hostid integer);
        create table admin_relations (id integer primary key, userid integer, hostid integer);
        create table loggedin_relations (id integer primary key, userid integer, hostid integer);
        insert into hosts values (1, '10.10.10.5', 'DC01', 'test.local', 'Windows', 1), (2, '10.10.10.6', 'SRV01', 'test.local', 'Windows', 0);
        insert into users values (1, 'test.local', 'dave', 'D4ve!', 'plaintext', null),
                                 (2, 'SRV01', 'Administrator', 'aad3b435b51404eeaad3b435b51404ee:fedcba9876543210fedcba9876543210', 'hash', 2),
                                 (3, 'TEST', 'erin', 'E1', 'plaintext', null);
        insert into admin_relations values (1, 2, 2);
        insert into loggedin_relations values (1, 1, 1);
    """)
    c.commit()
    c.close()
    os.utime(ws / "smb.db", (1793408400, 1793408400))   # 2026-10-31 10:00（見つけた日時を決めておく）
    data = home / ".local" / "share" / "hackdeck"
    (data / "wordlists").mkdir(parents=True)
    (data / "common").write_text("admin:\nhacker::試し\n:Welcome1\n", encoding="utf-8")
    (data / "wordlists" / "Auth_Bypass.txt").write_text("' or 1=1-- -\n", encoding="utf-8")
    (home / ".config" / "hackdeck").mkdir(parents=True)
    (home / ".config" / "hackdeck" / "settings.json").write_text(json.dumps(GENERIC), encoding="utf-8")
    env = {"HOME": str(home), "PATH": f"{BIN}:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TERM": "xterm-256color",
           "HACK_ROOT": str(case), "TMUX_TMPDIR": str(t / "tmux"), "HACKDECK_TMUX_SOCKET": "hackdeck-snap",
           "COLUMNS": "200", "LINES": "50"}
    (t / "tmux").mkdir()
    return env, work


def var_defs():
    """コマンド帳の $ の行（名前, コマンド）"""
    out = []
    for f in sorted((ROOT / "cheats").glob("*.cheat")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\$\s*([A-Za-z0-9_]+)\s*:\s*(.+)$", line)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def run(env, cwd, argv=None, shell=None):
    if shell is not None:
        r = subprocess.run(["bash", "-c", shell], env=env, cwd=cwd, capture_output=True, text=True, timeout=60)
    else:
        r = subprocess.run([str(BIN / "hackdeck"), *argv], env=env, cwd=cwd, capture_output=True, text=True,
                           timeout=60)
    return {"rc": r.returncode, "out": r.stdout, "err": r.stderr}


def collect():
    t = Path(tempfile.mkdtemp(prefix="hackdeck-snap-"))
    try:
        env, work = build(t)
        res = {}
        res["check"] = run(env, work, ["check"])
        for name, cmd in var_defs():
            body = re.sub(r"<([A-Za-z0-9_]+)>", lambda m: SAMPLE.get(m.group(1), "x"), cmd)
            protos = PROTOS if "$proto" in body else [None]
            for p in protos:
                e = dict(env, proto=p) if p else env
                res[f"$ {name}" + (f" [{p}]" if p else "")] = run(e, work, shell=body)
        # 打った文字で絞る（どの画面も同じ絞り方。足せる画面は足す行が残る）
        for argv in (["credsrows", ""], ["credsrows", "x:y"], ["credsrows", "srv01"], ["envrows", ""], ["envrows", "FOO=1"],
                     ["envrows", "10.10.10"], ["caserows", ""], ["caserows", "snap"], ["settingrows", ""],
                     ["settingrows", "ログ"], ["nxcfound"], ["history"], ["hosts"], ["files", "any"],
                     ["typed", "foo bar"], ["value", "a", "b"]):
            res[" ".join(["cli", *argv])] = run(env, work, argv)
        for f in sorted((ROOT / "opts").glob("*.tsv")):
            res[f"opts {f.stem}"] = run(env, work, ["opts", f.stem])
        outside = {k: v for k, v in env.items() if k != "HACK_ROOT"}   # 案件のセッションの外
        for argv in (["caserows", ""], ["settingrows", ""], ["credsrows", ""], ["history"], ["case", "ls"]):
            res[" ".join(["outside", *argv])] = run(outside, t, argv)
        # パスはその回の一時フォルダなので、比べられる形に置き換える
        txt = json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True).replace(str(t), "<T>")
        return json.loads(txt)
    finally:
        shutil.rmtree(t, ignore_errors=True)


def main(argv):
    if len(argv) != 2 or argv[0] not in ("record", "compare"):
        print(__doc__)
        return 2
    now = collect()
    if argv[0] == "record":
        Path(argv[1]).write_text(json.dumps(now, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"記録した: {len(now)} 件 → {argv[1]}")
        return 0
    old = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    diffs = [k for k in sorted(set(old) | set(now)) if old.get(k) != now.get(k)]
    for k in diffs:
        print(f"=== 違う: {k}")
        o, n = old.get(k) or {}, now.get(k) or {}
        for part in ("rc", "out", "err"):
            if o.get(part) != n.get(part):
                print(f"--- {part}（前）\n{o.get(part)}\n--- {part}（後）\n{n.get(part)}")
    print(f"{len(now)} 件のうち、違うのは {len(diffs)} 件")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
