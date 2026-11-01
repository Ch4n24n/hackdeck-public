"""fzf の2つの画面: コマンド選び（pick_entry）と、変数1つを聞く画面（prompt_var）。fzf から呼ばれる補助（カーソル合わせ・
補完・打った値の行）は fzfcall（軽くするため）。"""
import os
import re
import shlex
import subprocess
from pathlib import Path

from .text import display_width, fit, path_safe, shell_safe, term_cols
from .theme import C_RESET, _fzf_theme_color_opt
from .history import inputs_recent
from .cand_auth import adtarget_value
from .flow import flow_overview, render_command
from .fzfcall import HEADING, is_typed_row
from .ui import (CLOSE_KEYS, JUMP_PREFIX, TAB_PREFIX, UP_KEY, cand_fields, candidate_val_width, entry_label, foot_args,
    fzf_run, heading_text, item_preview, nav_hint, pad_candidate_line, tab_hit, work_file, work_subdir)
from . import theme
from . import ui


def c_footclick(map_file="-", head="0"):
    """足もとがクリックされたとき（fzf の click-footer から呼ばれる）。流れの図の行なら、その変数へ（変数の画面だけ。
    map_file）。head: 図の前にある行の数"""
    try:
        line = int(os.environ.get("FZF_CLICK_FOOTER_LINE") or 0)
    except ValueError:
        return
    if map_file != "-":
        c_flowclick(map_file, line - int(head))


def run_shell_candidates(cmd_text, env):
    """$ 定義のコマンド文字列（navi の時と同じ、hackdeck 自身を呼ぶ想定）を bash で走らせ、候補の行を返す"""
    r = subprocess.run(["bash", "-c", cmd_text], env=env, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l]


