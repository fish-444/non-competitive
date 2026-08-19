"""저장 — 상태를 통째로 SQLite 한 칸에 넣는다.

건수가 적은 앱이라 통째로 써도 싸다. 스키마 마이그레이션이 필요 없어서, 필드를
더할 때 코드만 고치면 된다. 건수가 수만 건으로 늘면 그때 테이블로 쪼갠다.
"""

import json
import sqlite3
from typing import Any, Dict

from . import config


def _connect():
    con = sqlite3.connect(config.db_path())
    con.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT)")
    return con


def save(state: Dict[str, Any]) -> None:
    """지금 상태를 저장. 실패해도 서비스는 계속 돈다 — 저장 실패로 요청까지
    죽이면 사용자는 방금 한 일을 통째로 잃는다."""
    if not config.db_path():
        return
    try:
        with _connect() as con:
            for key, val in state.items():
                con.execute(
                    "INSERT INTO state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(val, ensure_ascii=False)))
    except Exception as e:
        print(f"[경고] 저장 실패: {e}")


def load() -> Dict[str, Any]:
    """저장된 상태를 되살린다. 파일이 깨져 있어도 빈 상태로 뜬다 — 서버가 아예
    안 뜨는 것보다 낫다."""
    if not config.db_path():
        return {}
    try:
        with _connect() as con:
            rows = con.execute("SELECT key, value FROM state").fetchall()
        return {k: json.loads(v) for k, v in rows}
    except Exception as e:
        print(f"[경고] 불러오기 실패({e}) — 빈 상태로 시작합니다")
        return {}
