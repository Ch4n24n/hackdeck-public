"""配色（テーマ）と、画面で使う色・飾り。色は apply_theme で差し替わるので、ほかのモジュールは theme.C_TAG のように属性で読む。

選んだテーマは設定の theme（settings.py）。テーマを足すときは THEMES と THEME_ORDER に1つ足す。"""
import os
import subprocess

from .text import display_width, term_cols
from . import settings


def _fg(hex6):
    """#rrggbb の24bit前景色（SGR）。実機で確認済み: --ansi で埋め込んだこの色は、
    fzf の --color=fg+:... を指定しても選択行で上書きされない（fg+ は「色指定の無い
    部分」にだけ効く。2026-10-28、printf+fzf の最小再現で確認）"""
    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    return f"\x1b[38;2;{r};{g};{b}m"


# 配色のテーマ。3つのまとまり（GROUPS）: 端末の背景のまま色だけ変えるもの（はじめの4つ ocean・amber・rose・coral は
# 2026-10-28 に本人に見せて選んだもの）、背景ごと変えて雰囲気を変えるもの、ハッカーらしいもの（2026-10-31、本人の指摘「飽きない
# ように配色をたくさん。色が違うパターン、そもそもの雰囲気が違うパターン、ハッカーっぽいパターン」）。
# 色は16進（# なし）: tag 見出し・comment 説明・snippet コマンドの本文・hint 薄い字・selbg 選んでいる行の背景・vars 変数の6色。
# bg・fg・border があるものは、背景・地の文字・線も変える（窓の背景と枠も。tmux の display-popup の -s・-S）。selfg は選んでいる
# 行の文字の色（無ければ snippet）。形も変えるもの（2026-11-01、本人の指摘「他のテーマと全く異なる系のやつを何パターンも」）:
# frame 枠の線（fzf の rounded・sharp・bold・double・line）・popup 窓の枠の線（tmux の single・rounded・double・heavy・simple・
# padded）・pointer 選んでいる行の印・prompt 入力欄の頭・icon 見出しの印・separator 一覧と入力欄の間の線・ascii 罫線を使わない
# （fzf の --no-unicode）。無いものは既定（rounded・single・▌・> ・◆・─）。一覧の形も変えるもの（2026-11-01、本人の指摘
# 「今までのテーマとは特色が違う形のテーマを複数」）: fullline 選んでいる行の帯を行の端まで（fzf の --highlight-line）・altbg
# 1行おきの地の色（縞。fullline も付く）・gutter 一覧の左端の列の字（fzf の既定は ▌）・gutterfg その色・scrollbar スクロール
# バーの字・casecur・caseon 案件のタブの丸の色（いま入っている・動いている。既定は緑とオレンジ）。どの色も、
# 背景（無いものは暗い端末の #1e1e1e）との明るさの比（WCAG のコントラスト比）が、本文 7・見出しと変数 4.5・薄い字 3 以上
# （縞の地の上でも。tests/themes.py で確かめる）
GROUPS = [(1, "端末の背景のまま（色違い）"), (2, "背景ごと変える（雰囲気）"), (3, "ハッカー"), (4, "形も変える（枠・印・入力欄まで）"),
          (5, "和（京の色）"), (6, "身の回りの物（黒板・ノート・付箋・液晶…）"), (7, "見やすさ（くっきり・色の見分け）")]
