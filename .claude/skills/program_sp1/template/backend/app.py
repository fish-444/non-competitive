"""HTTP 층 — 얇게. 규칙은 logic.py, 저장은 store.py 가 한다.

라우트 안에 계산을 적기 시작하면 테스트할 때마다 서버를 띄워야 하고, 같은 규칙이
여러 라우트에 복사된다. 여기서는 '받고 → 부르고 → 돌려준다' 만 한다.
"""

import os
import uuid
from typing import Dict

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, store
from .logic import Item, summarize

app = FastAPI(title="{{NAME}}")

# 상태는 메모리에 두고 바뀔 때마다 파일에 쓴다. 그래서 워커는 **하나만** 띄운다
# (여럿이면 각자 다른 메모리를 들고 서로 덮어쓴다).
ITEMS: Dict[str, Item] = {}


def _snapshot() -> dict:
    return {"items": [vars(i) for i in ITEMS.values()]}


def _restore() -> None:
    ITEMS.clear()
    for raw in store.load().get("items", []):
        ITEMS[raw["id"]] = Item(**raw)


_restore()

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "frontend")
app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))


@app.get("/api/items")
def list_items():
    items = list(ITEMS.values())
    return {"items": [vars(i) for i in items], "summary": summarize(items)}


@app.post("/api/items")
def add_item(name: str = Form(...), tags: str = Form("")):
    """새 항목. 기본값이 있는 Form 인자는 **타입으로 걸러야 한다.**

    Form(...) 의 기본값은 HTTP 로 올 때만 채워진다. 파이썬에서 이 함수를 직접
    부르면(테스트가 그렇게 한다) 기본값 자리에 FieldInfo 객체가 그대로 들어와
    tags.split(",") 에서 터진다. isinstance 로 거르면 두 경로 모두에서 돈다.
    """
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise HTTPException(400, "이름을 입력해 주세요.")
    raw_tags = tags if isinstance(tags, str) else ""
    item = Item(id=uuid.uuid4().hex[:8], name=name,
                tags=[t.strip() for t in raw_tags.split(",") if t.strip()])
    ITEMS[item.id] = item
    store.save(_snapshot())
    return vars(item)


@app.patch("/api/items/{item_id}")
def update_item(item_id: str, name: str = Form(None), done: bool = Form(None)):
    """부분 수정. **보내지 않은 필드는 건드리지 않는다.**

    주의: FastAPI 는 빈 폼 문자열을 None 으로 바꾼다. 그래서 ""(지움)과
    '안 보냄'이 구분되지 않는다 — 값을 지우게 하려면 프런트에서 공백 한 칸처럼
    빈 문자열이 아닌 값을 보내고 여기서 strip() 해야 한다.
    """
    item = ITEMS.get(item_id)
    if item is None:
        raise HTTPException(404, "없는 항목입니다.")
    if isinstance(name, str):                 # 위와 같은 이유로 타입으로 거른다
        item.name = name.strip()
    if isinstance(done, bool):
        item.done = done
    store.save(_snapshot())
    return vars(item)


@app.delete("/api/items/{item_id}")
def remove_item(item_id: str):
    if ITEMS.pop(item_id, None) is None:
        raise HTTPException(404, "없는 항목입니다.")
    store.save(_snapshot())
    return {"ok": True}
