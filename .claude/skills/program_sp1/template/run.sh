#!/usr/bin/env bash
# 개발용 실행. 워커는 하나만 — 상태를 메모리에 들고 있어서 여럿이면 서로 덮어쓴다.
set -e
cd "$(dirname "$0")"
exec python3 -m uvicorn backend.app:app --reload --port "${{{ENV}}_PORT:-8000}"
