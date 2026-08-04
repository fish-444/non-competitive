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

DB = os.path.join(tempfile.mkdtemp(), "test_farm.db")
os.environ["FARM_DB"] = DB

import main


def _restart():
    """서버 재시작 흉내 — 모듈을 새로 읽어 저장된 상태를 불러온다."""
    for mod in [m for m in sys.modules if m == "main"]:
        del sys.modules[mod]
    return importlib.import_module("main")


def _clear():
    main.PLANTS.clear(); main.FEATS.clear(); main.POTS.clear()
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
    main.FEATS["p1"] = {"aspect": 1.2, "size": 100, "h": 60, "s": 180,
                        "v": 120, "has_color": True}
    main.save_state()

    m2 = _restart()
    assert "p1" in m2.PLANTS, m2.PLANTS
    p = m2.PLANTS["p1"]
    assert p["name"] == "프라이덱" and p["pos"] == "C3"
    assert p["rot"] == 90 and p["leaf_count"] == 5
    assert p["manual"] is True, "손으로 고친 표시가 사라졌다"
    assert m2.FEATS["p1"]["aspect"] == 1.2, "모양 특징이 안 살아났다"


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
    real, main.FARM_DB = main.FARM_DB, ""
    try:
        main.PLANTS["tmp"] = {"id": "tmp"}
        main.save_state()                    # 아무 일도 없어야 한다
    finally:
        main.FARM_DB = real
        main.PLANTS.pop("tmp", None)
        main.save_state()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과  (저장 파일: {DB})")
