#!/usr/bin/python3 -I
"""付属の雛形 template/ が既定で使われるかを確かめる（2026-11-02、本人「今は Private のリポジトリを参照してクローンしている
けど、Public 版では変えないとね」。設定の既定は、雛形がツールの template/、作業フォルダ・データの置き場所・ログが、その箱の形）。

  python3 -I tests/template.py

偽の HOME（一時フォルダ）で、設定を書かずに案件を作り、付属の雛形が写り、作業フォルダ・データの置き場所・ログが箱の形
（02-作業・02-作業/.hack・91-ログ/実行ログ.log）になるか。設定に書いた値（雛形を空にする・別の場所）がそちらより先か。
tmux には触らない（案件を作るだけで、始めない）。OK・NG を出し、NG があれば終わりの状態 1。
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


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"{'OK' if ok else 'NG'}  {name}" + (f"  … {detail}" if detail and not ok else ""))


def env_of(t):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TMUX_PANE", "ZDOTDIR", "HACK_ROOT") and not k.startswith("XDG_")
           and not k.startswith("HACKDECK_")}
    env.update(HOME=str(t / "home"), TMUX_TMPDIR=str(t / "tmux"), HACKDECK_TMUX_SOCKET="hdtemplate", LANG="C.UTF-8")
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


def main():
    t = Path(tempfile.mkdtemp(prefix="hackdeck-template."))
    try:
        for d in ("home", "tmux"):
            (t / d).mkdir()
        env = env_of(t)
        cases = t / "home" / "cases"

        # 設定を何も書かずに作る（公開版を入れたばかりの人と同じ）
        got = py(env, "from hackdeck import settings; print(json.dumps(settings.get('template')))")
        check("雛形の既定は、ツールの template フォルダ", Path(got).expanduser() == ROOT / "template", got)
        r = make(env, "box")
        check("設定なしで案件を作れる", r.returncode == 0, r.stderr[-300:])
        box = cases / "box"
        check("付属の雛形が写る（CLAUDE.md・番号のノート・見本）",
              all((box / n).exists() for n in ("CLAUDE.md", "10-現在地.md", "16-学び.md", "92-見本", "01-メモ")))
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(box)!r}))))")
        check("作業フォルダ・データの置き場所・ログは箱の形", (got["work"], got["state"], got["log"]) == tuple(BOX.values()),
              str(got))
        check("案件として見える（作業フォルダがある）", got["is_case"])
        check("セッションの環境（HACK_HOME・HACK_LOG）も箱の形",
              got["home"] == str(box / BOX["work"]) and got["logenv"] == str(box / BOX["log"]), f"{got['home']} {got['logenv']}")
        check("箱の中に、箱でない形のフォルダ（work・logs）を作らない", not (box / "work").exists() and not (box / "logs").exists())
        ls = subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "ls"], env=env, capture_output=True, text=True)
        check("hackdeck case ls に出る", "box" in ls.stdout, ls.stdout[-300:] + ls.stderr[-300:])

        # 雛形を空にすると、作業フォルダとログの置き場所だけ（場所は既定の箱の形）
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
        mine = cases / "mine"
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(mine)!r}))))")
        check("設定に書いた場所が既定より先（work・work/.hack・logs/session.log）",
              (got["work"], got["state"], got["log"]) == ("work", "work/.hack", "logs/session.log"), str(got))
        check("雛形の項目を書いた値が既定より先", py(env, "from hackdeck import settings; print(json.dumps(settings.get('template')))") == "")
    finally:
        shutil.rmtree(t, ignore_errors=True)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
