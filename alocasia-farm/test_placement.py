"""배치 최적화 스모크 테스트 (네트워크 불필요)

실행:  python3 test_placement.py

'어느 화분에 어느 식물을 두면 잘 자라나'를 계산하는 부분. 팬은 없고 빛만 본다.
조명은 화분 자리를 표시할 때 찍어 둔 세 지점이 기본값이고, 사람이 실측 위치로
바꿀 수 있다. 물리가 그럴듯한지(조명에 가까우면 밝다, 빔 각도 밖은 안 비친다,
큰 이웃이 그늘을 만든다)와 자리를 바꿔서 점수가 실제로 올라가는지를 확인한다.
"""

import asyncio
import json

from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import main
import placement


def _plant(pid, pos, grade="중품", leaf_cm=None, density=0):
    return {"id": pid, "name": f"식물 {pos}", "pos": pos, "size_class": grade,
            "leaf_max_cm": leaf_cm, "overlap_density": density,
            "leaf_count": 5, "shoot_count": 1, "mature_count": 3, "old_count": 1}


def _spot(slot, x_cm, z_cm, plant=None, r_cm=13.0, h_cm=28.0):
    return {"slot": slot, "x_cm": x_cm, "z_cm": z_cm, "r_cm": r_cm, "h_cm": h_cm,
            "plant": plant or _plant(slot, slot)}


def _reset():
    main.POTS.clear(); main.PLANTS.clear(); main.FEATS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear(); main.ENVIRONMENT.clear()


# ── 빛 ───────────────────────────────────────────────────────────────────
def test_under_the_lamp_is_brighter_than_the_corner():
    lamp = [{"x": 0.0, "y": 40.0, "z": 0.0, "power": 1.0, "angle": 60}]
    middle = placement.illuminance(0, 0, lamp)
    corner = placement.illuminance(-28, -18, lamp)
    assert middle > corner, (middle, corner)


def test_light_falls_off_with_distance_squared():
    """거리가 2배면 밝기는 대략 1/4 이하 (입사각까지 더 나빠진다)."""
    lamp = [{"x": 0.0, "y": 20.0, "z": 0.0, "power": 1.0, "angle": 89}]
    near = placement.illuminance(0, 0, lamp, canopy_y_cm=0)      # 20cm 아래
    far = placement.illuminance(0, 0, lamp, canopy_y_cm=-20)     # 40cm 아래
    assert far < near / 4 * 1.05, (near, far)


def test_two_lamps_beat_one():
    one = [{"x": 0.0, "y": 40.0, "z": 0.0, "angle": 60}]
    two = one + [{"x": 10.0, "y": 40.0, "z": 0.0, "angle": 60}]
    assert placement.illuminance(5, 0, two) > placement.illuminance(5, 0, one)


def test_outside_the_beam_angle_gets_nothing():
    """스팟등이라 빔 반각 밖은 아예 안 비친다."""
    narrow = [{"x": 0.0, "y": 30.0, "z": 0.0, "power": 1.0, "angle": 15}]
    under = placement.illuminance(0, 0, narrow)          # 바로 아래 — 빔 안
    far_side = placement.illuminance(25, 0, narrow)       # 30cm 높이에서 25cm 옆 — 빔 밖
    assert under > 0 and far_side == 0.0, (under, far_side)


def test_a_wider_beam_covers_more_ground():
    # y=30, canopy=18 → 수직 거리 12cm. 옆으로 10cm면 입사각 ≈ atan(10/12) ≈ 40도.
    lamp_x = lambda angle: {"x": 0.0, "y": 30.0, "z": 0.0, "power": 1.0, "angle": angle}
    assert placement.illuminance(10, 0, [lamp_x(15)]) == 0.0
    assert placement.illuminance(10, 0, [lamp_x(45)]) > 0.0


def test_default_lights_sit_where_pots_were_first_marked():
    """기본 조명은 화분 자리를 처음 표시할 때 찍은 세 지점이다."""
    assert len(placement.DEFAULT_LIGHTS) == placement.LIGHT_COUNT == 3
    xz = {(round(l["x"]), round(l["z"])) for l in placement.DEFAULT_LIGHTS}
    assert xz == {(-22, 17), (-22, -13), (22, 2)}, xz
    assert all(l.get("angle") == 30 for l in placement.DEFAULT_LIGHTS)
    assert {l["side"] for l in placement.DEFAULT_LIGHTS} == {"left", "right"}