THEMES = {
    # --- 端末の背景のまま（色違い）
    "ocean": {"group": 1, "label": "Ocean Blue（navi 由来の青・シアン）", "tag": "56d4dd", "comment": "6e9fff", "snippet": "e6edf3", "hint": "626a77", "selbg": "17222d",
             "vars": ["56d4dd", "6e9fff", "b490f0", "5fd68a", "e3c567", "f0a35f"]},
    "amber": {"group": 1, "label": "Amber（オレンジ中心）", "tag": "ff9e64", "comment": "ffc799", "snippet": "f2e5d8", "hint": "8a7265", "selbg": "2e2016",
             "vars": ["ff9e64", "ff6f91", "ffcf6b", "ff8a5c", "e8927c", "ffab91"]},
    "rose": {"group": 1, "label": "Rose（ピンク中心）", "tag": "ff6fa3", "comment": "ffa3c4", "snippet": "fbe4ee", "hint": "8a6478", "selbg": "33202b",
            "vars": ["ff6fa3", "c792ea", "ff8fc4", "a67ad4", "ff5c8a", "e0a3ff"]},
    "coral": {"group": 1, "label": "Coral Red（赤中心）", "tag": "ff6b6b", "comment": "ffa08a", "snippet": "fbe6e2", "hint": "8a6868", "selbg": "332122",
             "vars": ["ff6b6b", "ffb86c", "ff8787", "ffa94d", "ff5252", "ff9f43"]},
    "emerald": {"group": 1, "label": "Emerald（緑と青緑）", "tag": "3ddc84", "comment": "7ee8a8", "snippet": "e6f5ec", "hint": "6f8a78", "selbg": "14261c",
               "vars": ["3ddc84", "9be564", "4fd1c5", "b5e48c", "e9c46a", "7ad7f0"]},
    "violet": {"group": 1, "label": "Violet（紫とピンク）", "tag": "b388ff", "comment": "d0b3ff", "snippet": "efe8ff", "hint": "837898", "selbg": "231a33",
              "vars": ["b388ff", "ff79c6", "8be9fd", "d0b3ff", "f1fa8c", "82aaff"]},
    "sky": {"group": 1, "label": "Sky（明るい水色）", "tag": "7dd3fc", "comment": "a5b4fc", "snippet": "eef6ff", "hint": "7a8699", "selbg": "16222e",
           "vars": ["7dd3fc", "a5b4fc", "67e8f9", "93c5fd", "fde68a", "c4b5fd"]},
    "citrus": {"group": 1, "label": "Citrus（黄色とライム）", "tag": "d9f99d", "comment": "fde047", "snippet": "fbfbe6", "hint": "8a8a6c", "selbg": "262614",
              "vars": ["d9f99d", "fde047", "fb923c", "a3e635", "facc15", "fdba74"]},
    "sakura": {"group": 1, "label": "Sakura（桜色と白）", "tag": "ffb7c5", "comment": "ffd6e0", "snippet": "fff5f7", "hint": "9c7f87", "selbg": "2e1f24",
              "vars": ["ffb7c5", "f9a8d4", "c4b5fd", "fbcfe8", "fde68a", "a7f3d0"]},
    "mono": {"group": 1, "label": "Mono（白と灰色だけ）", "tag": "e0e0e0", "comment": "b0b0b0", "snippet": "f5f5f5", "hint": "7d7d7d", "selbg": "2a2a2a",
            "vars": ["ffffff", "d4d4d4", "a3a3a3", "e5e5e5", "bdbdbd", "cfcfcf"]},
    # --- 背景ごと変える（雰囲気）
    "midnight": {"group": 2, "label": "Midnight（深い紺の夜）", "bg": "0b1021", "fg": "c8d3f5", "border": "2f3b66", "tag": "7aa2f7", "comment": "89ddff", "snippet": "e4ecff", "hint": "6c77a8", "selbg": "1b2445",
                "vars": ["7aa2f7", "bb9af7", "7dcfff", "9ece6a", "e0af68", "ff9e64"]},
    "nord": {"group": 2, "label": "Nord（北欧の霜の青）", "bg": "2e3440", "fg": "d8dee9", "border": "4c566a", "tag": "88c0d0", "comment": "81a1c1", "snippet": "eceff4", "hint": "8a95ab", "selbg": "3b4252",
            "vars": ["88c0d0", "81a1c1", "c4a0bd", "a3be8c", "ebcb8b", "dc9a85"]},
    "dracula": {"group": 2, "label": "Dracula（紫の闇）", "bg": "282a36", "fg": "f8f8f2", "border": "44475a", "tag": "8be9fd", "comment": "bd93f9", "snippet": "f8f8f2", "hint": "8790bd", "selbg": "44475a",
               "vars": ["8be9fd", "ff79c6", "bd93f9", "50fa7b", "f1fa8c", "ffb86c"]},
    "gruvbox": {"group": 2, "label": "Gruvbox（古い端末の暖かい色）", "bg": "282828", "fg": "ebdbb2", "border": "504945", "tag": "fabd2f", "comment": "83a598", "snippet": "fbf1c7", "hint": "a89984", "selbg": "3c3836",
               "vars": ["fabd2f", "fe8019", "83a598", "b8bb26", "d3869b", "8ec07c"]},
    "solarized": {"group": 2, "label": "Solarized（深い青緑の地）", "bg": "002b36", "fg": "b2c1c1", "border": "0f4a57", "tag": "35b5aa", "comment": "4fa3e0", "snippet": "eee8d5", "hint": "7b939b", "selbg": "073642",
                 "vars": ["35b5aa", "4fa3e0", "8b8fe0", "9db000", "c9a000", "e8774c"]},
    "tokyo": {"group": 2, "label": "Tokyo Night（夜の街の青と紫）", "bg": "1a1b26", "fg": "c0caf5", "border": "3b4261", "tag": "7dcfff", "comment": "7aa2f7", "snippet": "c0caf5", "hint": "737ca8", "selbg": "283457",
             "vars": ["7dcfff", "bb9af7", "7aa2f7", "9ece6a", "e0af68", "f7768e"]},
    "mocha": {"group": 2, "label": "Mocha（やわらかいパステル）", "bg": "1e1e2e", "fg": "cdd6f4", "border": "45475a", "tag": "89dceb", "comment": "cba6f7", "snippet": "cdd6f4", "hint": "8b90a8", "selbg": "313244",
             "vars": ["89dceb", "f5c2e7", "cba6f7", "a6e3a1", "f9e2af", "fab387"]},
    "forest": {"group": 2, "label": "Forest（深い森の緑）", "bg": "18231c", "fg": "cfe3d4", "border": "34503b", "tag": "8fd19e", "comment": "a3c4a8", "snippet": "e8f3ea", "hint": "7a9a82", "selbg": "243529",
              "vars": ["8fd19e", "d4b36a", "7fb8c9", "c3e88d", "e6a26e", "b9a3d6"]},
    "desert": {"group": 2, "label": "Desert（夕暮れの砂漠）", "bg": "2a211b", "fg": "ecdcc6", "border": "5a4636", "tag": "f2a65a", "comment": "e5c07b", "snippet": "f7ecdc", "hint": "a8937e", "selbg": "3a2e25",
              "vars": ["f2a65a", "e5c07b", "e08a7a", "a7c080", "7fb4ca", "c9a0dc"]},
    "paper": {"group": 2, "label": "Paper（明るい紙。白い背景）", "bg": "f6f1e7", "fg": "3b3a36", "border": "c9bea8", "tag": "0c5f79", "comment": "8a4b08", "snippet": "1f1f1c", "hint": "7a7568", "selbg": "e6dcc8",
             "vars": ["0c5f79", "a3366e", "5b4fbf", "3a7d1f", "8a5c00", "b8410c"]},
    # --- ハッカー
    "matrix": {"group": 3, "label": "Matrix（黒地に緑の文字）", "bg": "000000", "fg": "00ff41", "border": "0b4a1c", "tag": "00ff41", "comment": "00c234", "snippet": "c8ffd4", "hint": "0f8f33", "selbg": "03200f",
              "vars": ["00ff41", "7dff9e", "00d4a0", "b6ff00", "39ff14", "9cffcb"]},
    "phosphor": {"group": 3, "label": "Phosphor（緑の燐光の CRT）", "bg": "07120a", "fg": "33ff66", "border": "1d4d2b", "tag": "66ff99", "comment": "33cc66", "snippet": "ccffdd", "hint": "2f8f50", "selbg": "0f2a17",
                "vars": ["66ff99", "33ff66", "99ffbb", "22dd88", "ccff66", "66ffcc"]},
    "amberterm": {"group": 3, "label": "Amber Terminal（琥珀色の古い端末）", "bg": "120c02", "fg": "ffb000", "border": "4d3508", "tag": "ffcc33", "comment": "ffa000", "snippet": "ffe0a0", "hint": "a27300", "selbg": "2a1d05",
                 "vars": ["ffcc33", "ffb000", "ffd966", "ff9900", "ffe680", "ffbb55"]},
    "redteam": {"group": 3, "label": "Red Team（黒地に赤。攻める側）", "bg": "0d0000", "fg": "ffd6d6", "border": "5a1616", "tag": "ff3b3b", "comment": "ff7a7a", "snippet": "ffe9e9", "hint": "a35c5c", "selbg": "2a0a0a",
               "vars": ["ff3b3b", "ff8a5c", "ff5c8a", "ffb347", "ff6b6b", "e05a9b"]},
    "blueteam": {"group": 3, "label": "Blue Team（黒地に青。守る側）", "bg": "020b16", "fg": "cfe8ff", "border": "16385c", "tag": "38bdf8", "comment": "60a5fa", "snippet": "e6f3ff", "hint": "5a7a99", "selbg": "0b2036",
                "vars": ["38bdf8", "60a5fa", "22d3ee", "818cf8", "a5f3fc", "93c5fd"]},
    "cyberpunk": {"group": 3, "label": "Cyberpunk（ネオンの黄・青・赤）", "bg": "0d0221", "fg": "e0e0ff", "border": "3d1f73", "tag": "fcee0c", "comment": "00f0ff", "snippet": "f5f5ff", "hint": "8070b0", "selbg": "26104a",
                 "vars": ["fcee0c", "00f0ff", "ff2a6d", "05ffa1", "ff9f1c", "b967ff"]},
    "synthwave": {"group": 3, "label": "Synthwave（80年代のネオン）", "bg": "241b2f", "fg": "f0e3ff", "border": "4a3a6a", "tag": "ff7edb", "comment": "36f9f6", "snippet": "fff0fb", "hint": "9a8ab5", "selbg": "34294f",
                 "vars": ["ff7edb", "36f9f6", "fede5d", "72f1b8", "fe6f7a", "c9a3e0"]},
    "tron": {"group": 3, "label": "Tron（黒地に光る水色）", "bg": "000814", "fg": "cfeeff", "border": "004466", "tag": "00e5ff", "comment": "7df9ff", "snippet": "e0fbff", "hint": "4a7f99", "selbg": "001a2c",
            "vars": ["00e5ff", "7df9ff", "ff9e00", "00ffa3", "ffe600", "ff3df5"]},
    "ghost": {"group": 3, "label": "Ghost（黒と銀。目立たない）", "bg": "0e0e10", "fg": "c7c7cc", "border": "2c2c32", "tag": "f5f5f7", "comment": "9a9aa2", "snippet": "ffffff", "hint": "6e6e78", "selbg": "1c1c20",
             "vars": ["f5f5f7", "c7c7cc", "a1a1aa", "e4e4e7", "d4d4d8", "b8b8c0"]},
    # --- 形も変える（枠・印・入力欄まで）
    "blueprint": {"group": 4, "label": "Blueprint（設計図。青地に白い細線）", "bg": "0b2a5b", "fg": "e8f1ff", "border": "9fc2ff", "tag": "7fdbff", "comment": "bcd6ff", "snippet": "ffffff", "hint": "8aa6d6", "selbg": "1d4b8f",
                 "vars": ["7fdbff", "ffd166", "ff9fb8", "8ce99a", "d0b8f0", "ffffff"],
                 "frame": "sharp", "popup": "single", "pointer": "▸", "prompt": "▸ ", "icon": "■", "separator": "┄"},
    "dos": {"group": 4, "label": "DOS（青地に黄。二重線の昔の画面）", "bg": "0000a8", "fg": "ffffff", "border": "55ffff", "tag": "ffff55", "comment": "55ffff", "snippet": "ffffff", "hint": "b8b8ff", "selbg": "00a8a8", "selfg": "000000",
           "vars": ["ffff55", "55ffff", "ff77ff", "55ff55", "ffffff", "ffaa55"],
           "frame": "double", "popup": "double", "pointer": "►", "prompt": "C:\\> ", "icon": "■", "separator": "═"},
    "brutal": {"group": 4, "label": "Brutal（白地に黒の太線と赤）", "bg": "ffffff", "fg": "000000", "border": "000000", "tag": "c00000", "comment": "000000", "snippet": "000000", "hint": "555555", "selbg": "ffe600", "selfg": "000000",
              "vars": ["c00000", "0047ab", "006b35", "6b2f94", "9a4a00", "000000"],
              "frame": "bold", "popup": "heavy", "pointer": "▶", "prompt": "→ ", "icon": "▶", "separator": "━"},
    "minimal": {"group": 4, "label": "Minimal（線を減らした静かな画面）", "tag": "9ccfd8", "comment": "c4c4c4", "snippet": "eeeeee", "hint": "7a7a7a", "selbg": "262626",
               "vars": ["9ccfd8", "c4a7e7", "f6c177", "a3d9a5", "eb9fb0", "cfcfcf"],
               "frame": "line", "popup": "padded", "pointer": "›", "prompt": "› ", "icon": "·", "separator": " "},
    "teletype": {"group": 4, "label": "Teletype（罫線を使わない ASCII の端末）", "bg": "101010", "fg": "d8d8d8", "border": "8a8a8a", "tag": "ffffff", "comment": "b8b8b8", "snippet": "ffffff", "hint": "8a8a8a", "selbg": "2e2e2e",
                "vars": ["ffffff", "d0d0d0", "b0b0b0", "e8e8e8", "c0c0c0", "a8a8a8"],
                "frame": "sharp", "popup": "simple", "pointer": ">", "prompt": "$ ", "icon": "#", "separator": "-", "ascii": True},
    "neon": {"group": 4, "label": "Neon（黒地に太いネオンの線）", "bg": "080808", "fg": "f0f0f0", "border": "ff2bd6", "tag": "ff2bd6", "comment": "00e5ff", "snippet": "ffffff", "hint": "8a8a9a", "selbg": "2a0a2a",
            "vars": ["ff2bd6", "00e5ff", "c6ff00", "ffea00", "ff7a00", "a58bff"],
            "frame": "bold", "popup": "heavy", "pointer": "➤", "prompt": "❯ ", "icon": "◆", "separator": "━"},
    "document": {"group": 4, "label": "Document（書類。紙に二重線）", "bg": "f4f1ea", "fg": "2b2b2b", "border": "8c8577", "tag": "1f4e79", "comment": "6b4f2a", "snippet": "111111", "hint": "707070", "selbg": "e3ddd0",
                "vars": ["1f4e79", "8b1e3f", "2e6b30", "6a3d9a", "8a5200", "00636b"],
                "frame": "double", "popup": "double", "pointer": "▸", "prompt": "» ", "icon": "§", "separator": "═"},
    # --- 和（京の色）
    "kyo": {"group": 5, "label": "京紫（紫と金。雅）", "bg": "1d1428", "fg": "ede4f2", "border": "5a3d78", "tag": "c9a0dc", "comment": "e8c37a", "snippet": "f7f0fa", "hint": "9a8aa8", "selbg": "33224a",
           "vars": ["c9a0dc", "e8c37a", "e8a0b4", "a8d8b9", "f2a07b", "b4c7e7"],
           "frame": "double", "popup": "double", "pointer": "◆", "prompt": "› ", "icon": "◆", "separator": "─"},
    "sumi": {"group": 5, "label": "墨と朱（書の黒に朱の印）", "bg": "1a1a1a", "fg": "e8e4dc", "border": "4a4640", "tag": "f06a4f", "comment": "c8b88a", "snippet": "f4f0e6", "hint": "8a857a", "selbg": "2c2a28",
            "vars": ["f06a4f", "d4a24c", "7fa8a0", "c97c8e", "a8b56b", "b3a6d6"],
            "frame": "sharp", "popup": "single", "pointer": "▸", "prompt": "› ", "icon": "■", "separator": "─"},
    "matcha": {"group": 5, "label": "抹茶（生成りの紙に抹茶と茶）", "bg": "f3efe2", "fg": "3d3a2e", "border": "b8af93", "tag": "465f21", "comment": "7a5a24", "snippet": "1f1d16", "hint": "6f6956", "selbg": "e2dcc6",
              "vars": ["465f21", "9a4a2a", "3a6688", "82406f", "7d6417", "2a6457"],
              "frame": "rounded", "popup": "rounded", "pointer": "●", "prompt": "› ", "icon": "●", "separator": "─"},
    "ai": {"group": 5, "label": "藍染（藍の地に白と金茶）", "bg": "0f1f3a", "fg": "e6edf7", "border": "34507f", "tag": "9cc3e6", "comment": "f0e6d2", "snippet": "ffffff", "hint": "7f93b3", "selbg": "1d3358",
          "vars": ["9cc3e6", "f2c35b", "e88a8a", "9fd3b8", "d8b4e2", "f0e6d2"],
          "frame": "sharp", "popup": "double", "pointer": "▶", "prompt": "› ", "icon": "◆", "separator": "─"},
    "momiji": {"group": 5, "label": "紅葉（焦茶に紅と山吹）", "bg": "24130e", "fg": "f5e6d8", "border": "5c3326", "tag": "ee6a44", "comment": "f2b134", "snippet": "fff3e8", "hint": "a8836e", "selbg": "3a2018",
              "vars": ["ee6a44", "f2b134", "e0956a", "c9b37a", "ec97aa", "a6c482"],
              "frame": "rounded", "popup": "rounded", "pointer": "▸", "prompt": "› ", "icon": "◆", "separator": "─"},
    "kinkaku": {"group": 5, "label": "金閣（漆黒に金）", "bg": "0d0c08", "fg": "efe6c8", "border": "6b5d2a", "tag": "e6c35c", "comment": "c9a24a", "snippet": "fff6dc", "hint": "8f8460", "selbg": "26220f",
               "vars": ["e6c35c", "f0d78c", "d4954a", "b9c46a", "e0a96d", "d8c7a0"],
               "frame": "double", "popup": "double", "pointer": "◆", "prompt": "› ", "icon": "◆", "separator": "═"},
    "yozakura": {"group": 5, "label": "夜桜（夜の地に桜と藤）", "bg": "1b1420", "fg": "f3e6ee", "border": "4e3a5a", "tag": "f7a8c4", "comment": "c8b6e2", "snippet": "fff0f6", "hint": "9a8a9e", "selbg": "30223a",
                "vars": ["f7a8c4", "c8b6e2", "f2d1a0", "a8d8c8", "f28b9a", "b8c8f0"],
                "frame": "rounded", "popup": "rounded", "pointer": "●", "prompt": "› ", "icon": "●", "separator": "─"},
    # --- 身の回りの物（黒板・ノート・付箋・液晶…）。地の色・線の形・一覧の左端の列・縞・選んだ行の帯まで、その物に見立てる
    "chalk": {"group": 6, "label": "黒板（深緑の地にチョークの色。木の枠）", "bg": "24392e", "fg": "e9ece4", "border": "a47a4c", "tag": "f4e07a", "comment": "f4a6b7", "snippet": "f3f4ee", "hint": "8aa293", "selbg": "33503f",
              "vars": ["f4e07a", "f4a6b7", "a9d6f0", "c8e6a0", "f7bd8a", "cfbdf0"],
              "frame": "rounded", "popup": "heavy", "pointer": "→", "prompt": "✎ ", "icon": "☆", "separator": "╌"},
    "notebook": {"group": 6, "label": "ノート（白い紙に青と赤のペン。左に赤い線、選ぶと蛍光ペン）", "bg": "fbfaf4", "fg": "2b2f36", "border": "8fb8de", "tag": "1d4fbf", "comment": "c0392b", "snippet": "222222", "hint": "727780", "selbg": "fff27a",
                 "vars": ["1d4fbf", "c0392b", "1e7b3a", "7b2fbf", "a35200", "0f6f78"],
                 "frame": "horizontal", "popup": "single", "pointer": "✓", "prompt": "✎ ", "icon": "◎", "separator": "┈",
                 "gutter": "│", "gutterfg": "e8868f"},
    "sticky": {"group": 6, "label": "付箋（黄色い紙に赤と青のペン）", "bg": "fff4a3", "fg": "2a2414", "border": "d8b43a", "tag": "9b1c1c", "comment": "1f3f8f", "snippet": "1c1a12", "hint": "7a6a2c", "selbg": "f6c445",
               "vars": ["9b1c1c", "1f3f8f", "1d6b2a", "6b2a8f", "8a4500", "0b5c66"],
               "frame": "block", "popup": "single", "pointer": "▶", "prompt": "› ", "icon": "●", "separator": "─"},
    "greenbar": {"group": 6, "label": "連続用紙（緑と白の縞の印刷用紙。端に送り穴）", "bg": "f7f9f1", "fg": "1e2a1e", "border": "9ab39a", "tag": "1b5e20", "comment": "1a3f7a", "snippet": "1a1a1a", "hint": "667066", "selbg": "a8d5a2",
                 "vars": ["1b5e20", "1a3f7a", "8a1c3a", "5b2a86", "7a4a00", "00606a"],
                 "frame": "dashed", "popup": "single", "pointer": "▸", "prompt": "> ", "icon": "■", "separator": "┄",
                 "altbg": "dcefd8", "gutter": "○", "gutterfg": "a3b3a3"},
    "lcd": {"group": 6, "label": "液晶（電卓の灰緑の地に濃い字。色を使わない）", "bg": "c4cfa1", "fg": "1c2611", "border": "6f7d55", "tag": "1f4a14", "comment": "3a3f1c", "snippet": "151c0e", "hint": "56623f", "selbg": "a7b583",
            "vars": ["1f4a14", "3a3f1c", "203a2a", "4a3a14", "2a2a2a", "143024"],
            "frame": "sharp", "popup": "single", "pointer": "►", "prompt": "> ", "icon": "▪", "separator": "─", "fullline": True},
    "pcb": {"group": 6, "label": "基板（緑の基板に金の配線と白い印字）", "bg": "0e3b24", "fg": "e8f0e6", "border": "c9a24a", "tag": "f0c75e", "comment": "d9e8dd", "snippet": "ffffff", "hint": "7fa58c", "selbg": "1a5634",
            "vars": ["f0c75e", "e8945a", "cfd8dc", "ff6e6e", "78bcff", "ffb84d"],
            "frame": "sharp", "popup": "double", "pointer": "▸", "prompt": "› ", "icon": "◉", "separator": "┄"},
    "classic": {"group": 6, "label": "灰色の窓（昔のパソコンの灰色の画面。行いっぱいの選択）", "bg": "c0c0c0", "fg": "000000", "border": "404040", "tag": "000080", "comment": "800000", "snippet": "000000", "hint": "505050", "selbg": "a6caf0",
                "vars": ["000080", "800000", "005a00", "6a006a", "5c4400", "005050"],
                "frame": "sharp", "popup": "single", "pointer": " ", "prompt": "> ", "icon": "■", "separator": "─", "fullline": True},
    # --- 見やすさ（くっきり・色の見分け）
    "contrast": {"group": 7, "label": "ハイコントラスト（真っ黒に白と黄。太い線と行いっぱいの選択）", "bg": "000000", "fg": "ffffff", "border": "ffffff", "tag": "ffff00", "comment": "00ffff", "snippet": "ffffff", "hint": "c8c8c8", "selbg": "0000c0", "selfg": "ffffff",
                 "vars": ["ffff00", "00ffff", "ff80ff", "80ff80", "ffb000", "ffffff"],
                 "frame": "bold", "popup": "heavy", "pointer": "▶", "prompt": "▶ ", "icon": "■", "separator": "━", "scrollbar": "┃",
                 "fullline": True},
    # 色の見分けにくさ（赤と緑など）があっても分かれる色（Okabe・Ito の色を、暗い地で読める明るさに）。案件の丸も青とオレンジに
    "universal": {"group": 7, "label": "色覚に配慮（見分けにくさがあっても分かれる色）", "bg": "1a1c22", "fg": "e6e6e6", "border": "4a5060", "tag": "56b4e9", "comment": "e69f00", "snippet": "f0f0f0", "hint": "8c9099", "selbg": "2c3140",
                  "vars": ["e69f00", "56b4e9", "009e73", "f0e442", "e8743a", "cc79a7"], "casecur": "56b4e9", "caseon": "e69f00"},
}
THEME_ORDER = list(THEMES)
DEFAULT_THEME = "ocean"


