"""変数の候補: ユーザー・パスワード・ハッシュと、道具ごとの資格情報の渡し方（認証の形）。"""
import contextlib
import io
import ipaddress
import os
import re
import shlex

from .text import ENV_REF, VAR_RE, display_width, fit, out, q, shell_safe
from .creds import (common_creds, common_user_rows, cred_domain, cred_host, cred_is_local, cred_rows, cred_sorted,
    creds, secret_shown)
from .cand_net import domain_groups
from .cand_files import ccache_principal, list_rows, takes_cred_files
from .ui import out_grouped


def c_users(mode=""):
    """ユーザー（user・target_user・member）。上から よく使うユーザー（いつもの Administrator も）、資格情報（上の「候補の並び」）。
    mode が self なら、いちばん下（最初のカーソル。default_focus）に自分＝組み立てに使う資格情報のユーザー（2026-10-31。AddSelf の
    入れる人・GenericAll や FullControl を付ける先は、ふつう自分）"""
    me = auth_now()[1] if mode == "self" else ""
    out_grouped([("自分", [(me, "いま使う資格情報のユーザー")] if me else []),
                 ("資格情報", cred_rows(creds(), lambda c: c["user"], secret_shown)),
                 ("よく使うユーザー", common_user_rows(fixed=("Administrator",)))])

def c_passwords():
    """撒くパスワード（spray_pass）。資格情報のパスワード（説明つき）と、よく使うパスワード（設定の
    タブで書く）。pw_pass と同じ一覧（2026-10-29、棚卸しの2番で、別に持っていた spray-pass.tsv をやめてそろえた）。
    一覧ファイルの行は出さない（スプレーでは「パスワードの一覧」の枝で選ぶ）"""
    c_secrets_for("pass", lists=False)


def c_hashes():
    """撒く NT ハッシュ（spray_hash）。nt_hash と同じ一覧から、一覧ファイルの行だけ外す（スプレーでは「NT ハッシュの
    一覧」の枝で選ぶ。2026-10-30）"""
    c_secrets_for("nt", lists=False)


# 認証の形（2026-10-29、本人の指摘「資格情報の設定方法によってエントリーが変わるのはおかしい。機能は同じで、
# 資格情報がパスワードかハッシュかチケットかの違いだけ。分岐ができるように作り直す」で追加）。値に
# <pw_user> などを含み、選ぶと続けてその変数を聞く。proto に関係なく同じ一覧（本人の指摘）
AUTH_FORMS = {
    # netexec の1番の形（パスワード・NT ハッシュ・パスワード（Kerberos）・チケット・匿名・guest）は、2026-10-30 に資格情報を
    # 先に選ぶ形（c_authcreds）へ替えた
    # 2番の総当たりの認証のしかた（2026-10-30、本人の指摘「2番は汎用的にブルートフォースで使うからスプレーじゃない。1番と
    # 同じで NTLM・Kerberos・PtH のどれにするかを選ぶ項目を。spray_cred と言うよりも passfile」。前は撒くもの（パスワード
    # 1つ・一覧・NT ハッシュ・その一覧）を選ぶ spray_cred）。ユーザー・パスワード・ハッシュは、どれも一覧のファイルでも、
    # 打った1つでもよい（ファイルの候補の「そのまま使う」）。最初のカーソルは NTLM 認証（画面では下から NTLM・Kerberos・PtH・
    # ローカル）。ローカル認証は1番から外してここへ（2026-10-30、本人の指摘「認証を試すのは2番。認証のしかたに、NTLM と PtH で」）。
    # そのプロトコルで使える形だけを出す（c_authforms）
    "brute": [("-u <userfile> -p <passfile>", "NTLM 認証（パスワード）"),
              ("-u <userfile> -p <passfile> -k", "Kerberos 認証（パスワード）"),
              ("-u <userfile> -H <hashfile>", "PtH（NT ハッシュ）"),
              ("-u <userfile> -p <passfile> --local-auth", "ローカル認証（パスワード）"),
              ("-u <userfile> -H <hashfile> --local-auth", "ローカル認証・PtH（NT ハッシュ）")],
}
KIND_LABEL = {"pass": "パスワード", "nt": "NT ハッシュ"}


