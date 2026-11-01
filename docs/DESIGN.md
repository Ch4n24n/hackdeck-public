# hackdeck の作り

直す人（AI を含む）向け。使い方は [../README.md](../README.md)、なぜそうしたかはコードのコメント。

## 全体の形

```
端末 ── hackdeck（cli.launch。案件の外の Ctrl+G は hackdeck shell-init の zsh の1行がこれを呼ぶ）
         ├─ 専用の tmux の中 ……… tmux display-popup → hackdeck popup <ペイン>（popup.c_popup）
         ├─ ほかの tmux の中 …… tmux display-popup → hackdeck ui（案件と設定のタブだけ）
         └─ tmux の外 ………………… 専用の tmux の待合（session.LOBBY。空のセッション）につなぎ、その上で
                                  display-popup → hackdeck ui --lobby <クライアント>。案件を選べば switch-client、
                                  選ばずに閉じれば detach-client（元の端末に戻る）
端末（設定の outside）── 開いたときから、専用の tmux の案件の外のセッション（_out-<端末の番号>）。窓のキーは案件の中と同じ

専用の tmux サーバー（tmux -L hackdeck。session.py）
  設定 ~/.cache/hackdeck/tmux.conf（session.conf_text が設定から毎回作る。~/.tmux.conf は source-file で読むだけ）
  セッション = 案件（名前は案件のフォルダの名前）。環境に HACK_ROOT・HACK_CASE・HACK_HOME・HACK_STATE・HACK_LOG・NXC_PATH
  窓のキー（bind -n C-g）: display-popup で hackdeck popup <ペイン>。組み立てたコマンドを paste-buffer で元のペインに貼る
    （どのプログラムの中でも同じ。窓の地と枠の色は配色から＝theme.popup_style）
  シェル: ZDOTDIR を ~/.cache/hackdeck/zsh に向ける → その .zshenv が元の ZDOTDIR に戻して自分の設定を読み、
          最初のプロンプトで shell/hack.zsh を読む（対話でない zsh は ZDOTDIR を戻さず、その子の対話の zsh にも入る）

窓の中（builder.run_builder）: 画面の列（nav）の今の画面を出し、画面が返した操作で列を動かす、を閉じるまで繰り返す
```

**案件の内外は `HACK_ROOT` だけで決める**（`case.case_root`）。いまいる場所（cwd）は見ない。外では、コマンド・資格情報・環境の
タブが無く（`ui.tabs`）、案件のファイルは `None`（読む側は空、書く側は何もしない）。

**案件の名前を変えるのは、止まっているときだけ**（`session.case_rename`。案件のタブの Ctrl+E・`hackdeck case rename`）。動いて
いるセッションの環境とシェルは前の場所を指したままになる（ログは前の名前のフォルダを作り直してそこへ書き、窓は案件の外の扱いに
なり、案件のタブからは止まって見える）。

**案件の外で覚えるものは、名前や場所ではなく案件の目印で見分ける**（データの置き場所の `id`。`case.case_id`）。窓の画面の列
（`nav/`。`case.case_scope`）と直前の案件（`last`。`case.last_case`）。名前を変えても、hackdeck の外で `mv` しても、止まっている
案件ならそのまま続く。残した並びは、残したときの案件の場所を `layout.tsv` の `r` の行に書き、`session.case_saved` がペインの場所を
今の場所へ読み替える。案件の外に何かを足して覚えるときも、目印で見分ける。

**案件の外のセッション**（設定の `outside`。`session.outside_*`）: `hackdeck shell-init` の1行が、VTE の端末の対話の zsh で
`hackdeck outside` を呼び、専用の tmux に `_out-<端末の番号>` のセッションを作ってつなぐ（`@hack_outside`・持ち主の端末
`@hack_owner`）。窓のキーは tmux が受けるので、どのプログラムが動いていても効く。案件に入ると switch-client、prefix+d と案件の
タブの「案件から離れる」（`session.leave`）でそこへ戻る（無ければ detach）。端末を閉じると、client-detached のフック
（`hackdeck outside gc`）が、持ち主の端末が無くなったものを終える。セッションが終わると、呼んだ zsh も終わる（端末が閉じる）。

