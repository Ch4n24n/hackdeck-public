"""fzf から、打つたび・カーソルが動くたび・画面を出すたびに呼ばれる小さな補助（カーソル合わせ・補完・打った値の行・見出しつきの
絞り込み）。毎回 hackdeck を起こし直して走るので、読み込むモジュールを最小にする（2026-11-01、本人の希望「反応速度がはやくなると
嬉しい」。前は prompt・ui・candidates にあり、どれもほぼ全部のモジュールを読んで、1回 0.07 秒かかっていた）。
ほかのモジュールは、使う関数の中でだけ読む（カーソル合わせ・補完は os だけで動く。打った値の行と絞り込みは text、資格情報・
AD の形にする所は、そのときだけ）。"""
import os

HEADING = "hackdeck-heading:"   # 候補の見出しと空行の値（選んでも何もしない。ui.grouped が作る）


def match_at(text, query):
    """打った文字が text のどこに当たるか（当たらなければ -1）。大文字を含まなければ大文字小文字を区別しない（fzf の smart-case）"""
    if not query:
        return 0
    return (text if any(c.isupper() for c in query) else text.lower()).find(query if any(c.isupper() for c in query)
                                                                           else query.lower())


def mark_match(text, query):
    """当たったところに下線（fzf に絞らせていたときの色の代わり）。色の印（ESC[…m）は字に数えず、印の中には引かない（前は印の
    数字にも当たり、案件の丸や配色の見本の色が崩れることがあった）"""
    if not query:
        return text
    from .text import ANSI_RE
    at, pos = [], 0   # 見える字の、text の中の位置
    for m in [*ANSI_RE.finditer(text), None]:
        at += range(pos, m.start() if m else len(text))
        pos = m.end() if m else pos
    i = match_at("".join(text[j] for j in at), query)
    if i < 0:
        return text
    s, e = at[i], at[i + len(query) - 1] + 1
    return f"{text[:s]}\x1b[4m{text[s:e]}\x1b[24m{text[e:]}"


def filter_rows(rows, query):
    """一覧の行 [(印, 見せる字, 探す字)] のうち、打った文字が探す字（その行の字の全部。列の幅で切り詰める前のもの）に当たる行を、
    「印<TAB>見せる字」の形で（当たった所に下線）。打つと一覧を絞る画面は、どれもこれで絞る（見出しのある一覧は filter_grouped。
    2026-11-01、本人の指摘「検索窓があるのに検索ができない画面がある（設定のタブなど）。すべてのタブで統一した作りに」。前は
    設定の項目の一覧が打った文字を使わず、資格情報と設定の一覧の項目は足す値にだけ使い、案件と環境は名前だけで絞っていた）"""
    return [f"{mark}\t{mark_match(shown, query)}" for mark, shown, full in rows if match_at(full, query) >= 0]


def filter_grouped(lines, query):
    """候補の行（見出し・空行を含む。出す順）を、打った文字で絞る。当たった行のあるまとまりだけを見出しつきで残し、まとまりの間に
    空行（2026-10-30、本人の指摘「検索したときの候補にも見出しを」。fzf に絞らせると、見出しの行は打った文字に当たらず消えた）。
    比べるのは表示の列（2列目）"""
    from .text import ANSI_RE
    groups, rows = [], []
    for line in lines:
        f = line.split("\t")
        if f[0] != HEADING:
            rows.append(f)
        elif f[1].strip():
            groups.append((rows, line))
            rows = []
    if rows:
        groups.append((rows, None))
    kept = []
    for rows, head in groups:
        hit = [f for f in rows if len(f) > 1 and match_at(ANSI_RE.sub("", f[1]), query) >= 0]
        if hit:
            kept.append(["\t".join([f[0], mark_match(f[1], query), *f[2:]]) for f in hit] + ([head] if head else []))
    flat = []
    for i, g in enumerate(kept):
        flat += g + ([f"{HEADING}\t \t"] if i + 1 < len(kept) else [])
    return flat


def read_lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def is_typed_row(fields):
    """候補の1行（タブで分けた欄）が、先頭の「打った値をそのまま使う」行（c_typed が作る）か"""
    return len(fields) > 1 and fields[1].endswith("そのまま使う")


