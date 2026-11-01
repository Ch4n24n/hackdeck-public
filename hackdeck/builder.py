"""画面を回す本体（run_builder）。列の1つずつに合う画面を出し、戻ってきた操作で列を動かす。

案件のセッションの外（case.case_root() が None）は、案件と設定のタブだけ（ui.tabs）。"""
from .case import case_root
from .env import env_vars
from .session import case_open
from .history import history_append
from .cand_files import write_used_lists
from .cheatbook import parse_cheat_files
from .flow import flow_overview, flow_rows_max
from .nav import home_entry, nav_adopt, nav_load, nav_only, nav_push, nav_save, nav_saved, nav_step, tab_entry, up_entry
from .tab_cmd import list_screen, picker_screen, var_screen
from .tab_creds import creds_screen, nxc_screen
from .tab_env import env_screen
from .tab_case import case_screen
from .tab_memo import memo_screen
from .tab_settings import settings_screen
from . import theme
from . import ui


def run_builder(base_env):
    """1回分。組み立てた文字列（閉じたら空）を返し、できたら履歴に積む。開くと、閉じる直前の画面から始まる。案件の
    セッションの外は、案件のタブ（閉じる直前が設定のタブならそこ）から始まる"""
    entries, defs = parse_cheat_files()
    # 説明欄の高さ。コマンド選びの図と、変数の画面の図（枝を開いた分と、下の空行・注意書き1つ）のうち、いちばん高いもの
    # （2026-10-30。1番を作り直してコマンド選びの図が短くなり、変数の画面の方が高くなったので、両方を見る）
    ui.FOOT_ROWS = max((max(len(flow_overview(r["command"], defs)[0]), flow_rows_max(r["command"], defs) + 2)
                     for r in entries if r.get("where")), default=0)
    ui.work_clean()   # 止められた窓が残した作業の置き場所（~/.cache/hackdeck/run/<番号>/）を消す
    nav_adopt(case_root())   # 前の形（案件の場所ごと）の列のファイルなら、案件の目印ごとへ移す
    nav = nav_load()
    inside = case_root() is not None
    nav_only(nav, [k for k, _ in ui.tabs()])   # 出していないタブの画面は外す（案件の外のコマンド・切ったメモ）
    cur = nav["entries"][nav["index"]] if nav["entries"] else None
    if cur is None:
        nav_push(nav, tab_entry(nav, "case") if not inside else {"s": "picker", "q": "", "f": None})
    result, attach = "", None
    try:
        with open("/dev/tty", "w") as tty:
            # 代わりの画面に1回だけ入る（各画面の fzf は入り直さない）。カーソルは隠す（fzf_run）。背景を変えるテーマは地の色で消す
            tty.write(f"\x1b[?1049h\x1b[?25l{theme.C_BASE}\x1b[H\x1b[2J\x1b[0m")
    except OSError:
        pass
    env_names = {n for n, _ in env_vars()}   # 開いたときに環境変数のファイルにあった名前
    try:
        while True:
            e = nav["entries"][nav["index"]]
            back, fwd = nav_step(nav, -1, defs), nav_step(nav, 1, defs)
            ui.NAV_UP = up_entry(nav, e, defs) is not None
            if e["s"] == "var":
                # 環境のタブで変えた値も、次の変数の候補から効くように、ファイルのいまの中身に差し替える（消した名前は外す）
                env = {**{k: v for k, v in base_env.items() if k not in env_names}, **dict(env_vars())}
                act = var_screen(nav, e, defs, env, back is not None, fwd is not None)
            elif e["s"] == "creds":
                act = creds_screen(e, back is not None, fwd is not None)
            elif e["s"] == "nxc":
                act = nxc_screen(e, back is not None, fwd is not None)
            elif e["s"] == "env":
                act = env_screen(e, back is not None, fwd is not None)
            elif e["s"] == "case":
                act = case_screen(e, back is not None, fwd is not None)
            elif e["s"] == "memo":
                act = memo_screen(e, back is not None, fwd is not None)
            elif e["s"] == "settings":
                act = settings_screen(e, back is not None, fwd is not None)
            elif e["s"] == "history":
                act = list_screen(e, back is not None, fwd is not None)
            else:
                act = picker_screen(nav, e, entries, defs, back is not None, fwd is not None)
            kind, arg = act[0], (act[1] if len(act) > 1 else None)
            if kind == "back" and back is not None:
                nav["index"] = back
            elif kind == "forward" and fwd is not None:
                nav["index"] = fwd
            elif kind == "up":   # Alt+↑（いちばん上の画面では何もしない）
                up = up_entry(nav, e, defs)
                if up:
                    nav_push(nav, up)
            elif kind in ("back", "home"):   # 戻る先が無い（配色を選んだ等）ときもコマンド選びへ（案件の外は案件のタブへ）
                nav_push(nav, home_entry(nav, arg) if inside else tab_entry(nav, "case"))
            elif kind == "push":
                nav_push(nav, arg)
            elif kind == "tab":
                nav_push(nav, tab_entry(nav, arg))
            elif kind == "tabhome":   # そのタブの初期画面（検索語もカーソルも空。設定は3項目）
                nav_push(nav, {"s": "creds", "tab": arg, "q": "", "f": None, "e": None} if arg == "creds"
                         else {"s": arg, "q": "", "f": None, "e": None})
            elif kind == "saved":
                nav_saved(nav, arg)
            elif kind == "done":
                result = arg
                write_used_lists(arg)   # 使う一覧だけを置き場所に作る（履歴から出し直したときも、いまの中身で）
                # 次に開くとコマンド選びから。Alt+← で、組み終えたコマンドの最後の画面に戻って直せる（おすすめ3）
                nav_push(nav, {"s": "picker", "q": "", "f": None})
                break
            elif kind == "attach":
                attach = arg
                break
            elif kind == "close":
                break
            nav_save(nav)   # 画面を移るたびに残す（窓ごと落ちても、直前の画面から開き直せる）
    except KeyboardInterrupt:
        result = ""
    finally:
        nav_save(nav)
        ui.work_clean(mine=True)   # この窓の作業の置き場所
        # 各画面は --no-clear（切り替え時のちらつき防止）で、終了時に自分で画面を戻していないので、
        # 全部終わったこの時点でまとめて元の画面に戻す（fzf の --no-clear の注記にある tput rmcup 相当）
        try:
            with open("/dev/tty", "w") as tty:
                tty.write("\x1b[?1049l\x1b[?25h")   # 隠したカーソルも戻す
        except OSError:
            pass
    if attach:
        case_open(attach)   # 画面を元に戻したあとで、案件のセッションに入る（tmux の外は、このプロセスが tmux に置き換わる）
    if result:
        history_append(result)
    return result