**本物の tmux には触らない。** 試すときは `HACKDECK_TMUX_SOCKET`（ソケットの名前）と `TMUX_TMPDIR`・偽の `HOME` で隔離する（`tests/`）。
本物のペインにキーを送らない。組み立てたコマンドを Enter で走らせない。

## 場所

| 置き場所 | 中身 | 定義 |
|---|---|---|
| ツール（`paths.ROOT`） | `bin/`・`hackdeck/`・`shell/`・ツールに付いているコマンド帳（`cheats/`・`opts/`） | `paths.py` |
| `~/.config/hackdeck/`（`XDG_CONFIG_HOME`） | `settings.json`・`wpscan-api-token`・自分のコマンド帳（既定） | `paths.CONFIG_DIR` |
| `~/.local/share/hackdeck/`（`XDG_DATA_HOME`） | `common`（よく使うユーザー・パスワード）・案件をまたぐ一覧（`~cmn`）・`resurrect/` | `paths.DATA_DIR` |
| `~/.local/state/hackdeck/` | `last`（直前の案件）・`autosave`（並びを自動で残した時刻） | `paths.STATE_DIR` |
| `~/.cache/hackdeck/` | `tmux.conf`・`zsh/.zshenv`・`nav/`（閉じたときの画面の列）・`copy-state`・`magic.json`（ファイルの候補の `file -b`。場所・大きさ・更新時刻ごと）・`run/<窓の番号>/`（窓ごとの作業の置き場所。上の枠の中身・変数の候補・流れの図の対応表・カーソルの動き・fzf と vim の一時ファイル。`ui.work_dir`。閉じたら消し、止められて残ったものは次に窓を開いたときに消す。/tmp には書かない） | `paths.CACHE_DIR` |
| 案件のフォルダ（`<cases_dir>/<名前>`） | 作業フォルダ（`work_dir`）・データの置き場所（`state_dir`）・ログ（`log_file`）。どれも案件のフォルダからの場所 | `case.py`（設定から） |
| 雛形の既定（`settings.TEMPLATE_URL`） | 雛形のリポジトリ `https://github.com/Ch4n24n/Hacking-Op-public.git`（番号で持ち主を分けた問題のフォルダ・`CLAUDE.md`）。問題を作るとき clone する。場所の3つの既定（`02-作業`・`02-作業/.hack`・`91-ログ/実行ログ.log`）もこの雛形の形 | 別のリポジトリ（2026-11-02 に分けた） |
| データの置き場所（`case.case_file(root, 名前)`） | `creds`・`env`・`env-names`・`history`・`inputs`・`session/`・`nxc/` | 700。`case.ensure_state` が作り、git の中なら `.git/info/exclude` に足す |

ファイルの書式: `creds` は1行に `user:secret:説明`（`creds.parse_cred_line`）、`env` は `export 名前=値`（シェルが source する）、
`env-names` は `名前` か `名前:説明`、`history` は `時刻<TAB>コマンド`、`inputs` は `変数名<TAB>値`、`session/layout.tsv` は窓（`w`）と
ペイン（`p`）の行、`session/<窓>.<ペイン>.txt` は画面の中身（600）。

## モジュールの地図（`hackdeck/`）

依存は下から上へ（下のものは上のものを import しない。輪は作らない）。