def test_rail_x_is_fixed_by_side():
    """조명은 레일에 달려 있다 — x 는 좌/우로만 정해지고 사람이 못 바꾼다."""
    left, right = placement.rail_x("left"), placement.rail_x("right")
    assert left == -right and left < 0 < right
    assert left == placement.DEFAULT_LIGHTS[0]["x"]


# ── 채점 ─────────────────────────────────────────────────────────────────
def test_score_reports_every_spot():
    spots = [_spot("C3", -10, 0), _spot("C7", 10, 0)]
    got = placement.score_layout(spots)
    assert 0 <= got["score"] <= 100
    assert {s["slot"] for s in got["spots"]} == {"C3", "C7"}
    for s in got["spots"]:
        for key in ("light", "shade", "score", "need_light"):
            assert key in s, (key, s)


def test_a_big_plant_needs_more_light():
    assert placement._need_light(20.0) > placement._need_light(7.0)


def test_measured_leaf_beats_the_grade():
    """실측 잎 길이가 있으면 등급 기본값 대신 그걸 쓴다."""
    r_graded, _ = placement.plant_shape(_plant("p1", "C3", "소품"))
    r_measured, _ = placement.plant_shape(_plant("p2", "C4", "소품", leaf_cm=24))
    assert r_measured > r_graded * 2, (r_graded, r_measured)


def test_empty_farm_scores_zero_without_crashing():
    assert placement.score_layout([])["score"] == 0.0


# ── 최적화 ───────────────────────────────────────────────────────────────
def test_swapping_a_shaded_small_plant_helps():
    """어두운 구석의 대품과 밝은 자리의 소품을 바꾸면 점수가 올라야 한다."""
    lamp = [{"x": -25.0, "y": 40.0, "z": 0.0, "angle": 60}]
    big = _plant("big", "C2", "대품", leaf_cm=22)
    small = _plant("small", "C9", "소품", leaf_cm=6)
    spots = [_spot("C2", 25, 0, small, r_cm=6, h_cm=13),    # 밝은 자리에 소품
             _spot("C9", -25, 0, big, r_cm=22, h_cm=48)]    # 어두운 자리에 대품
    res = placement.optimize(spots, lamp)
    assert res["after"] >= res["before"], res
    if res["moves"]:
        assert res["gain"] > 0, res


def test_every_plant_gets_exactly_one_new_home():
    """제안이 '한 자리에 둘'이 되면 사람이 실행할 수 없다."""
    lamp = [{"x": -25.0, "y": 40.0, "z": 0.0, "angle": 60}]
    spots = [_spot("C1", -25, 0, _plant("a", "C1", "소품", leaf_cm=6), 6, 13),
             _spot("C5", 0, 0, _plant("b", "C5", "중품", leaf_cm=13), 13, 28),
             _spot("C9", 25, 0, _plant("c", "C9", "대품", leaf_cm=22), 22, 48)]
    res = placement.optimize(spots, lamp)
    slots = [s["slot"] for s in spots]
    froms = [m["from"] for m in res["moves"]]
    tos = [m["to"] for m in res["moves"]]
    assert len(set(froms)) == len(froms), froms
    assert len(set(tos)) == len(tos), tos
    assert set(froms) == set(tos), (froms, tos)      # 자리를 서로 채워 준다
    for mv in res["moves"]:
        assert mv["from"] in slots and mv["to"] in slots and mv["from"] != mv["to"], mv


