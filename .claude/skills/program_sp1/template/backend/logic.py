"""순수 계산 — 외부 의존성 0.

여기에는 프레임워크도, 데이터베이스도, 파일도 안 들어온다. 그래야
  · 테스트가 서버를 안 띄우고 바로 부를 수 있고
  · 규칙이 바뀌었을 때 어디를 고칠지 한 곳으로 좁혀지고
  · 나중에 다른 화면(CLI, 배치 작업)에서 그대로 재사용된다.
API 는 이 함수들을 부르기만 한다.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Item:
    """한 건. 필드는 실제로 쓰는 것만 둔다 — 안 쓰는 필드는 거짓말이 된다."""
    id: str
    name: str
    tags: List[str] = field(default_factory=list)
    done: bool = False


def summarize(items: List[Item]) -> dict:
    """목록 요약. 화면이 필요로 하는 형태로 미리 접어서 넘긴다.

    프런트에서 매번 세는 대신 여기서 세는 이유: 세는 규칙이 바뀔 때 고칠 곳이
    한 군데면 화면과 API 가 서로 다른 숫자를 말하는 일이 없다.
    """
    done = sum(1 for i in items if i.done)
    tags = sorted({t for i in items for t in i.tags})
    return {"total": len(items), "done": done, "left": len(items) - done,
            "tags": tags}
