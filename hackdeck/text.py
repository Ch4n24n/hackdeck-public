"""文字の扱い（見た目の幅・切り詰め・引用符・候補の1行の出し方・クリップボード）。どのモジュールにも頼らない。
fzf から何度も起き直す補助（fzfcall）も読むので、読み込むものは少なく（クリップボードの subprocess などは、使うときに読む）。"""
import os
import re
import shlex
import unicodedata


IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
NT = re.compile(r"^(?:[0-9a-fA-F]{32}:)?([0-9a-fA-F]{32})$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def out(value, label=""):
    print(f"{value}\t{label}" if label else value)


def q(s):
    """必ず単引用符で囲む（ログで見る打ち方に合わせる。中の ' は閉じて逃がす）"""
    return "'" + s.replace("'", "'\\''") + "'"


LMNT = re.compile(r"[0-9a-fA-F]{32}:[0-9a-fA-F]{32}")


def fit_values(head, vals, w):
    """一覧の説明「head: 値・値・…）」を、見た目の幅 w に入るだけの値で作る（入りきらない値があれば最後に …）"""
    best = f"{head}）"
    for k in range(1, len(vals) + 1):
        cand = f"{head}: {'・'.join(vals[:k])}{'…' if k < len(vals) else ''}）"
        if display_width(cand) > w:
            break
        best = cand
    return best


def fit_desc(desc, w):
    """候補の説明を見た目の幅 w に。値を「・」で並べて ）で閉じる説明（一覧の中身など）は、入る値まで残して …） で閉じる。
    ほかは fit と同じく … で切る"""
    if display_width(desc) <= w:
        return desc
    if desc.endswith("）") and "・" in desc:
        parts = desc[:-1].split("・")
        for k in range(len(parts) - 1, 0, -1):
            cand = "・".join(parts[:k]) + "…）"
            if display_width(cand) <= w:
                return cand
    return fit(desc, w).rstrip()


ENV_REF = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$")


def shell_safe(value):
    """打った値をコマンドに埋め込んでも安全な形にする。
    $TARGET のような環境変数参照はそのまま（クォートすると展開されなくなる）、
    それ以外でスペースや記号（; | & など）を含むなら単引用符で囲む（shlex.quote、必要なときだけ付く）"""
    if not value or ENV_REF.match(value):
        return value
    return shlex.quote(value)


def path_safe(value):
    """ファイルのパスを、空白や記号があるときだけ囲む（shell_safe のパス版）。~hack/・~cmn/・~/ の頭は囲みの外に出す（囲むと
    展開されない。2026-10-30、本人の画面で '~cmn' と囲まれていた）。もう囲んである値（list_arg の ~hack/'名前' など）はそのまま"""
    if not value or ENV_REF.match(value):
        return value
    try:
        if ("'" in value or '"' in value) and len(shlex.split(value)) == 1:
            return value
    except ValueError:
        pass
    if value.startswith("~"):
        head, sep, rest = value.partition("/")
        return head + sep + shell_safe(rest) if rest else value
    return shell_safe(value)


# --- コマンド帳の読み込み ----------------------------------------------------

VAR_RE = re.compile(r"<([A-Za-z0-9_]+)>")
DOLLAR_RE = re.compile(r"(?<!\$)\$(?!\()([a-z][a-z0-9_]*)\b")


def clip(s, w):
    """見た目の幅 w を超えるときだけ「…」で切る（fit と違って右を空白で埋めない）"""
    return s if display_width(s) <= w else fit(s, w).rstrip()


def display_width(s):
    """端末上の見た目の幅（全角は2、それ以外は1）。
    曖昧幅（東アジアの実装によって半角・全角どちらにもなりうる "→" "…" のような文字）は
    半角で数える。全角扱い（"WFA"）にしていたところ、作者の実機ではこれらの文字が実際には
    半角で描画され、その文字を含む行だけコメント列が実際の見た目より1文字分広く計算されて、
    後ろのコマンド列が1文字分左にズレて見えた（2026-10-28、「ズレているのはコマンド列」との
    指摘で実機確認して特定）。
    英数字だけなら文字数のまま。ほかも、全角（W・F）の字は U+1100 より後にしか無いので、そこから後の字だけ調べる（打つたびに
    何百回も呼ばれるので。2026-11-01）"""
    if s.isascii():
        return len(s)
    return len(s) + sum(1 for c in s if c > "\u10ff" and unicodedata.east_asian_width(c) in "WF")


def fit(s, w):
    """見た目の幅 w に収める。元は Python の文字数（len）で切っていたため、全角の日本語は
    実際の半分の文字数で打ち切られ、説明文が不要に短く省略されていた（2026-10-28、本人の指摘）"""
    s = s.replace("\n", " ").replace("\t", " ")
    width = display_width(s)
    if width <= w:
        return s + " " * (w - width)
    ellipsis_w = display_width("…")
    out, cur = "", 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if cur + cw + ellipsis_w > w:  # 次の文字 + 省略記号で w を超えるなら打ち切り
            break
        out += c
        cur += cw
    return out + "…" + " " * max(0, w - cur - ellipsis_w)


def term_cols():
    """端末の見た目の幅。shutil.get_terminal_size() は環境変数 COLUMNS・LINES が
    セットされていればそれを優先する仕様（Python 公式ドキュメント）。tmux の
    prefix+C-g（display-popup）経由で開いたとき、元のペインの古い幅が COLUMNS に
    残っている場合、popup 自体の幅より広い値を拾ってしまい、タグ・コメント列が
    実際の表示幅に対して広すぎてコマンド列が右に押し出される、という不具合が
    実機で報告された（2026-10-28、「tmux上で開くとコマンドが右によりすぎている。
    PJT外で実行した場合と見た目を揃えてほしい」との指摘）。os.get_terminal_size()
    は環境変数を見ず、実際の tty から直接幅を取るので、こちらを使う"""
    # Ctrl+G（zsh）からは標準出力がシェルへのパイプなので、標準エラー・標準入力・/dev/tty の順に端末を探す
    for fd in (2, 0, 1):
        try:
            return os.get_terminal_size(fd).columns
        except OSError:
            pass
    try:
        with open("/dev/tty") as t:
            return os.get_terminal_size(t.fileno()).columns
    except OSError:
        return 100


def copy_text(text):
    """クリップボードへ。Wayland は wl-copy、それ以外は xclip"""
    import shutil
    import subprocess
    cmd = ["wl-copy"] if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") \
        else ["xclip", "-selection", "clipboard"]
    try:
        subprocess.run(cmd, input=text, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def short_home(p):
    home = os.path.expanduser("~")
    return "~" + str(p)[len(home):] if str(p).startswith(home + "/") else str(p)
