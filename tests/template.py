#!/usr/bin/python3 -I
"""雛形と、案件の中の場所の既定を確かめる（2026-11-02）。

  python3 -I tests/template.py

・既定は、雛形に頼らない一般的な形: 雛形は空、作業フォルダ work・データの置き場所 work/.hack・ログ logs/session.log（本人
  「hackdeck のデフォルトは Hacking-Op に依存していない形にしてほしい。そのうえで、Hacking-Op に合う設定にしたという形にしたい」）
・雛形の git リポジトリを設定し、その雛形のフォルダの名前に合わせて場所の3つも設定すると、clone した案件がその形で動く（作者の環境の
  ように、番号のフォルダの雛形に合わせた例）

ネットにはつながない: clone は、試しの中で作った小さな雛形の git リポジトリで確かめる。偽の HOME（一時フォルダ）で、tmux には
触らない（案件を作るだけで、始めない）。OK・NG を出し、NG があれば終わりの状態 1。
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
DEFAULT = ("work", "work/.hack", "logs/session.log")
NUMBERED = ("02-作業", "02-作業/.hack", "91-ログ/実行ログ.log")   # 番号のフォルダの雛形に合わせた設定の例


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
          "f = lambda r: {'places': [str(case.work_of(r).relative_to(r)), str(case.state_of(r).relative_to(r)), "
          "str(case.log_of(r).relative_to(r))], 'is_case': case.is_case_dir(r), "
          "'home': case.case_env(r)['HACK_HOME'], 'logenv': case.case_env(r)['HACK_LOG']}; ")


def make(env, name):
    return subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "make", name], env=env, capture_output=True, text=True)


def fixture(d, env):
    """番号のフォルダの雛形の、小さな git リポジトリ"""
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

        # 既定（設定を何も書いていない）
        got = py(env, "from hackdeck import settings; print(json.dumps([settings.get(k) for k in ('template', 'work_dir', 'state_dir', 'log_file')]))")
        check("雛形の既定は空（ほかのリポジトリにつながない）", got[0] == "", got[0])
        check("場所の3つの既定は一般的な名前（work・work/.hack・logs/session.log）", tuple(got[1:]) == DEFAULT, got[1:])
        r = make(env, "first")
        first = cases / "first"
        check("設定なしで作ると、作業フォルダとログの置き場所だけ（ネットにつながない）",
              r.returncode == 0 and (first / "work").is_dir() and (first / "logs").is_dir() and not (first / ".git").exists(),
              r.stderr[-300:] + str(sorted(p.name for p in first.iterdir()) if first.exists() else ""))
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(first)!r}))))")
        check("既定の案件の場所（work・work/.hack・logs/session.log）", tuple(got["places"]) == DEFAULT, got["places"])

        # 雛形に合わせた設定（作者の環境のように、番号のフォルダの雛形を使う例）
        fixture(t / "tpl", env)
        py(env, f"from hackdeck import settings; settings.save(template={str(t / 'tpl')!r}, work_dir={NUMBERED[0]!r}, "
                f"state_dir={NUMBERED[1]!r}, log_file={NUMBERED[2]!r}); print(json.dumps(1))")
        r = make(env, "box")
        box = cases / "box"
        check("雛形の git リポジトリから案件を作れる（clone）", r.returncode == 0, r.stderr[-300:])
        check("雛形の中身が来る（CLAUDE.md・番号のノート）・clone なので .git もある",
              all((box / n).exists() for n in ("CLAUDE.md", "10-現在地.md", "01-メモ", ".git")))
        got = py(env, LAYOUT + f"print(json.dumps(f(Path({str(box)!r}))))")
        check("設定した場所（雛形に合わせた 02-作業 など）が既定より先", tuple(got["places"]) == NUMBERED, got["places"])
        check("案件として見える（作業フォルダがある）", got["is_case"])
        check("セッションの環境（HACK_HOME・HACK_LOG）も設定した場所",
              got["home"] == str(box / NUMBERED[0]) and got["logenv"] == str(box / NUMBERED[2]), f"{got['home']} {got['logenv']}")
        check("雛形に無い場所は作る（作業フォルダ・ログの置き場所）", (box / NUMBERED[0]).is_dir() and (box / NUMBERED[2]).parent.is_dir())
        ls = subprocess.run([str(ROOT / "bin" / "hackdeck"), "case", "ls"], env=env, capture_output=True, text=True)
        check("hackdeck case ls に出る", "box" in ls.stdout, ls.stdout[-300:] + ls.stderr[-300:])
    finally:
        shutil.rmtree(t, ignore_errors=True)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
