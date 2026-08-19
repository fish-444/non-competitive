"""API 테스트 — 라우트가 규칙을 제대로 부르는지, 그리고 저장이 실제로 되는지."""

import os
import tempfile

import pytest
from fastapi import HTTPException

from backend import app as app_mod
from backend.app import add_item, list_items, remove_item, update_item


def test_adding_an_item_shows_up_in_the_list():
    add_item(name="장보기", tags="집, 급함")
    data = list_items()
    assert data["summary"]["total"] == 1
    assert data["items"][0]["tags"] == ["집", "급함"]


def test_a_blank_name_is_rejected():
    """공백만 친 것도 빈 이름이다 — 목록에 이름 없는 줄이 생기면 지우기도 어렵다."""
    with pytest.raises(HTTPException) as e:
        add_item(name="   ")
    assert e.value.status_code == 400


def test_marking_done_moves_it_between_the_counters():
    it = add_item(name="하나")
    update_item(it["id"], name=None, done=True)
    s = list_items()["summary"]
    assert (s["done"], s["left"]) == (1, 0)


def test_fields_you_do_not_send_are_left_alone():
    """부분 수정이 안 보낸 필드를 지워 버리면, 이름만 고쳐도 완료 표시가 풀린다."""
    it = add_item(name="원래 이름")
    update_item(it["id"], name=None, done=True)
    after = update_item(it["id"], name="새 이름", done=None)
    assert after["name"] == "새 이름" and after["done"] is True


def test_touching_something_that_is_not_there_is_a_404():
    for call in (lambda: update_item("없음", name="x", done=None),
                 lambda: remove_item("없음")):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 404


class TestSaving:
    """저장을 실제로 확인하는 묶음 — 여기서만 진짜 파일을 쓴다."""

    @pytest.fixture(autouse=True)
    def _real_db(self):
        # conftest 가 매 테스트 앞에서 DB 를 "" 로 되돌리므로 여기서 다시 잡는다.
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        os.environ["{{ENV}}_DB"] = db
        yield db
        os.environ["{{ENV}}_DB"] = ""

    def test_items_survive_a_restart(self, _real_db):
        """서버를 껐다 켜도 남아야 한다 — 안 그러면 매번 처음부터 입력해야 한다.

        재시작은 메모리를 비우고 _restore() 를 다시 태워서 흉내 낸다. 모듈을
        sys.modules 에서 갈아 끼우는 방법도 있지만, 그러면 이 파일이 맨 위에서
        가져온 함수는 옛 모듈을, conftest 는 새 모듈을 보게 돼 상태가 두 벌로
        갈린다 — 순서를 섞을 때만 깨지는 버그가 된다.
        """
        add_item(name="살아남을 항목", tags="중요")
        app_mod.ITEMS.clear()                 # 서버가 꺼졌다
        app_mod._restore()                    # 다시 켜면 파일에서 되살린다
        assert [i.name for i in app_mod.ITEMS.values()] == ["살아남을 항목"]

    def test_korean_is_not_mangled(self, _real_db):
        add_item(name="한글 항목", tags="태그")
        app_mod.ITEMS.clear()
        app_mod._restore()
        assert list(app_mod.ITEMS.values())[0].tags == ["태그"]


def test_nothing_is_written_when_saving_is_off(tmp_path):
    """{{ENV}}_DB="" 는 '이 실행은 아무것도 남기지 않는다'는 뜻이다."""
    os.environ["{{ENV}}_DB"] = ""
    add_item(name="안 남을 항목")
    assert list(tmp_path.iterdir()) == []
