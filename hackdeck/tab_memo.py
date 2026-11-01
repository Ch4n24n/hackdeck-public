"""メモのタブ（設定の「メモのタブ」で出す。2026-11-01、本人の提案「簡単なメモをするときに使えたら便利。Lab のたびに Obsidian で
整理するのは面倒」）。案件ごとの軽いメモを、本物の vim（自分の .vimrc のまま）で書く。データの置き場所（.hack）の memo.md。

キー: ノーマルモードの Tab・Shift+Tab でタブを移る（GNOME Terminal は Ctrl+Tab を Tab と同じに送る。挿入モードの Tab は字下げ、
←・→ はカーソル移動のまま）。Ctrl+G はどのモードでも窓を閉じる。:q・:wq も窓を閉じる。タブを移るとき・閉じるとき・手を止めた
とき（0.5秒）に保存し、:w でも保存する（確かめは出さない）。

見た目はほかのタブと同じ（2026-11-01、本人の指摘「他のタブはタブの下に１行スペースが開いている。平仄は合わせたほうがいいかも」
「説明欄とか、色々も他のタブと合わせたほういいかな」）: いちばん上の行にタブの並び、1行あけて上の枠（題・置き場所・キー）、説明欄、線、その下が書く所。
上の枠から線までは、vim の上の窓（書けない。入ろうとすると書く所へ戻す）に、ほかの画面の fzf と同じ字と色で描く。"""
import json
import os
import shutil
import subprocess

from .case import case_root, state_of
from .paths import CACHE_DIR
from .text import display_width, short_home
from .ui import nav_key, tabs, work_dir
from . import settings
from . import theme
from . import ui

MEMO_VIM = CACHE_DIR / "memo.vim"   # vim に読ませる設定（開くたびに作り直す。配色とタブの並びに合わせるため）
EXIT_KEYS = {10: "tab", 11: "btab"}   # vim を :cquit で終えた番号 → タブを移るキー（ほかの終わり方は窓を閉じる）
# 前の画面の上にそのまま描く（2026-11-01、本人の指摘「メモタブに移動すると、チカチカする」。vim は起動すると、代わりの画面に入り
# 直し（t_ti）、画面を全部消して（t_cl）から描き、端末を調べるために2〜3行目に試しの字を書いて消していた（t_u7。上の枠の角が一瞬
# 消えた）。消せないと、vim は全部のマスを描き直す（ほかの画面の fzf と同じ）。--cmd は端末の設定を読んだあと、.vimrc と起動の
# 描画より前に効く。t_te が空なので、閉じても窓の代わりの画面のまま（次の画面を描くまで前の画面が見えたりしない）
VIM_EARLY = "set t_ti= t_te= t_cl= t_u7="
# 上の枠の線（fzf が --preview-window の border-<形> で描くのと同じ字）。左上・横・右上・左・右・左下・下・右下
BOX = {"rounded": "╭─╮││╰─╯", "sharp": "┌─┐││└─┘", "bold": "┏━┓┃┃┗━┛", "double": "╔═╗║║╚═╝", "dashed": "╭╶╮┆┆╰╶╯",
       "block": "▛▀▜▌▐▙▄▟", "thinblock": "🭽▔🭾▏▕🭼▁🭿"}


def memo_file(root=None):
    """その案件のメモ（データの置き場所の memo.md）"""
    return state_of(root or case_root()) / "memo.md"


def x256(color):
    """16進の色（ff9e64）に近い、端末の256色の番号（vim が真の色を使っていないときの色）"""
    rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
    steps = [0, 95, 135, 175, 215, 255]
    cube = [min(range(6), key=lambda i: abs(steps[i] - c)) for c in rgb]
    gray = min(range(24), key=lambda i: abs(8 + 10 * i - sum(rgb) / 3))
    cands = [(16 + 36 * cube[0] + 6 * cube[1] + cube[2], [steps[i] for i in cube]), (232 + gray, [8 + 10 * gray] * 3)]
    return min(cands, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[1], rgb)))[0]


def frame():
    """上の枠の形（fzf の形と同じ）。line は下に線だけ、horizontal は上と下に線だけ（どちらも左右の線と字の前の空白が無い）。
    罫線を使わない配色（--no-unicode）は + - |"""
    h = "-" if theme.ASCII else "─"
    if theme.FRAME in ("line", "horizontal"):
        return {"top": theme.FRAME == "horizontal", "side": False, "chars": ["", h, "", "", "", "", h, ""]}
    return {"top": True, "side": True, "chars": list("+-+||+-+" if theme.ASCII else BOX.get(theme.FRAME, BOX["rounded"]))}