def pick_entry(rows, query="", focus_idx=None, keys=(), hint=(), defs=None, esc="ignore", tab="cmd", foot=(), place=None,
               what="コマンド"):
    """コマンド選び・履歴・配色の画面を出す。rows: [{tag, comment, command(, display)}, ...]。
    query: 検索ボックスに出す文字列。focus_idx: rows の何番目の行にカーソルを合わせるか。query で絞り込んだ後の
    候補の中から、fzf の result イベント＋hackdeck findidx で探す（絞り込みが挟まると rows の位置と画面の位置が
    ずれるので、load:pos(N) のような固定の指定は使えない。2026-10-28）。
    keys: Enter と閉じるキー（CLOSE_KEYS）のほかに受け付けるキー（--expect）。Alt+←・Alt+→ は keys に
    無ければ押しても何も起きない（fzf の既定の「1語左右」にさせない。2026-10-29）。
    esc: keys に Esc が無いときの Esc の動き（fzf のアクション。画面は閉じない。既定は何もしない）。
    hint: プレビューの最下部に常時出す、その画面で使えるキー（2026-10-28、「Ctrl+R で履歴が見られることを画面に
    書いておいて」との指摘で追加）。
    navi 時代と同じく、画面上部に選んでいる行のタグ・コメント・コマンド全文をプレビューで出す（カーソルの動きに
    追従する --preview。行ごとに一時ファイルへ書き出し、選択中の番号のファイルを cat するだけ）。
    defs: 渡すと（コマンド選びの画面）、プレビューの枠のすぐ下（fzf の --footer）に、カーソルのあるコマンドの
    流れ（聞く順と枝分かれ。flow_overview）を出す。カーソルを動かすたびに focus イベントで差し替える。見るだけで、
    クリックしても何も起きない（2026-10-29 追加）。
    tab: プレビューの枠の上に出すタブの並びで、どれを開いているタブとして見せるか。what: 打った文字に当たる行が無いときの枠の
    「当たる<what>は無い」（ui.item_preview）。
    戻り値: (押したキー（fzf が何も返さなければ ""）, 検索語, カーソルのあった行の rows での番号 / None)"""
    cols = term_cols()
    # タグ列は、いちばん長いタグ（"target, windows" など）がまるごと入る幅に固定する。
    # 割合（10%）で決めていたときは、タグが長いと省略されて "ad, blood…" のようになり、
    # 省略されるタグとされないタグが混ざって列の開始位置もそろわなかった
    # （2026-10-28、「タグが省略される／説明文の列が揃っていない」との指摘で直した）。
    # コメント列はタグ・コマンドより優先して広く取る（コマンド全文は上のプレビューでも見えるため）
    tag_w = max((display_width(r["tag"]) for r in rows), default=8) + 1
    tag_w = min(tag_w, int(cols * 0.22))
    # コメント列も、タグ列と同じ理由で画面幅の割合ではなく実際の長さに合わせる（2026-10-28、
    # 「まだ説明文が右によっている」との指摘で原因を調べ直して判明）。56% 固定だと、画面が広い
    # （tmux popup・通常のシェルどちらも、ペイン幅が238文字程度あると com_w=133 になる）ときに、
    # 実際のコメント文の長さ（60件で最大66・中央値38）よりずっと広い枠を確保してしまい、その差
    # （133-66=67文字分など）が「コメント列とコマンド列の間の大きな空白」として見えていた。
    # tmux popup 固有の問題ではなく、画面が広い環境なら通常のシェルでも同じ症状が実機で再現した。
    # ただし tag_w と同じ「全体の最長」に合わせる方式を試したところ、「一部の説明文の列が
    # 合っていない」と指摘された（2026-10-28）。タグは種類が少なく長さのばらつきも小さいが、
    # コメントは自由な日本語の説明文で長さの差が大きく（60件で21〜66文字）、最長1件に
    # 引っ張られて、短いコメントの行だけコマンド列の開始位置が左に寄って見えていた。
    # 95 パーセンタイル（この60件なら60文字。超えるのは2件だけ）に合わせ、それより長い
    # コメントだけ fit() で「…」に切り詰める方式に変更。ほとんどの行はそろい、ごく一部の
    # 長い説明だけが省略される
    com_widths = sorted(display_width(r["comment"]) for r in rows)
    com_w = (com_widths[min(int(len(com_widths) * 0.95), len(com_widths) - 1)] + 1) if com_widths else 30
    com_w = min(com_w, int(cols * 0.56))  # 画面が極端に狭いときの上限はこれまでどおり維持
    com_w = max(com_w, 30)
    # display: 候補一覧・プレビューに見せる文字列。無ければ command をそのまま見せる（配色の画面は色見本を見せる）
    lines = [f"{i}\x1f{theme.C_TAG}{fit(r['tag'], tag_w)}{C_RESET}  {theme.C_COMMENT}{fit(r['comment'], com_w)}{C_RESET}  {r.get('display', r['command'])}"
              for i, r in enumerate(rows)]
    # 注意: fzf 0.74.4 で --with-nth と --nth を同時に指定すると、日本語の行の絞り込みが
    # 一致しなくなる（2026-10-28 に確認。隠した1列目が数字だけなので、--nth は外しても実害はない）
    # --no-clear: 変数の画面へ続けて切り替わるときに一瞬 popup の裏（元のペイン）が見えてしまうのを防ぐ
    # （fzf を複数回続けて起動するアプリ向けの既定の対策。run_builder の最後でまとめて元の画面に戻す）
    expect = ",".join(dict.fromkeys(["enter", *keys, *CLOSE_KEYS]))
    hint_line = f"{theme.C_HINT}{'  '.join(hint)}{C_RESET}"
    preview_dir = work_subdir("rows")   # 行ごとの上の枠と流れの図（作業の置き場所。ui.work_dir）
    flows = {}
    for i, r in enumerate(rows):
        shown_cmd = f"{theme.C_SNIPPET}{r.get('display', r['command'])}{C_RESET}"
        if defs is not None:
            flows[i] = []
            if r.get("where"):
                # コマンド帳の行だけ。変数を流れの図と同じ色で塗る（2026-10-29、図との対応が見えるように）
                flows[i], colors = flow_overview(r["command"], defs)
                shown_cmd = render_command(r["command"], {}, set(), colors, None)
        (preview_dir / str(i)).write_text(
            f"{entry_label(r)}\n{shown_cmd}\n{hint_line}", encoding="utf-8")
    # 図の高さは、全コマンドでいちばん高い図の行数にそろえる（足りない分は空白1つの行で埋める）。
    # コマンドごとの高さのままだと、カーソルを動かすたびに図と一覧の境目が上下して見にくかった
    # （2026-10-29、本人の指摘「サイズが毎回変わると見にくい。一番大きくなりそうなもので固定して」）
    flow_h = max([ui.FOOT_ROWS] + [len(f) for f in flows.values()])   # ほかの画面と同じ説明欄の高さ（2026-10-30）
    for i, flow in flows.items():
        (preview_dir / f"{i}.flow").write_text(   # 1行目はタブの並び（足もとを差し替えても残す）
            "\n".join(flow + [" "] * (flow_h - len(flow))), encoding="utf-8")
    (preview_dir / "none.flow").write_text("\n".join([" "] * max(flow_h, 1)), encoding="utf-8")   # 当たる行が無いとき
    # up,3: 枠の中身（コメント・コマンド・キーのヒント）は3行。4行のままだと枠の中の最後に空行が
    # 1行残っていた（2026-10-29、本人の指摘「この空行はなくせないの？」）。noinfo は変数の画面と同じ
    # （中身が枠にちょうど収まっていても右上に「1/3」が出るのを消す）
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--exact", "--no-sort", "--no-clear",
            "--delimiter", "\x1f", "--with-nth=2", "--print-query", f"--expect={expect}",
            "--color", _fzf_theme_color_opt(),
            *item_preview(f"cat {shlex.quote(str(preview_dir))}/{{1}}", what, hint_line),
            "--preview-window", "up,3,border-rounded,noinfo", *foot_args(tab, foot)]
    if "esc" not in keys:
        args += ["--bind", f"esc:{esc}"]
    if defs is not None:
        flow = shlex.quote(str(preview_dir))   # 当たる行が無いと {1} は空（高さはそのまま、空の行で）
        args += ["--bind", f"focus:transform-footer:cat {flow}/{{1}}.flow 2>/dev/null || cat {flow}/none.flow",
                 "--footer-border=line"]
    if query:
        args += ["--query", query]
    if focus_idx is not None:
        # 変数の画面の cursor_value と同じ仕組み。result イベント（いまの検索語での絞り込みが終わったとき）で
        # hackdeck findidx を呼び、絞り込み後の候補から rows[focus_idx] の行を探して pos(N) で合わせる。
        # --sync は result イベントを確実に起こすため
        args += ["--sync", "--bind", f"result:transform:hackdeck findidx {focus_idx} {{*f}}"]
    r = fzf_run(args, tab, input="\n".join(lines), capture_output=True, text=True, place=place)
    parts = r.stdout.splitlines()
    if not parts:
        return "", "", None
    hit = tab_hit(parts[1:])
    rest = [l for l in parts[2:] if not l.startswith(TAB_PREFIX)]
    key = f"tab:{hit}" if hit else parts[1] if len(parts) > 1 else ""
    sel = rest[0] if rest else ""
    return key, parts[0], int(sel.split("\x1f", 1)[0]) if sel else None