| 段 | モジュール | 役割 |
|---|---|---|
| 土台 | `text` | 見た目の幅・切り詰め・引用符・候補の1行・クリップボード。どのモジュールにも頼らない |
| | `paths` | ツールと XDG の置き場所 |
| | `settings` | 設定の項目の一覧（`SETTINGS`）・`get`・`save`・`problem`（値の確かめ） |
| | `case` | 案件の置き場所・案件の中の場所・いまの案件（`case_root`）・データの置き場所・`~hack`/`~cmn` |
| | `theme` | 配色（`THEMES`）。色は `theme.C_TAG` のように属性で読む（選び直すと差し替わる） |
| データ | `creds` | 資格情報とよく使うもの |
| | `env` | 環境変数のファイルと書き戻し |
| | `history` | 組み立てた履歴・打った値 |
| | `nxc` | netexec の DB を読む・見つけた日時・足したあとの説明の書き直し |
| | `session` | 専用の tmux サーバー（設定・案件のセッション・並びを残す・戻す・作る・入る） |
| | `panelog` | `prefix + F` のログ（zsh の側と同じ `@hack_last` を使う） |
| 画面の部品 | `ui` | fzf の共通の部品（タブ・足もと・説明欄の行 `foot_lines`・行ごとの上の枠 `item_preview`・キーの意味・2回押しの確かめ・`fzf_run`） |
| | `cheatbook` | コマンド帳の読み込み（ツールの分と設定の `books`）・変数の依存の順・置き換え |
| | `flow` | 変数の枝分かれ・流れの図・組み立て中のコマンドの見せ方 |
| | `cand_net`・`cand_auth`・`cand_files` | 変数の候補（ホスト・資格情報と認証の形・ファイルと一覧） |
| | `candidates` | `hackdeck <種類>` の振り分け（`CANDIDATE_CMDS`・`run_candidate_cmd`）・`opts` |
| | `prompt` | fzf の2つの画面（コマンド選び `pick_entry`・変数1つ `prompt_var`）と、流れの図のクリック |
| | `fzfcall` | fzf から打つたび・動くたび・画面を出すたびに呼ばれる小さな補助（カーソル合わせ `findpos`・`findidx`・`casepos`、補完、打った値の行 `typed`・`pick`、見出し `HEADING`、打った文字での絞り込み `filter_rows`・見出しつきの `filter_grouped`）。毎回 hackdeck が起き直すので、読み込むものを最小に（ほかのモジュールは関数の中で読む） |
| | `nav` | 画面の列（戻る・進む・上へ）と保存（案件ごと） |
| タブ | `tab_cmd`・`tab_creds`・`tab_env`・`tab_memo`・`tab_case`・`tab_settings` | 各タブの画面。`*_screen(e, can_back, can_fwd)` が操作を返す（`tab_memo` は fzf ではなく vim を開き、終わり方の番号でタブを移るか閉じる。上の枠・説明欄・線は、vim の上の窓（書けない。入ると書く所へ戻す）に、fzf と同じ字と色で描く＝`tab_memo.INFO_VIM`） |
| 入口 | `builder` | 画面を回す本体（`run_builder`） |
| | `popup` | 専用の tmux の窓の中身（案件の環境を入れて `run_builder`、貼る・zsh に返す） |
| | `check` | コマンド帳の点検 |
| | `cli` | `hackdeck <サブコマンド>` |

`shell/hack.zsh` は案件のセッションの zsh に入る部分（`~hack`・戻るコマンド・環境変数の読み直しと書き戻し・ログ・実行の時刻・
netexec の日時・並びの自動保存）。時刻と戻るコマンドの設定は、`session.shell_conf` が書く小さなファイル（`HACK_SHELL_CONF`）を
プロンプトのたびに見て、変わっていれば読み直す（開いているペインにも効く）。フックの順: preexec は 書き戻す名前を控える → 読み直し → ログの印 → 始まりの時刻。precmd は
終わりの時刻 → ログ → 書き戻し → 読み直し → netexec → 自動保存。どちらも配列の先頭に置く（ほかのフックが出す文字より先に
時刻を出す）。自分の `precmd` 関数（`~/.zshrc` の `precmd()`）は中で包み、その前に終わりの時刻を出す。

## 画面のしくみ

- **列（nav）**: 通った画面を1本の列で持つ（`{"v": 1, "entries": [...], "index": n, "builds": {...}, "last": ...}`。案件ごとに
  `~/.cache/hackdeck/nav/` に残す）。列の1つは `{"s": 画面, "q": 検索語, "f": カーソルの行の印, "e": 書いている行}` など。
  `s` は `picker`（コマンド選び）・`var`（変数。`b` 組み立て1回分の番号・`v` 変数名）・`history`・`creds`（`tab`）・`nxc`・
  `env`・`case`・`settings`（`v` 開いている項目）。