def info(root, f):
    """上の窓に描くもの（ほかのタブと同じ決まり: 上の枠は題・置き場所・キー、説明欄は1行目がファイルと中身、2行目からは
    書き方。字と色の組 [字, 色の名前] の並びで、行ごとに）"""
    hints = ["i 書く", "Esc 書くのをやめる", ":w 保存", ":q・Ctrl+G 閉じる"]
    box = [[["メモ", "HackdeckTitle"], [" ", ""], [f"[{root.name}]", "HackdeckScope"]],
           [["置き場所", "HackdeckHint"], [f" {short_home(f)}", ""]],
           [["  ".join(hints), "HackdeckHint"]]]
    srcs = [(f.name, "この案件の軽いメモ。中身は自由（Markdown で書いてもよい）"),
            ("書き方", "本物の vim（自分の .vimrc のまま）。挿入モードの Tab は字下げ、←・→ はカーソルの移動"),
            ("残し方", "タブを移る・閉じる・手を止める（0.5秒）と、そのつど保存する（確かめは出さない）")]
    w = max(display_width(n) for n, _ in srcs)
    foot = [[[n, ""], [" ", ""], ["─" * (w - display_width(n) + 1), "HackdeckDash"], [f" {d}", ""]] for n, d in srcs]
    return {"box": box, "foot": foot, "rows": max(ui.FOOT_ROWS, len(foot)), "frame": frame(),
            "line": "-" if theme.ASCII else "─"}


def vim_script():
    """vim に -S で読ませる設定。自分の .vimrc のあとに読むので、ここのキーが勝つ"""
    t = theme.THEMES[theme.CURRENT_THEME]
    root = case_root()

    def hl(group, color, attr="NONE"):
        return (f"highlight {group} guifg=#{color} ctermfg={x256(color)} guibg=NONE ctermbg=NONE "
                f"gui={attr} cterm={attr}")

    # 枠と線の色は fzf と同じ（背景を変えない配色は fzf の既定の 59 番、変える配色はその配色の線の色）
    border = (f"highlight HackdeckBorder guifg=#{t.get('border') or t['hint']} ctermfg={x256(t.get('border') or t['hint'])} "
              if t.get("bg") else "highlight HackdeckBorder guifg=#5f5f5f ctermfg=59 ") \
        + "guibg=NONE ctermbg=NONE gui=NONE cterm=NONE"
    # いちばん上の行に、ほかの画面と同じタブの並び（いまのタブを太字・下線・色付き）と、右端にタブの移り方（窓が狭いときは
    # 右から切る）。右端を1マスあけるのは、ほかの画面と同じ（ui.tab_line）
    names = "  ".join(f"%#HackdeckTabCur#{n}%#HackdeckTab#" if k == "memo" else n for k, n in tabs())
    tabline = (f"%#HackdeckTab#{names}%<%=%#HackdeckLine#│%#HackdeckTab# タブの移動 Ctrl+Tab（次）・Ctrl+Shift+Tab（前）"
               "  ここではノーマルモードで ")
    data = json.dumps(info(root, memo_file(root)), ensure_ascii=False).replace("'", "''")
    return "\n".join([
        '" hackdeck のメモのタブ（hackdeck が開くたびに作る。手で直さない）',
        "set noswapfile nobackup nowritebackup autowriteall updatetime=500",
        # .vimrc で undo のファイルを入れていて、置き場所が既定（同じフォルダ）なら、.hack に作らない
        "if &undofile && &undodir ==# '.' | set noundofile | endif",
        # 書く所の下に、ファイルの名前の行を出さない（上の窓を足すと、既定の 1 では2つの窓のどちらにも出る）
        "if &laststatus == 1 | set laststatus=0 | endif",
        "augroup hackdeck_memo",
        "  autocmd!",
        "  autocmd InsertLeave,TextChanged,CursorHold,CursorHoldI,VimLeavePre * silent! update",
        # 終わるときにカーソルを出さない（次の画面を描くまで、左下にカーソルが一瞬出ていた。:cquit は VimLeavePre を通らない
        # ので、タブを移るキーでも空にする）
        "  autocmd VimLeavePre * set t_ve=",
        "  autocmd ColorScheme * call s:hackdeck_colors()",
        "augroup END",
        "function! s:hackdeck_colors() abort",
        "  " + hl("HackdeckTab", t["hint"]),
        "  " + hl("HackdeckTabCur", t["comment"], "bold,underline"),
        "  " + hl("HackdeckLine", "5f5f5f"),
        "  " + hl("HackdeckTitle", t["comment"]),
        "  " + hl("HackdeckScope", t["tag"]),
        "  " + hl("HackdeckHint", t["hint"]),
        "  " + hl("HackdeckDash", "5f5f5f"),
        "  " + border,
        "endfunction",
        "call s:hackdeck_colors()",
        # 背景を変える配色は、vim にも地の明るさを伝える（明るい地に、暗い地向けの淡い色で書かないように。変えると vim が色を
        # 読み直すので、こちらの色も塗り直す）
        *([f"set background={'light' if sum(int(t['bg'][i:i + 2], 16) for i in (0, 2, 4)) > 3 * 128 else 'dark'}",
           "call s:hackdeck_colors()"] if t.get("bg") else []),
        "set showtabline=2",
        "let &tabline = '" + tabline.replace("'", "''") + "'",
        "nnoremap <silent> <Tab> <Cmd>silent! wall<Bar>set t_ve=<Bar>cquit 10<CR>",
        "nnoremap <silent> <S-Tab> <Cmd>silent! wall<Bar>set t_ve=<Bar>cquit 11<CR>",
        "noremap <silent> <C-g> <Cmd>silent! wall<Bar>qall!<CR>",
        "inoremap <silent> <C-g> <Cmd>silent! wall<Bar>qall!<CR>",
        "let s:info = json_decode('" + data + "')",
        INFO_VIM,
    ]) + "\n"