def prompt_var(cmd_text, env, preview_text, query="", cursor_value=None, example_label="",
               can_back=False, can_fwd=False, footer=None, footer_map=None, old_must_exist=False,
               cursor_typed=True, title="", var_name="", place=None):
    """1つの変数を聞く。候補の先頭に「打った値をそのまま使う」を常に1行出す（ファイル系を含む全画面共通）。
    打つたびに hackdeck typed <クエリ> を候補の先頭に挟んで候補一式を作り直す（reload）。
    先頭行の値そのものがクエリ文字列なので、fzf 自身の絞り込みでも必ず残る
    （固定の1行を足すだけだと、打った文字がその行の表示に含まれず、絞り込みで消えてしまっていた。2026-10-28）。
    preview_text: 画面上部に出す、組み立て中のコマンド（navi 時代にあった表示。枠線付きの --preview で出す）。
    query: 検索ボックスに出す文字列。cursor_value: 指定すると、query で絞り込んだ候補の中から、この値と一致する
    行へカーソルを合わせる（検索語は打っていたもの（例 "10"）のまま、カーソルは選んでいた値（例 "10900"）に、
    との指摘で追加。最初の結果（fzf の result イベント）でだけ pos(N) に飛ばし、以後は unbind(result) で外す。
    打ち直しているときに毎回ジャンプされると邪魔なため。2026-10-28）。cursor_typed が False なら、同じ値でも
    「そのまま使う」行には合わせない。
    example_label: 「この変数の例」。検索ボックスが空のときだけ薄い字で出す（--ghost。6段階で位置を変えた末に
    本人が選んだ形。2026-10-28）。
    can_back / can_fwd: Alt+← / Alt+→ を受け付けるか（通った画面の列に1つ前・1つ後があるか）。無いときは押しても
    何も起きない。fzf はこのキーを検索ボックスの「1語左右」に使っているが、本人の希望で上書きしている（単語移動が
    できなくなるのは承知の上。Ctrl+B・Ctrl+F の「1文字」の移動は残る）。
    footer / footer_map: プレビューの枠のすぐ下に出す流れの図（flow_footer の戻り値）。飛べる変数の行をクリック
    すると、その名前を返す（2026-10-29 追加）。
    old_must_exist: 決め直しの変数（使っている変数の値が変わった）。前の値が新しい一覧に無ければ、検索語も
    カーソルも空から聞く。
    戻り値: {"key": 押したキー（enter・alt-left・alt-right・esc・ctrl-g・ctrl-c・tab:タブ（タブの並びのクリック）。fzf が何も返さなければ ""）,
    "jump": 図でクリックした変数, "value": 選んだ値, "shown": 表示名（候補の3列目。認証の形なら「パスワード」）,
    "query": 検索語, "focus": カーソルのあった行の値（閉じて開き直したときに同じ行へ戻すため）,
    "typed": その行が「そのまま使う」行か}"""
    is_files =re.search(r"(?:^|\s)hackdeck\s+files(?:\s|$)", cmd_text) is not None
    tmp_path = None
    if is_files:
        source_cmd = f"{cmd_text} --typed --query {{q}}"
    else:
        cand_lines = run_shell_candidates(cmd_text, env)
        if title and cand_lines and not any(l.startswith(HEADING) for l in cand_lines):
            cand_lines.append(f"{HEADING}\t{heading_text(title)}")   # 1つのまとまりの候補にも見出し（VAR_HEADINGS）
        # 前に打った値を、いちばん下（「そのまま使う」のすぐ上）のまとまりに。もう候補にある値は出さない。入れる形は打った値と
        # 同じ（引用符の中なら、そのまま。c_typed）
        have = {cand_fields(l)[0] for l in cand_lines}
        raw = env.get("HACKDECK_TYPED_RAW")
        # dacledit・owneredit の対象は、打った名前・DN・SID を -target などの形にして入れる（c_typed と同じ）
        ad = cmd_text.split()[2] if cmd_text.startswith("hackdeck adtarget ") else ""
        recent = [(adtarget_value(ad, v) if ad else v if raw else shell_safe(v), v)
                  for v in (inputs_recent(var_name) if var_name else [])]
        recent = [(val, v) for val, v in recent if val not in have]
        if recent:
            cand_lines = ([f"{val}\t{v}\t" for val, v in recent] + [f"{HEADING}\t{heading_text('前に打った値')}"]
                          + ([f"{HEADING}\t "] if cand_lines else []) + cand_lines)
        if old_must_exist and cursor_value is not None and cursor_value != shell_safe(query) \
                and cursor_value not in {cand_fields(l)[0] for l in cand_lines}:
            # 決め直しの変数で、前の値が新しい一覧に無い（proto を変えたら前のオプションが無い等）。まだ決めて
            # いない変数として、検索語もカーソルも空から聞く（2026-10-29。手で打った値は一覧に無くても残す）
            cursor_value, query = None, ""
        # 値の列の幅をそろえて説明の開始位置を行ごとに合わせる（2026-10-28、「値と説明が行ごとに
        # バラバラで見にくい」との指摘）。opts/*.tsv をそのまま候補にしていたため、値の長さが
        # 行ごとに違うとタブの位置（タブストップ依存）がそろわなかった。「そのまま使う」行（c_typed、
        # reload のたびに別プロセスで作り直す）にも同じ幅を使いたいので、環境変数で渡す
        val_w = candidate_val_width(cand_lines)
        if val_w:
            env = dict(env, HACKDECK_VAL_W=str(val_w))
        if cmd_text.startswith("hackdeck authcreds "):   # 打った user:pass を道具の渡し方に（c_typed）
            env = dict(env, HACKDECK_TYPED_CRED=cmd_text.split()[2])
        if ad:
            env = dict(env, HACKDECK_TYPED_AD=ad)
        desc_w = term_cols() - val_w - 6   # 行頭の印 2・値と説明の間 2・右端 2
        tmp_path = str(work_file("items.tsv", "\n".join(pad_candidate_line(l, val_w, desc_w) for l in cand_lines)))
        source_cmd = f"cat {shlex.quote(tmp_path)}"
    # ファイルの画面は、打った値の行も hackdeck files が出す（説明の列をそろえるため）
    reload_cmd = source_cmd if is_files else f"hackdeck pick {{q}} {shlex.quote(tmp_path)}"
    # 使えるキーのヒントをプレビュー最下部に常時出す（pick_entry と同じ考え方）
    hint = ["Enter 選ぶ", "Tab 補完"] + nav_hint(can_back, can_fwd)
    preview_text = f"{preview_text}\n{theme.C_HINT}{'  '.join(hint)}{C_RESET}"
    preview_path = work_file("preview.txt", preview_text)
    preview_lines = preview_text.count("\n") + 1
    # --no-clear: 1つ前の画面（コマンド選びや別の変数）から切り替わるときに、一瞬 popup の裏（元のペイン）が
    # 見えてしまうのを防ぐ（run_builder の最後でまとめて元の画面に戻す）
    # --print-query: 画面を離れるとき、その時点で打っていた（まだ確定していない）文字列も一緒に拾うため
    # （2026-10-28、戻ると打ちかけの値が消えるとの指摘を受けて追加）
    keys = ["enter", "esc", "btab", *CLOSE_KEYS] + (["alt-left"] if can_back else []) + (["alt-right"] if can_fwd else []) \
        + ([UP_KEY] if ui.NAV_UP else [])
    # with-nth: ファイルの画面は元どおり「値\t説明」の2列をそのまま表示（ファイル名の列は長さが
    # バラバラで揃える意味が薄く、c_files の候補はクエリ入力のたびに動的に作り直すため、全候補を
    # 見ての幅計算ができない）。それ以外（opts 等の静的候補）は、2列目に pad_candidate_line /
    # c_typed が作った「そろえた値＋説明」が入っているので、2列目だけを表示する（1,2 のままだと
    # 値が「19700   19700  Kerberoast」のように2回表示されてしまう。2026-10-28、本人の指摘で追加）
    with_nth = "2"   # ファイルの画面も、値の幅をそろえた表示の列（2026-10-30〜。前は「値\t説明」をそのまま）
    # --disabled: 絞り込みは hackdeck 側（pick・files）で、見出しを残すため（2026-10-30〜。前は fzf の --exact で絞っていた）
    args = ["fzf", "--layout=default", "--height=-1", "--ansi", "--disabled", "--no-sort", "--no-select-1", "--no-clear",
            "--color", _fzf_theme_color_opt(),
            "--preview", f"cat {shlex.quote(str(preview_path))}",
            # noinfo: 枠の右上のスクロール位置（「1/3」）を出さない。中身が枠にちょうど収まっていても
            # 出ていて、見た目のノイズになっていた（2026-10-29、本人が選んだ見た目の案に合わせて消した）
            "--preview-window", f"up,{preview_lines},border-rounded,noinfo",
            "--delimiter", "\t", f"--with-nth={with_nth}", "--print-query",
            "--query", query, f"--expect={','.join(keys)}",
            "--bind", "tab:transform-query:hackdeck complete {q} {} {*f}",
            "--bind", f"change:reload({reload_cmd})", "--bind", "load:first"]
    # 見出し・空行にはカーソルを止めない（ui.fzf_run。どの画面も同じ）
    if example_label:
        # 本人が選んだ「ゴースト文字」案（2026-10-28、案5が「ごちゃごちゃしている」との指摘を
        # 受けて6案目として提示）: --ghost は検索ボックスが空のときだけ薄い字で出て、何か打ち
        # 始めると自然に消えるプレースホルダー。候補一覧のすぐ下が検索ボックスだけになり、
        # 罫線（--header-border）も独立行も不要になった。件数表示（N/N）はそのまま残す
        # （AskUserQuestion で「残すか --info=hidden で消すか選べる」と説明したのに、確認せず
        # 消す側で実装してしまっていた。2026-10-28、本人の指摘「水平線＋候補の数があるはずだよね？
        # それがないよ？」で気づいて戻した）。ANSI カラーコードは解釈されない仕様のため、
        # example_label は最初からプレーンテキストで作っている（変数名の色付けは諦めた）
        args += ["--ghost", example_label]
    if cursor_value is not None:
        find_cmd = f"hackdeck findpos {shlex.quote(cursor_value)} {{*f}} {1 if cursor_typed else 0}"
        args += ["--sync", "--bind", f"result:transform:{find_cmd}"]
    map_path = None
    if footer:
        # 流れの図（足もとの2行目から。1行目はタブの並び）。クリックした行を対応表で引き、飛べる変数なら名前を print して
        # 閉じる（c_footclick → c_flowclick）。transform は画面を閉じずにその場で動くので、execute のようなチラつきが無い
        map_path = str(work_file("flow.tsv", "".join(f"{n}\t{1 if ok else 0}\n" for n, ok in footer_map or [])))
    args += foot_args("cmd", footer or [], clickonly=True, flowmap=map_path)
    # 一覧は最初から渡す（start:reload で後から入れると、変数の画面に移るたびに一覧が空の画面が一瞬出た）
    first = subprocess.run(["bash", "-c", reload_cmd.replace("{q}", shlex.quote(query))], env=env,
                           capture_output=True, text=True).stdout
    r = fzf_run(args, "cmd", clickonly=True, input=first, env=env, capture_output=True, text=True, place=place)
    parts = r.stdout.splitlines()
    if not parts:
        return {"key": "", "jump": None, "query": query, "focus": cursor_value, "typed": cursor_typed}
    res = {"key": parts[1] if len(parts) > 1 else "", "jump": None, "query": parts[0]}
    if tab_hit(parts[1:]):
        res["key"] = f"tab:{tab_hit(parts[1:])}"   # タブの並びのクリック
    rest = [l for l in parts[2:] if not l.startswith(TAB_PREFIX)]
    # 図のクリック（print → accept）は、検索語・キーの行のあと、カーソルのある行の前に1行入る
    if rest and rest[0].startswith(JUMP_PREFIX):
        res["jump"] = rest[0][len(JUMP_PREFIX):]
        rest = rest[1:]
    fields = rest[0].split("\t") if rest else []
    res["focus"], res["typed"] = (fields[0] if fields else None), is_typed_row(fields)
    if res["key"] == "enter" and fields and fields[0] == HEADING:
        res["key"] = "heading"   # 見出しの行では Enter しても何もしない（var_screen が同じ画面を出し直す）
    if res["key"] != "enter":
        return res
    if not fields:
        res.update(value=parts[0], shown=parts[0])  # 候補ゼロで Enter: 打った文字をそのまま使う
        return res
    val = fields[0]
    sel_label = fields[1] if len(fields) > 1 else ""
    shown = fields[2] if len(fields) > 2 else val
    # ファイルの画面で選んだ実ファイル（フォルダ・「そのまま使う」行は除く。前者はまだ中へ進む途中、
    # 後者は c_typed() で既に shell_safe() 済み）は、ここでクォートする。navi の頃は候補の値を
    # そのまま埋め込んでいて、ファイル名の空白や記号を考えていなかった（2026-10-28、本人の指摘）
    if is_files and not is_typed_row(fields) and not val.endswith("/"):
        val = shown = path_safe(val)
    res.update(value=val, shown=shown)
    return res


def c_flowclick(map_file, line=None):
    """変数の画面の流れの図（--footer）がクリックされたとき、fzf の click-footer から呼ばれる。押した行が
    飛べる変数（決めた変数と、まだ決めていない最初の変数）なら、その名前を print して画面を閉じる（var_screen が
    その変数の画面を列に足す）。行は FZF_CLICK_FOOTER_LINE（1始まり）だけで決める（クリックした単語の
    FZF_CLICK_*_WORD は誤ることがあるため使わない。1行に変数は1つ）"""
    try:
        line = int(os.environ.get("FZF_CLICK_FOOTER_LINE") or 0) if line is None else line
        rows = Path(map_file).read_text(encoding="utf-8").splitlines()
    except (ValueError, OSError):
        return
    if 1 <= line <= len(rows):
        name, _, ok = rows[line - 1].partition("\t")
        if ok == "1":
            print(f"print({JUMP_PREFIX}{name})+accept")
