"""設定（~/.config/hackdeck/settings.json）: 項目の一覧（SETTINGS）と、読み書き・値の取り出し（get）。

設定のタブ（tab_settings.py）は、この一覧から画面を作る。項目を足すときは SETTINGS に1つ足し、使う側で get(キー) を
呼ぶ（tab_settings.py は、新しい種類を足すときだけ触る）。試すときは、環境変数 HACKDECK_<キーの大文字> が設定より勝つ
（例 HACKDECK_CASES_DIR）。"""
import json
import os
import re
from pathlib import Path

from .paths import SETTINGS_FILE, USER_BOOK
from .text import short_home

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Setting:
    """設定の項目。dataclass にしないのは、読み込みに時間がかかる（inspect を引く）ため（hackdeck は fzf から何度も起き直す）"""
    __slots__ = ("key", "label", "kind", "default", "help", "hint")

    def __init__(self, key, label, kind, default, help, hint=""):
        self.key = key          # settings.json のキー
        self.label = label      # 設定のタブに出す名前
        self.kind = kind        # choice（候補から選ぶ）・dir（あるフォルダ）・text（文字）・bool（する・しない）・list（一覧を
                                # 書く）・common（よく使うユーザー・パスワード。中身は paths.COMMON_CREDS）
        self.default = default
        self.help = help        # 何を決めるものか（説明欄に出す）
        self.hint = hint        # 書き方（書く画面の説明欄に出す）


TEMPLATE_URL = "https://github.com/Ch4n24n/Hacking-Op-public.git"   # 雛形の既定（公開のリポジトリ）

SETTINGS = [
    Setting("theme", "配色", "choice", "ocean", "画面の色と雰囲気。選ぶとすぐ変わる"),
    Setting("cases_dir", "案件の置き場所", "dir", "~/cases",
            "案件のフォルダを並べるフォルダ。案件のタブには、この中の（作業フォルダのある）フォルダが出る", "あるフォルダ（~ も使える）"),
    # 既定は、雛形のリポジトリ Hacking-Op-public（番号で持ち主を分けた問題のフォルダ）を HTTPS で clone する。場所の3つの既定も、その
    # 雛形の形（2026-11-02、本人「今は Private のリポジトリを参照してクローンしているけど、Public 版では変えないとね」「template の
    # 考え方と hackdeck を混ぜたのが良くなかった。リポジトリを分けたほうがいい」。SSH は鍵のある本人しか使えないので HTTPS。本人の環境は
    # settings.json に雛形（非公開の Hacking-Op を SSH で）と場所が書いてあるので変わらない）
    Setting("template", "新しい案件の雛形", "text", TEMPLATE_URL,
            "新しい案件を作るときの元。git のリポジトリなら clone し、手元のフォルダなら写す。空なら作業フォルダとログの置き場所だけを作る。"
            "既定は、雛形のリポジトリ Hacking-Op-public（番号で持ち主を分けたフォルダ）",
            "git の URL（git@… https://…）か、手元のフォルダ"),
    Setting("work_dir", "作業フォルダ", "text", "02-作業",
            "案件のフォルダの中で作業する場所（シェルでは ~hack・$HACK_HOME）。新しいペインはここから始まる",
            "案件のフォルダの中の場所（案件のフォルダそのものなら .）"),
    Setting("state_dir", "データの置き場所", "text", "02-作業/.hack",
            "hackdeck が案件ごとに保存するもの（資格情報・環境変数・履歴・メモ・窓の並び・netexec の記録・案件の目印）を入れるフォルダ。"
            "git で追わない場所にする（作業フォルダの中など）", "案件のフォルダからの場所（例 02-作業/.hack）"),
    Setting("log_file", "ログのファイル", "text", "91-ログ/実行ログ.log",
            "コマンドごとに、画面に出たものを残すファイル。空なら残さない", "案件のフォルダの中の場所"),
    Setting("stamps", "コマンドの前後の時刻", "bool", True, "コマンドの前と後に、時刻とかかった秒数を出す（新しく開いたペインから）"),
    Setting("home_cmd", "作業フォルダへ戻るコマンド", "text", "",
            "案件のセッションのシェルで、この名前を打つと作業フォルダへ戻る（新しく開いたペインから）。空なら作らない"
            "（~hack と打って Enter でも戻れる）", "英字・数字・_ -（例 hk）"),
    Setting("books", "自分のコマンド帳", "list", [short_home(USER_BOOK)],
            "ツールに付いているコマンド帳に足して読むフォルダ（中に cheats/*.cheat と opts/*.tsv）。同じ名前の変数と opts は、"
            "下に書いたものが勝つ", "フォルダ（~ も使える）"),
    Setting("key", "窓を開くキー", "text", "C-g",
            "案件のセッションで窓を開くキー（prefix のあとに押しても開く）", "tmux のキーの書き方（C-g が Ctrl+G・M-g が Alt+G・F5 など）"),
    Setting("user_tmux_conf", "~/.tmux.conf を読む", "bool", True,
            "案件のセッションの tmux でも、自分の ~/.tmux.conf（マウス・キー・見た目など）を読む。hackdeck の分（窓のキー・ログ・"
            "並びの保存）はそのあとに足すので、ぶつからない。切ったときは、案件のセッションを全部終えてから効く"),
    Setting("outside", "案件の外も tmux で開く", "bool", False,
            "GNOME Terminal など（VTE の端末）で開いた端末を、はじめから専用の tmux の中（案件の無いセッション）で動かす。窓のキーが、"
            "案件の中と同じく、どのプログラムが動いていても効く（しないときは、zsh のプロンプトでだけ効く）。状態の行・スクロールは"
            " tmux のものになる。新しく開いた端末から（Orca・VS Code・ssh の端末は入れない）"),
    Setting("memo", "メモのタブ", "bool", False,
            "環境と案件のタブの間に、案件ごとの軽いメモのタブを出す（本物の vim で書く。データの置き場所の memo.md に残す）"),
    Setting("env_defaults", "どの案件にも並ぶ環境変数", "list", ["TARGET", "LHOST", "DOMAIN", "KRB5CCNAME", "KRB5_CONFIG"],
            "どの案件の環境のタブにも、はじめから並ぶ名前（シェルで export しても書き戻す）", "名前:説明（説明は省ける）"),
    Setting("common_users", "よく使うユーザー", "common", None, "ユーザーを選ぶ画面に、どの案件でも出す名前",
            "ユーザー:説明（説明は省ける）"),
    Setting("common_passwords", "よく使うパスワード", "common", None, "パスワードを選ぶ画面に、どの案件でも出す値",
            "パスワード:説明（説明は省ける。パスワードに : があるときは最後に : を足す。32桁の16進は NT ハッシュ）"),
]
BY_KEY = {s.key: s for s in SETTINGS}