- **画面は操作を返す**: `("stay",)`・`("close",)`・`("push", 列の1つ)`・`("back",)`・`("forward",)`・`("up",)`・`("home",)`・
  `("tab", 名前)`・`("tabhome", 名前)`・`("saved", カーソル)`・`("done", コマンド)`・`("attach", 案件)`。`builder.run_builder` が列を動かす。
- **fzf の決まり**: どの画面も `--expect` でキーを受け、`--print-query` で打った文字を受ける。候補は `hackdeck <…>rows` を `reload` で
  作り直す（打つたびに）。最初の候補は `ui.rows_now` で同じ関数から作る。カーソルは `result:transform:hackdeck findpos <印> {*f}` で
  合わせる。画面の一言は `ui.note_args`（検索欄の上）。2回押しの確かめは `ui.twice`。足もとの高さは `ui.FOOT_ROWS` にそろえる。
- **一覧の見え方**: 画面を出し直しても、一覧の同じ所が見えるようにする。`ui.fzf_run(…, place=e)` が、カーソルの動きの向きが
  変わった所を `e["o"]`（検索語 `e["oq"]` のときのもの）に覚え、次に同じ画面を出すとき `HACKDECK_REPLAY` で渡す。`findpos`・
  `findidx` が、最初の画面を描く前に `pos(…)` を続けて出す（fzf はずらし方を外に出さないが、ずらし方はカーソルの動きで決まる）。
  画面を足すときは `place=e` を渡し、カーソルは `findpos`・`findidx` で合わせる。`--scroll-off=0`（端の行をクリックしても一覧が
  ずれない）。
- **検索欄**: どの画面も、打った文字で一覧を絞る（2026-11-01、本人の指摘「検索窓があるのに検索ができない画面がある。すべての
  タブで統一した作りに」。前は設定の項目の一覧が打った文字を使わず、資格情報と設定の一覧を書く項目は足す値にだけ使っていた）。
  fzf に絞らせるのは、見出しも足す行も無いコマンド選び・履歴・netexec の一覧だけ。ほかは `--disabled` で、`…rows {q}` の `reload` が
  絞る: 見出しの無い一覧は `fzfcall.filter_rows`（行ごとに見せる字と探す字。探す字は列の幅で切り詰める前の、行の字の全部）、
  見出しのある一覧は `fzfcall.filter_grouped`。どちらも打った文字をそのまま含む行を残し、大文字を打たなければ大文字小文字を
  区別しない（fzf の smart-case と同じ）。当たった所に下線（`fzfcall.mark_match`。色の印の中には引かない。`--ansi` が要る）。
  足せる画面（資格情報・環境・案件・設定の一覧を書く項目）は、先頭（画面ではいちばん下）の「＋」の行を絞らずに出し、打った文字が
  そのまま足す値になる（変数の画面の「そのまま使う」の行も同じ）。打ったら `load:first` でその行へ（案件のタブだけは、当たる案件が
  あればその先頭へ。入るのが主なので。`casepos`）。足す行でない行の Enter は「書き換えは Ctrl+E」。書き換え・値を書く項目は、
  保存の1行だけ（打った文字が値）。打った文字は列の `e["q"]` に残す（タブを移って戻っても・一言を出し直しても）。カーソルの行ごとに
  上の枠が変わる画面（コマンド選び・履歴・設定の項目の一覧）は `ui.item_preview` で、当たる行が無いときも題とキーを出す（fzf は
  カーソルの行が無いと枠を空にする）。足もとを行ごとに変える画面は、当たる行が無いときに同じ高さの空の行を出す（`{1}` が空）。
- **見出し**: 候補の見出しと空行は、1列目が `ui.HEADING` の行（`ui.grouped`・`fzfcall.filter_grouped` が作る）。選択肢ではないので、
  `ui.fzf_run` が、候補の1列目をタブで区切る画面すべてで、カーソルを見出しに止めない（`focus` で、移った向きにもう1つ進む。
  いちばん上の見出しは一覧を1行ずらして見せる）。見出しのある一覧は、絞るのも hackdeck 側（`filter_grouped`。当たった行のある
  まとまりだけを見出しつきで残す。fzf は `--disabled`。fzf に絞らせると、見出しも打った文字に当たる1行になる）。
