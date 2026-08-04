"""원근 보정 + 여러 장 합치기 스모크 테스트 (네트워크 불필요)

실행:  python3 test_perspective.py

사진을 이어 붙이지 않고, 사진마다 네 모서리로 원근 변환을 구해
'탐지 좌표'만 하나의 선반 좌표계로 옮기는 부분을 검증한다.
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
from main import apply_h, homography, warp_box


def box(cx, cy, w, h, cls="leaf", conf=0.9):
    return {"cls": cls, "conf": conf,
            "x1": cx - w / 2, "y1": cy - h / 2, "x2": cx + w / 2, "y2": cy + h / 2,
            "area": w * h}


class _Upload:
    content_type = "image/jpeg"

    def __init__(self, raw):
        self._raw = raw

    async def read(self):
        return self._raw


def _jpeg(w=1200, h=900):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (25, 90, 35)).save(buf, format="JPEG")
    return buf.getvalue()


def test_identity_homography():
    """같은 사각형끼리 대응시키면 점이 그대로 나와야 한다."""
    sq = [(0, 0), (100, 0), (100, 50), (0, 50)]
    H = homography(sq, sq)
    for x, y in [(0, 0), (50, 25), (100, 50), (30, 10)]:
        u, v = apply_h(H, x, y)
        assert math.isclose(u, x, abs_tol=1e-6) and math.isclose(v, y, abs_tol=1e-6)


def test_corners_map_exactly_to_target():
    """찍은 네 모서리는 목표 직사각형의 네 꼭짓점으로 정확히 간다."""
    quad = [(120, 80), (900, 40), (1050, 700), (60, 640)]     # 비스듬한 사각형
    dst = [(0, 0), (1000, 0), (1000, 667), (0, 667)]
    H = homography(quad, dst)
    for (x, y), (tx, ty) in zip(quad, dst):
        u, v = apply_h(H, x, y)
        assert math.isclose(u, tx, abs_tol=1e-6), (u, tx)
        assert math.isclose(v, ty, abs_tol=1e-6), (v, ty)


def test_perspective_actually_undoes_a_tilt():
    """사다리꼴로 찍힌(=기울어진) 사진에서 '멀리 있는 중앙'이 제자리로 돌아온다.

    보정을 안 하면 사진 좌표를 그대로 비율로 쓰게 되는데, 그러면 위치가 밀린다.
    """
    # 위쪽(먼 쪽)이 좁은 사다리꼴 = 위에서 비스듬히 내려다본 선반
    quad = [(300, 100), (700, 100), (900, 800), (100, 800)]
    dst = [(0, 0), (1000, 0), (1000, 1000), (0, 1000)]
    H = homography(quad, dst)

    # 사다리꼴 '위쪽 변의 한가운데' → 보정 후엔 선반 맨 위 정중앙(500, 0)
    u, v = apply_h(H, 500, 100)
    assert math.isclose(u, 500, abs_tol=1e-6) and math.isclose(v, 0, abs_tol=1e-6)

    # 사다리꼴 좌변 위 어떤 점이든 보정 후 x=0 (왼쪽 끝)
    u2, _ = apply_h(H, 200, 450)
    assert math.isclose(u2, 0, abs_tol=1.0), u2

    # 보정 없이 사진 폭으로 나눴다면 한참 엉뚱한 값이 나왔을 것
    naive = 200 / 1000 * 1000
    assert abs(naive - u2) > 100


def test_warp_box_keeps_a_box():
    quad = [(0, 0), (100, 0), (100, 100), (0, 100)]
    H = homography(quad, [(0, 0), (200, 0), (200, 200), (0, 200)])   # 2배 확대
    out = warp_box(H, box(50, 50, 10, 10))
    assert math.isclose(out["x1"], 90) and math.isclose(out["x2"], 110)
    assert math.isclose(out["area"], 400)      # 10x10 → 20x20


def test_degenerate_corners_rejected():
    """네 점이 일직선이면 변환을 만들 수 없다 — 조용히 이상한 값을 내면 안 된다."""
    line = [(0, 0), (10, 0), (20, 0), (30, 0)]
    try:
        homography(line, [(0, 0), (1, 0), (1, 1), (0, 1)])
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("일직선 모서리를 거부해야 한다")


def _run_multi(per_image_boxes, regions, quads=None):
    """detect_boxes 를 사진별로 다른 결과를 내도록 바꿔 scan-multi 를 돌린다."""
    n = len(per_image_boxes)
    calls = {"i": 0}

    def fake_detect(image, detector=None):
        b = per_image_boxes[calls["i"]]
        calls["i"] += 1
        return b, float(1200 * 900)

    if quads is None:
        quads = [[[0, 0], [1200, 0], [1200, 900], [0, 900]] for _ in range(n)]

    orig_detect = main.detect_boxes
    orig_plants, orig_feats = dict(main.PLANTS), dict(main.FEATS)
    main.detect_boxes = fake_detect
    main.PLANTS.clear(); main.FEATS.clear()
    try:
        return asyncio.run(main.scan_multi(
            files=[_Upload(_jpeg()) for _ in range(n)],
            corners=json.dumps(quads), regions=json.dumps(regions),
            replace=None, pot_refs=None, mode=None))
    finally:
        main.detect_boxes = orig_detect
        main.PLANTS.clear(); main.PLANTS.update(orig_plants)
        main.FEATS.clear(); main.FEATS.update(orig_feats)


def _plant(cx, cy):
    """화분 1개 + 잎 3장."""
    out = [box(cx, cy, 200, 200, "pot")]
    for dx, dy in [(-170, -80), (170, -80), (0, -190)]:
        out.append(box(cx + dx, cy + dy, 160, 160))
    return out


def test_two_photos_merge_into_one_shelf():
    """좌/우 반쪽씩 찍은 두 장 → 한 선반으로 합쳐 4개체."""
    left = _plant(300, 300) + _plant(300, 700)
    right = _plant(900, 300) + _plant(900, 700)
    res = _run_multi([left, right], regions=[[0, 0, 0.5, 1], [0.5, 0, 1, 1]])
    assert res["photos"] == 2
    assert res["count"] == 4, res["count"]

    # 왼쪽 사진 식물은 왼쪽 열(1~5), 오른쪽 사진 식물은 오른쪽 열(6~10)에 놓여야 한다
    cols = sorted(int(p["pos"][1:]) for p in res["plants"])
    assert sum(1 for c in cols if c <= 5) == 2, cols
    assert sum(1 for c in cols if c >= 6) == 2, cols


def test_overlap_duplicates_are_removed():
    """겹치는 구역에서 같은 식물이 두 사진에 다 찍혀도 하나로 센다."""
    # 두 사진 모두 '가운데 식물'을 담고 있고, 각자 자기 쪽 식물도 하나씩.
    # 선반 한가운데(u=500)는 1번 사진에선 x=1091, 2번 사진에선 x=109 에 찍힌다.
    #   1번: u = x/1200*550          → x = 500/550*1200 = 1091
    #   2번: u = 450 + x/1200*550    → x = (500-450)/550*1200 = 109
    shared_left = _plant(1091, 450)
    shared_right = _plant(109, 450)     # 위와 같은 실물
    left = _plant(300, 450) + shared_left
    right = shared_right + _plant(1000, 450)

    # 구역이 0.45~0.55 만큼 겹치게 잡으면 두 사진의 가운데 식물이 같은 자리로 온다
    res = _run_multi([left, right], regions=[[0, 0, 0.55, 1], [0.45, 0, 1, 1]])
    assert res["deduped"] > 0, "중복 제거가 하나도 안 일어났다"
    assert res["count"] == 3, f"가운데 식물이 두 번 세어졌다: {res['count']}"


def test_corner_count_must_match_photo_count():
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())],
                                    corners=json.dumps([[[0, 0], [1, 0], [1, 1], [0, 1]]] * 2),
                                    regions=None, replace=None, pot_refs=None, mode=None))
    except HTTPException as e:
        assert e.status_code == 400 and "모서리" in e.detail
    else:
        raise AssertionError("사진 수와 모서리 수가 다르면 거부해야 한다")


def test_bad_corner_json_rejected():
    try:
        asyncio.run(main.scan_multi(files=[_Upload(_jpeg())], corners="{망가진",
                                    regions=None, replace=None, pot_refs=None, mode=None))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("깨진 JSON 을 거부해야 한다")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