# settings.json の [更新時刻と大きさ, 中身]。変わったときだけ読み直す（get は1つの画面で何十回も呼ばれ、そのたびに読んでいた）
_LOADED = [None, {}]


def _stamp():
    try:
        st = SETTINGS_FILE.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def load():
    """settings.json の中身（変えないで読むだけ。書くのは save）"""
    stamp = _stamp()
    if stamp is None:
        return {}
    if _LOADED[0] != stamp:
        try:
            d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        _LOADED[:] = [stamp, d if isinstance(d, dict) else {}]
    return _LOADED[1]


def save(**kv):
    d = {**load(), **kv}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _LOADED[:] = [_stamp(), d]   # 同じ時刻の刻みのうちに書き直しても、古い中身を返さないように


# 専用の tmux とシェルに効く項目。tmux の設定は settings.json のとおりに作る（その回だけ変えると、変えたものが tmux に残って
# しまう）ので、一時的には変えられない
SERVER_KEYS = ("stamps", "home_cmd", "key", "user_tmux_conf")


def env_name(key):
    """一時的に上書きする環境変数の名前（一覧の項目と SERVER_KEYS は上書きできないので None）"""
    return None if BY_KEY[key].kind in ("list", "common") or key in SERVER_KEYS else f"HACKDECK_{key.upper()}"


def overridden(key):
    """いま環境変数で上書きされている値（無ければ None）"""
    n = env_name(key)
    return os.environ.get(n) if n else None


def get(key, env_ok=True):
    """設定の値（無ければ既定）。環境変数 HACKDECK_<キー> が勝つ（env_name が None の項目は使えない）。env_ok=False は
    settings.json のまま（専用の tmux の設定を作るとき）"""
    s = BY_KEY[key]
    name = env_name(key) if env_ok else None
    env = os.environ.get(name) if name else None
    if env is not None and s.kind != "list":
        return env not in ("", "0", "false", "no") if s.kind == "bool" else env
    v = load().get(key, s.default)
    if s.kind == "bool":
        return bool(v)
    if s.kind == "list":
        return [str(x) for x in v] if isinstance(v, list) else list(s.default)
    return v if isinstance(v, str) else s.default


def command_kind(name):
    """シェルでその名前がもう何かを指しているか（zsh の whence -w。コマンド・組み込み・予約語など。空なら空いている）"""
    import shutil
    import subprocess
    if shutil.which("zsh"):
        r = subprocess.run(["zsh", "-fc", 'whence -w -- "$1"', "zsh", name], capture_output=True, text=True)
        kind = r.stdout.strip().rpartition(":")[2].strip()
        return "" if kind in ("", "none") else kind
    return shutil.which(name) or ""


def problem(key, value):
    """書こうとしている値の問題（無ければ None）。設定のタブが、保存の前と、打つたびの一言に使う"""
    s, v = BY_KEY[key], value.strip()
    if s.kind == "dir":
        return None if v and Path(v).expanduser().is_dir() else "そのフォルダは無い（先に作る）"
    if key in ("work_dir", "state_dir") and not v:
        return "空にはできない"
    if key in ("work_dir", "state_dir", "log_file") and v:
        if Path(v).is_absolute() or v.startswith("~"):
            return "案件のフォルダからの場所で書く（/ や ~ から始めない）"
        if ".." in Path(v).parts:
            return "案件のフォルダの外は指せない（.. は使えない）"
    if key == "home_cmd" and v:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", v):
            return "英字・数字・_ - で（頭は英字か _）"
        used = command_kind(v)
        if used:
            return f"その名前はもう使われている（{used}）。別の名前にする"
    if key == "key" and not re.match(r"^(?:(?:C|M|S)-)*(?:[A-Za-z0-9]|F[0-9]{1,2}|Space|Enter|Tab|BSpace)$", v):
        return "tmux のキーの書き方で（C-g・M-g・F5 など）"
    if key == "env_defaults":
        n = v.partition(":")[0].strip()
        return None if ENV_NAME_RE.match(n) else "名前:説明 の形で（名前は英字・数字・_）"
    if key == "books" and not v:
        return "空にはできない"
    return None
