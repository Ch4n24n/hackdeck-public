"""変数の候補: ホスト・ドメイン・DC・URL・自分の IP・インターフェース・ネットワーク。"""
import ipaddress
import os
import re
import subprocess
from pathlib import Path

from .text import IPV4, out
from .ui import out_grouped


# 自分側の値。対象のホストの候補には出さない
NOT_HOST_VARS = {"LHOST", "LPORT"}


def etc_hosts():
    """/etc/hosts の (名前, IP)。下に足したものほど新しいので、下から順に返す。HACKDECK_ETC_HOSTS があれば、そのファイルを
    読む（README の画面を撮るときに、手元の /etc/hosts＝解いている箱の名前が写らないように。2026-11-02。publish/shots.py）"""
    pairs, seen = [], set()
    try:
        lines = Path(os.environ.get("HACKDECK_ETC_HOSTS") or "/etc/hosts").read_text(errors="replace").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        line = line.split("#", 1)[0].split()
        if len(line) < 2 or not IPV4.match(line[0]) or line[0].startswith("127."):
            continue
        for name in line[1:]:
            if name not in seen:
                seen.add(name)
                pairs.append((name, line[0]))
    return pairs


def ifaces():
    """(名前, IP, ネットワーク)。tun を先に出す（HTB の VPN）"""
    try:
        txt = subprocess.run(["ip", "-o", "-4", "addr", "show"], capture_output=True, text=True).stdout
    except OSError:
        return []
    rows = []
    for line in txt.splitlines():
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\S+)", line)
        # docker・lxc などの仮想の口は LHOST にならないので出さない
        if m and m.group(1) != "lo" and not m.group(1).startswith(("docker", "br-", "lxcbr", "veth", "virbr")):
            itf = ipaddress.ip_interface(m.group(2))
            rows.append((m.group(1), str(itf.ip), str(itf.network)))
    return sorted(rows, key=lambda r: (not r[0].startswith("tun"), r[0]))


def env_hosts():
    """IP が入っている環境変数。TARGET を先に"""
    names = [n for n, v in os.environ.items() if IPV4.match(v) and n not in NOT_HOST_VARS]
    return sorted(names, key=lambda n: (n != "TARGET", n))


# --- 候補 -------------------------------------------------------------------

def c_connect():
    """ピボットでつなぎ返す先（ligolo の agent・相手に落とす wget・送り返す FileUpload）。相手の上に貼るので値で入れる。
    ダブルピボットもあるので、手元のインターフェース（ネットワーク）ではなく、環境変数の値と /etc/hosts の値（IP）を出す
    （2026-10-30、本人の指摘「ネットワーク全体や特定の環境変数ではなく、環境変数と /etc/hosts の値を」）。LHOST（つなぎ返す定番）を
    先に、/etc/hosts は IP で重複を外す"""
    env, seen_env = [], set()
    if IPV4.match(os.environ.get("LHOST", "")):   # env_hosts は LHOST を外すが、つなぎ返す先では定番なので先頭に
        env.append((os.environ["LHOST"], "$LHOST"))
        seen_env.add(os.environ["LHOST"])
    for n in env_hosts():
        if os.environ[n] not in seen_env:
            seen_env.add(os.environ[n])
            env.append((os.environ[n], f"${n}"))
    seen, etc = set(), []
    for name, ip in etc_hosts():
        if ip not in seen:
            seen.add(ip)
            etc.append((ip, name))
    # 自分の tun の IP も（2026-10-31、本人の指摘「ligolo-agent に自分の IP（tun0）も」。$LHOST と同じ値でも出す。どこから来た値かが
    # 見えるように。ほかの口（eth0・wlan0）は相手から届かないので出さない）
    tun = list(dict.fromkeys((ip, name) for name, ip, _ in ifaces() if name.startswith("tun")))
    out_grouped([("環境変数", env), ("自分の IP", tun), ("/etc/hosts", etc)])


def c_hosts():
    # 環境変数は $名前 のまま入れる（打つときに展開される。ログもいつもの打ち方になる）
    groups = [("環境変数", [(f"${n}", os.environ[n]) for n in env_hosts()]),
              ("/etc/hosts", [(name, ip) for name, ip in etc_hosts() if "." in name])]
    if tpl_uses_netexec():
        groups.append(("まとめて", hosts_bulk()))
    out_grouped(groups)


def tpl_uses_netexec():
    """組み立てているコマンドに netexec があるか（行き先を範囲や複数のホストで取れる。HACKDECK_TPL）"""
    return bool(re.search(r"(?:^|\s)(?:netexec|nxc)\s", os.environ.get("HACKDECK_TPL", "")))


def tun_routes():
    """tun の口を通る経路の範囲 [(範囲, 口)]（VPN の向こうの箱がいる範囲。tun 自身の範囲は、VPN の利用者の範囲のことが
    あるので入れない）"""
    try:
        txt = subprocess.run(["ip", "-o", "-4", "route", "show"], capture_output=True, text=True).stdout
    except OSError:
        return []
    rows = []
    for line in txt.splitlines():
        f = line.split()
        dev = f[f.index("dev") + 1] if "dev" in f[:-1] else ""
        if f and f[0] != "default" and "via" in f and dev.startswith("tun") and (f[0], dev) not in rows:
            rows.append((f[0], dev))
    return rows