def load_theme_name():
    """設定のテーマ名。無ければ既定（ocean）"""
    name = settings.get("theme")
    return name if name in THEMES else DEFAULT_THEME


def save_theme_name(name):
    settings.save(theme=name)


def _bg(hex6):
    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    return f"\x1b[48;2;{r};{g};{b}m"


def apply_theme(name):
    """C_TAG 等のグローバル変数と CURRENT_THEME をテーマの色で差し替える。設定画面で選び直した
    直後にも呼ぶので、画面を再読み込みしなくても次の pick_entry/prompt_var から新しい色になる。
    C_BASE は、背景を変えるテーマの地の色（fzf の外で自分で描く所＝タブの並び・画面を消すときに使う。端末の背景のままなら空）"""
    global C_TAG, C_COMMENT, C_SNIPPET, C_HINT, VAR_COLORS, CURRENT_THEME, C_BASE, CASE_CUR, CASE_ON
    global FRAME, POPUP_LINES, POINTER, PROMPT, ICON, SEPARATOR, ASCII, FULLLINE, GUTTER, SCROLLBAR
    t = THEMES[name]
    FRAME, POPUP_LINES = t.get("frame", "rounded"), t.get("popup", "single")
    POINTER, PROMPT, ICON = t.get("pointer", "▌"), t.get("prompt", "> "), t.get("icon", "◆")
    SEPARATOR, ASCII = t.get("separator", "─"), bool(t.get("ascii"))
    FULLLINE, GUTTER, SCROLLBAR = bool(t.get("fullline") or t.get("altbg")), t.get("gutter"), t.get("scrollbar")
    CASE_CUR, CASE_ON = _fg(t.get("casecur", "5fd68a")), _fg(t.get("caseon", "ffa94d"))
    C_TAG = _fg(t["tag"])
    C_COMMENT = _fg(t["comment"])
    C_SNIPPET = _fg(t["snippet"])
    C_HINT = _fg(t["hint"])
    VAR_COLORS = [_fg(c) for c in t["vars"]]
    C_BASE = _fg(t["fg"]) + _bg(t["bg"]) if t.get("bg") else ""
    CURRENT_THEME = name