def test_a_three_way_rotation_is_reported_as_a_ring():
    """둘씩 맞바꿔서 안 끝나는 배치는 '고리'로 알려 줘야 한다."""
    lamp = [{"x": -28.0, "y": 40.0, "z": -18.0, "angle": 70}]
    grades = ["대품", "소품", "중품", "대품", "소품", "중품"]
    spots = [_spot(f"C{i+1}", -25 + i * 10, (i % 2) * 12 - 6,
                   _plant(f"p{i}", f"C{i+1}", g, density=i * 15),
                   *placement.GRADE_SHAPE[g])
             for i, g in enumerate(grades)]
    res = placement.optimize(spots, lamp)
    moved = {m["from"] for m in res["moves"]}
    # 고리에 든 자리를 다 합치면 움직이는 자리 전체와 같아야 한다
    assert {s for ring in res["cycles"] for s in ring} == moved, (res["cycles"], moved)
    for ring in res["cycles"]:
        assert len(ring) == len(set(ring)) >= 2, ring


def test_one_plant_has_nothing_to_swap():
    res = placement.optimize([_spot("C3", 0, 0)])
    assert res["moves"] == [] and res["cycles"] == []
    assert res["before"] == res["after"]


def test_optimize_never_makes_it_worse():
    lamp = [{"x": -20.0, "y": 40.0, "z": 10.0, "angle": 60}]
    grades = ["소품", "중품", "대품", "중품", "소품"]
    spots = [_spot(f"C{i+1}", -24 + i * 12, 0, _plant(f"p{i}", f"C{i+1}", g))
             for i, g in enumerate(grades)]
    res = placement.optimize(spots, lamp)
    assert res["after"] >= res["before"] - 1e-9, res


# ── 히트맵 ───────────────────────────────────────────────────────────────
def test_heatmap_covers_the_shelf():
    hm = placement.heatmap(60, 40, 10, 7)
    assert hm["cols"] == 10 and hm["rows"] == 7
    assert len(hm["light"]) == 7 and len(hm["light"][0]) == 10
    assert max(v for row in hm["light"] for v in row) == 1.0   # 제일 밝은 곳이 1


# ── 엔드포인트 ───────────────────────────────────────────────────────────
def test_environment_defaults_to_the_originally_marked_lights():
    _reset()
    env = main.get_environment()
    assert env["custom"] is False
    assert env["lights"] == placement.DEFAULT_LIGHTS
    _reset()


def _three(*overrides):
    base = [{"side": "left", "z": 17, "y": 47, "power": 1, "angle": 30},
            {"side": "left", "z": -13, "y": 47, "power": 1, "angle": 30},
            {"side": "right", "z": 2, "y": 47, "power": 1, "angle": 30}]
    for i, patch in enumerate(overrides):
        base[i] = {**base[i], **patch}
    return base


def test_environment_then_takes_real_positions():
    _reset()
    asyncio.run(main.set_environment(
        lights=json.dumps(_three({"y": 55, "z": 5, "power": 2, "angle": 25}))))
    env = main.get_environment()
    assert env["custom"] is True and env["lights"][0]["y"] == 55
    assert env["lights"][0]["angle"] == 25
    _reset()


def test_environment_pins_x_to_the_rail_regardless_of_what_is_sent():
    """레일에 고정돼 있으니 x 를 직접 보내도 무시하고 side 로만 정한다."""
    _reset()
    sneaky = _three({"x": 0})       # 가운데로 보내 봐도
    asyncio.run(main.set_environment(lights=json.dumps(sneaky)))
    env = main.get_environment()
    assert env["lights"][0]["x"] == placement.rail_x("left"), env["lights"][0]
    _reset()


def test_environment_z_is_clamped_to_the_shelf():
    _reset()
    asyncio.run(main.set_environment(lights=json.dumps(_three({"z": 999}))))
    env = main.get_environment()
    assert env["lights"][0]["z"] == main._D / 2, env["lights"][0]
    _reset()


def test_bad_environment_is_refused():
    _reset()
    bad_count = json.dumps(_three()[:2])          # 2개뿐 — 레일엔 3개가 달려 있다
    bad_side = json.dumps(_three({"side": "middle"}))
    for bad in ("{oops", json.dumps({"x": 1}), json.dumps([]), bad_count, bad_side):
        try:
            asyncio.run(main.set_environment(lights=bad))
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError(f"거부해야 한다: {bad}")
    _reset()