- **マウス**: 1回のクリックはカーソルを動かすだけ（fzf の既定）、2回のクリックは Enter と同じ（`ui.fzf_run` が `double-click` に
  印の print を足し、出力の押したキーを `enter` に読み替える）。画面の側で `left-click` を割り当てない（1回で決めると、2回目の
  クリックが次の画面に届く）。
- **窓の見た目**: 題・枠の線・枠の色・地は `theme.popup_style` だけで決める（窓を開く2か所と、配色を変えたときの
  `theme.restyle_popup` が同じものを渡す。開いている窓を変えるとき、tmux は渡さなかった題を空にする）。
- **タブ**: `ui.ALL_TABS`。案件の外は `ui.OUTSIDE_TABS`（案件・設定）だけ。タブの並びは画面のいちばん上の行（`ui.fzf_run` が描く）。
- **画面の移り方**: fzf は `--height=-1 --no-clear` で、前の画面の上にそのまま描く（消してから描くとチカチカする）。画面を
  全部消す処理は書かない（配色を変えたときも。地は fzf と `ui.fzf_run` が塗り直す）。メモのタブの vim も、`--cmd` で `t_ti`・`t_cl`・
  `t_u7` を空にして前の画面の上に描かせる（`tab_memo.VIM_EARLY`。消してから描き、端末を調べる試しの字も書いていた）。起動時に
  Python で位置を合わせる画面は `--sync` を付け、最初の描画の前に終わらせる（付けないと、枠だけ先に描かれて中身が遅れる）。tmux 3.7c の窓
  では、前の画面の全角の字の地の色が右半分だけ残る（端末が VTE のとき）ので、`ui.fzf_run` が、新しい画面を描いた直後（キーを押す
  前の focus）に tmux に窓ごと描き直させる。fzf の起動を `ui.fzf_run` の外で書かない。

## 足し方

### コマンド帳（`cheats/*.cheat`・`opts/*.tsv`）

navi と同じ記号。読むのは `cheatbook.parse_cheat_files`。

```
% 目的, 道具                         ← 見出し（一覧の左の列。目的の順: 探索 → 侵入 → 資格情報 → 横移動 → ピボット → 受け渡し）
# 道具: 説明                         ← 一覧に出る説明
コマンド。変数は <名前>

$ 名前: hackdeck <種類> [引数]        ← 変数の候補（cheats/00-vars.cheat に集める。どのファイルからも見える）
! 例の値                             ← $ の直後。変数の画面に「例」として出る
? 何を入れるか                       ← $ の直後。変数の画面の説明
; コメント
```

- `$` の行は `hackdeck` から候補を出す（決まった値も `hackdeck value a b`。`hackdeck check` が確かめる）。
- `$` の行の `<変数>` は先に決めた値に置き換わり、決めた値は変数名の環境変数としても渡る（`$proto` など）。
- 候補の値の中に `<変数>` を書くと、それを選んだあとで続けてその変数を聞く（枝分かれ。`opts/nxc-smb.tsv` など）。
- `opts/<名前>.tsv`: 1行に `値<TAB>説明`（3列なら `値<TAB>名前<TAB>例`）。値が空の行は「付けない」。`hackdeck opts <名前>` で出る。
- 自分のコマンド帳は、設定の `books` のフォルダの `cheats/`・`opts/`（同じ名前の `$` と `opts` は、あとのものが勝つ）。
- 足したら `hackdeck check`。直したものは次に窓を開いたときから効く。
- 資格情報を渡す形（`auth_*`）は `cand_auth.py` の `AUTH_FORMS`・`AUTHCREDS_SHAPE`・`authcred_value`。**Kerberos の形は、作者のノートに
  あるものだけ**（ツールの `--help` やソースから形を作らない）。

### 候補の種類（`hackdeck <種類>`）

