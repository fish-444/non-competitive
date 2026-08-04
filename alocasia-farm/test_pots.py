"""미리 지정한 화분 자리 스모크 테스트 (네트워크 불필요)

실행:  python3 test_pots.py

모델에 pot 클래스를 라벨링하는 대신, 화분 자리를 한 번 찍어 두고 재사용하는 경로를 검증한다.
핵심 이득은 두 가지: 라벨링 불필요, 그리고 화분마다 자리가 고정돼 개체가 안 섞이는 것.
"""

import asyncio
import io
import json
import math

from PIL import Image
from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import main
from main import group_plants, synthetic_pots


def box(cx, cy, w, h, cls="leaf"):
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


def _set_pots(points):
    return asyncio.run(main.set_pots(points=json.dumps(points), points_px=None, corners=None))


def _reset():
    main.POTS.clear(); main.PLANTS.clear(); main.FEATS.clear()


def test_pots_get_distinct_slots():
    _reset()
    res = _set_pots([[0.2, 0.3], [0.5, 0.3], [0.8, 0.3]])
    assert res["count"] == 3
    slots = [p["slot"] for p in res["pots"]]
    assert len(set(slots)) == 3, slots
    # 왼쪽에 찍은 화분이 왼쪽 자리를 받아야 한다
    assert int(slots[0][1:]) < int(slots[2][1:]), slots
    _reset()


def test_pixel_clicks_are_perspective_corrected():
    """사진 픽셀로 찍어 보내면 서버가 네 모서리로 왜곡을 펴서 저장한다."""
    _reset()
    # 위쪽이 좁은 사다리꼴 = 비스듬히 찍은 선반
    quad = [[300, 100], [700, 100], [900, 800], [100, 800]]
    # 사다리꼴 위쪽 변의 한가운데 → 선반에선 위쪽 정중앙(u=0.5, v=0)
    res = asyncio.run(main.set_pots(points=None, points_px=json.dumps([[500, 100]]),
                                    corners=json.dumps(quad)))
    assert abs(res["pots"][0]["u"] - 0.5) < 0.01, res["pots"]
    assert abs(res["pots"][0]["v"] - 0.0) < 0.01, res["pots"]
    _reset()


def test_pots_need_some_input():
    _reset()
    try:
        asyncio.run(main.set_pots(points=None, points_px=None, corners=None))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("입력이 없으면 거부해야 한다")
    _reset()


def test_bad_pot_input_rejected():
    _reset()
    for bad in ["{망가진", "[]", '[["a","b"]]']:
        try:
            asyncio.run(main.set_pots(points=bad, points_px=None, corners=None))
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError(f"거부해야 한다: {bad}")
    _reset()


def test_pot_coords_are_clamped():
    """범위를 벗어난 좌표가 와도 0~1 로 눌러 담는다."""
    _reset()
    res = _set_pots([[-0.5, 2.0]])
    assert res["pots"][0]["u"] == 0.0 and res["pots"][0]["v"] == 1.0
    _reset()


def test_synthetic_pot_size_follows_spacing():
    """화분 크기를 이웃 간격에서 추정한다 — 빽빽하면 작게, 성기면 크게."""
    _reset()
    _set_pots([[0.1, 0.5], [0.2, 0.5], [0.3, 0.5]])
    tight = synthetic_pots(1000, 667)[0]
    _reset()
    _set_pots([[0.1, 0.5], [0.5, 0.5], [0.9, 0.5]])
    loose = synthetic_pots(1000, 667)[0]
    assert (loose["x2"] - loose["x1"]) > (tight["x2"] - tight["x1"])
    _reset()


def test_preset_pots_group_leaves_without_any_pot_class():
    """모델이 화분을 전혀 안 잡아도, 지정해 둔 자리로 잎이 갈린다."""
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])
    canvas = (1000.0, 667.0)
    # 화분 클래스 없이 잎만 — 두 덩어리
    leaves = [box(250, 333, 90, 90), box(200, 300, 90, 90),
              box(750, 333, 90, 90), box(800, 300, 90, 90)]
    groups, slots = group_plants(leaves, canvas=canvas)
    assert len(groups) == 2, [len(g) for g in groups]
    assert len(slots) == 2, slots
    assert set(slots.values()) == {p["slot"] for p in main.POTS}
    _reset()


def test_model_pots_win_over_preset():
    """모델이 화분을 잡았으면 그걸 쓴다 (지정값은 대비책)."""
    _reset()
    _set_pots([[0.5, 0.5]])                      # 지정은 1개뿐
    boxes = [box(250, 333, 150, 150, "pot"), box(750, 333, 150, 150, "pot"),
             box(250, 333, 90, 90), box(750, 333, 90, 90)]
    groups, slots = group_plants(boxes, canvas=(1000.0, 667.0))
    assert len(groups) == 2, "모델 화분 2개를 따라야 한다"
    assert slots == {}, "모델이 잡았으면 고정 자리를 쓰지 않는다"
    _reset()