# 上の窓（上の枠・説明欄・線）。書く所（memo.md の窓）の上に、高さを決めた書けない窓を置き、ほかの画面の fzf と同じ字と色で
# 描く。線は、その窓の状態の行（vim は、上下に並べた窓の上の窓に、いつも状態の行を出す）。入ろうとしたら書く所へ戻し、
# 高さ・ずれを変えられたら戻す。:q では先に上の窓を閉じる（書く所だけになって、vim が終わる）
INFO_VIM = r"""
function! s:fit(segs, width) abort
  " 字と色の組の並びを、見た目の幅 width に入るだけに（入らなければ ·· で切る）。戻り値は [並び, 使った幅]
  let out = []
  let used = 0
  for [text, group] in a:segs
    let tw = strdisplaywidth(text)
    if used + tw <= a:width
      call add(out, [text, group])
      let used += tw
      continue
    endif
    let cut = ''
    for ch in split(text, '\zs')
      if used + strdisplaywidth(cut . ch) + 2 > a:width
        break
      endif
      let cut .= ch
    endfor
    if used + strdisplaywidth(cut) + 2 <= a:width
      call add(out, [cut . '··', group])
      let used += strdisplaywidth(cut) + 2
    endif
    break
  endfor
  return [out, used]
endfunction

function! s:render() abort
  if win_id2win(s:info_win) == 0
    return
  endif
  let width = &columns
  let f = s:info.frame
  let [c_tl, c_t, c_tr, c_l, c_r, c_bl, c_b, c_br] = f.chars
  let out = [[]]
  if f.top
    call add(out, [[c_tl . repeat(c_t, width - strdisplaywidth(c_tl . c_tr)) . c_tr, 'HackdeckBorder']])
  endif
  for segs in s:info.box
    if f.side
      let [fit, used] = s:fit(segs, width - 4)
      call add(out, [[c_l . ' ', 'HackdeckBorder']] + fit + [[repeat(' ', width - 4 - used) . ' ' . c_r, 'HackdeckBorder']])
    else
      call add(out, s:fit(segs, width)[0])
    endif
  endfor
  call add(out, [[c_bl . repeat(c_b, width - strdisplaywidth(c_bl . c_br)) . c_br, 'HackdeckBorder']])
  for segs in s:info.foot
    call add(out, [['  ', '']] + s:fit(segs, width - 2)[0])
  endfor
  for n in range(s:info.rows - len(s:info.foot))
    call add(out, [])
  endfor
  let lines = map(copy(out), {i, segs -> join(map(copy(segs), {j, seg -> seg[0]}), '')})
  call setbufvar(s:info_buf, '&modifiable', 1)
  call setbufline(s:info_buf, 1, lines)
  if len(getbufline(s:info_buf, 1, '$')) > len(lines)
    call deletebufline(s:info_buf, len(lines) + 1, '$')
  endif
  call setbufvar(s:info_buf, '&modifiable', 0)
  call prop_clear(1, len(lines), {'bufnr': s:info_buf})
  for i in range(len(out))
    let col = 1
    for [text, group] in out[i]
      if group !=# '' && text !=# ''
        call prop_add(i + 1, col, {'length': strlen(text), 'type': group, 'bufnr': s:info_buf})
      endif
      let col += strlen(text)
    endfor
  endfor
  let s:info_height = len(lines)
  call setwinvar(s:info_win, '&statusline', '%#HackdeckBorder#' . repeat(s:info.line, width))
  call s:keep_info()
endfunction

function! s:keep_info() abort
  " 上の窓の高さと見えている所を、決めたとおりに（マウスで線を動かす・ホイールで動かす、などのあと）
  if win_id2win(s:info_win) == 0
    return
  endif
  if winheight(s:info_win) != s:info_height
    call win_execute(s:info_win, 'resize ' . s:info_height)
  endif
  call win_execute(s:info_win, 'if line("w0") != 1 || winsaveview().leftcol != 0 | call winrestview({"topline": 1, "lnum": 1, "col": 0, "leftcol": 0}) | endif')
endfunction

function! s:leave_info() abort
  " 上の窓には入らない（クリックしても書く所へ）。書く所が無くなっていたら終える
  if win_id2win(s:main_win) > 0
    call win_gotoid(s:main_win)
  else
    call timer_start(0, {-> execute('silent! wall | qall!')})
  endif
endfunction

function! s:close_info() abort
  if win_id2win(s:info_win) > 0 && win_getid() == s:main_win
    execute win_id2win(s:info_win) . 'close'
  endif
endfunction

let s:main_win = win_getid()
let s:info_height = 0
topleft new
let s:info_win = win_getid()
let s:info_buf = bufnr()
setlocal buftype=nofile bufhidden=wipe noswapfile nobuflisted noundofile nomodifiable
setlocal nonumber norelativenumber nolist nowrap nospell nocursorline nocursorcolumn
setlocal signcolumn=no foldcolumn=0 colorcolumn= winfixheight scrolloff=0 sidescrolloff=0
for s:name in ['HackdeckBorder', 'HackdeckTitle', 'HackdeckScope', 'HackdeckHint', 'HackdeckDash']
  call prop_type_add(s:name, {'highlight': s:name, 'bufnr': s:info_buf})
endfor
call win_gotoid(s:main_win)
call s:render()
augroup hackdeck_memo_info
  autocmd!
  autocmd WinEnter * if win_getid() == s:info_win | call s:leave_info() | endif
  autocmd QuitPre * call s:close_info()
  autocmd VimResized * call s:render()
  autocmd WinResized,WinScrolled * call s:keep_info()
augroup END
"""


def memo_screen(e, can_back, can_fwd):
    """メモのタブの画面。vim を開き、終わり方でタブを移るか窓を閉じる。戻り値は var_screen と同じ"""
    if not settings.get("memo") or case_root() is None:
        return ("tab", "case")   # 切ったあとに Alt+← などで戻ってきたとき
    f = memo_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    MEMO_VIM.parent.mkdir(parents=True, exist_ok=True)
    MEMO_VIM.write_text(vim_script(), encoding="utf-8")
    exe = shutil.which("vim") or shutil.which("vi")
    if exe is None:
        return ("tab", "case")   # vim が無い（窓ごと落ちないように、次のタブへ）
    with open("/dev/tty", "r+b", buffering=0) as tty:
        r = subprocess.run([exe, "-n", "--cmd", VIM_EARLY, "-S", str(MEMO_VIM), str(f)], stdin=tty, stdout=tty, stderr=tty,
                           env={**os.environ, "TMPDIR": str(work_dir())})   # vim の一時ファイルも、窓の作業の置き場所に
        tty.write(b"\x1b[?25l")   # カーソルは隠したまま（ほかの画面と同じ。fzf_run）
    key = EXIT_KEYS.get(r.returncode)
    return nav_key(key, "memo") if key else ("close",)
