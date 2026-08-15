"""저장/복원 스모크 테스트 (네트워크 불필요)

실행:  python3 test_persist.py

서버를 껐다 켜도 식물·화분 자리·손으로 고친 값·새 잎 기록이 남는지 확인한다.
'다시 불러오기'는 모듈을 새로 임포트해서 실제 재시작을 흉내 낸다.
"""

import importlib
import json
import os
import sqlite3
import sys
import tempfile

import pytest

DB = os.path.join(tempfile.mkdtemp(), "test_farm.db")


@pytest.fixture(autouse=True)
def _use_the_temp_db():
    """이 파일의 테스트가 도는 동안만 임시 DB 를 쓴다.

    conftest 가 매 테스트 앞에서 FARM_DB 를 "" 로 되돌리므로, 저장을 실제로
    확인하는 이 파일은 여기서 다시 잡아야 한다. 모듈 픽스처가 conftest 것보다
    나중에 돌아 이긴다.
    """
    os.environ["FARM_DB"] = DB
    yield
    # 어지른 건 치우고 나간다. 이 파일은 저장을 확인하려고 PLANTS/POTS 에 값을
    # 넣는데 _clear() 는 테스트 **시작할 때**만 부르므로, 마지막에 넣은 값이 그대로
    # 남는다. 이 딕셔너리들은 모든 테스트 파일이 같이 쓰는 전역이라 남겨 두면
    # 뒤에 도는 파일이 영향을 받는다 — 실제로 test_grouping 이 '화분 자리가 아직
    # 없다'를 전제로 하는데 여기서 남긴 POTS 2개 때문에 깨졌다(순서가 섞일 때만).
    for mod in {id(main): main, id(sys.modules.get("main")): sys.modules.get("main")}.values():
        if mod is not None:
            mod.PLANTS.clear(); mod.POTS.clear()
            mod.LEAVES.clear(); mod.LEAF_FIXES.clear()


def _restart():
    """서버 재시작 흉내 — 모듈을 새로 읽어 저장된 상태를 불러온다.

    main 의 전역(PLANTS 등)을 비우고 load_state() 를 다시 태우는 게 목적이다.
    저장 경로는 main.get_db_path() 가 부를 때마다 읽으므로 여기서 손댈 게 없다.
    """
    sys.modules.pop("main", None)
    return importlib.import_module("main")


os.environ["FARM_DB"] = DB          # 아래 import 때 load_state() 가 이 DB 를 보게
import main                                          # noqa: E402


def _clear():
    main.PLANTS.clear(); main.POTS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear()
    main.save_state()


def test_leaf_records_and_hand_moves_survive_a_restart():
    """잎 소속을 손으로 고쳐 놓고 서버를 껐다 켜면 그대로 있어야 한다."""
    _clear()
    main.LEAVES["lf_1"] = {"leaf_id": "lf_1", "scan_id": "sc_1", "mask_id": 0,
                           "plant_id": "p1", "pot_slot": "C3", "stage": "mature",
                           "centroid_uv": [0.4, 0.6], "long_side_cm": 12.4,
                           "conf": 0.88, "ambiguous": False, "manual": True,
                           "assign": {"nearest": "C5", "second": "C3", "margin": 0.07}}
    main.LEAF_FIXES.append({"u": 0.4, "v": 0.6, "pot_slot": "C3"})
    main.save_state()

    m2 = _restart()
    assert m2.LEAVES["lf_1"]["pot_slot"] == "C3", m2.LEAVES
    assert m2.LEAVES["lf_1"]["assign"]["nearest"] == "C5"
    assert m2.LEAF_FIXES == [{"u": 0.4, "v": 0.6, "pot_slot": "C3"}], m2.LEAF_FIXES


def test_plants_survive_a_restart():
    _clear()
    main.PLANTS["p1"] = {"id": "p1", "name": "프라이덱", "pos": "C3",
                         "x": 0, "z": 0, "rot": 90, "leaf_count": 5,
                         "shoot_count": 1, "mature_count": 3, "old_count": 1,
                         "size_class": "중품", "manual": True}
    main.save_state()

    m2 = _restart()
    assert "p1" in m2.PLANTS, m2.PLANTS
    p = m2.PLANTS["p1"]
    assert p["name"] == "프라이덱" and p["pos"] == "C3"
    assert p["rot"] == 90 and p["leaf_count"] == 5
    assert p["manual"] is True, "손으로 고친 표시가 사라졌다"


def test_pot_layout_survives_a_restart():
    """1회차 화분 자리 지정을 매번 다시 하지 않아도 된다."""
    _clear()
    main.POTS.extend([{"i": 0, "u": 0.2, "v": 0.3, "slot": "B2"},
                      {"i": 1, "u": 0.8, "v": 0.7, "slot": "D8"}])
    main.save_state()

    m2 = _restart()
    assert [p["slot"] for p in m2.POTS] == ["B2", "D8"], m2.POTS
    assert m2.POTS[0]["u"] == 0.2


def test_leaf_log_survives_a_restart():
    """새 잎이 언제 났는지 기록이 남아야 추적이 의미가 있다."""
    _clear()
    main.PLANTS["p1"] = {"id": "p1", "name": "흑룡", "pos": "A1", "x": 0, "z": 0,
                         "leaf_count": 7,
                         "leaf_log": [{"at": "2026-07-20 09:00:00", "added": 2, "total": 5},
                                      {"at": "2026-07-25 09:00:00", "added": 2, "total": 7}]}
    main.save_state()

    m2 = _restart()
    log = m2.PLANTS["p1"]["leaf_log"]
    assert len(log) == 2 and log[-1]["added"] == 2, log


def test_korean_text_is_not_mangled():
    _clear()
    main.PLANTS["p1"] = {"id": "p1", "name": "거북알로카시아", "size_class": "대품"}
    main.save_state()
    raw = sqlite3.connect(DB).execute(
        "SELECT value FROM state WHERE key='plants'").fetchone()[0]
    assert "거북알로카시아" in raw, "한글이 이스케이프돼 저장됐다"
    assert json.loads(raw)["p1"]["size_class"] == "대품"


def test_deleting_everything_is_also_saved():
    """지운 상태도 저장돼야 한다 — 안 그러면 재시작 때 되살아난다."""
    _clear()
    main.PLANTS["p1"] = {"id": "p1", "name": "삭제될 식물"}
    main.save_state()
    main.PLANTS.clear()
    main.save_state()

    m2 = _restart()
    assert m2.PLANTS == {}, m2.PLANTS


def test_corrupt_db_does_not_crash_startup():
    """저장 파일이 깨져도 서버는 떠야 한다 (빈 상태로)."""
    _clear()                                 # 저장 파일·테이블부터 만들어 두고
    with sqlite3.connect(DB) as con:
        con.execute("INSERT INTO state(key,value) VALUES('plants','{깨진 JSON') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    m2 = _restart()
    assert isinstance(m2.PLANTS, dict)      # 예외 없이 떴으면 성공
    _clear()


def test_saving_is_off_when_no_path():
    """FARM_DB='' 면 파일을 만들지 않는다."""
    real = os.environ.get("FARM_DB")
    os.environ["FARM_DB"] = ""
    try:
        main.PLANTS["tmp"] = {"id": "tmp"}
        main.save_state()                    # 아무 일도 없어야 한다
    finally:
        if real is None:
            os.environ.pop("FARM_DB", None)
        else:
            os.environ["FARM_DB"] = real
        main.PLANTS.pop("tmp", None)
        main.save_state()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과  (저장 파일: {DB})")