`cand_net`・`cand_auth`・`cand_files` のどれかに `c_<種類>()`（1行に `値<TAB>説明` を出す。`text.out` を使う）を書き、
`candidates.CANDIDATE_CMDS`（引数が無いもの）か `candidates.run_candidate_cmd`（引数があるもの）に足す。見出しで分けるなら `ui.out_grouped`。

### 設定の項目

`settings.SETTINGS` に `Setting(キー, 名前, 種類, 既定, 説明, 書き方)` を1つ足し、使う所で `settings.get(キー)` を呼ぶ。設定のタブは
一覧から作るので触らない（新しい種類のときだけ `tab_settings.py` に見せ方を足す。説明欄の「保存先」「一時的に」も項目から作る）。
値の確かめは `settings.problem`。専用の tmux の設定に効く項目は `tab_settings.TMUX_KEYS` に足す（保存したら `session.write_conf` が
作り直す）。環境変数 `HACKDECK_<キー>` で、その回だけ上書きできる（`settings.env_name`。`hackdeck` が開く窓には `display-popup -e` で
渡す）。専用の tmux とシェルに効く項目は `settings.SERVER_KEYS` に足す（一時的には変えられない。tmux の設定は
`settings.get(キー, env_ok=False)`＝settings.json のとおりに作る。その回だけの値が tmux に残らないように）。

### 配色

`theme.THEMES` に1つ足す（並びが選ぶ画面の順。`THEME_ORDER` は THEMES の順）。`group` は `theme.GROUPS` のまとまり、色は16進
（`#` なし）: `tag`（見出し・窓の枠）・`comment`・`snippet`（コマンドの本文）・`hint`（薄い字）・`selbg`（選んでいる行の背景）・`vars`
（変数の6色）。背景ごと変えるなら `bg`・`fg`・`border` も（fzf の地・線、自分で描く行の地＝`theme.C_BASE`・`theme.based`、窓の地）。
`selfg` は選んでいる行の文字。形も変えるなら `frame`（fzf の枠の線）・`popup`（tmux の窓の枠の線）・`pointer`・`prompt`・`icon`
（見出しの印）・`separator`・`ascii`（罫線を使わない）。一覧の形も変えるなら `fullline`（選んでいる行の帯を行の端まで＝fzf の
`--highlight-line`）・`altbg`（1行おきの地の色＝縞。`fullline` も付く）・`gutter`・`gutterfg`（一覧の左端の列の字と色）・`scrollbar`。
案件のタブの丸の色は `casecur`・`caseon`（`theme.CASE_CUR`・`theme.CASE_ON`）。形は `ui.fzf_run` が全部の画面の fzf に付ける
（`theme.fzf_shape_args`）。枠の形（`frame`）はメモのタブも同じ字で描く（`tab_memo.BOX`。新しい形を使うときは足す）。
配色を選ぶと、開いている窓も `theme.restyle_popup` が変える（窓の中から display-popup。窓には目印の `HACKDECK_POPUP=1` を渡す）。
足したら `python3 -I tests/themes.py`（明るさの比（縞の地の上も）と、fzf・tmux が形を受け付けるか）。

### タブ・画面

`tab_<名前>.py` に `<名前>_screen(e, can_back, can_fwd)` を書き（上の決まりで操作を返す）、`builder.run_builder` の振り分け・
`ui.ALL_TABS`・`ui.tab_of`・`nav.tab_entry`・`nav.up_entry` に足す。候補の行を作る `c_<名前>rows` は `cli.main` に足す。
検索欄は上の「画面のしくみ」の決まりにそろえる（`c_<名前>rows(query)` で `fzfcall.filter_rows` を通す・足す行は絞らない・
打った文字は `e["q"]` に残す）。

## 試し方