def c_authforms(fmt, proto=""):
    """認証の形の候補。1行は「値\\t表示名\\t説明」の3列（画面には表示名と説明だけを出す）。2番の総当たり（brute）は、その
    プロトコルで使える形だけ（ローカル認証は --local-auth のあるプロトコルだけ。ssh・ftp はパスワードだけ）"""
    forms, proto = AUTH_FORMS.get(fmt, []), (proto or "").strip()
    if fmt == "brute" and proto in PLAIN_PROTOS:
        forms = [("-u <userfile> -p <passfile>", "パスワード")]
    elif fmt == "brute" and proto and proto not in LOCAL_AUTH_PROTOS:
        forms = [(v, n) for v, n in forms if "--local-auth" not in v]
    for value, name in forms:
        desc = value
        if value == "--use-kcache":
            cc = os.environ.get("KRB5CCNAME")
            desc = f"{value}（{cc}）" if cc else value   # 空のときの注意は流れの図の下に
        print(f"{value}\t{name}\t{desc}")


def c_users_for(kind):
    """分岐の中のユーザー（pw_user・nt_user）。よく使うユーザー、資格情報（説明にホストと紐づくパスワード・NT ハッシュ）、
    一覧ファイル（netexec のとき）を、見出しで分けて（上の「候補の並び」）。値は shell_safe() 済み（cheats の定義では
    <pw_user> を引用符で囲まずに使う）"""
    if kind not in KIND_LABEL:
        return
    out_grouped([("ユーザーの一覧", list_rows("user")[0] if takes_cred_files() else []),
                 ("資格情報", cred_rows(creds(), lambda c: shell_safe(c["user"]), secret_shown)),
                 ("よく使うユーザー", common_user_rows(shell_safe))])

def c_secrets_for(kind, user="", lists=True):
    """分岐の中のパスワード・NT ハッシュ（pw_pass・nt_hash）。よく使うもの、資格情報（説明にホストと紐づくユーザー）、一覧
    ファイル（netexec で lists のとき）を、見出しで分けて（上の「候補の並び」）。user（選んだユーザー）は、前は並びに使っていた
    （その人の分を先に）。いまは使わない"""
    if kind not in KIND_LABEL:
        return
    label = "よく使うパスワード" if kind == "pass" else "よく使う NT ハッシュ"
    common = {}
    for c in common_creds():   # 同じ値は1行（持ち主・説明を並べる）
        if c["kind"] == kind:
            common.setdefault(c["secret"], []).append("・".join(x for x in (c["user"], c["desc"]) if x))
    common_rows = []
    for secret in sorted(common, key=str.lower, reverse=True):
        notes = "・".join(dict.fromkeys(n for n in common[secret] if n))
        common_rows.append((q(secret) if kind == "pass" else secret, f"{label}（{notes}）" if notes else label))
    out_grouped([(f"{KIND_LABEL[kind]}の一覧",
                  list_rows("pass" if kind == "pass" else "hash")[0] if lists and takes_cred_files() else []),
                 ("資格情報", cred_rows([c for c in creds() if c["kind"] == kind],
                                     lambda c: q(c["secret"]) if kind == "pass" else c["secret"], lambda c: c["user"])),
                 (label, common_rows)])

def imp_id(domain, user):
    if "\\" in user:
        d, u = user.split("\\", 1)
        return f"{d}/{u}"
    if "/" in user or not domain:
        return user
    return f"{domain}/{user}"


