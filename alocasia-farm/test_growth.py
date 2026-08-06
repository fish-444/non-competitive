"""개체 측정 이력 스모크 테스트 (네트워크 불필요)

실행:  python3 test_growth.py

스캔할 때마다 existing.update(metrics) 가 직전 측정을 덮어쓰고 있었다. 물 준 날은
남기면서 크기는 안 남겨서 '지난달보다 얼마나 컸나' 에 답할 수가 없었다.
"""

import os
from datetime import date

os.environ["FARM_DB"] = ""

import main                                          # noqa: E402
from fastapi import HTTPException                    # noqa: E402


def _plant(**kw):
    p = {"id": "g1", "name": "테스트", "pos": "A1", "x": 0, "z": 0, "rot": 0,
         "canopy_cm": 15.0, "leaf_max_cm": 9.0, "leaf_count": 4, "size_class": "중품"}
    p.update(kw)
    main.PLANTS["g1"] = p
    return p


def _reset():
    main.PLANTS.clear()


def test_a_measurement_is_kept_instead_of_being_overwritten():
    p = _plant()
    main._record_growth(p)
    assert len(p["growth_log"]) == 1, p["growth_log"]
    row = p["growth_log"][0]
    assert row["canopy_cm"] == 15.0 and row["leaf_count"] == 4, row
    assert row["on"] == date.today().isoformat() and row["src"] == "scan", row
    _reset()


def test_scanning_twice_in_a_day_leaves_one_row():
    """같은 날 세 번 찍었다고 이력이 세 줄이 되면 추이를 못 읽는다."""
    p = _plant()
    main._record_growth(p)
    p["canopy_cm"] = 16.0
    main._record_growth(p)
    p["canopy_cm"] = 17.0
    main._record_growth(p)
    assert len(p["growth_log"]) == 1, p["growth_log"]
    assert p["growth_log"][0]["canopy_cm"] == 17.0, "그날 마지막 측정으로 갱신돼야 한다"
    _reset()


def test_different_days_pile_up():
    p = _plant()
    p["growth_log"] = [{"on": "2026-07-01", "src": "scan", "canopy_cm": 12.0}]
    main._record_growth(p)
    assert len(p["growth_log"]) == 2, p["growth_log"]
    _reset()


def test_hand_edits_are_marked_apart_from_scans():
    """손으로 고친 값이 오히려 정답에 가깝다 — 남기되 구분은 해 둔다."""
    p = _plant()
    main._record_growth(p, src="manual")
    assert p["growth_log"][0]["src"] == "manual"
    _reset()


def test_the_log_does_not_grow_without_bound():
    p = _plant()
    p["growth_log"] = [{"on": f"2020-01-{i:02d}", "src": "scan"} for i in range(1, 29)] * 40
    main._record_growth(p)
    assert len(p["growth_log"]) <= main.GROWTH_LOG_DAYS, len(p["growth_log"])
    _reset()


def test_a_missing_measurement_is_recorded_as_none_not_dropped():
    """캐노피를 못 잡은 날도 한 줄로 남아야 추이에 구멍이 보인다."""
    p = _plant(canopy_cm=None, size_class="미검출")
    main._record_growth(p)
    row = p["growth_log"][0]
    assert row["canopy_cm"] is None and row["size_class"] == "미검출", row
    _reset()


# ── /api/plants/{pid}/history ────────────────────────────────────────────
def test_history_reports_how_much_it_grew():
    p = _plant()
    p["growth_log"] = [{"on": "2026-06-01", "src": "scan", "canopy_cm": 12.0, "leaf_count": 3},
                       {"on": "2026-07-01", "src": "scan", "canopy_cm": 15.5, "leaf_count": 4}]
    out = main.plant_history("g1")
    assert out["grew_cm"] == 3.5, out
    assert out["since"] == "2026-06-01" and len(out["rows"]) == 2, out
    _reset()


def test_history_of_a_shrinking_plant_is_negative():
    p = _plant()
    p["growth_log"] = [{"on": "2026-06-01", "src": "scan", "canopy_cm": 20.0},
                       {"on": "2026-07-01", "src": "scan", "canopy_cm": 17.0}]
    assert main.plant_history("g1")["grew_cm"] == -3.0
    _reset()


def test_history_with_one_row_has_no_growth_number_yet():
    p = _plant()
    main._record_growth(p)
    out = main.plant_history("g1")
    assert out["grew_cm"] is None and len(out["rows"]) == 1, out
    _reset()


def test_history_survives_a_gap_in_canopy_measurements():
    """캐노피를 못 잰 날이 섞여도 숫자가 깨지면 안 된다."""
    p = _plant()
    p["growth_log"] = [{"on": "2026-06-01", "src": "scan", "canopy_cm": None},
                       {"on": "2026-07-01", "src": "scan", "canopy_cm": 15.0}]
    assert main.plant_history("g1")["grew_cm"] is None
    _reset()


def test_history_of_an_unknown_plant_is_404():
    _reset()
    try:
        main.plant_history("없는것")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 식물은 404 여야 한다")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
