"""순수 계산 테스트 — 서버를 안 띄운다.

규칙이 여기 모여 있으니 테스트도 여기 모인다. 빠르고, 실패했을 때 원인이 좁다.
"""

from backend.logic import Item, summarize


def test_an_empty_list_summarizes_to_zeros():
    s = summarize([])
    assert s == {"total": 0, "done": 0, "left": 0, "tags": []}


def test_done_and_left_always_add_up_to_total():
    """이 둘이 안 맞으면 화면에 서로 모순되는 숫자가 뜬다."""
    items = [Item("a", "하나", done=True), Item("b", "둘"), Item("c", "셋")]
    s = summarize(items)
    assert s["done"] + s["left"] == s["total"] == 3
    assert s["done"] == 1


def test_tags_are_deduplicated_and_sorted():
    """같은 태그가 여러 항목에 있어도 목록에는 한 번만 — 정렬은 화면이 흔들리지
    않게 하려고."""
    items = [Item("a", "하나", tags=["급함", "집"]),
             Item("b", "둘", tags=["집"])]
    assert summarize(items)["tags"] == ["급함", "집"]
