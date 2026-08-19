#!/usr/bin/env python3
"""골격을 새 폴더로 찍어 낸다.

    python3 new_project.py <경로> [--name "표시 이름"]

template/ 을 통째로 복사하면서 자리표시자를 바꾼다.
  {{NAME}}  화면·문서에 보이는 이름      예) 재고 관리
  {{SLUG}}  파일·패키지에 쓰는 이름      예) inventory
  {{ENV}}   환경변수 접두사(대문자)      예) INVENTORY  →  INVENTORY_DB
"""

import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template")
TEXT_EXT = {".py", ".html", ".md", ".txt", ".sh", ".bat", ".ini", ".yaml", ".yml"}


def slugify(name: str) -> str:
    """표시 이름 → 파일에 써도 되는 이름. 한글은 살릴 수 없으니 못 쓰면 app 으로."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return s or "app"


def env_prefix(slug: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", slug.upper()) or "APP"


def render(text: str, name: str, slug: str, env: str) -> str:
    return (text.replace("{{NAME}}", name)
                .replace("{{SLUG}}", slug)
                .replace("{{ENV}}", env))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="백엔드/프런트엔드 골격 만들기")
    ap.add_argument("path", help="만들 폴더 (이미 있으면 비어 있어야 한다)")
    ap.add_argument("--name", help="표시 이름 (기본: 폴더 이름)")
    a = ap.parse_args(argv)

    dest = os.path.abspath(a.path)
    if os.path.exists(dest) and os.listdir(dest):
        print(f"[중단] {dest} 가 비어 있지 않습니다. 덮어쓰지 않습니다.", file=sys.stderr)
        return 1

    name = a.name or os.path.basename(dest.rstrip(os.sep))
    slug = slugify(a.name or os.path.basename(dest.rstrip(os.sep)))
    env = env_prefix(slug)

    made = 0
    for root, _dirs, files in os.walk(TEMPLATE):
        rel = os.path.relpath(root, TEMPLATE)
        out_dir = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(out_dir, exist_ok=True)
        for fn in files:
            src, dst = os.path.join(root, fn), os.path.join(out_dir, fn)
            if os.path.splitext(fn)[1] in TEXT_EXT:
                with open(src, encoding="utf-8") as f:
                    body = render(f.read(), name, slug, env)
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(body)
                shutil.copymode(src, dst)
            else:
                shutil.copy2(src, dst)
            made += 1

    print(f"\n{dest}\n  파일 {made}개 · 이름 '{name}' · 환경변수 접두사 {env}_\n")
    print("  cd " + dest)
    print("  pip install -r requirements.txt")
    print("  pytest            # 순서를 섞어 돈다")
    print("  ./run.sh          # 윈도우는 run.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