def hosts_bulk():
    """netexec の行き先にまとめて入れる行（2026-10-30、本人の指摘「tun0 のネットワーク全体、/etc/hosts に書かれたドメインの
    ホスト全体を指定できたら」）。tun を通る範囲と、/etc/hosts にある、いまのドメイン（DOMAIN）のホスト全部（同じ IP は1つ。
    2台以上のとき。1台なら下の /etc/hosts の行と同じ）"""
    rows = [(net, f"{dev} を通る範囲") for net, dev in tun_routes()]
    dom = os.environ.get("DOMAIN", "").lower().strip(".")
    if dom:
        names, ips = [], set()
        for name, ip in reversed(etc_hosts()):   # /etc/hosts の上から
            if name.lower().endswith("." + dom) and ip not in ips:
                ips.add(ip)
                names.append(name)
        if len(names) >= 2:
            rows.append((" ".join(names), f"/etc/hosts の {dom} のホスト全部（{len(names)}台）"))
    return rows


def c_urls():
    """URL の候補（http://名前）。IP の入っている環境変数（$名前 のまま）と、/etc/hosts の名前。続きのパスは打つ（Tab でこの行を
    検索欄に入れてから足せる）"""
    out_grouped([("環境変数", [(f"http://${n}", os.environ[n]) for n in env_hosts()]),
                 ("/etc/hosts", [(f"http://{name}", ip) for name, ip in etc_hosts() if "." in name])])


def c_dcs():
    """DC（と DNS サーバー）の候補。IP の入った環境変数（DC・DC01 のような名前を先に）と /etc/hosts の名前。まとめての行は出さない"""
    names = sorted(env_hosts(), key=lambda n: (not n.upper().startswith("DC"), n != "TARGET", n))
    out_grouped([("環境変数", [(f"${n}", os.environ[n]) for n in names]),
                 ("/etc/hosts", [(name, ip) for name, ip in etc_hosts() if "." in name])])


def c_hostips():
    """/etc/hosts に足す行の IP。IP の入っている環境変数（$名前 のまま。打つときに展開される）。行は "…" で囲まない（打った名前に
    空白があると '…' で囲まれ、echo が空白でつないで1行にする。"…" の中だと ' がそのまま書き込まれる）"""
    out_grouped([("環境変数", [(f"${n}", os.environ[n]) for n in env_hosts()])])


def c_hostnames():
    """/etc/hosts に足す行の名前。ドメイン名（DC の行に足す）を出す。ほかは打つ（例 dc01.test.local test.local dc01）"""
    dom = os.environ.get("DOMAIN", "")
    out_grouped([("ドメイン", [(dom, "ドメイン名（DC の行に足す）")] if dom else [])])


def c_fqdns():
    for name, ip in etc_hosts():
        if "." in name:
            out(name, ip)


def c_domains():
    out_grouped(domain_groups())


def domain_groups():
    """ドメインの候補のまとまり（$DOMAIN・/etc/hosts）。ドメインの DN（c_domaindn）も同じものから作る"""
    seen, env_rows, host_rows = set(), [], []
    if os.environ.get("DOMAIN"):
        seen.add(os.environ["DOMAIN"])
        env_rows.append((os.environ["DOMAIN"], "$DOMAIN"))
    seen = set()   # /etc/hosts の分は、$DOMAIN と同じでも出す（2026-10-30、本人の指摘「<domain> は /etc/hosts も探したほうがいい」。
    # 同じだと出していなかったので、/etc/hosts を見ていないように見えた）
    for name, _ in etc_hosts():
        parts = name.split(".")
        dom = ".".join(parts[1:]) if len(parts) >= 3 else name if len(parts) == 2 else ""
        if dom and dom not in seen:
            seen.add(dom)
            host_rows.append((dom, ""))
    return [("環境変数", env_rows), ("/etc/hosts", host_rows)]


def c_lhost():
    # 相手側に貼ることがあるので、$LHOST ではなく値を入れる
    seen, env_rows, if_rows = set(), [], []
    if IPV4.match(os.environ.get("LHOST", "")):
        seen.add(os.environ["LHOST"])
        env_rows.append((os.environ["LHOST"], "$LHOST"))
    for name, ip, _ in ifaces():
        if ip not in seen:
            seen.add(ip)
            if_rows.append((ip, name))
    out_grouped([("環境変数", env_rows), ("ネットワーク", if_rows)])


def c_ifaces():
    for name, ip, _ in ifaces():
        out(name, ip)


def c_cidrs():
    seen = []
    for n in env_hosts():
        seen.append((str(ipaddress.ip_network(os.environ[n] + "/24", strict=False)), f"${n} の /24"))
    for name, _, net in ifaces():
        seen.append((net, name))
    done = set()
    for net, label in seen:
        if net not in done:
            done.add(net)
            out(net, label)
