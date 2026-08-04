"""잎 낱개 소속 판정 스모크 테스트 (네트워크 불필요)

실행:  python3 test_leaves.py

지금까지는 '잎 무리 = 식물'까지만 있었다. 잎 하나하나에 이름을 붙여 두면
화분 두 개 사이에 걸친 잎을 사람이 끌어다 옮길 수 있다. 그 경로를 검증한다.
소속은 격자 칸이 아니라 **화분 실측 위치 최근접**으로 반올림한다.
"""

import asyncio
import io
import json

from PIL import Image
from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import main


def box(cx, cy, w, h, cls="mature leaf"):
    return {"cls": cls, "conf": 0.9,
            "x1": cx - w / 2, "y1": cy - h / 2, "x2": cx + w / 2, "y2": cy + h / 2,
            "area": w * h}


class _Upload:
    content_type = "image/jpeg"

    def __init__(self, raw):
        self._raw = raw

    async def read(self):
        return self._raw


def _jpeg(w=1200, h=800):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (25, 90, 35)).save(buf, format="JPEG")
    return buf.getvalue()


def _reset():
    main.POTS.clear(); main.PLANTS.clear(); main.FEATS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear()


def _set_pots(points):
    return asyncio.run(main.set_pots(points=json.dumps(points), points_px=None, corners=None))


def _scan(boxes, mode="update"):
    orig = main.detect_boxes
    main.detect_boxes = lambda im, det=None: (boxes, float(1200 * 800))
    try:
        return asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=mode))
    finally:
        main.detect_boxes = orig


def _leaf_of(plant, n=0):
    return main.LEAVES[plant["leaf_ids"][n]]


# ── 최근접 화분으로 반올림 ───────────────────────────────────────────────
def test_leaf_goes_to_the_nearest_pot():
    _reset()
    _set_pots([[0.2, 0.5], [0.8, 0.5]])
    left, right = (p["slot"] for p in main.POTS)
    assert main.assign_leaf_to_pot((0.25, 0.5))["pot_slot"] == left
    assert main.assign_leaf_to_pot((0.75, 0.5))["pot_slot"] == right
    _reset()


def test_distance_is_measured_in_cm_not_in_uv():
    """uv 는 60x40cm 를 똑같이 0~1 로 눌러 놓은 좌표라 그대로 재면 세로가 부풀려진다."""
    _reset()
    # 잎은 (0.5, 0.5). 가로로 0.30 떨어진 화분(=18cm)과 세로로 0.40 떨어진 화분(=16cm)
    _set_pots([[0.2, 0.5], [0.5, 0.1]])
    side, above = (p["slot"] for p in main.POTS)
    # uv 거리만 보면 side(0.30)가 더 가깝지만, 실제로는 above(16cm)가 더 가깝다
    v = main.assign_leaf_to_pot((0.5, 0.5))
    assert v["pot_slot"] == above, v
    _reset()


def test_a_leaf_between_two_pots_is_flagged_ambiguous():
    _reset()
    _set_pots([[0.2, 0.5], [0.8, 0.5]])
    middle = main.assign_leaf_to_pot((0.5, 0.5))
    assert middle["ambiguous"] is True, middle
    assert middle["margin"] < main.AMBIGUOUS_MARGIN
    clear = main.assign_leaf_to_pot((0.21, 0.5))
    assert clear["ambiguous"] is False, clear
    _reset()


def test_margin_names_both_candidates():
    """왜 애매한지 보여 줄 수 있어야 사람이 판단한다."""
    _reset()
    _set_pots([[0.2, 0.5], [0.8, 0.5]])
    a, b = (p["slot"] for p in main.POTS)
    v = main.assign_leaf_to_pot((0.52, 0.5))
    assert {v["nearest"], v["second"]} == {a, b}, v
    assert 0.0 <= v["margin"] <= 1.0
    _reset()


def test_no_pots_means_no_verdict():
    _reset()
    v = main.assign_leaf_to_pot((0.5, 0.5))
    assert v["pot_slot"] is None and v["ambiguous"] is True
    _reset()


# ── 스캔이 잎 기록을 남긴다 ─────────────────────────────────────────────
def test_scan_records_every_leaf():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90), box(340, 430, 90, 90),
               box(900, 400, 90, 90)])
    assert len(main.LEAVES) == 3, main.LEAVES
    total = sum(len(p["leaf_ids"]) for p in d["plants"])
    assert total == 3, [p["leaf_ids"] for p in d["plants"]]
    _reset()