def test_same_pot_keeps_same_slot_across_scans():
    """같은 화분은 몇 번을 스캔해도 같은 자리 = 같은 개체. 이름도 유지된다."""
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5]])

    def leaves_at(shift):
        # 촬영마다 잎이 조금씩 움직여도 자리가 흔들리면 안 된다
        return [box(250 + shift, 333, 90, 90), box(750 + shift, 333, 90, 90)]

    orig_detect = main.detect_boxes
    try:
        for shift in (0, 40, -35):
            main.detect_boxes = lambda image, det=None, s=shift: (leaves_at(s), float(1200 * 800))
            res = asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
            assert res["count"] == 2, res["count"]
            assert res["grouped_by"] == "pot_preset", res["grouped_by"]
            if shift == 0:
                first = sorted(p["pos"] for p in res["plants"])
                # 사용자가 이름을 붙여 둔다
                for p in main.PLANTS.values():
                    p["name"] = "내 " + p["pos"]
            else:
                assert sorted(p["pos"] for p in res["plants"]) == first, "자리가 흔들렸다"
                assert len(main.PLANTS) == 2, f"개체가 늘었다: {len(main.PLANTS)}"
                assert all(p["name"].startswith("내 ") for p in main.PLANTS.values())
    finally:
        main.detect_boxes = orig_detect
        _reset()


def test_scan_without_preset_still_works():
    """화분 자리를 안 정해 뒀으면 기존 동작(거리+생김새) 그대로."""
    _reset()
    orig_detect = main.detect_boxes
    main.detect_boxes = lambda image, det=None: (
        [box(200, 300, 90, 90), box(900, 300, 90, 90)], float(1200 * 800))
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
        assert res["count"] == 2 and res["grouped_by"] == "distance", res
    finally:
        main.detect_boxes = orig_detect
        _reset()


