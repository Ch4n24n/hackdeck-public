"""netexec の DB を読み、見つけた資格情報を Ctrl+N の一覧と、足したあとの説明の（netexec …）に出す。"""
import configparser
import datetime
import fcntl
import hashlib
import os
import re
import sqlite3
from pathlib import Path

from .text import NT, display_width, fit, out, q
from .case import case_file, case_root, keep_out_of_git
from .creds import cred_host, creds_file, own_creds, parse_cred_line
from .history import HISTORY_SHOW


# --- netexec が見つけた資格情報 -----------------------------------------------------
# 資格情報のタブの Ctrl+N（2026-10-31）。netexec の DB（NXC_PATH/workspaces/<workspace>/*.db）を読み、まだ資格情報の
# ファイルに無いものを並べて、選んで足す（本人が選んだ案 B。自動では足さない＝creds_screen の「自動で保存するとゴミが
# 集まる」と同じ考え。NetExecWrapper4ExegolHistory は netexec を打つたびに自動で足す形で、Exegol の中でしか動かず、
# ライセンスも無いので、考え方だけ借りて自前で書いた）。DB は読むだけで、書くのは資格情報のファイルだけ。
# 案件の NXC_PATH は、案件のデータの nxc（案件のセッションの環境に入る。session.case_create）。分けないと、前の案件で
# 見つけた分まで並ぶため（本人の判断）
NXC_GLOBAL = Path.home() / ".nxc"
# 案件の nxc から、共通の ~/.nxc を指すリンクにするもの。案件ごとにするのは DB（workspaces）だけで、設定（nxc.conf の
# ignore_opsec）・ダンプ（logs/lsa・logs/ntds）・モジュールの出力（modules/lsassy など）は今までの場所のまま
NXC_SHARED = ("nxc.conf", "logs", "modules", "obfuscated_scripts", "screenshots", "tmp")
# 見つけた日時の記録（netexec の置き場所の中。netexec の DB には時刻が無いので、hackdeck が残す。nxc_seen）
NXC_SEEN_NAME = "hackdeck-seen.tsv"
NXC_SHOW = HISTORY_SHOW   # netexec の画面に出す件数の上限（履歴と同じ。2026-10-31、本人の指定「履歴と揃えて、300件でいい」）
# netexec の Pwn3d!（DB の admin_relations）が、プロトコルごとに意味すること（2026-10-31、本人の指摘「smb 以外で Pwn3d! に
# なっても管理者権限ではない」。前はどのプロトコルの分も「管理者」と出していた）。netexec 1.5.1 の判定で確かめた: smb は
# サービスの管理（svcctl）を開ける＝ローカルの管理者、ssh は `id; sudo -ln` が root・NOPASSWD: ALL・(ALL : ALL) ALL
# （Windows なら whoami /priv に SeDebugPrivilege）、mssql は SQL Server の sysadmin（OS の管理者ではない）、winrm は WinRM の
# シェルを開ける（管理者ではない）。ldap は Domain Admins・Enterprise Admins・Administrators・Server Operators・Backup
# Operators のどれか（RID 512・519・544・549・551）、rdp は RDP の画面まで入れる（本人の指摘「ldap・rdp も意味のある出力」）。
# ただし netexec 1.5.1 は ldap の Pwn3d! と rdp の資格情報を DB に残さない（ldap.db は users・hosts だけ、rdp.db は hosts
# だけ）ので、いまは出てこない（DB に残る版になれば、この名前で出る）。強い順に並べる（nxc_where はこの順に全部出す）。
# ほかのプロトコルはその名前で出す
NXC_PWN = {"ldap": "ldap 管理者", "smb": "管理者", "ssh": "ssh 管理者", "mssql": "mssql sysadmin", "winrm": "winrm",
           "rdp": "rdp"}


def nxc_home():
    """いまの netexec の置き場所（NXC_PATH）。案件の中は案件のデータの nxc、案件の外は netexec の既定
    （自分で NXC_PATH を入れていればそれ、無ければ ~/.nxc）"""
    root = case_root()
    if root is not None:
        return case_file(root, "nxc")
    return Path(os.environ.get("NXC_PATH") or NXC_GLOBAL).expanduser()


