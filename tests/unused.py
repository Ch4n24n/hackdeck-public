#!/usr/bin/python3 -I
"""使っていないものの点検（綺麗化のときに流す。pyflakes などが入っていなくても動くように、構文木と文字で調べる）。

  python3 -I tests/unused.py     hackdeck/*.py の、使っていない import と、どこからも使っていない関数・クラス・定数を出す
                                 （1つでもあれば終わりの状態 1）

関数・定数は、名前が hackdeck/・bin/・shell/・tests/ のどこかにもう1回出てくれば「使っている」とみなす（fzf の bind や
cli の振り分けのように、文字で呼ぶものもあるため）。import は、そのファイルの中で名前を使っていなければ「使っていない」。
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    mods = sorted((ROOT / "hackdeck").glob("*.py"))
    others = [p for d in ("tests", "shell", "bin") for p in sorted((ROOT / d).glob("*")) if p.is_file()]
    alltext = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in [*mods, *others])
    found = 0
    for p in mods:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
               {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    name = (a.asname or a.name).split(".")[0]
                    if name != "*" and name not in used:
                        print(f"{p.name}:{node.lineno}: 使っていない import {name}")
                        found += 1
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if len(re.findall(rf"\b{re.escape(node.name)}\b", alltext)) <= 1:
                    print(f"{p.name}:{node.lineno}: どこからも使っていない {node.name}")
                    found += 1
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if len(re.findall(rf"\b{re.escape(name)}\b", alltext)) <= 1:
                    print(f"{p.name}:{node.lineno}: どこからも使っていない定数 {name}")
                    found += 1
    print(f"{len(mods)} 個のモジュールを調べた" + ("、使っていないものは無い" if not found else f"、{found} 個"))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
