"""설정 — 전부 **부를 때마다** 환경변수를 읽는다.

모듈 최상단에서 한 번 읽어 전역에 박아 두면 안 된다. 파이썬은 같은 모듈을 두 번
임포트해도 처음 것을 그대로 돌려주므로, 나중에 환경변수를 바꿔도 이미 박힌 값이
살아남는다. 테스트가 파일마다 다른 DB 를 잡는데 먼저 임포트된 파일의 값으로
고정돼, 파일 하나만 돌리면 통과하고 전체를 돌리면 깨진다.
"""

import os


def db_path() -> str:
    """저장할 SQLite 파일. 빈 문자열이면 아무것도 저장하지 않는다(테스트용)."""
    return os.environ.get("{{ENV}}_DB", "{{SLUG}}.db")


def data_dir() -> str:
    """업로드·산출물을 둘 곳. 저장을 끄면 여기도 끈다 — 안 그러면 테스트가
    돌 때마다 파일이 쌓인다."""
    return os.environ.get("{{ENV}}_DATA", "data" if db_path() else "")


def port() -> int:
    return int(os.environ.get("{{ENV}}_PORT", "8000"))