def test_pot_refs_recover_a_tilted_shot():
    """모서리가 안 보여도, 이미 아는 화분 4개만 찍으면 원근이 펴진다.

    케이지가 좁아 트레이 모서리를 프레임에 못 담는 실제 상황을 위한 경로.
    """
    _reset()
    # 화분 4개를 선반 네 귀퉁이 쪽에 지정해 둔다
    _set_pots([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    CANVAS, ch = 1000.0, 1000.0 * (main._D / main._W)

    # 그 화분들이 비스듬한 사진에서 이렇게 찍혔다고 하자 (사다리꼴)
    seen = [(400, 200), (800, 200), (950, 700), (250, 700)]
    refs = [[i, x, y] for i, (x, y) in enumerate(seen)]

    def fake_detect(image, detector=None):
        # 각 화분 위치에 잎 하나씩
        return [box(x, y, 60, 60) for x, y in seen], float(1200 * 800)

    orig = main.detect_boxes
    main.detect_boxes = fake_detect
    try:
        res = asyncio.run(main.scan_multi(
            files=[_Upload(_jpeg())], corners=None, regions=None,
            replace=None, pot_refs=json.dumps([refs]), mode=None))
        assert res["count"] == 4, res["count"]
        assert res["grouped_by"] == "pot_preset", res["grouped_by"]
        # 지정해 둔 화분의 자리에 정확히 들어가야 한다
        assert sorted(p["pos"] for p in res["plants"]) == sorted(p["slot"] for p in main.POTS)
    finally:
        main.detect_boxes = orig
        _reset()


def test_every_marked_pot_shows_up_even_with_no_leaves():
    """지정한 화분 수 = 등록되는 개체 수.

    잎이 하나도 안 잡힌 화분(빈 화분이거나 완전히 가려짐)이 빠지면서
    개체 수가 실제 화분 수보다 적게 나왔다.
    """
    _reset()
    _set_pots([[0.25, 0.5], [0.75, 0.5], [0.4, 0.8]])     # 화분 3개
    orig = main.detect_boxes
    # 잎은 첫 두 화분 근처에만 잡힌다
    main.detect_boxes = lambda im, det=None: (
        [box(300, 400, 90, 90, "mature leaf"), box(900, 400, 90, 90, "shoot")],
        float(1200 * 800))
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
        assert res["count"] == 3, f"화분 3개인데 개체 {res['count']}개"
        assert sorted(p["pos"] for p in res["plants"]) == sorted(p["slot"] for p in main.POTS)
        empties = [p for p in res["plants"] if p.get("empty")]
        assert len(empties) == 1 and empties[0]["leaf_count"] == 0, empties
        # 잎을 못 찾은 것과 '작은 식물'은 다르다 — 소품으로 적으면 실제 소품과 섞인다
        assert empties[0]["size_class"] == "미검출", empties[0]["size_class"]
    finally:
        main.detect_boxes = orig
        _reset()


def test_plants_sit_at_their_measured_spot_not_the_grid_cell():
    """격자 칸 중앙으로 스냅하면 가까운 화분끼리 한 줄로 뭉쳐 보인다."""
    _reset()
    _set_pots([[0.10, 0.62], [0.22, 0.66], [0.34, 0.70]])   # 촘촘하고 비스듬한 배치
    main._ensure_pot_slots([])
    for p in main.PLANTS.values():
        slot = main._slot_by_label(p["pos"])
        assert (p["x"], p["z"]) != (slot["x"], slot["z"]), "칸 중앙으로 스냅됐다"
    zs = sorted(round(p["z"], 1) for p in main.PLANTS.values())
    assert len(set(zs)) == 3, f"세 화분이 같은 줄로 뭉쳤다: {zs}"
    _reset()


def test_reassigning_pots_clears_the_old_ghosts():
    """화분 자리를 다시 찍으면 예전 자리 식물은 유령이 된다.

    화분 14개를 지정했는데 개체가 24개로 불어난 게 이것 때문이었다.
    """
    _reset()
    _set_pots([[0.2, 0.2], [0.8, 0.2]])
    main._ensure_pot_slots([])
    assert len(main.PLANTS) == 2

    # 다른 위치로 다시 지정 → 예전 자리 두 개는 유령
    res = _set_pots([[0.3, 0.7], [0.7, 0.7], [0.5, 0.4]])
    assert res["removed"] == 2, res["removed"]
    assert len(main.PLANTS) == 0, main.PLANTS

    main._ensure_pot_slots([])
    assert len(main.PLANTS) == 3 == len(main.POTS)
    _reset()


def test_scan_cleans_ghosts_and_reports_them():
    _reset()
    _set_pots([[0.5, 0.5]])
    main.PLANTS["ghost"] = {"id": "ghost", "name": "예전 식물", "pos": "A1",
                            "x": 0, "z": 0, "leaf_count": 3}
    orig = main.detect_boxes
    main.detect_boxes = lambda im, det=None: (
        [box(600, 400, 90, 90, "mature leaf")], float(1200 * 800))
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
        assert res["removed"] == 1, res["removed"]
        assert res["count"] == 1 and "ghost" not in main.PLANTS
    finally:
        main.detect_boxes = orig
        _reset()


def test_no_pots_defined_means_no_cleanup():
    """화분 자리를 안 정했으면 함부로 지우지 않는다."""
    _reset()
    main.PLANTS["p1"] = {"id": "p1", "name": "손으로 넣은 식물", "pos": "A1", "x": 0, "z": 0}
    assert main._drop_orphans() == 0
    assert "p1" in main.PLANTS
    _reset()


def test_empty_flag_clears_once_leaves_appear():
    """빈 화분에 잎이 잡히면 '빈 화분' 표시가 사라져야 한다."""
    _reset()
    _set_pots([[0.5, 0.5]])
    orig = main.detect_boxes
    try:
        main.detect_boxes = lambda im, det=None: ([], float(1200 * 800))
        try:
            asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
        except HTTPException:
            pass                       # 잎이 하나도 없으면 스캔 자체는 거부됨
        main.PLANTS.clear()
        main._ensure_pot_slots([])     # 빈 화분 자리만 만들어 둔다
        pid = list(main.PLANTS)[0]
        assert main.PLANTS[pid].get("empty") is True

        main.detect_boxes = lambda im, det=None: (
            [box(600, 400, 90, 90, "mature leaf")], float(1200 * 800))
        asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode="keep"))
        assert "empty" not in main.PLANTS[pid], main.PLANTS[pid]
        assert main.PLANTS[pid]["leaf_count"] == 1
    finally:
        main.detect_boxes = orig
        _reset()


def test_pot_refs_need_four_points():
    _reset()
    _set_pots([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8]])
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())], corners=None, regions=None,
                                    replace=None,
                                    pot_refs=json.dumps([[[0, 10, 10], [1, 90, 10]]]), mode=None))
    except HTTPException as e:
        assert e.status_code == 400 and "4개" in e.detail, e.detail
    else:
        raise AssertionError("기준점이 모자라면 거부해야 한다")
    _reset()