def based(text):
    """自分で描く文字に、地の色を通す（途中の C_RESET のあとも地の色に戻す）"""
    return C_BASE + text.replace(C_RESET, C_RESET + C_BASE) if C_BASE else text


def swatch(name):
    """配色を選ぶ画面の見本（そのテーマの背景の上に、見出しの印と、見出し・説明・本文・変数の色の ■）。記号だけにして、文字で
    絞るときに見本の文字が当たらないようにする（2026-11-01、本人の指摘「配色は検索できないのですか」）"""
    t = THEMES[name]
    back = _bg(t["bg"]) if t.get("bg") else ""
    cols = [t["tag"], t["comment"], t["snippet"], *t["vars"]]
    return f"{back} {_fg(t['tag'])}{t.get('icon', '◆')} " + " ".join(f"{_fg(c)}■" for c in cols) + f" {C_RESET}"


def fzf_shape_args():
    """fzf の形の引数（選んでいる行の印・入力欄の頭・一覧と入力欄の間の線・罫線を使わない・選んだ行の帯を行の端まで・一覧の
    左端の列の字・スクロールバーの字）"""
    return (["--pointer", POINTER, "--prompt", PROMPT, "--separator", SEPARATOR] + (["--no-unicode"] if ASCII else [])
            + (["--highlight-line"] if FULLLINE else []) + ([f"--gutter={GUTTER}"] if GUTTER else [])
            + ([f"--scrollbar={SCROLLBAR}"] if SCROLLBAR else []))


