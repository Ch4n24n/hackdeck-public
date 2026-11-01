#!/usr/bin/python3 -I
"""雛形の既定と、雛形の git リポジトリから案件を作る流れを確かめる（2026-11-02。雛形は hackdeck から分けて、別のリポジトリ
Hacking-Op-public にした。本人「template の考え方と hackdeck を混ぜたのが良くなかった。リポジトリを分けたほうがいい」。既定は、その
リポジトリを HTTPS で clone する。本人「SSH 経由でクローンしているので、やるとしたら HTTP 経由になる」）。

  python3 -I tests/template.py

ネットにはつながない: 雛形の既定は値だけを確かめ、clone は試しの中で作った小さな雛形の git リポジトリで確かめる。偽の HOME
（一時フォルダ）で、tmux には触らない（案件を作るだけで、始めない）。OK・NG を出し、NG があれば終わりの状態 1。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []
BOX = {"work": "02-作業", "state": "02-作業/.hack", "log": "91-ログ/実行ログ.log"}
URL = "https://github.com/Ch4n24n/Hacking-Op-public.git"


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"{'OK' if ok else 'NG'}  {name}" + (f"  … {detail}" if detail and not ok else ""))


def env_of(t):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "ZDOTDIR", "HACK_ROOT") and not k.startswith("XDG_")
           and not k.startswith("HACKDECK_") and not k.startswith("GIT_")}
    env.update(HOME=str(t / "home"), TMUX_TMPDIR=str(t / "tmux"), HACKDECK_TMUX_SOCKET="hdtemplate", LANG="C.UTF-8",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return env


def py(env, code):
    """偽の HOME の hackdeck を読み込んで code を走らせ、最後の行の JSON を返す"""
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys, json; sys.path.insert(0, {str(ROOT)!r}); {code}"],
                       env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


LAYOUT = ("from pathlib import Path; from hackdeck import case; "
          "f = lambda r: {'work': str(case.work_of(r).relative_to(r)), 'state': str(case.state_of(r).relative_to(r)), "
          "'log': str(case.log_of(r).relative_to(r)) if case.log_of(r) else '', 'is_case': case.is_case_dir(r), "
          "'home': case.case_env(r)['HACK_HOME'], 'logenv': case.case_env(r)['HACK_LOG']}; ")


def make(env, name):
    return subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "make", name], env=env, capture_output=True, text=True)


def fixture(d, env):
    """雛形の git リポジトリの、小さな写し（番号のフォルダと CLAUDE.md）"""
    for f in ("02-作業/.gitkeep", "91-ログ/.gitkeep", "01-メモ/雑記.md", "10-現在地.md", "CLAUDE.md"):
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text("試し\n", encoding="utf-8")
    g = lambda *a: subprocess.run(["git", "-C", str(d), *a], env=env, capture_output=True, text=True, check=True)
    g("init", "-q", "-b", "main")
    g("add", "-A")
    g("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "雛形")


def main():
    t = Path(tempfile.mkdtemp(prefix="hackdeck-template."))
    try:
        for d in ("home", "tmux", "tpl"):
            (t / d).mkdir()
        env = env_of(t)
        cases = t / "home" / "cases"

        # 既定（設定を何も書いていない＝公開版を入れたばかりの人）
        got = py(env, "from hackdeck import settings, session; print(json.dumps([settings.get('template'), session.template_kind()]))")
        check("雛形の既定は、雛形のリポジトリの HTTPS の URL", got[0] == URL, got[0])
        check("その既定は git として clone する", got[1] == "git", got[1])
        got = py(env, "from hackdeck import settings; print(json.dumps([settings.get(k) for k in ('work_dir', 'state_dir', 'log_file')]))")
        check("場所の3つの既定は、雛形の形（02-作業・02-作業/.hack・91-ログ/実行ログ.log）", tuple(got) == tuple(BOX.values()), got)

        # 雛形の git リポジトリから作る（ネットの代わりに、手元に作った小さな雛形）
        fixture(t / "tpl", env)
        py(env, f"from hackdeck import settings; settings.save(template={str(t / 'tpl')!r}); print(json.dumps(1))")
        r = make(env, "box")
        check("雛形の git リポジトリから案件を作れる（clone）", r.returncode == 0, r.stderr[-300:])
        box = cases / "box"
        check("雛形の中身が来る（CLAUDE.md・番号のノート）・clone なので .git もある",
              all((box / n).exists() for n in ("CLAUDE.md", "10-現在地.md", "01-メモ", ".git")))
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(box)!r}))))")
        check("作業フォルダ・データの置き場所・ログは、雛形の形", (got["work"], got["state"], got["log"]) == tuple(BOX.values()), str(got))
        check("案件として見える（作業フォルダがある）", got["is_case"])
        check("セッションの環境（HACK_HOME・HACK_LOG）も雛形の形",
              got["home"] == str(box / BOX["work"]) and got["logenv"] == str(box / BOX["log"]), f"{got['home']} {got['logenv']}")
        ls = subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "ls"], env=env, capture_output=True, text=True)
        check("hackdeck case ls に出る", "box" in ls.stdout, ls.stdout[-300:] + ls.stderr[-300:])

        # 雛形を空にすると、作業フォルダとログの置き場所だけ
        py(env, "from hackdeck import settings; settings.save(template=''); print(json.dumps(1))")
        make(env, "plain")
        plain = cases / "plain"
        check("雛形を空にすると、作業フォルダとログの置き場所だけ",
              (plain / BOX["work"]).is_dir() and (plain / BOX["log"]).parent.is_dir() and not (plain / "CLAUDE.md").exists(),
              str(sorted(p.name for p in plain.iterdir())))

        # 設定に書いた場所が既定より先（本人の環境のように、雛形と場所を自分で決める人）
        py(env, "from hackdeck import settings; settings.save(work_dir='work', state_dir='work/.hack', log_file='logs/session.log');"
                " print(json.dumps(1))")
        make(env, "mine")
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(cases / 'mine')!r}))))")
        check("設定に書いた場所が既定より先（work・work/.hack・logs/session.log）",
              (got["work"], got["state"], got["log"]) == ("work", "work/.hack", "logs/session.log"), str(got))
    finally:
        shutil.rmtree(t, ignore_errors=True)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