def test_leaf_record_carries_what_the_ui_needs():
    _reset()
    _set_pots([[0.25, 0.5]])
    d = _scan([box(300, 400, 120, 90, "shoot")])
    leaf = _leaf_of(d["plants"][0])
    for key in ("leaf_id", "scan_id", "mask_id", "plant_id", "pot_slot", "stage",
                "centroid_uv", "long_side_cm", "conf", "ambiguous", "manual", "assign"):
        assert key in leaf, (key, leaf)
    assert leaf["stage"] == "shoot"
    assert leaf["bbox_px"] == [240.0, 355.0, 360.0, 445.0], leaf["bbox_px"]
    assert leaf["long_side_cm"] == 6.0, leaf["long_side_cm"]   # 120px * 60cm/1200px
    _reset()


def test_report_groups_leaves_by_pot():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90), box(900, 400, 90, 90), box(940, 430, 90, 90)])
    rep = d["leaves"]
    per_pot = {p["slot"]: len(p["leaf_ids"]) for p in rep["pots"]}
    assert sorted(per_pot.values()) == [1, 2], per_pot
    assert rep["unassigned"] == [], rep["unassigned"]
    assert rep["scan_id"].startswith("sc_")
    _reset()


def test_counts_match_the_leaf_records():
    """개체 수치와 잎 기록이 어긋나면 둘 중 하나는 거짓말이다."""
    _reset()
    _set_pots([[0.25, 0.5]])
    d = _scan([box(300, 400, 90, 90, "shoot"), box(340, 430, 90, 90, "mature leaf"),
               box(280, 360, 90, 90, "old leaf")])
    p = d["plants"][0]
    stages = [main.LEAVES[i]["stage"] for i in p["leaf_ids"]]
    assert stages.count("shoot") == p["shoot_count"]
    assert stages.count("mature") == p["mature_count"]
    assert stages.count("old") == p["old_count"]
    _reset()


def test_rescan_replaces_records_instead_of_piling_up():
    _reset()
    _set_pots([[0.25, 0.5]])
    _scan([box(300, 400, 90, 90), box(340, 430, 90, 90)])
    _scan([box(300, 400, 90, 90)])
    assert len(main.LEAVES) == 1, main.LEAVES
    _reset()


def test_empty_pots_have_an_empty_leaf_list():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90)])
    empty = [p for p in d["plants"] if p.get("empty")]
    assert empty and empty[0]["leaf_ids"] == [], empty
    _reset()


# ── 손으로 옮기기 ────────────────────────────────────────────────────────
def _move(leaf_id, slot):
    return asyncio.run(main.move_leaf(leaf_id=leaf_id, pot_slot=slot))


def test_moving_a_leaf_moves_the_count_too():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90), box(340, 430, 90, 90), box(900, 400, 90, 90)])
    big = max(d["plants"], key=lambda p: p["leaf_count"])
    small = min(d["plants"], key=lambda p: p["leaf_count"])
    assert (big["leaf_count"], small["leaf_count"]) == (2, 1)

    res = _move(big["leaf_ids"][0], small["pos"])
    assert res["moved"] is True
    assert main.PLANTS[big["id"]]["leaf_count"] == 1, main.PLANTS[big["id"]]
    assert main.PLANTS[small["id"]]["leaf_count"] == 2, main.PLANTS[small["id"]]
    _reset()


def test_moved_leaf_is_marked_and_no_longer_ambiguous():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90), box(900, 400, 90, 90)])
    a, b = d["plants"][0], d["plants"][1]
    leaf_id = a["leaf_ids"][0]
    _move(leaf_id, b["pos"])
    leaf = main.LEAVES[leaf_id]
    assert leaf["manual"] is True and leaf["ambiguous"] is False
    assert leaf["pot_slot"] == b["pos"] and leaf["plant_id"] == b["id"]
    _reset()


def test_moving_to_an_empty_slot_is_refused():
    _reset()
    _set_pots([[0.25, 0.5]])
    d = _scan([box(300, 400, 90, 90)])
    try:
        _move(d["plants"][0]["leaf_ids"][0], "E10")
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("식물 없는 자리로는 못 옮긴다")
    _reset()


def test_moving_an_unknown_leaf_is_a_404():
    _reset()
    _set_pots([[0.25, 0.5]])
    _scan([box(300, 400, 90, 90)])
    try:
        _move("lf_nope", main.POTS[0]["slot"])
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 잎은 404")
    _reset()


def test_move_survives_a_rescan():
    """잎에는 고유번호가 없다. 자리로 기억해 둬야 보정이 살아남는다."""
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    boxes = [box(300, 400, 90, 90), box(340, 430, 90, 90), box(900, 400, 90, 90)]
    d = _scan(boxes)
    big = max(d["plants"], key=lambda p: p["leaf_count"])
    small = min(d["plants"], key=lambda p: p["leaf_count"])
    _move(big["leaf_ids"][0], small["pos"])

    d2 = _scan(boxes)                     # 똑같은 사진을 다시 스캔
    again = {p["pos"]: p["leaf_count"] for p in d2["plants"]}
    assert again[small["pos"]] == 2, again
    assert again[big["pos"]] == 1, again
    _reset()