def nxc_home_prepare(d):
    """案件の netexec の置き場所を作る（案件のセッションを作るときに session.case_create が呼ぶ）。NXC_SHARED を共通の
    ~/.nxc を指すリンクにする。DB の workspaces は netexec が初めて動いたときに自分で作る。もうあるものには触らない"""
    d = Path(d).expanduser()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in NXC_SHARED:
        src, dst = NXC_GLOBAL / name, d / name
        if src.exists() and not (dst.exists() or dst.is_symlink()):
            try:
                dst.symlink_to(src)
            except FileExistsError:   # 同じ案件の別のペインが、同時に作った
                pass
    keep_out_of_git(d)


def nxc_workspace_dir(home):
    """netexec がいま使う workspace の DB の場所（nxc.conf の [nxc] workspace。無ければ default）"""
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(home / "nxc.conf", encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        pass
    return home / "workspaces" / (cp.get("nxc", "workspace", fallback="default").strip() or "default")


def nxc_db_rows(db):
    """netexec の DB 1つの資格情報と、ホストの名前・ドメイン名。資格情報は (行番号, domain, user, secret, credtype, Pwn3d! に
    なったホストの名前（admin_relations。意味はプロトコルで違う＝NXC_PWN）, 見つけたホストの名前) の新しい順。見つけたホストは、ログインできたホスト（smb の loggedin_relations。
    netexec はログインに通ると書く）と、抜いたホスト（SAM・LSA・NTDS の pillaged_from_hostid）。表と列はプロトコルで違う
    （smb・ldap・winrm・mssql は users、ssh・ftp などは credentials。ドメインや credtype の無い表もある）ので、あるものだけ読む"""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
    try:
        cols = {n: {r[1] for r in con.execute(f'pragma table_info("{n}")')}
                for (n,) in con.execute("select name from sqlite_master where type='table'")}
        pick = lambda t, *names: ", ".join(c if c in cols.get(t, ()) else "null" for c in names)
        hosts, names, doms = {}, set(), set()
        if "hosts" in cols:
            for hid, name, ip, dom in con.execute(f"select {pick('hosts', 'id', 'hostname', 'ip', 'domain')} from hosts"):
                hosts[hid] = name or ip or ""
                if name:
                    names.add(name.lower())
                if dom and "." in dom:
                    doms.add(dom)
        table = "users" if "users" in cols else "credentials" if "credentials" in cols else None
        if table is None:
            return [], names, doms

        def related(name):   # {資格情報の id: [ホストの名前]}（その表が無ければ空）
            rel, out = cols.get(name, set()), {}
            uid = "userid" if "userid" in rel else "credid" if "credid" in rel else None
            if uid and "hostid" in rel:
                for u, h in con.execute(f'select {uid}, hostid from "{name}"'):
                    if hosts.get(h) and hosts[h] not in out.setdefault(u, []):
                        out[u].append(hosts[h])
            return out
        admin, login = related("admin_relations"), related("loggedin_relations")
        rows = []
        for i, d, u, p, ct, pil in con.execute(
                f"select {pick(table, 'id', 'domain', 'username', 'password', 'credtype', 'pillaged_from_hostid')}"
                f' from "{table}" order by id desc'):
            found = login.get(i, []) + ([hosts[pil]] if hosts.get(pil) and hosts[pil] not in login.get(i, []) else [])
            rows.append((i or 0, d or "", u or "", p or "", ct or "plaintext", admin.get(i, []), found))
        return rows, names, doms
    finally:
        con.close()


def nxc_scope(dom, names, doms):
    """netexec の domain を、資格情報の範囲（説明の頭）に。ドメイン名（. がある）と端末名（DB のホストの名前＝ローカルの
    アカウント）はそのまま。NetBIOS のドメイン名（INLANEFREIGHT など）は、DB にあるドメイン名で頭の語が同じもの
    （INLANEFREIGHT.LOCAL）に直す（範囲に . が無いと、ローカルのアカウントとして扱われるため。cred_is_local）"""
    if not dom or "." in dom or dom.lower() in names:
        return dom
    return next((d for d in sorted(doms) if d.split(".")[0].lower() == dom.lower()), dom)


def nxc_seen(home, update):
    """netexec の画面の記録（home の NXC_SEEN_NAME）を、鍵（flock）をかけて読み、update(kept, hwm) で直して書き戻す。戻り値は
    update の戻り値。kept は {印: (見つけた時刻, DB, 行番号)}（Ctrl+N で扱う資格情報の元の行。NXC_SHOW 件まで）、hwm は
    {DB: どこまで見たかの行番号}（これより後ろの行は、新しく見つけた分）。1行に @DB<TAB>行番号 か 印<TAB>時刻<TAB>DB<TAB>
    行番号。印は DB・ドメイン・ユーザー・値から作る（値そのものは書かない）。
    netexec の DB には時刻が無いので（2026-10-31、本人の指摘「Ctrl+N の画面には、いつ表示されたのかの日時を書いて」）、
    hackdeck が初めて見た行に、その DB を書いた時刻（ファイルの更新時刻）を付けて残す。shell/hack.zsh が、DB がこの記録より
    新しくなったあとの最初のプロンプトで呼ぶので、ふつうはその netexec を打った時刻になる。毎回書き直す（更新時刻が今になり、
    zsh が同じ DB の変化で何度も呼ばない）。作り直さずに中身だけ書き換える（同時に書く別のペインとも、鍵で順番になる）"""
    if not home.is_dir():
        return update({}, {})
    with os.fdopen(os.open(home / NXC_SEEN_NAME, os.O_RDWR | os.O_CREAT, 0o600), "r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        kept, hwm = {}, {}
        for line in fh.read().splitlines():
            f = line.split("\t")
            if f[0].startswith("@") and len(f) == 2 and f[1].isdigit():
                hwm[f[0][1:]] = int(f[1])
            elif len(f) == 4 and f[1].isdigit() and f[3].isdigit() and (f[0] not in kept or int(f[1]) < kept[f[0]][0]):
                kept[f[0]] = (int(f[1]), f[2], int(f[3]))
        result = update(kept, hwm)
        fh.seek(0)
        fh.truncate()
        fh.write("".join(f"@{p}\t{n}\n" for p, n in sorted(hwm.items()))
                 + "".join(f"{k}\t{t}\t{p}\t{i}\n" for k, (t, p, i) in kept.items()))
    return result


def nxc_when(t):
    """見つけた日時（netexec の画面の列だけ。足したあとの説明には入れない）。案件のタブの作成日・更新日と同じ形
    （2026-10-31、本人の指摘「案件タブと表示の平仄があっていない。漢字は使わないで」。前は 10/31 16時07分）"""
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"


def nxc_where(c):
    """見つけたホストと権限（netexec の画面の列と、足したあとの説明の（）。2026-10-31、本人の指定「コマンド・見つけたホスト・
    権限（netexec SRV01 管理者）くらいの表示粒度でいい」）。Pwn3d! になったものは全部、強い順（NXC_PWN）に、同じ権限の
    ホストをまとめて出す（同日、本人の指摘「ldap や winrm で Pwn3d! になったとして、強い方だけでなく両方」。前はいちばん
    強いものだけ）。Pwn3d! が無ければ、ログインできた・抜いたホスト（権限は書かない）。ホストは権限ごとに3つまで
    （残りは ほか N）。[(ホスト, 権限)]"""
    hosts_text = lambda hs: "・".join(hs[:3]) + (f" ほか {len(hs) - 3}" if len(hs) > 3 else "")
    if not c["admin"]:
        return [(hosts_text(c["hosts"]), "")]
    rank = lambda p: (list(NXC_PWN).index(p), p) if p in NXC_PWN else (len(NXC_PWN), p)
    return [(hosts_text([h for h, p in c["admin"] if p == proto]), NXC_PWN.get(proto, proto))
            for proto in sorted({p for _, p in c["admin"]}, key=rank)]


def nxc_note(c):
    """説明の（）の中身（netexec SRV01 管理者、WS01 winrm）。: は区切り（user:pass:説明）と読まれるので全角に"""
    groups = [f"{h} {p}".strip() for h, p in nxc_where(c) if h or p]
    return ("netexec " + "、".join(groups) if groups else "netexec").replace(":", "：")


def nxc_desc(c):
    """足すときの説明。範囲のあとの（）に、見つけたコマンド・ホスト・権限（dummy.local（netexec SRV01 管理者））。見つけた
    日時は入れない（2026-10-31、本人の指摘「時刻は Ctrl+N で表示していいが、取り込んだ後はいらない」）"""
    return f"{c['scope']}（{nxc_note(c)}）"


# 足したあとの説明の中の、netexec が書いた（）（nxc_refresh が、いまの DB の中身で書き直す）
NXC_NOTE_RE = re.compile(r"（netexec[^）]*）")


def nxc_refresh(f=None):
    """足したあとの資格情報の説明の（netexec …）を、いまの DB の中身で書き直す（2026-10-31、本人の指摘「説明欄を更新する
    ことで両方描いてほしい」。足したあとで別のホスト・プロトコルでも Pwn3d! になったら、説明にも足す）。触るのは、説明に
    （netexec …）がある行の、その（）だけ（手で書いた説明・ほかの書き足しは残す）。DB の資格情報とユーザー・値が同じ行で、
    範囲も同じものがあればそれ、無ければ最初のもの。shell/hack.zsh が netexec のあとのプロンプトで（nxc-stamp）、資格情報の
    タブが開くたびに呼ぶ。書き直した行の数"""
    f = f or creds_file()
    entries, _ = nxc_entries(manage=False) if f else ([], False)   # 300件から外れた古い資格情報でも、足してあれば書き直す
    if not entries:
        return 0
    by_cred = {}
    for c in entries:
        by_cred.setdefault((c["user"].lower(), c["secret"]), []).append(c)
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    new = {}
    for n, line in enumerate(lines):
        c = parse_cred_line(line)
        if not c or not NXC_NOTE_RE.search(c["desc"]):
            continue
        cands = by_cred.get((c["user"].lower(), c["secret"].lower() if c["kind"] == "nt" else c["secret"]))
        if not cands:
            continue
        e = next((x for x in cands if x["scope"].lower() == cred_host(c).lower()), cands[0])
        fixed = line[:len(line) - len(c["desc"])] + NXC_NOTE_RE.sub(f"（{nxc_note(e)}）", c["desc"], count=1) \
            if line.endswith(c["desc"]) else line
        if fixed != line:
            new[n] = (line, fixed)
    if not new:
        return 0
    # 書く直前に読み直し、その行がまだ同じときだけ置き換える（資格情報のタブで同時に書き換えた行は、そちらを残す）
    lines = f.read_text(encoding="utf-8").splitlines()
    done = 0
    for n, (old, fixed) in new.items():
        if n < len(lines) and lines[n] == old:
            lines[n] = fixed
            done += 1
    if done:
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")   # 前からあるファイルなので 600 のまま
    return done


def nxc_found():
    """netexec の画面に出すもの: 扱う資格情報（nxc_entries。新しいほうから300件）のうち、まだ資格情報のファイルに無いもの
    （並びはそのまま）。戻り値は (資格情報の並び, DB があるか)"""
    entries, has_db = nxc_entries()
    have = {(c["user"].lower(), c["secret"].lower() if c["kind"] == "nt" else c["secret"]) for c in own_creds()}
    return [c for c in entries if (c["user"].lower(), c["secret"]) not in have], has_db


def nxc_merge(srcs, names, doms, times):
    """DB の行（nxc_entries の srcs）を資格情報ごとに1つにまとめる（同じユーザー・値・範囲。見つけた日時は早い方、ホストと
    Pwn3d! は合わせる）。見つけた日時の新しい順（同じ日時なら DB を書いた時刻の新しい順、その中は新しい行から）。
    times: {印: 見つけた時刻}"""
    found = {}
    for proto, _, dom, user, secret, kind, admin, hosts, key, _ in srcs:
        scope, t = nxc_scope(dom, names, doms), times.get(key, 0)
        c = found.setdefault((user.lower(), secret, scope.lower()),
                             {"user": user, "secret": secret, "kind": kind, "scope": scope, "admin": [], "hosts": [],
                              "when": t, "keys": []})
        c["when"] = min(c["when"], t)
        c["keys"].append(key)
        c["admin"] += [(h, proto) for h in admin if (h, proto) not in c["admin"]]   # Pwn3d! のホストと、そのプロトコル
        c["hosts"] += [h for h in hosts if h not in c["hosts"]]
    return sorted(found.values(), key=lambda c: c["when"], reverse=True)


def nxc_entries(manage=True):
    """netexec の画面で扱う資格情報（もう足したものも）。見つけた日時の新しい順に NXC_SHOW 件まで（履歴と同じ300件。
    2026-10-31、本人の指定「見える方も管理する数も300に」）。記録（nxc_seen）に残すのもこの300件の分だけで、それより古いものは
    もう出さない（netexec の DB には残る。hackdeck は netexec の DB を消さない）。記録に無い行のうち、どこまで見たか（hwm）
    より後ろの行と、記録にある行番号で値が変わった行（netexec が新しい値で上書きした）は、新しく見つけた分。
    manage=False: 記録を使わず、DB の全部をまとめて返す（足したあとの説明を書き直すとき。nxc_refresh）。
    戻り値は ([{user, secret, kind, scope, admin, hosts, when, keys}], DB があるか)"""
    home = nxc_home()
    ws = nxc_workspace_dir(home)
    try:
        dbs = sorted(ws.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        dbs = []
    loaded, names, doms = [], set(), set()
    for db in dbs:
        try:
            rows, n, d = nxc_db_rows(db)
            mtime = int(db.stat().st_mtime)
        except (sqlite3.Error, OSError):
            continue
        loaded.append((db.stem, rows, mtime, max((r[0] for r in rows), default=0)))
        names |= n
        doms |= d | {r[1] for r in rows if "." in r[1]}
    srcs = []   # (DB, 行番号, ドメイン, ユーザー, 値, 種類, Pwn3d! のホスト, 見つけたホスト, 印, DB の更新時刻)
    for proto, rows, mtime, _ in loaded:
        for i, dom, user, secret, ctype, admin, hosts in rows:
            if not user or not secret or ctype == "key":
                continue   # 空のパスワード・SSH の鍵は、資格情報のファイルに書けない
            m = NT.match(secret)
            if ctype == "hash" and not m:
                continue   # NT でないハッシュ
            kind, secret = ("nt", m.group(1).lower()) if ctype == "hash" else ("pass", secret)
            k = hashlib.sha1(f"{proto}\0{dom.lower()}\0{user.lower()}\0{secret}".encode()).hexdigest()[:16]
            srcs.append((proto, i, dom, user, secret, kind, admin, hosts, k, mtime))
    if not manage:
        return nxc_merge(srcs, names, doms, {}), bool(loaded)

    def update(kept, hwm):
        for proto, _, _, top in loaded:
            if top < hwm.get(proto, 0):
                hwm[proto] = 0   # DB が作り直された（行番号が始めに戻った）
        at = {(p, i) for _, p, i in kept.values()}
        live, times = [], {}
        for s in srcs:
            proto, i, key, mtime = s[0], s[1], s[8], s[9]
            if key in kept:
                times[key] = kept[key][0]
            elif (proto, i) in at or i > hwm.get(proto, 0):
                times[key] = mtime   # 新しく見つけた行（値が変わった行も）
            else:
                continue   # 300件から外れた古い分
            live.append(s)
        entries = nxc_merge(live, names, doms, times)[:NXC_SHOW]
        keep = {k for c in entries for k in c["keys"]}
        kept.clear()
        kept.update({s[8]: (times[s[8]], s[0], s[1]) for s in live if s[8] in keep})
        for proto, _, _, top in loaded:
            hwm[proto] = max(hwm.get(proto, 0), top)
        return entries
    return nxc_seen(home, update), bool(loaded)


def nxc_key(c):
    """netexec の画面の行を見分ける印（足したあとも、カーソルを同じ位置に合わせるため。値そのものは出さない）"""
    return "nxc:" + hashlib.sha1(f"{c['user']}\0{c['secret']}\0{c['scope']}".encode()).hexdigest()[:12]


def c_nxcrows(query=""):
    """netexec の画面の候補（見つけた日時の新しい順。画面ではいちばん下が新しい）。列は ユーザー・値・範囲・見つけた日時・
    コマンド・見つけたホスト・権限（nxc_where）で、どの列も幅をそろえる（2026-10-31、本人の指摘「ほかのタブと同じく列を揃えて」。
    前は DB の並びのあとに管理者のホストが続き、行ごとにずれていた）。無ければ、なぜ無いかを1行（選んでも何もしない）"""
    rows, has_db = nxc_found()
    if not rows:
        why = "netexec が見つけた分は、全部もう足してある" if has_db else "この案件では、まだ netexec の記録が無い"
        print(f"none\t{why}")
        return
    where = [nxc_where(c) for c in rows]
    sw = min(max(display_width(c["scope"] or "—") for c in rows), 24)
    hw = min(max(display_width(w[0][0] or "—") for w in where), 30)   # 最初のホストの列の幅（権限の列がそろう）
    for c, groups in zip(rows, where):
        secret = f"NT {c['secret']}" if c["kind"] == "nt" else q(c["secret"])
        (hosts, priv), rest = groups[0], groups[1:]
        more = "".join(f"、{h} {p}" for h, p in rest)   # 2つ目からの Pwn3d!（強い順）
        print(f"{nxc_key(c)}\t{fit(c['user'], 15)}  {fit(secret, 36)}  {fit(c['scope'] or '—', sw)}  "
              f"{nxc_when(c['when'])}  netexec  {fit(hosts or '—', hw)}  {priv}{more}".rstrip())