def captured_rows(fn, *a):
    """候補を出す関数の出力を [(値, 説明)] に（見出しのまとまりにするため）"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return [tuple(l.split("\t", 1)) if "\t" in l else (l, "") for l in buf.getvalue().splitlines()]


AUTH_GROUPS = ("NTLM 認証・Kerberos 認証（パスワード・ハッシュ）", "Kerberos 認証（チケット）", "匿名")


def auth_kind(value):
    """渡し方の種類（見出し）。パスワード・ハッシュを渡す形は、そのままなら NTLM 認証、末尾に -k で Kerberos 認証（2026-10-30、
    棚卸しの6番で本人の指摘「上はチケットの Kerberos 認証、下は -k を付けるかで NTLM 認証にも Kerberos 認証にもなる」）。
    チケットだけで入る形（-no-pass・--use-kcache・ccache・-k だけ）は Kerberos 認証（チケット）、空のユーザー・guest・-N は匿名"""
    if re.search(r"-u '' |-u 'guest'|(?:^|\s)-N(?:\s|$)", value):
        return "匿名"
    if re.search(r"(?:^|\s)(?:-no-pass|--use-kcache)(?:\s|$)|ccache", value) or value.strip() == "-k":
        return "Kerberos 認証（チケット）"
    return "NTLM 認証・Kerberos 認証（パスワード・ハッシュ）"


def c_auth(fmt, domain="", host=""):
    """道具ごとの資格情報の渡し方を、NTLM 認証・Kerberos 認証・匿名の見出しで分けて（2026-10-30、棚卸しの5番で本人の指摘
    「見出しは、資格情報・決まった形ではなく、NTLM 認証か Kerberos 認証かの違い」）"""
    # 説明の列（範囲）の幅は、資格情報の行とチケットの行でそろえる（本人の指摘「説明が揃っていない」）
    hw = max([display_width(cred_host(c)) for c in creds()] + [display_width(domain or ""), 1])
    rows = captured_rows(auth_from_creds, fmt, domain, host, hw) + captured_rows(auth_fixed, fmt, domain, host, hw)
    out_grouped([(k, [r for r in rows if auth_kind(r[0]) == k]) for k in AUTH_GROUPS])


def auth_from_creds(fmt, domain, host, hw=1):
    """資格情報から作る渡し方。ユーザー・パスワードの候補と同じく、ホストごと・その中で名前の A→Z（画面では上から）、説明は
    ホストと残りの説明の列（2026-10-30、棚卸しの3番で本人の指摘「1番とそろえて」。前はファイルに書いた順・説明はユーザー（説明））"""
    rows = cred_sorted(creds())
    for c in reversed(rows):   # 下から上へ並ぶ画面なので逆に出す
        u, s, nt = c["user"], c["secret"], c["kind"] == "nt"
        note = c["desc"].strip()[len(cred_host(c)):].strip() or ("NT ハッシュ" if nt else "パスワード")
        lab = f"{fit(cred_host(c) or '—', hw)}  {note}"
        if fmt in ("nxc", "winrm"):
            out(f"-u {q(u)} -H {q(s)}" if nt else f"-u {q(u)} -p {q(s)}", lab)
        elif fmt == "certipy":
            dom = cred_host(c) if "." in cred_host(c) else domain   # certipy はドメインのアカウントだけ
            un = u if ("@" in u or not dom) else f"{u}@{dom}"
            out(f"-u {q(un)} -hashes :{s}" if nt else f"-u {q(un)} -p {q(s)}", lab)
        elif fmt == "bh":
            out(f"-u {q(u)} --hashes :{s}" if nt else f"-u {q(u)} -p {q(s)}", lab)


def auth_fixed(fmt, domain, host, hw=1):
    """Kerberos と定番（ユーザーごとの行は名前の A→Z。画面では上から）。Kerberos の行の説明に、いまの KRB5CCNAME を
    （netexec の認証の形の「チケット」と同じ。空なら「KRB5CCNAME が空」）"""
    cc = os.environ.get("KRB5CCNAME")
    # 説明は資格情報の行と同じ列（範囲・残り）に。チケットはドメインのもの。空のときの注意は流れの図の下に
    tk = f"{fit(domain or '—', hw)}  （Kerberos のチケット{'・' + cc if cc else ''}）"
    none = f"{fit('—', hw)}  "
    # Kerberos はドメインのアカウントだけ（範囲が端末名だけのユーザー＝ローカルのアカウントは出さない）
    rows = [c for c in cred_sorted(creds()) if "." in cred_host(c) or not cred_host(c)]
    if fmt == "nxc":
        for c in reversed(rows):
            if c["kind"] == "pass":
                out(f"-u {q(c['user'])} -p {q(c['secret'])} -k", f"{c['user']}（Kerberos で）")
        out("-u '' -p ''", none + "（null セッション）")
        out("-u 'guest' -p ''", none + "（guest）")
        out("--use-kcache", tk)
    elif fmt == "certipy":
        out("-k -no-pass", tk)


# 資格情報を先に選ぶ形（2026-10-30、棚卸しの1番の作り直し。本人の案「プロトコル → 資格情報 → 認証のしかた → オプション」に、
# 私の案「チケット・匿名は資格情報の画面に置き、認証のしかたは使えるものだけ」を本人が OK。案のページ
# https://claude.ai/artifact/Tybq2ZJCRAzW85S9EJxsa7 。3・4番の evil-winrm も同じ画面にして1つにした）。netexec 1.5.1 の
# ソースで、--use-kcache は -u・-p が要らない、-k はパスワードにもハッシュにも付く、--local-auth は smb・winrm・mssql・rdp・wmi
# だけ（mssql では SQL Server のログイン）を確かめた。
# 2026-10-31、impacket の実行系（psexec・wmiexec など）・impacket-smbclient・mssqlclient・smbclient・xfreerdp・bloodyAD・
# dacledit・owneredit・GetUserSPNs も、この形にそろえた（本人の指摘「新しく足したコマンドは質が低い。組み立てるときに不要な
# オプションを聞かれる（psexec・mssqlclient）」。前は hackdeck auth が、先に聞いたドメインで組を1行ずつ並べていて、資格情報が
# 範囲（ドメイン・端末）を持っているのにドメインを聞き、mssqlclient は Windows 認証にするかも別に聞いていた）。行き先は資格情報
# より先に聞く（evil-winrm・secretsdump と同じ）
LOCAL_AUTH_PROTOS = {"smb", "winrm", "mssql", "rdp", "wmi"}
PLAIN_PROTOS = {"ssh", "ftp", "vnc", "nfs"}   # 認証のしかたの違いが無い（パスワードの資格情報だけを出す）
# コマンド選びの図に出す枝（候補はその場で作るので、形だけ）。資格情報のあと続けて聞く変数（値の中の <…>）。
# netexec の1番は認証のしかた（nxc_how）、impacket 実行系・impn・bloodyAD は NTLM/Kerberos（krb_how。-k を付けるか）、
# mssql は Windows 認証/SQL のログイン（mssql_how）。netexec の1番・winrm・secretsdump だけ、KRB5CCNAME のチケットを事前の
# 行として出す（本人のノートにある形。それ以外のでっち上げの事前チケット行は 2026-10-31 に削除。関連メモリ
# bulk-transform-verbatim-then-verify）
AUTHCREDS_SHAPE = {"nxc": [("資格情報", ["nxc_how"]), ("チケット", []), ("匿名・guest", [])],
                   "winrm": [("資格情報", []), ("チケット", ["realm"])],
                   "dump": [("資格情報", []), ("チケット", ["dc_fqdn"])],
                   "imp": [("資格情報", ["krb_how"])],
                   "mssql": [("資格情報", ["mssql_how"])],
                   "impn": [("資格情報", ["krb_how"])],
                   "bloody": [("資格情報", ["krb_how"])],
                   "smb": [("資格情報", []), ("匿名", [])],
                   "e4l": [("資格情報", []), ("チケット", ["dc_fqdn"]), ("NULL セッション", [])]}
# 候補のコマンドの2つ目の引数（行き先）が入る変数。打った user:pass を渡し方にするとき（c_typed）、この名前で値を読む。netexec は
# プロトコル
AUTHCREDS_TARGET = {"nxc": "proto", "dump": "dc", "imp": "host", "mssql": "host", "impn": "dc", "bloody": "dc", "e4l": "host"}
AUTHCREDS_DOMAIN_ONLY = {"impn", "bloody"}   # DC の LDAP に入る道具。端末の範囲（ローカル）の資格情報は出さない
TICKET_ROW = {"nxc", "winrm", "dump", "e4l"}   # KRB5CCNAME のチケットを事前の行として出す道具（本人のノートにある形だけ）


def authcred_value(fmt, target, c):
    """資格情報1つを、その道具の渡し方に。(値, 画面に出す形)。target は行き先（AUTHCREDS_TARGET の変数の値。netexec は
    プロトコル）。ドメインは資格情報の範囲（説明の頭）か、無ければ $DOMAIN（cred_domain。端末の範囲ならその端末＝ローカルの
    アカウント）。値の中の <nxc_how>・<domain> は続けて聞く"""
    u, s, nt = c["user"], c["secret"], c["kind"] == "nt"
    dom = cred_domain(c, os.environ.get("DOMAIN", ""))
    if fmt in ("dump", "imp"):
        # impacket の ドメイン/名前:パスワード@行き先（secretsdump は本人の例 Administrator:'Password123'@IP・
        # -hashes ':NT' 'ドメイン/administrator@IP'）。imp（psexec など）は続けて NTLM/Kerberos を選ぶ（<krb_how>。-k を付けるか）
        i = shell_safe(imp_id(dom, u))
        base = f"-hashes :{s} {i}@{target}" if nt else f"{i}:{q(s)}@{target}"
        return (f"{base} <krb_how>", base) if fmt == "imp" else (base, base)
    if fmt == "mssql":
        # 続けて Windows 認証か SQL のログインかを選ぶ（<mssql_how>）。ドメインの前置は、実ドメインの範囲の資格情報だけ
        # （sa のような SQL のログインには付けない。端末名の範囲も付けない）
        dom2 = cred_host(c) if "." in cred_host(c) else ""
        i = shell_safe(f"{dom2}/{u}" if dom2 else u)
        base = f"-hashes :{s} {i}@{target}" if nt else f"{i}:{q(s)}@{target}"
        return f"{base} <mssql_how>", base
    if fmt == "impn":   # 名乗りだけ（GetUserSPNs・dacledit・owneredit。行き先はコマンドの -dc-ip）。続けて NTLM/Kerberos（<krb_how>）
        i = shell_safe(imp_id(dom or "<domain>", u))
        base = f"{i} -hashes :{s}" if nt else f"{i}:{q(s)}"
        return f"{base} <krb_how>", base
    if fmt == "bloody":   # 本人の例 -u … -p … -d ドメイン --host 行き先。NT ハッシュは -p ':NT'（bloodyAD の --help）。
        cred = f"-u {q(u)} -p {q(':' + s) if nt else q(s)} -d {dom or '<domain>'}"   # 続けて NTLM/Kerberos（<krb_how>）
        return f"{cred} --host {target} <krb_how>", cred
    if fmt == "smb":   # smbclient の -U ドメイン/名前%パスワード（smbclient --help の形）。NT ハッシュは --pw-nt-hash
        i = f"{dom}/{u}" if dom and "\\" not in u and "/" not in u else u
        v = f"--pw-nt-hash -U {q(i + '%' + s)}" if nt else f"-U {q(i + '%' + s)}"
        return v, v
    if fmt == "e4l":   # enum4linux-ng（本人の例 -A $TARGET -u 'ドメイン\名前' -p '…'）。行き先が先。パスワードだけ（-H はノートに無い）
        i = f"{dom}\\{u}" if dom and "\\" not in u and "/" not in u else u
        v = f"{target} -u {q(i)} -p {q(s)}"
        return v, v
    if fmt == "rdp":   # ドメインのアカウントは /d: を付ける（端末の範囲は付けない）。NT ハッシュは /pth:
        v = f"/u:{q(u)} " + (f"/pth:{s}" if nt else f"/p:{q(s)}") + ("" if cred_is_local(c) or not dom else f" /d:{dom}")
        return v, v
    base = f"-u {q(u)} -H {q(s)}" if nt else f"-u {q(u)} -p {q(s)}"
    if fmt == "winrm":
        return base, base   # 行き先はコマンドの -i <host> で先に聞く（2026-10-30、本人の指摘「host → creds だろ」）
    if target in PLAIN_PROTOS:
        return base, base
    if cred_is_local(c) and target in LOCAL_AUTH_PROTOS:
        return f"{base} --local-auth", f"{base} --local-auth"   # ローカル認証しか無いので、認証のしかたは聞かない
    return f"{base} <nxc_how>", base


def by_address(h):
    """行き先が IP か環境変数（$TARGET）か。チケット（Kerberos）は名前（FQDN）で入るので、そのときは名前を続けて聞く"""
    try:
        return bool(ENV_REF.match(h)) or bool(ipaddress.ip_address(h))
    except ValueError:
        return False


def ticket_value(fmt, target):
    """KRB5CCNAME のチケットで入る形（事前の行として出すのは本人のノートにある道具だけ＝netexec・evil-winrm・secretsdump。
    2026-10-31、でっち上げの事前チケット行を削除）。secretsdump の名乗りはチケットの持ち主（DC01$ のように資格情報のタブに
    無いことが多い。読めなければ書かず、impacket がチケットから取る）。行き先が IP か環境変数なら、IP は -dc-ip に回して名前
    （FQDN）を続けて聞く（本人の例 -k -no-pass -dc-ip IP 'レルム/DC01$'@名前）"""
    if fmt == "winrm":
        return "-r <realm>"
    if fmt == "e4l":   # 本人の例 -A -K $KRB5CCNAME 名前。行き先が IP か環境変数なら、名前（FQDN）を続けて聞く
        return f"-K $KRB5CCNAME {'<dc_fqdn>' if by_address(target) else target}"
    if fmt == "dump":
        p = ccache_principal(os.environ.get("KRB5CCNAME", ""))
        at = f"{shell_safe(p[0] + '/' + p[1])}@" if p else ""
        return f"-k -no-pass -dc-ip {target} {at}<dc_fqdn>" if by_address(target) else f"-k -no-pass {at}{target}"
    return "--use-kcache"


def c_authcreds(fmt, target=""):
    """資格情報を先に選ぶ画面の候補。資格情報のタブの組み合わせを全部、範囲ごと（ドメインが上）に、その道具の渡し方で。続けて
    チケット（KRB5CCNAME）・匿名の形。target は行き先（AUTHCREDS_TARGET の変数の値。netexec はプロトコル）。netexec はチケット・
    匿名を選んだら認証のしかた（nxc_how）を聞かない。ldap・AUTHCREDS_DOMAIN_ONLY は端末の資格情報を出さず、ssh・ftp はパスワードの
    資格情報だけ。xfreerdp はチケットの形が無い。1行は「値\\t画面に出す形\\t説明」"""
    target = (target or "").strip()
    rows = cred_sorted(creds())
    if fmt == "nxc" and target in PLAIN_PROTOS:
        rows = [c for c in rows if c["kind"] == "pass"]
    if (fmt == "nxc" and target == "ldap") or fmt in AUTHCREDS_DOMAIN_ONLY:
        rows = [c for c in rows if not cred_is_local(c)]
    if fmt == "e4l":   # enum4linux-ng はパスワードだけ（本人のノートに -H の形が無い）
        rows = [c for c in rows if c["kind"] == "pass"]
    domain, cc = os.environ.get("DOMAIN", ""), os.environ.get("KRB5CCNAME")
    # チケットの行の範囲。secretsdump は名乗りがチケットの持ち主なので、そのレルム（$DOMAIN と違う箱のチケットのことがある）
    realm = (ccache_principal(cc or "") or (domain,))[0] if fmt == "dump" else domain
    hw = max([display_width(cred_host(c)) for c in rows] + [display_width(realm), 1])
    tk = f"{fit(realm or '—', hw)}  （Kerberos のチケット{'・' + cc if cc else ''}）"   # 空のときの注意は流れの図の下に
    none = f"{fit('—', hw)}  "
    cred_lines = []
    for c in reversed(rows):   # 下から上へ並ぶ画面なので逆に出す
        value, shown = authcred_value(fmt, target, c)
        note = c["desc"].strip()[len(cred_host(c)):].strip() or ("NT ハッシュ" if c["kind"] == "nt" else "パスワード")
        if fmt == "rdp" and c["kind"] == "nt":
            note += "・相手に Restricted Admin が要る"
        cred_lines.append((value, f"{shown}\t{fit(cred_host(c) or '—', hw)}  {note}"))
    if fmt == "nxc" and target in PLAIN_PROTOS:
        out_grouped([("パスワード", cred_lines)])
        return
    if fmt == "nxc":
        out_grouped([("パスワード・ハッシュ（このあと認証のしかたを選ぶ）", cred_lines),
                     ("Kerberos 認証（チケット）", [("--use-kcache", f"--use-kcache\t{tk}")]),
                     ("匿名", [("-u 'guest' -p ''", f"-u 'guest' -p ''\t{none}（guest）"),
                              ("-u '' -p ''", f"-u '' -p ''\t{none}（null セッション）")])])
        return
    label = ("パスワード・ハッシュ（このあと認証のしかたを選ぶ）" if fmt in ("imp", "impn", "mssql", "bloody")
             else "パスワード" if fmt == "e4l" else "パスワード・ハッシュ")
    groups = [(label, cred_lines)]
    if fmt in TICKET_ROW:   # 本人のノートにある形だけ事前のチケット行を出す（winrm・dump）
        tv = ticket_value(fmt, target)
        groups.append(("Kerberos 認証（チケット）", [(tv, f"{tv}\t{tk}")]))
    if fmt == "smb":
        groups.append(("匿名", [("-N", f"-N\t{none}（パスワードを聞かない）")]))
    if fmt == "e4l":   # 資格情報を付けない（本人の例 -A $TARGET）
        groups.append(("NULL セッション", [(target, f"{target}\t{none}（資格情報なし）")]))
    out_grouped(groups)


def c_authhow(fmt, proto=""):
    """資格情報を選んだあとの、認証のしかた。netexec の1番（nxc）と impacket 実行系・impn・bloodyAD（krb）は NTLM/Kerberos
    （-k を付けるか）。mssql は Windows 認証（-windows-auth）か SQL のログイン（何も足さない）か。最初のカーソルは default_focus が
    決める（nxc・krb は NTLM、mssql は資格情報の形から）。値が空の形は、組み上げるときに前の空白ごと外す（drop_empty）"""
    if fmt == "mssql":
        rows = [("-windows-auth", "Windows 認証", "-windows-auth", "AD のアカウント・PtH（NTLM/Kerberos）"),
                ("", "SQL のログイン", "（何も足さない）", "SQL Server のユーザー（sa など）")]
    else:
        rows = [("", "NTLM 認証", "（何も足さない）", "ドメインのアカウントとして入る"),
                ("-k", "Kerberos 認証", "-k", "KRB5CCNAME のチケット（無ければパスワード・ハッシュで取得）。行き先は名前(FQDN)で")]
    fw = max(display_width(f) for _, _, f, _ in rows)
    for value, name, flag, desc in rows:
        print(f"{value}\t{name}\t{fit(flag, fw)}  {desc}")


def auth_identity(value):
    """資格情報の値（auth_… の値）から (ドメイン, ユーザー) を取る。-u・-d（bloodyAD）、-U（smbclient）、/u:・/d:（xfreerdp）、
    impacket の ドメイン/名前。名前の無いチケットの形は KRB5CCNAME の持ち主。取れないものは空"""
    try:
        toks = shlex.split(value)
    except ValueError:
        return "", ""
    dom = user = ""
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if t == "-u":
            user = nxt
        elif t == "-d":
            dom = nxt
        elif t == "-U":
            d, _, user = nxt.split("%", 1)[0].replace("\\", "/").rpartition("/")
            dom = d or dom
        elif t.startswith("/u:"):
            user = t[3:]
        elif t.startswith("/d:"):
            dom = t[3:]
    if not user:
        for t in toks:   # impacket の ドメイン/名前[:パスワード][@行き先]（-hashes の値・$TARGET には / が無い）
            if not t.startswith(("-", "$")) and "/" in t:
                d, _, user = t.rsplit("@", 1)[0].split(":", 1)[0].rpartition("/")
                dom = dom or d
                break
    if not user and any(t in ("-k", "--use-kcache") or t.startswith("--use-krb5-ccache") for t in toks):
        p = ccache_principal(os.environ.get("KRB5CCNAME", ""))
        if p:
            dom, user = dom or p[0].lower(), p[1]
    return dom, user


def auth_now(values=None):
    """組み立て中のコマンドで決めた資格情報（auth_… の変数）の (ドメイン, ユーザー)。候補のコマンドには、決めた値が環境変数で来る
    （values を渡さなければ os.environ）。値の中の <変数>（<domain> など）も、決めた値で埋めてから読む"""
    values = os.environ if values is None else values
    for k, v in values.items():
        if k.startswith("auth_") and v:
            dom, user = auth_identity(VAR_RE.sub(lambda m: values.get(m.group(1), m.group(0)), v))
            if dom or user:
                return dom, user
    return "", ""


def dn_of(domain):
    """corp.htb → DC=corp,DC=htb"""
    return "DC=" + ",DC=".join(domain.split("."))


def c_domaindn():
    """ドメインの DN（domain_dn）。組み立てに使う資格情報のドメインを、いちばん下（最初のカーソル）に。続けて $DOMAIN・/etc/hosts
    のドメインから（2026-10-31。前はドメインを聞いてから作っていた。資格情報がドメインを持っているので聞かない）"""
    me = auth_now()[0]
    groups = [("資格情報のドメイン", [(me, "いま使う資格情報")] if "." in me else [])] + domain_groups()
    out_grouped([(t, [(dn_of(v), f"{v}  {d}".rstrip()) for v, d in rows]) for t, rows in groups])


# dacledit・owneredit の対象（2026-10-31）。名前か DN かを別に聞かず、値の形で -target・-target-dn・-target-sid を決める
# （本人の指摘「不要なオプションを聞かれる」。前の dacledit は DN 決め打ちで、案件の OU（OU=ADCS）が候補に入っていた）
def adtarget_value(mode, text):
    """対象の値をオプションに。DN（= がある）は -target-dn、SID は -target-sid、ほかは名前の -target。dacledit（mode=dacl）の
    DN は OU・コンテナーなので -inheritance も付ける（中のオブジェクトにも継承する。adminCount=1 のものは除かれる）"""
    if re.match(r"(?i)S-1-\d", text):
        return f"-target-sid {q(text)}"
    if "=" in text:
        return f"-target-dn {q(text)}" + (" -inheritance" if mode == "dacl" else "")
    return f"-target {q(text)}"


def c_adtarget(mode=""):
    """dacledit・owneredit の対象の候補。ユーザー（資格情報・よく使うユーザー）と、ドメインの DN（ドメイン全体・Users・
    Computers）。OU やグループは打つ（BloodHound の名前か distinguishedname を貼る。打った値の形で決まる。c_typed）。1行は
    「値\\t画面に出す名前\\t説明」"""
    def conv(rows):
        return [(adtarget_value(mode, v), f"{v}\t{d}") for v, d in rows]
    dom = auth_now()[0]
    dom = dom if "." in dom else os.environ.get("DOMAIN", "")
    dns = [(dn_of(dom), "ドメイン全体"), (f"CN=Users,{dn_of(dom)}", "Users コンテナー"),
           (f"CN=Computers,{dn_of(dom)}", "Computers コンテナー")] if dom else []
    out_grouped([("資格情報", conv(cred_rows(creds(), lambda c: c["user"], secret_shown))),
                 ("よく使うユーザー", conv(common_user_rows(fixed=("Administrator",)))),
                 ("ドメインの DN", conv(dns))])
