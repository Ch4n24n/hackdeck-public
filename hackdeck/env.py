"""案件の環境変数（案件のデータの env。1行に export 名前=値）と、シェルで export・unset した名前の書き戻し。

書くのは環境のタブとシェル（shell/hack.zsh の precmd が env-capture を呼ぶ）。読むのは shell/hack.zsh（コマンドを打つたびに
読み直す）と、窓（候補の $TARGET など）。どれも案件のセッションの中だけ。"""
import fcntl
import os
import re
import shlex
import time

from .text import out
from . import settings
from .case import keep_out_of_git, state_file


# 環境のタブでは書かない名前（ファイルから消えたときに zsh が unset するので、シェルや案件のセッションが壊れる名前は入れさせない。
# shell/hack.zsh の _hack_env_reload も同じ名前を外す）
ENV_RESERVED = {"PATH", "HOME", "SHELL", "USER", "LOGNAME", "TERM", "PWD", "OLDPWD", "LANG", "ZDOTDIR",
                "TMUX", "TMUX_PANE", "NXC_PATH"}


def env_reserved(name):
    return name in ENV_RESERVED or name.startswith("HACK_")
ENV_LINE = re.compile(r"^export ([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ENV_ADD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # 名前だけ（= なし）で、書き戻す名前に足す（本人の指摘）


def env_defaults_items():
    """既定の環境変数 [(名前, 説明)]。設定のタブで変える（設定の env_defaults に 名前 か 名前:説明。2026-10-30、本人の指摘
    「既定値はすべて設定画面で設定できるように」）"""
    out = []
    for it in settings.get("env_defaults"):
        n, _, d = str(it).partition(":")
        if ENV_NAME_RE.match(n.strip()):
            out.append((n.strip(), d.strip()))
    return out


def env_defaults():
    return [n for n, _ in env_defaults_items()]


def env_parse(text):
    """環境のタブで打った文字を (名前, 値, 説明) に分ける。値・説明は無ければ None。名前:値:説明（2026-10-30、本人の案。
    値に : があれば、最後の : の後ろが説明）・名前:値・名前=値・名前だけ。形が違えば None"""
    text = text.strip()
    m = ENV_ADD_RE.match(text)
    if m:
        return m.group(1), m.group(2).strip(), None
    name, sep, rest = text.partition(":")
    if not ENV_NAME_RE.match(name):
        return None
    if not sep:
        return name, None, None
    val, sep2, desc = rest.rpartition(":") if ":" in rest else (rest, "", None)
    return name, (val.strip() or None), (desc.strip() if sep2 else None)


def env_file():
    """いまの案件の環境変数のファイル（案件の外は None）"""
    return state_file("env")


def env_vars(f=None):
    """[(名前, 値)]（ファイルの順。同じ名前が2行あれば、source と同じく後ろの値）"""
    f = f or env_file()
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f else []
    except OSError:
        return []
    vals = {}
    for line in lines:
        m = ENV_LINE.match(line)
        if m:
            try:
                vals[m.group(1)] = (shlex.split(m.group(2)) or [""])[0]
            except ValueError:
                vals[m.group(1)] = m.group(2)
    return list(vals.items())


def env_names_file():
    """いまの案件の、書き戻す名前のファイル（案件の外は None）。2026-10-30、本人の指摘「使う環境変数は案件ごとに違う。必ず
    記録するものは既定でいいが、サーバー名などは案件ごとに」"""
    return state_file("env-names")


def env_name_lines():
    """いまの案件の名前のファイルの {名前: 説明}（1行に 名前 か 名前:説明。既定の名前の説明もここに書ける）"""
    f = env_names_file()
    try:
        text = f.read_text(encoding="utf-8") if f else ""
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        n, _, d = line.partition(":")
        n = n.strip()
        if ENV_NAME_RE.match(n):
            out[n] = d.strip()
    return out


def env_extra_names():
    return [n for n in env_name_lines() if n not in env_defaults()]


def env_keep():
    """シェルの export で書き戻す名前: 既定の名前（どの案件でも）＋案件の名前（env-names）＋もう値のある名前"""
    return list(dict.fromkeys([*env_defaults(), *env_extra_names(), *(n for n, _ in env_vars())]))


def env_keep_write(names, descs=None):
    """この場所の名前を書く（既定の名前は、説明があるときだけ書く）。descs: {名前: 説明}（無ければ前のまま）"""
    descs = {**env_name_lines(), **(descs or {})}
    keep = [n for n in dict.fromkeys([*names, *(n for n in descs if n in env_defaults() and descs[n])])]
    f = env_names_file()
    if not f:
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(f"{n}:{descs[n]}\n" if descs.get(n) else f"{n}\n" for n in keep), encoding="utf-8")


def env_update(ops, f=None):
    """環境変数のファイル（既定は env_file()）を書き換える。ops: [(名前, 値)]、値が None なら消す。前からある名前は同じ行の
    位置で、新しい名前は末尾に。ファイル自身に鍵（flock）をかけてから読み・書きし、ファイルは作り直さずに中身だけ書き換える
    （ほかのペインのシェルが、同時に書き戻しても混ざらない）"""
    f = f or env_file()
    if not f:
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    new = not f.exists()
    fd = os.open(f, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    return False
                time.sleep(0.05)
        data = b""
        while chunk := os.read(fd, 65536):
            data += chunk
        out, pos = [], {}
        for line in data.decode("utf-8", errors="replace").splitlines():
            m = ENV_LINE.match(line)
            if m and m.group(1) in pos:
                out[pos[m.group(1)]] = line   # 同じ名前の2行目（後ろの値が効いていた）は、1行目の位置へ
                continue
            if m:
                pos[m.group(1)] = len(out)
            out.append(line)
        for name, val in ops:
            line = None if val is None else f"export {name}={shlex.quote(val)}"
            if name in pos:
                out[pos[name]] = line
            elif line is not None:
                pos[name] = len(out)
                out.append(line)
        text = "".join(l + "\n" for l in out if l is not None).encode("utf-8")
        if text != data:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, text)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    if new:
        keep_out_of_git(f)
    return True


def c_envcapture(args):
    """シェルで export・unset した変数を、環境変数のファイルに書き戻す（shell/hack.zsh の precmd から呼ばれる）。引数は
    「set 名前 値」「unset 名前 ''」の3つ組の並び。set は書き戻す名前（env_keep）だけ、unset は名前に関係なく効かせる
    （書き戻す名前から外した変数も、unset で片づけられるように）"""
    keep, ops = set(env_keep()), []
    for i in range(0, len(args) - 2, 3):
        op, name, val = args[i:i + 3]
        if env_reserved(name) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if op == "set" and name in keep:
            ops.append((name, val))
        elif op == "unset":
            ops.append((name, None))
    if ops:
        env_update(ops)