def restyle_popup():
    """いま開いている tmux の窓（hackdeck の窓の中から呼ぶ）の地と枠を、いまの配色にする。tmux 3.6 から、窓の中で display-popup を
    呼ぶと、その窓が変わる（2026-11-01、本人の指摘「外枠の色は、一度閉じないと変わらない。インタラクティブに変わらないの」）"""
    if os.environ.get("HACKDECK_POPUP") and os.environ.get("TMUX"):
        subprocess.run(["tmux", "display-popup", *popup_style()], capture_output=True)


def popup_style(name=None):
    """tmux の窓（display-popup）の引数。題、枠の線の形と色（見出しの色）、背景を変えるテーマは窓の地も（変えないテーマは地を
    端末のままに戻す。開いている窓を変えるときに、前の配色の地が残らないように）。name: テーマ（既定はいま）。
    題もここで渡す: 開いている窓を変えるとき（restyle_popup）、tmux は -T が無いと題を空にする（2026-11-01、本人の報告「配色を
    変えると左上の hackdeck という文字が消える」）"""
    t = THEMES.get(name or CURRENT_THEME) or THEMES[DEFAULT_THEME]
    head = ["-T", " hackdeck ", "-b", t.get("popup", "single")]
    if t.get("bg"):
        return [*head, "-s", f"bg=#{t['bg']},fg=#{t['fg']}", "-S", f"fg=#{t.get('border') or t['tag']},bg=#{t['bg']}"]
    return [*head, "-s", "bg=default,fg=default", "-S", f"fg=#{t['tag']},bg=default"]