def test_pot_refs_require_defined_pots():
    _reset()
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())], corners=None, regions=None,
                                    replace=None, pot_refs=json.dumps([[[0, 1, 1]]]), mode=None))
    except HTTPException as e:
        assert e.status_code == 400 and "화분 자리" in e.detail
    else:
        raise AssertionError("화분 자리가 없으면 거부해야 한다")
    _reset()


def test_unknown_pot_index_rejected():
    _reset()
    _set_pots([[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]])
    bad = [[0, 10, 10], [1, 90, 10], [2, 90, 90], [9, 10, 90]]     # 9번 화분은 없음
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())], corners=None, regions=None,
                                    replace=None, pot_refs=json.dumps([bad]), mode=None))
    except HTTPException as e:
        assert e.status_code == 400 and "9번" in e.detail, e.detail
    else:
        raise AssertionError("없는 화분 번호를 거부해야 한다")
    _reset()


def test_neither_corners_nor_pot_refs_rejected():
    _reset()
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())], corners=None, regions=None,
                                    replace=None, pot_refs=None, mode=None))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("기준이 아무것도 없으면 거부해야 한다")
    _reset()


def test_extra_pot_refs_average_out_click_error():
    """4개보다 많이 찍으면 최소제곱으로 클릭 오차가 줄어든다."""
    from main import homography_lstsq, apply_h
    true_src = [(100, 100), (900, 120), (920, 700), (80, 680), (500, 400), (300, 200)]
    dst = [(0, 0), (1000, 0), (1000, 667), (0, 667), (500, 333), (250, 111)]
    # 손떨림처럼 몇 px 씩 어긋나게 찍었다고 하자
    noisy = [(x + d, y - d) for (x, y), d in zip(true_src, [6, -5, 4, -6, 5, -4])]

    four = homography_lstsq(noisy[:4], dst[:4])
    six = homography_lstsq(noisy, dst)
    err = lambda H: sum(math.dist(apply_h(H, *s), d) for s, d in zip(true_src, dst))
    assert err(six) < err(four), (err(six), err(four))


# ── canopy 앵커 + 화분 자리 매칭 ──────────────────────────────────────────
# canopy 는 잎을 묶어 주지만(화분처럼) '이 자리 = 항상 같은 식물' 이라는 고정
# 라벨은 안 준다(모델이 그 사진에서 직접 잡은 박스라 predefined 가 아니다). 그래서
# 무리의 무게중심을 마크해 둔 화분 중 가장 가까운 곳에 매칭해야 한다 — 격자 50칸
# 전체에서 고르면 마크 안 한 빈 칸이 걸릴 수 있다.
from main import _nearest_pot_or_slot


def test_nearest_pot_or_slot_only_considers_marked_pots():
    _reset()
    _set_pots([[0.1, 0.1], [0.9, 0.9]])
    marked = {p["slot"] for p in main.POTS}
    # 정중앙 — 격자로만 고르면 마크 안 한 가운데 칸이 뽑히지만, 화분은 두 개뿐이다
    slot = _nearest_pot_or_slot(0.0, 0.0, set())
    assert slot["label"] in marked, (slot, marked)
    _reset()


def test_nearest_pot_or_slot_falls_back_to_the_grid_when_nothing_is_marked():
    _reset()
    slot = _nearest_pot_or_slot(0.0, 0.0, set())
    assert slot is not None and slot["label"] not in set()
    _reset()


def test_nearest_pot_or_slot_returns_none_when_every_marked_pot_is_taken():
    _reset()
    _set_pots([[0.1, 0.1]])
    taken = {p["slot"] for p in main.POTS}
    assert _nearest_pot_or_slot(0.0, 0.0, taken) is None
    _reset()


def test_canopy_grouped_scan_lands_on_the_marked_pot_not_a_stray_grid_cell():
    """캐노피로 묶인 무리가, 격자상 더 가까운 빈 칸이 아니라 실제 화분 자리로 간다."""
    _reset()
    _set_pots([[0.15, 0.5], [0.85, 0.5]])
    left_slot, right_slot = (p["slot"] for p in main.POTS)

    canopy = [box(180, 400, 300, 300, cls="canopy"), box(1020, 400, 300, 300, cls="canopy")]
    leaves = [box(160, 380, 60, 60), box(200, 420, 60, 60),   # 왼쪽 캐노피 안
             box(1000, 380, 60, 60)]                           # 오른쪽 캐노피 안

    orig = main.detect_boxes
    main.detect_boxes = lambda im, det=None: (canopy + leaves, float(1200 * 800))
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=None))
    finally:
        main.detect_boxes = orig

    assert res["grouped_by"] == "canopy", res
    positions = {p["pos"] for p in res["plants"]}
    assert positions == {left_slot, right_slot}, (positions, left_slot, right_slot)
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
