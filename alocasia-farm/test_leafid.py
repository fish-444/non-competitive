"""잎 신원 유지 스모크 테스트 (네트워크 불필요)

실행:  python3 test_leafid.py

예전에는 스캔할 때마다 잎 기록을 통째로 지우고 새 id 를 뽑았다. 그래서 '이 잎'
을 시간축으로 따라갈 수 없었다 — 새순이 언제 성엽이 됐는지, 어떤 잎이 떨어졌는지
알 방법이 없었다. 같은 자리에 있던 잎은 예전 id 를 물려받아야 한다.
"""

import os

os.environ["FARM_DB"] = ""

from fastapi import HTTPException                    # noqa: E402

import main                                          # noqa: E402


def _wipe():
    main.PLANTS.clear(); main.LEAVES.clear()


def leaf(cx, cy, w=60, h=60, cls="mature leaf"):
    return {"cls": cls, "conf": 0.9, "x1": cx - w / 2, "y1": cy - h / 2,
            "x2": cx + w / 2, "y2": cy + h / 2, "area": float(w * h)}


def _scan(plant, boxes, uvs, scan_id="sc_x"):
    """탐지된 잎들을 기록에 넣는다. uvs 는 잎마다의 선반 정규좌표."""
    verdicts = {id(b): {"pot_slot": "A1", "centroid_uv": list(uv), "ambiguous": False,
                        "manual": False, "nearest": "A1", "second": None, "margin": 1.0}
                for b, uv in zip(boxes, uvs)}
    main._record_leaves(plant, boxes, verdicts, scan_id, cm_per_unit=1.0)


def _plant():
    p = {"id": "p1", "name": "t", "pos": "A1"}
    main.PLANTS["p1"] = p
    return p


# ── 신원 유지 ────────────────────────────────────────────────────────────
def test_a_leaf_that_stayed_put_keeps_its_id():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    first = p["leaf_ids"][0]
    _scan(p, [leaf(103, 101)], [(0.305, 0.402)])      # 살짝 움직였을 뿐
    assert p["leaf_ids"] == [first], (first, p["leaf_ids"])
    _wipe()


def test_a_leaf_that_moved_far_is_treated_as_new():
    """너무 멀리 옮겨 갔으면 다른 잎이다 — 신원이 건너뛰면 안 된다."""
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    first = p["leaf_ids"][0]
    _scan(p, [leaf(700, 700)], [(0.80, 0.90)])
    assert p["leaf_ids"] != [first]
    assert p["gone_leaf_ids"] == [first], p["gone_leaf_ids"]
    _wipe()


def test_each_old_leaf_is_claimed_once():
    """가까운 잎이 둘이어도 옛 기록 하나가 둘에게 붙으면 안 된다."""
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    old = p["leaf_ids"][0]
    _scan(p, [leaf(100, 100), leaf(105, 100)], [(0.30, 0.40), (0.31, 0.40)])
    assert len(set(p["leaf_ids"])) == 2, p["leaf_ids"]
    assert old in p["leaf_ids"] and len(p["new_leaf_ids"]) == 1
    _wipe()


def test_the_nearest_pair_wins():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100), leaf(200, 100)], [(0.30, 0.40), (0.34, 0.40)])
    a, b = p["leaf_ids"]
    _scan(p, [leaf(200, 100), leaf(100, 100)], [(0.341, 0.40), (0.301, 0.40)])
    assert p["leaf_ids"] == [b, a], "가까운 쪽끼리 이어져야 한다"
    _wipe()


# ── 나이와 단계 ──────────────────────────────────────────────────────────
def test_a_leaf_remembers_when_it_first_appeared():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    born = main.LEAVES[p["leaf_ids"][0]]["first_seen"]
    for _ in range(3):
        _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    rec = main.LEAVES[p["leaf_ids"][0]]
    assert rec["first_seen"] == born, "처음 본 날은 안 바뀐다"
    assert rec["seen"] == 4, rec["seen"]
    _wipe()


def test_stage_since_resets_only_when_the_stage_changes():
    """새순이 언제 성엽이 됐는지 — 이게 알고 싶은 것이다."""
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100, cls="shoot")], [(0.30, 0.40)])
    since = main.LEAVES[p["leaf_ids"][0]]["stage_since"]
    _scan(p, [leaf(100, 100, cls="shoot")], [(0.30, 0.40)])
    assert main.LEAVES[p["leaf_ids"][0]]["stage_since"] == since, "단계 그대로면 안 바뀐다"

    # 초 단위라 같은 초에 돌면 값이 같아 구분이 안 된다 — 옛 시각을 박아 두고 본다.
    main.LEAVES[p["leaf_ids"][0]]["stage_since"] = "2020-01-01 00:00:00"
    _scan(p, [leaf(100, 100, cls="mature leaf")], [(0.30, 0.40)])
    rec = main.LEAVES[p["leaf_ids"][0]]
    assert rec["stage"] == "mature", rec["stage"]
    assert rec["stage_since"] != "2020-01-01 00:00:00", "단계가 바뀌면 새로 찍혀야 한다"

    # 단계가 그대로면 방금 찍힌 값이 유지된다
    was = rec["stage_since"]
    _scan(p, [leaf(100, 100, cls="mature leaf")], [(0.30, 0.40)])
    assert main.LEAVES[p["leaf_ids"][0]]["stage_since"] == was
    _wipe()


def test_new_and_gone_are_reported_separately():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100), leaf(300, 300)], [(0.30, 0.40), (0.60, 0.70)])
    kept, dropped = p["leaf_ids"][0], p["leaf_ids"][1]
    _scan(p, [leaf(100, 100), leaf(500, 500)], [(0.30, 0.40), (0.90, 0.90)])
    assert kept in p["leaf_ids"]
    assert p["gone_leaf_ids"] == [dropped], p["gone_leaf_ids"]
    assert len(p["new_leaf_ids"]) == 1
    _wipe()


def test_one_plants_leaves_never_borrow_anothers_identity():
    _wipe()
    a = {"id": "a", "name": "a", "pos": "A1"}; main.PLANTS["a"] = a
    b = {"id": "b", "name": "b", "pos": "A2"}; main.PLANTS["b"] = b
    _scan(a, [leaf(100, 100)], [(0.30, 0.40)])
    _scan(b, [leaf(100, 100)], [(0.30, 0.40)])          # 같은 자리지만 다른 화분
    assert a["leaf_ids"][0] != b["leaf_ids"][0]
    assert main.LEAVES[a["leaf_ids"][0]]["plant_id"] == "a"
    _wipe()


# ── /api/plants/{pid}/leaves ─────────────────────────────────────────────
def test_the_endpoint_reports_age_and_stage():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100, cls="shoot")], [(0.30, 0.40)])
    out = main.plant_leaves("p1")
    assert len(out["rows"]) == 1, out
    r = out["rows"][0]
    assert r["stage"] == "shoot" and r["seen"] == 1
    assert r["days_old"] == 0 and r["days_in_stage"] == 0, r
    _wipe()


def test_the_endpoint_survives_a_broken_timestamp():
    _wipe(); p = _plant()
    _scan(p, [leaf(100, 100)], [(0.30, 0.40)])
    main.LEAVES[p["leaf_ids"][0]]["first_seen"] = "언젠가"
    assert main.plant_leaves("p1")["rows"][0]["days_old"] is None
    _wipe()


def test_leaves_of_an_unknown_plant_is_404():
    _wipe()
    try:
        main.plant_leaves("없는것")
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