```bash
python3 -I tests/snapshot.py record /tmp/before.json      # 直す前に（CLI の出力と、コマンド帳の $ の行を全部）
python3 -I tests/snapshot.py compare /tmp/before.json     # 直したあとに
python3 -I tests/ui_snapshot.py record|compare <file>     # 画面（隔離した tmux で各タブを開いて文字で記録）
bash tests/e2e.sh                                          # 通し（専用の tmux・窓のキー・ログ・並びの復元・待合。約3分）
python3 -I tests/themes.py                                 # 配色（明るさの比・fzf が受け付けるか）
python3 -I tests/vte.py                                    # GNOME Terminal と同じ VTE で、画面を移ったあとの残骸（約30秒）
python3 -I tests/flicker.py [--root <場所>]                # 同じ VTE で、画面を移る瞬間のチカチカ（枠の線が消える・中身が遅れる。約40秒）
python3 -I tests/timing.py [--against <場所>]              # 反応の速さ（fzf から呼ばれる補助・候補・窓を開く処理。直す前と並べられる）
python3 -I tests/unused.py                                 # 使っていない import・関数・定数（綺麗化のとき）
python3 -I tests/pane_record.py [--memo] [キー ...]        # 画面に書かれたものを時刻つきで記録し、画面を消す制御などを数える（原因を探すとき）
python3 -I tests/keys.py '<題>|<キー>...' ...              # キーを送って画面を文字で出す（手で確かめるとき。L:<文字> でそのまま打つ）
python3 -I tests/theme_shots.py <出力> <配色> ...          # 配色の見本（主な画面を撮って並べた1枚。配色を作るとき）
python3 -I tests/template.py                              # 雛形の既定（URL）と、雛形の git リポジトリから案件を作る流れ（ネットにはつながない）
hackdeck check                                             # コマンド帳
```

`snapshot.py` と `ui_snapshot.py` は、直す前の記録と比べる道具（違いが出たら、意図した違いかを見る）。`e2e.sh`・`vte.py`・
`flicker.py`・`unused.py` は OK・NG（または見つけた数）を出す。`timing.py`・`pane_record.py`・`keys.py`・`theme_shots.py` は測る・記録する・見せる・撮るだけ。
作業用の台本は /tmp に置き捨てず、使い回すものは `tests/` に入れる（2026-11-01、本人の指摘）。
`vte.py`・`flicker.py`・`theme_shots.py` は Xvfb の仮の画面で VTE に描かせる（`e2e.sh` の外側の tmux は、tmux と同じ描き方をするので、
端末ごとの違いは出ない）。xvfb-run・python3-gi と VTE・PIL が無ければ飛ばす。
どれも偽の HOME と別の tmux の置き場所で動き、本物には触らない。試しの多くは、箱でない形（雛形は空・`work`・`work/.hack`・
`logs/session.log`。`tests/snapshot.py` の `GENERIC`）を設定に書いて使う（既定は付属の雛形の箱の形）。ただし、ホストの候補は本物の `/etc/hosts` と `ip` を読む
（画面を見せるために撮るときは `publish/shots.py`。`HACKDECK_ETC_HOSTS` と作り物の `ip` で、手元の値を写さない）。

## 書き方の決まり

- Python の標準ライブラリだけ。外のコマンドは tmux・fzf・git・flock と、候補を作る道具（ip など）。
- **起動を軽く。** fzf から打つたび・画面を出すたびに `hackdeck` が起き直す（1回の起動がそのまま反応の遅さになる）。`bin/hackdeck` は
  `python3 -IS`（site を読まない）、`cli.main` はサブコマンドごとに要るモジュールだけを、呼ぶときに読む。fzf から呼ばれる補助は
  `fzfcall` に置き、ほかのモジュールを頭で読まない。土台（`text`・`settings`）にも重いものを足さない（`dataclasses` は `inspect` を
  引くので使わない。`subprocess` などは使う関数の中で）。同じ窓の中で何度も使う結果（opts の場所と中身・流れの図・設定の中身）は
  覚えて使い回す（設定は settings.json が変わったときだけ読み直す）。
- 画面とコメントの言葉は日本語。初めて見ても分かる言葉で（画面の説明欄は「ファイルと中身」「書き方と見分け方」。キーの操作は上の枠に）。
- 直した理由は、日付と本人の言葉をコメントに残す（あとで「なぜこうなっているか」を追えるように）。
- 後方互換のための読み替えは持たない（本人の方針）。形を変えたら、切り替えのときに一度だけ移す。