CURRENT_THEME = load_theme_name()
C_RESET = "\x1b[0m"
apply_theme(CURRENT_THEME)
# 流れの図（2026-10-29 追加）の線の色と文字の飾り。線は fzf の枠線（256色の59番）と同じ灰色
C_LINE = _fg("5f5f5f")
B_ON, U_ON, DIM = "\x1b[1m", "\x1b[4m", "\x1b[2m"


def callout(text):
    """注意書きの1行（どの画面でも同じ形。2026-10-30、本人の指摘「注意書きは、色や見た目を共通に」「文字ばかりの説明の中に置かず、
    コールアウトのような見た目で」）"""
    # 行全体を黄色の地にした帯（黒い字）。見本のページで3案から本人が選んだ（2026-10-30。前は「注意」のラベルと黄色の本文）
    body = f" 注意  {text}"
    pad = max(0, term_cols() - 6 - display_width(body))
    return f"\x1b[30;48;2;255;207;107m \x1b[1m注意\x1b[22m  {text}{' ' * pad}{C_RESET}"


def _fzf_theme_color_opt():
    """fzf --color の値。選択行の背景・ポインター・fg+ を今のテーマ（CURRENT_THEME）に
    合わせる。--ansi で候補データに埋め込んだ前景色（C_TAG・C_COMMENT 等）は、この fg+ の
    指定があっても上書きされない（fg+ は色指定の無い部分にだけ効く。2026-10-28、
    printf+fzf の最小再現で実機確認済み）"""
    t = THEMES[CURRENT_THEME]
    # footer:-1: 流れの図（--footer）の地の文字を端末の既定色にする。fzf の既定（256色の109番）のままだと、
    # 図の値（admin など）が灰青色になり、候補一覧の文字と色が違って見えた（2026-10-29、実機で確認）
    base = f"bg+:#{t['selbg']},pointer:#{t['tag']},fg+:#{t.get('selfg') or t['snippet']}" \
        + (f",alt-bg:#{t['altbg']}" if t.get("altbg") else "")
    if not t.get("bg"):
        return base + ",footer:-1" + (f",gutter:#{t['gutterfg']}" if t.get("gutterfg") else "")
    # 背景を変えるテーマ: fzf が描く所（一覧・説明の箱・足もと・線・入力欄）を全部、そのテーマの地と線の色に（一覧の左端の列は、
    # 色の決まっていない配色では地の色にして見せない）
    bg, fg, line = t["bg"], t["fg"], t.get("border") or t["hint"]
    return (f"{base},bg:#{bg},fg:#{fg},preview-bg:#{bg},preview-fg:#{fg},gutter:#{t.get('gutterfg') or bg},footer:#{fg},"
            f"header:#{t['comment']},"
            f"border:#{line},preview-border:#{line},footer-border:#{line},separator:#{line},scrollbar:#{line},"
            f"label:#{t['tag']},preview-label:#{t['tag']},prompt:#{t['tag']},query:#{t['snippet']},info:#{t['hint']},"
            f"spinner:#{t['tag']},marker:#{t['tag']},hl:#{t['tag']},hl+:#{t['tag']}")


# 案件のタブの丸は apply_theme が決める（CASE_CUR いま入っている案件＝既定は緑、CASE_ON 動いているが入っていない案件＝既定は
# オレンジ。2026-10-30、本人の指定。色覚に配慮した配色では青とオレンジ）