def c_typed(query):
    """prompt_var の変数の画面で、打っている文字をそのまま使う候補を先頭に出す（打つたびに作り直す）。
    クエリが空でも出す（候補が無い場所で迷わないように。2026-10-28、本人の指摘で常時表示に変更）。
    値は shell_safe() を通す（特殊文字があればクォートする。2026-10-28、本人の指摘）。
    HACKDECK_VAL_W（prompt_var が立てる環境変数）があれば、他の候補と同じ幅に値をそろえてから
    「そのまま使う」を続ける（2026-10-28、値と説明の開始位置を行ごとに合わせる対応の一部）"""
    from .text import fit, shell_safe
    # コマンド帳の行で '…' か "…" の中にある変数は、打った文字を囲まずにそのまま入れる（var_screen が HACKDECK_TYPED_RAW を
    # 立てる。2026-10-30。囲むと hydra の "…:F=失敗の文" や ffuf の -d "…&…" の中に ' が入って壊れた）
    val = query if os.environ.get("HACKDECK_TYPED_RAW") else shell_safe(query)
    val_w = int(os.environ.get("HACKDECK_VAL_W") or 0)
    fmt = os.environ.get("HACKDECK_TYPED_CRED")
    if fmt and query and not query.startswith("-"):
        from .creds import parse_cred_line
        c = parse_cred_line(query)
        if c and c["kind"] in ("pass", "nt") and not (fmt == "e4l" and c["kind"] == "nt"):   # enum4linux-ng はパスワードだけ
            # 資格情報を先に選ぶ画面では、打った user:pass（:範囲（説明） も書ける）をその道具の渡し方にする（2026-10-30。資格
            # 情報のタブには足さない。本人の指摘「自動で保存するとゴミみたいな情報が集まる」）
            from .cand_auth import AUTHCREDS_TARGET, authcred_value
            val, shown = authcred_value(fmt, os.environ.get(AUTHCREDS_TARGET.get(fmt, ""), ""), c)
            print(f"{val}\t{fit(shown, val_w)}  そのまま使う\t{shown}" if val_w else f"{val}\t{shown}  そのまま使う\t{shown}")
            return
    ad = os.environ.get("HACKDECK_TYPED_AD")
    if ad and query:
        # dacledit・owneredit の対象は、打った名前・DN・SID をオプションの形に（adtarget_value）
        from .cand_auth import adtarget_value
        val = adtarget_value(ad, query)
        print(f"{val}\t{fit(query, val_w)}  そのまま使う\t{query}" if val_w else f"{val}\t{query}  そのまま使う\t{query}")
        return
    # out() だと value（1列目 = 選んだときに返す実際の値）までパディングしてしまうので使わない。
    # pad_candidate_line と同じ形（値\t そろえた表示）で、1列目は打った値そのままにする
    print(f"{val}\t{fit(val, val_w)}  そのまま使う" if val_w else f"{val}\tそのまま使う")


def c_pick(query, items_file):
    """変数の画面の候補（打つたびに作り直す。fzf には絞らせない）。先頭に打った値の行、空行をはさんで、打った文字で絞った候補
    （見出しつき。filter_grouped）。空行は本人の指摘「そのまま使うとその上には1行あけたほうが見栄えがいい」"""
    c_typed(query)
    rows = filter_grouped(read_lines(items_file), query)
    if rows:
        print(f"{HEADING}\t \t")
        print("\n".join(rows))


def c_complete(query, current, items_file):
    """Tab: カーソルがフォルダ（値が / で終わる）の行にあれば、即その中へ（navi の「Tab で中へ」どおりの動き。
    カーソル位置を見ずクエリだけで共通部分を計算していたため、フォルダを選んでいても他の候補との
    共通部分までしか進まず、中に入れなかった。2026-10-28、本人の指摘で直した）。
    それ以外は、いま出ている候補（{*f}）のうち、打った文字で始まるものの共通の部分まで伸ばす。
    候補が1つなら、その値にする。
    「打った値をそのまま使う」行（値がクエリと同じ）は、常に自分自身で頭打ちになって
    補完が進まなくなるので、他に候補があれば外す（2026-10-28）"""
    current_val = current.split("\t", 1)[0] if current else ""
    if current_val.endswith("/"):
        print(current_val)
        return
    rows = [l.split("\t") for l in read_lines(items_file) if l and not l.startswith(HEADING)]
    vals = [f[0] for f in rows if not is_typed_row(f)] or [f[0] for f in rows]
    if len(vals) == 1:
        print(vals[0])
        return
    pre = [v for v in vals if v.lower().startswith(query.lower())]
    common = os.path.commonprefix([v.lower() for v in pre]) if pre else ""
    print(pre[0][:len(common)] if len(common) > len(query) else query)