def test_forgetting_fixes_gives_the_automatic_verdict_back():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    boxes = [box(300, 400, 90, 90), box(340, 430, 90, 90), box(900, 400, 90, 90)]
    d = _scan(boxes)
    big = max(d["plants"], key=lambda p: p["leaf_count"])
    small = min(d["plants"], key=lambda p: p["leaf_count"])
    _move(big["leaf_ids"][0], small["pos"])
    main.clear_leaf_fixes()

    d2 = _scan(boxes)
    again = {p["pos"]: p["leaf_count"] for p in d2["plants"]}
    assert again[big["pos"]] == 2, again
    _reset()


# ── 기존 수동 보정은 그대로 ─────────────────────────────────────────────
def test_plus_minus_buttons_still_work_with_leaf_records():
    """잎 기록이 생겨도 개체 단위 ± 버튼은 예전 그대로 동작해야 한다."""
    _reset()
    _set_pots([[0.25, 0.5]])
    d = _scan([box(300, 400, 90, 90)])
    pid = d["plants"][0]["id"]
    args = {"name": None, "rot": None, "note": None, "size_class": None,
            "shoot_count": None, "mature_count": 5, "old_count": None}
    p = asyncio.run(main.update_plant(pid=pid, **args))
    assert p["mature_count"] == 5 and p["leaf_count"] == 5, p
    assert p["manual"] is True
    _reset()


def test_a_hand_bump_survives_a_leaf_move_off_that_plant():
    """가려져서 못 잡은 잎을 손으로 메꿔 놨는데, 잡힌 잎 하나를 다른 화분으로
    옮기면 그 보정치가 통째로 사라지면 안 된다 — 옮긴 만큼만 깎여야 한다.
    """
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90, "mature leaf"), box(900, 400, 90, 90, "mature leaf")])
    a, b = d["plants"][0], d["plants"][1]          # 화분마다 실제 잎 1장씩
    assert a["leaf_count"] == 1 and b["leaf_count"] == 1

    # 가려진 잎이 하나 더 있다고 보고 손으로 mature_count 를 3으로 올린다
    asyncio.run(main.update_plant(pid=a["id"], name=None, rot=None, note=None, size_class=None,
                                  shoot_count=None, mature_count=3, old_count=None))
    assert main.PLANTS[a["id"]]["leaf_count"] == 3

    # 실제 잡힌 잎 1장을 옆 화분으로 옮긴다
    _move(a["leaf_ids"][0], b["pos"])

    # 옮긴 만큼(1장)만 깎여야 한다 — 3 - 1 = 2, LEAVES 기준으로 통째로 다시 세서 0 이 되면 안 된다
    assert main.PLANTS[a["id"]]["leaf_count"] == 2, main.PLANTS[a["id"]]
    assert main.PLANTS[a["id"]]["mature_count"] == 2, main.PLANTS[a["id"]]
    # 받은 쪽은 원래 1장에 옮겨온 1장을 더해 2장
    assert main.PLANTS[b["id"]]["leaf_count"] == 2, main.PLANTS[b["id"]]
    _reset()


def test_deleting_a_plant_forgets_its_leaves():
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    d = _scan([box(300, 400, 90, 90), box(900, 400, 90, 90)])
    main.remove_plant(d["plants"][0]["id"])
    left = {l["plant_id"] for l in main.LEAVES.values()}
    assert d["plants"][0]["id"] not in left, left
    _reset()


def test_leaves_endpoint_can_filter_to_the_ambiguous_ones():
    _reset()
    _set_pots([[0.45, 0.5], [0.55, 0.5]])       # 6cm 간격 — 사이에 낀 잎은 애매하다
    _scan([box(600, 400, 90, 90), box(200, 400, 90, 90)])
    every = main.list_leaves(ambiguous=None)
    only = main.list_leaves(ambiguous="1")
    assert every["count"] >= only["count"]
    assert all(l["ambiguous"] for l in only["leaves"])
    _reset()


def test_scan_without_marked_pots_still_works():
    """화분을 안 찍어 뒀으면 기준이 없다. 예전처럼 개체만 등록되면 된다."""
    _reset()
    d = _scan([box(300, 400, 90, 90), box(900, 400, 90, 90)])
    assert d["count"] >= 1
    assert main.LEAVES == {}, main.LEAVES
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
