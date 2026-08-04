"""식물 자리 이동 스모크 테스트 (네트워크 불필요)

실행:  python3 test_move.py

지금까지는 화분 자리가 자동(스캔·화분 최근접·배치 최적화 적용)으로만 정해졌다.
자동 배치가 틀렸을 때, 혹은 실제로 화분을 옮긴 뒤 기록만 맞출 때 사람이 직접
'이 식물을 저 자리로' 옮길 수단이 없었다. 그 경로를 검증한다.
"""

import asyncio
import json

from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import main


def _reset():
    main.POTS.clear(); main.PLANTS.clear(); main.FEATS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear()


def _plant(pid, pos, **kw):
    p = {"id": pid, "name": f"식물 {pos}", "pos": pos, "x": 0, "z": 0, "rot": 0,
         "size_class": "중품", "leaf_count": 3, "shoot_count": 0,
         "mature_count": 3, "old_count": 0, "top_leaf_size": "중엽",
         "top_leaf_pct": 12.0, "overlap_count": 0, "overlap_density": 0,
         "updated": "2026-01-01 00:00:00"}
    p.update(kw)
    main.PLANTS[pid] = p
    return p


def _move(pid, pos):
    return asyncio.run(main.move_plant(pid=pid, pos=pos))


def test_moving_to_an_empty_slot_relocates_it():
    _reset()
    _plant("p1", "C3")
    res = _move("p1", "D8")
    assert res["moved"] is True
    assert main.PLANTS["p1"]["pos"] == "D8"
    assert res["swapped_with"] is None
    _reset()


def test_the_coordinates_follow_the_new_slot():
    _reset()
    p = _plant("p1", "C3")
    before_x, before_z = p["x"], p["z"]
    _move("p1", "E10")
    moved = main.PLANTS["p1"]
    assert (moved["x"], moved["z"]) != (before_x, before_z)
    _reset()


def test_moving_onto_an_occupied_slot_swaps_instead_of_stacking():
    """자리 하나에 식물 둘이 앉으면 안 된다 — 자동으로 서로 자리를 맞바꾼다."""
    _reset()
    a = _plant("a", "C3")
    b = _plant("b", "D8")
    res = _move("a", "D8")
    assert res["moved"] is True
    assert res["swapped_with"]["id"] == "b"
    assert main.PLANTS["a"]["pos"] == "D8"
    assert main.PLANTS["b"]["pos"] == "C3", "쫓겨난 식물이 옮긴 식물의 옛 자리로 가야 한다"
    _reset()


def test_no_two_plants_ever_share_a_slot_after_a_swap():
    _reset()
    _plant("a", "C3"); _plant("b", "D8"); _plant("c", "E5")
    _move("a", "D8")
    positions = [p["pos"] for p in main.PLANTS.values()]
    assert len(positions) == len(set(positions)), positions
    _reset()


def test_moving_to_the_same_slot_is_a_no_op():
    _reset()
    _plant("a", "C3")
    res = _move("a", "C3")
    assert res["moved"] is False
    _reset()


def test_moving_to_an_unknown_slot_is_rejected():
    _reset()
    _plant("a", "C3")
    try:
        _move("a", "Z99")
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("없는 자리는 거부해야 한다")
    _reset()


def test_moving_an_unknown_plant_is_a_404():
    _reset()
    try:
        _move("nope", "C3")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 식물은 404")
    _reset()


def test_move_is_marked_manual():
    _reset()
    p = _plant("a", "C3")
    assert "manual" not in p
    assert main.PLANTS["a"] is p
    _move("a", "D8")
    assert main.PLANTS["a"]["manual"] is True
    _reset()


def test_leaves_follow_the_plant_when_it_moves():
    _reset()
    _plant("a", "C3")
    main.LEAVES["lf_1"] = {"leaf_id": "lf_1", "plant_id": "a", "pot_slot": "C3",
                           "stage": "mature", "centroid_uv": [0.2, 0.3],
                           "ambiguous": False, "manual": False,
                           "assign": {"nearest": "C3", "second": "C4", "margin": 0.3}}
    _move("a", "D8")
    assert main.LEAVES["lf_1"]["pot_slot"] == "D8"
    _reset()


def test_leaves_follow_both_plants_in_a_swap():
    _reset()
    _plant("a", "C3"); _plant("b", "D8")
    main.LEAVES["lf_a"] = {"leaf_id": "lf_a", "plant_id": "a", "pot_slot": "C3",
                           "stage": "mature", "centroid_uv": [0.1, 0.1],
                           "ambiguous": False, "manual": False,
                           "assign": {"nearest": "C3", "second": None, "margin": 1.0}}
    main.LEAVES["lf_b"] = {"leaf_id": "lf_b", "plant_id": "b", "pot_slot": "D8",
                           "stage": "old", "centroid_uv": [0.8, 0.8],
                           "ambiguous": False, "manual": False,
                           "assign": {"nearest": "D8", "second": None, "margin": 1.0}}
    _move("a", "D8")
    assert main.LEAVES["lf_a"]["pot_slot"] == "D8"
    assert main.LEAVES["lf_b"]["pot_slot"] == "C3"
    _reset()


def test_move_invalidates_hand_moved_leaf_memory():
    """손으로 옮긴 잎 기억은 좌표에 묶여 있다. 화분 배치가 바뀌면 무효다."""
    _reset()
    _plant("a", "C3"); _plant("b", "D8")
    main.LEAF_FIXES.append({"u": 0.2, "v": 0.3, "pot_slot": "C3"})
    _move("a", "D8")
    assert main.LEAF_FIXES == []
    _reset()


def test_pot_marked_farm_moves_the_real_pot_coordinates():
    """화분 자리를 지정해 뒀으면 격자 중앙이 아니라 실측 화분 위치로 옮겨야 한다."""
    _reset()
    asyncio.run(main.set_pots(points=json.dumps([[0.1, 0.5], [0.9, 0.5]]),
                              points_px=None, corners=None))
    slots = [pot["slot"] for pot in main.POTS]
    _plant("a", slots[0])
    _move("a", slots[1])
    expected = main._pot_xz_cm(slots[1])
    moved = main.PLANTS["a"]
    assert (moved["x"], moved["z"]) == (round(expected[0], 2), round(expected[1], 2))
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
