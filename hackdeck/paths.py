"""hackdeck が読み書きする場所（ツールの置き場所と、XDG の設定・データ・状態・キャッシュ）。

案件の中の場所（作業フォルダ・データの置き場所・ログ）は、設定で決まるので case.py にある。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # ツールの置き場所（bin・hackdeck・cheats・opts・shell）
BUILTIN_BOOK = ROOT                             # ツールに付いているコマンド帳（cheats/*.cheat・opts/*.tsv）
SHELL_DIR = ROOT / "shell"                      # 案件のセッションのシェルに入れるもの（zsh）


def _xdg(var, *default):
    return Path(os.environ.get(var) or Path.home().joinpath(*default)) / "hackdeck"


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config")      # 設定・秘密・自分のコマンド帳
DATA_DIR = _xdg("XDG_DATA_HOME", ".local", "share")  # 案件をまたぐデータ
STATE_DIR = _xdg("XDG_STATE_HOME", ".local", "state")
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache")         # 消しても作り直せるもの

SETTINGS_FILE = CONFIG_DIR / "settings.json"
WPSCAN_TOKEN = CONFIG_DIR / "wpscan-api-token"       # wpscan のコマンドが読む（600）
USER_BOOK = CONFIG_DIR                               # 自分のコマンド帳の既定の置き場所（cheats/・opts/）

COMMON_CREDS = DATA_DIR / "common"   # よく使うユーザー（名前:）・パスワード（:値）。設定のタブで書く
COMMON_LISTS = DATA_DIR              # 案件をまたぐ一覧ファイル（common.user など。シェルでは ~cmn）

CASE_LAST = STATE_DIR / "last"           # 直前に入った案件（名前と目印。case.last_case）
AUTOSAVE_STAMP = STATE_DIR / "autosave"  # 並びを自動で残した時刻（hackdeck case autosave）

NAV_DIR = CACHE_DIR / "nav"              # 閉じたときの画面の列（案件ごと）
COPY_STATE = CACHE_DIR / "copy-state"    # 資格情報の画面で最後にコピーした行と欄（Ctrl+Y の2回目）
RUN_DIR = CACHE_DIR / "run"              # 窓ごとの作業の置き場所（run/<窓のプロセスの番号>/。ui.work_dir。閉じたら消す）
MAGIC_CACHE = CACHE_DIR / "magic.json"   # ファイルの候補の file -b の結果（場所・大きさ・更新時刻ごと。直前に出した場所の分だけ）
TMUX_CONF = CACHE_DIR / "tmux.conf"      # 専用の tmux サーバーの設定（設定から毎回作る）
ZDOTDIR = CACHE_DIR / "zsh"              # 案件のセッションの zsh が最初に読む場所（.zshenv だけ）
SHELL_CONF = ZDOTDIR / "settings"         # 案件のシェルが、プロンプトのたびに見る設定（時刻・戻るコマンド。shell/hack.zsh）
RESURRECT_DIR = DATA_DIR / "resurrect"   # ~/.tmux.conf の tmux-resurrect が、ふだんの保存を上書きしないための置き場所