def c_casepos(query=""):
    """案件のタブで、打って候補が変わったときのカーソル（fzf の load から）。打った文字に当たる案件があれば（新しい案件の行の
    ほかにも行が残っていれば。絞るのは c_caserows）、その先頭（新しい案件の行のすぐ上）。無ければ新しい案件の行"""
    hit = query.strip() and int(os.environ.get("FZF_TOTAL_COUNT") or 0) > 1
    print("pos(2)" if hit else "first")


def replay():
    """前にこの画面を出していたときのカーソルの動き（向きの変わった所）をたどり直す pos(…)+ の並び。ui.fzf_run が覚えて
    HACKDECK_REPLAY で渡す。最初の画面を描く前に動かすので、一覧の見え方が前と同じになる（途中の動きは見えない）"""
    return "".join(f"pos({p})+" for p in os.environ.get("HACKDECK_REPLAY", "").split() if p.isdigit())


def c_findpos(value, items_file, typed="1"):
    """変数の画面を Alt+← → Alt+→ でたどり直すとき、検索語はそのまま（例: "10"）にしつつ、
    カーソルだけ確定していた値（例: "10900"）に合わせるために使う。
    いま出ている候補（{*f}、result イベントの時点＝絞り込み結果が確定した後）の中から value と
    一致する行を探し、fzf の pos(N) を出す（--bind result:transform:... から呼ばれ、出力が
    そのままアクションとして実行される）。この先もう打ち直す可能性があるので、毎回のジャンプは
    うるさい。最初の1回だけ効けばいいので、見つかった／見つからなかったに関わらず、続けて
    unbind(result) も出して以後は呼ばれないようにする（2026-10-28、本人の指摘で追加）。
    typed が "0" なら「そのまま使う」行には合わせない（打った文字と同じ値の候補があるとき、カーソルがあった方の
    行へ戻すため。2026-10-29）"""
    hits = [idx for idx, line in enumerate(read_lines(items_file))
            if (fields := line.split("\t"))[0] == value and (typed == "1" or not is_typed_row(fields))]
    if not hits:
        print("unbind(result)")
        return
    # 同じ値の行が複数あれば（見出しと空行はどれも同じ値）、前のカーソルの位置にいちばん近い行（2026-11-01。前は最初の行へ
    # 飛び、配色の一覧で見出しの行で Enter すると、別の見出しへ移っていた）
    last = [int(p) for p in os.environ.get("HACKDECK_REPLAY", "").split() if p.isdigit()]
    idx = min(hits, key=lambda i: abs(i + 1 - last[-1])) if last else hits[0]
    print(f"{replay()}pos({idx + 1})+unbind(result)")


def c_findidx(idx, items_file):
    """コマンド選びの画面（候補行は "idx\\x1f..." 形式。idx は rows 内の絶対位置、0始まり）で、
    Alt+← → Alt+→ とたどり直すとき、検索語（例: "hashcat"）はそのまま残しつつ、カーソルだけ
    直前に選んでいたコマンドに合わせるために使う。c_findpos と同じ考え方（result イベント＋
    unbind(result) で最初の1回だけ合わせる）だが、値ではなく各行の先頭の隠し列（idx）で比較する
    （2026-10-28、「コマンド選択画面でも検索語を残してほしい」との指摘で追加）"""
    for pos, line in enumerate(read_lines(items_file)):
        if line.split("\x1f", 1)[0] == idx:
            print(f"{replay()}pos({pos + 1})+unbind(result)")
            return
    print("unbind(result)")