def _farm(grades):
    """화분을 찍고 그 자리에 식물을 앉힌다."""
    _reset()
    pts = [[0.1 + 0.16 * i, 0.5] for i in range(len(grades))]
    asyncio.run(main.set_pots(points=json.dumps(pts), points_px=None, corners=None))
    for i, (pot, grade) in enumerate(zip(main.POTS, grades)):
        xz = main._pot_xz_cm(pot["slot"])
        main.PLANTS[f"p{i}"] = {**_plant(f"p{i}", pot["slot"], grade), "x": xz[0], "z": xz[1]}


def test_placement_endpoint_grades_the_current_layout():
    _farm(["대품", "소품", "중품"])
    got = main.get_placement()
    assert 0 <= got["score"] <= 100
    assert len(got["spots"]) == 3
    assert len(got["worst"]) == 3 and got["worst"][0]["score"] <= got["worst"][-1]["score"]
    _reset()


def test_optimize_endpoint_suggests_without_moving_anything():
    """제안만 한다. 화분은 사람이 옮기기 전까지 기록이 안 바뀌어야 한다."""
    _farm(["소품", "중품", "대품"])
    before = {pid: p["pos"] for pid, p in main.PLANTS.items()}
    got = main.optimize_placement()
    assert "moves" in got and "cycles" in got, got
    after = {pid: p["pos"] for pid, p in main.PLANTS.items()}
    assert before == after, (before, after)
    _reset()


def _swap_moves(a, b):
    return json.dumps([{"plant_id": a["id"], "from": a["pos"], "to": b["pos"]},
                       {"plant_id": b["id"], "from": b["pos"], "to": a["pos"]}])


def test_apply_swaps_the_records_and_the_coordinates():
    _farm(["소품", "대품"])
    a, b = (main.PLANTS["p0"], main.PLANTS["p1"])
    slot_a, slot_b = a["pos"], b["pos"]
    x_a = a["x"]
    res = asyncio.run(main.apply_placement(moves=_swap_moves(a, b)))
    assert res["applied"] == 2
    assert a["pos"] == slot_b and b["pos"] == slot_a
    assert a["x"] != x_a, "좌표가 자리를 따라가야 한다"
    _reset()


def test_apply_walks_a_three_way_ring():
    """A→B, B→C, C→A. 둘씩 바꾸는 게 아니라 고리째 돌아간다."""
    _farm(["소품", "중품", "대품"])
    a, b, c = main.PLANTS["p0"], main.PLANTS["p1"], main.PLANTS["p2"]
    sa, sb, sc = a["pos"], b["pos"], c["pos"]
    res = asyncio.run(main.apply_placement(moves=json.dumps([
        {"plant_id": a["id"], "from": sa, "to": sb},
        {"plant_id": b["id"], "from": sb, "to": sc},
        {"plant_id": c["id"], "from": sc, "to": sa}])))
    assert res["applied"] == 3
    assert (a["pos"], b["pos"], c["pos"]) == (sb, sc, sa)
    assert len({a["pos"], b["pos"], c["pos"]}) == 3, "두 식물이 한 자리에 앉으면 안 된다"
    _reset()


def test_apply_refuses_a_plan_that_stacks_two_plants():
    _farm(["소품", "중품", "대품"])
    a, b, c = main.PLANTS["p0"], main.PLANTS["p1"], main.PLANTS["p2"]
    try:
        asyncio.run(main.apply_placement(moves=json.dumps([
            {"plant_id": a["id"], "from": a["pos"], "to": c["pos"]},
            {"plant_id": b["id"], "from": b["pos"], "to": c["pos"]}])))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("한 자리에 둘은 거부해야 한다")
    _reset()


def test_apply_refuses_moving_onto_a_plant_that_stays_put():
    _farm(["소품", "중품", "대품"])
    a, c = main.PLANTS["p0"], main.PLANTS["p2"]
    try:
        asyncio.run(main.apply_placement(moves=json.dumps([
            {"plant_id": a["id"], "from": a["pos"], "to": c["pos"]}])))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("가만히 있는 식물 자리로는 못 간다")
    _reset()


def test_apply_moves_the_leaf_records_too():
    _farm(["소품", "대품"])
    a, b = main.PLANTS["p0"], main.PLANTS["p1"]
    main.LEAVES["lf_1"] = {"leaf_id": "lf_1", "plant_id": "p0", "pot_slot": a["pos"],
                           "stage": "mature", "centroid_uv": [0.1, 0.5],
                           "ambiguous": False, "manual": False,
                           "assign": {"nearest": a["pos"], "second": b["pos"], "margin": 0.4}}
    main.LEAF_FIXES.append({"u": 0.1, "v": 0.5, "pot_slot": a["pos"]})
    slot_a, slot_b = a["pos"], b["pos"]
    asyncio.run(main.apply_placement(moves=_swap_moves(a, b)))
    assert main.LEAVES["lf_1"]["pot_slot"] == slot_b
    assert main.LEAF_FIXES == [], "식물이 옮겨졌으니 좌표에 묶인 보정은 무효다"
    _reset()


def test_apply_ignores_slots_with_no_plant():
    _farm(["소품", "대품"])
    res = asyncio.run(main.apply_placement(
        moves=json.dumps([{"plant_id": "nope", "from": "E10", "to": "E9"}])))
    assert res["applied"] == 0
    _reset()


def test_apply_refuses_junk():
    _reset()
    for bad in ("{oops", json.dumps({"from": "A1"})):
        try:
            asyncio.run(main.apply_placement(moves=bad))
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError(f"거부해야 한다: {bad}")
    _reset()


def test_heatmap_endpoint_clamps_silly_sizes():
    _reset()
    assert main.get_heatmap(cols=999, rows=1)["cols"] == 60
    assert main.get_heatmap(cols=1, rows=999)["rows"] == 40
    _reset()


# ── 예전 자유배치 저장값 되살리기 ────────────────────────────────────────
def test_old_side_less_lights_migrate_to_the_matching_rail():
    """레일 도입 전 저장값(side 없음)은 x 부호로 좌/우를 되살린다."""
    _reset()
    main.ENVIRONMENT["lights"] = [
        {"x": -22, "y": 47, "z": 17, "power": 1, "angle": 30},
        {"x": -22, "y": 47, "z": -13, "power": 1, "angle": 30},
        {"x": 22, "y": 47, "z": 2, "power": 1, "angle": 30}]
    env = main.get_environment()
    sides = sorted(l["side"] for l in env["lights"])
    assert sides == ["left", "left", "right"], sides
    assert all(l["x"] == placement.rail_x(l["side"]) for l in env["lights"])
    _reset()


def test_migration_persists_so_it_only_happens_once():
    """한 번 되살리면 저장돼서 다음부터는 그대로 쓴다."""
    _reset()
    main.ENVIRONMENT["lights"] = [
        {"x": -22, "y": 47, "z": 17, "power": 1, "angle": 30},
        {"x": -22, "y": 47, "z": -13, "power": 1, "angle": 30},
        {"x": 22, "y": 47, "z": 2, "power": 1, "angle": 30}]
    main.get_environment()
    assert all("side" in l for l in main.ENVIRONMENT["lights"])
    _reset()


def test_a_save_after_migration_actually_works():
    """예전 값을 물려받은 채로 드래그해도 저장이 거부되면 안 된다."""
    _reset()
    main.ENVIRONMENT["lights"] = [
        {"x": -22, "y": 47, "z": 17, "power": 1, "angle": 30},
        {"x": -22, "y": 47, "z": -13, "power": 1, "angle": 30},
        {"x": 22, "y": 47, "z": 2, "power": 1, "angle": 30}]
    env = main.get_environment()          # 프런트가 로드하며 되살아난 값
    env["lights"][0]["z"] = 9.9           # 사람이 끌어서 옮긴 것을 흉내낸다
    asyncio.run(main.set_environment(lights=json.dumps(env["lights"])))
    assert main.get_environment()["lights"][0]["z"] == 9.9
    _reset()


def test_a_wrong_light_count_from_before_the_rail_falls_back_to_default():
    """레일 도입 전 자유롭게 늘렸던 개수는 안전하게 기본값으로 되돌린다."""
    _reset()
    main.ENVIRONMENT["lights"] = [{"x": 0, "y": 47, "z": 0, "power": 1, "angle": 30}]
    env = main.get_environment()
    assert env["lights"] == placement.DEFAULT_LIGHTS
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
