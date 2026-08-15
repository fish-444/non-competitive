"""선반 배율 보정 스모크 테스트 (네트워크 불필요)

실행:  python3 test_calib.py

보정 전에는 'cm_per_unit = 60cm ÷ 사진 폭' 이라 **사진을 어떻게 찍느냐에 따라**
모든 cm 가 달라졌다. 여유 있게 찍으면 작게, 바짝 찍으면 크게. 선반 네 모서리를
한 번 찍어 두면 박스를 선반 cm 좌표로 옮겨서 그 흔들림이 사라진다.
"""

import asyncio
import io
import json
import os

os.environ["FARM_DB"] = ""

from PIL import Image                                # noqa: E402
from fastapi import HTTPException                    # noqa: E402

import main                                          # noqa: E402

# 사진 보관함은 끈다 (main.get_photo_dir() 이 부를 때마다 환경변수를 읽는다)
os.environ["PHOTO_DIR"] = ""


def _reset():
    main.PLANTS.clear(); main.POTS.clear(); main.CALIB.clear(); main.LEAVES.clear()


class _Upload:
    content_type = "image/jpeg"

    def __init__(self, raw):
        self._raw = raw

    async def read(self):
        return self._raw


def _jpeg(w=1200, h=900):
    b = io.BytesIO()
    Image.new("RGB", (w, h), (20, 60, 30)).save(b, format="JPEG")
    return b.getvalue()


def box(cx, cy, w, h, cls="mature leaf"):
    return {"cls": cls, "conf": 0.9, "x1": cx - w / 2, "y1": cy - h / 2,
            "x2": cx + w / 2, "y2": cy + h / 2, "area": float(w * h)}


def _scan_with(boxes, img_w, img_h, corners=None):
    """탐지기를 가짜로 바꿔 한 장 스캔을 돌리고, 등록된 식물을 돌려준다."""
    _reset()
    if corners:
        asyncio.run(main.set_calibration(corners=json.dumps(corners)))
    orig = main.detect_boxes
    main.detect_boxes = lambda image, det=None: (boxes, float(img_w * img_h))
    try:
        asyncio.run(main.scan_farm(file=_Upload(_jpeg(img_w, img_h)),
                                   replace=None, mode=None))
        return list(main.PLANTS.values())
    finally:
        main.detect_boxes = orig


# ── 보정을 안 걸었을 때는 예전 그대로 ────────────────────────────────────
def test_without_corners_nothing_changes():
    plants = _scan_with([box(600, 450, 200, 200, "canopy"), box(600, 450, 90, 90)],
                        1200, 900)
    assert len(plants) == 1, plants
    # 사진 폭 1200 이 60cm → 캐노피 200px 는 10cm
    assert abs(plants[0]["canopy_cm"] - 10.0) < 0.6, plants[0]["canopy_cm"]
    _reset()


def test_framing_wider_shrinks_everything_when_uncalibrated():
    """같은 포기를 여유 있게 찍으면 작게 측정된다 — 이게 고치려는 문제다."""
    tight = _scan_with([box(600, 450, 200, 200, "canopy"), box(600, 450, 90, 90)],
                       1200, 900)[0]["canopy_cm"]
    # 두 배 넓게 찍음: 같은 포기가 화면에서 절반 크기로 잡힌다
    wide = _scan_with([box(600, 450, 100, 100, "canopy"), box(600, 450, 45, 45)],
                      1200, 900)[0]["canopy_cm"]
    assert wide < tight * 0.6, (tight, wide)
    _reset()


# ── 모서리를 찍어 두면 흔들리지 않는다 ───────────────────────────────────
def test_the_same_pot_measures_the_same_however_it_is_framed():
    """핵심 — 촬영 범위가 달라도 같은 포기는 같은 cm 로 나와야 한다."""
    # ① 선반이 사진에 꽉 차게: 모서리가 사진 끝
    tight = _scan_with([box(600, 450, 200, 200, "canopy"), box(600, 450, 90, 90)],
                       1200, 900,
                       corners=[[0, 0], [1, 0], [1, 1], [0, 1]])[0]["canopy_cm"]
    # ② 여유 있게: 선반이 사진 가운데 절반만 차지 → 포기도 화면에서 절반
    wide = _scan_with([box(600, 450, 100, 100, "canopy"), box(600, 450, 45, 45)],
                      1200, 900,
                      corners=[[0.25, 0.25], [0.75, 0.25],
                               [0.75, 0.75], [0.25, 0.75]])[0]["canopy_cm"]
    assert abs(tight - wide) < 0.5, (tight, wide)
    _reset()


def test_a_calibrated_scan_measures_in_real_shelf_cm():
    """선반 폭의 1/6 을 차지하는 캐노피는 10cm 여야 한다(선반 60cm)."""
    p = _scan_with([box(600, 450, 200, 200, "canopy"), box(600, 450, 90, 90)],
                   1200, 900, corners=[[0, 0], [1, 0], [1, 1], [0, 1]])[0]
    assert abs(p["canopy_cm"] - 10.0) < 0.6, p["canopy_cm"]
    _reset()


def test_position_still_lands_in_the_right_half():
    """보정 뒤에도 사진 왼쪽 포기는 온실 왼쪽에 있어야 한다."""
    plants = _scan_with([box(300, 450, 120, 120, "canopy"), box(300, 450, 60, 60),
                         box(900, 450, 120, 120, "canopy"), box(900, 450, 60, 60)],
                        1200, 900, corners=[[0, 0], [1, 0], [1, 1], [0, 1]])
    xs = sorted(p["x"] for p in plants)
    assert xs[0] < 0 < xs[1], xs
    _reset()


# ── 지정·해제 ────────────────────────────────────────────────────────────
def test_corners_are_remembered_for_later_scans():
    _reset()
    asyncio.run(main.set_calibration(corners=json.dumps([[0, 0], [1, 0], [1, 1], [0, 1]])))
    assert main.get_calibration()["calibrated"] is True
    assert len(main.CALIB["corners"]) == 4
    _reset()


def test_clearing_goes_back_to_the_rough_guess():
    _reset()
    asyncio.run(main.set_calibration(corners=json.dumps([[0, 0], [1, 0], [1, 1], [0, 1]])))
    main.clear_calibration()
    assert main.get_calibration()["calibrated"] is False
    _reset()


def test_four_points_on_a_line_are_refused():
    """일직선이면 호모그래피를 못 만든다 — 저장하기 전에 막는다."""
    _reset()
    try:
        asyncio.run(main.set_calibration(
            corners=json.dumps([[0, 0], [0.3, 0], [0.6, 0], [0.9, 0]])))
    except HTTPException as e:
        assert e.status_code == 400 and "일직선" in e.detail, e.detail
    else:
        raise AssertionError("일직선은 거부해야 한다")
    _reset()


def test_wrong_number_of_points_is_refused():
    _reset()
    for bad in ([[0, 0], [1, 0], [1, 1]], [], [[0, 0]] * 5):
        try:
            asyncio.run(main.set_calibration(corners=json.dumps(bad)))
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError(f"거부해야 한다: {bad}")
    _reset()


def test_pixel_coordinates_are_refused():
    """비율(0~1)로 받아야 다음에 다른 해상도로 찍어도 쓸 수 있다."""
    _reset()
    try:
        asyncio.run(main.set_calibration(
            corners=json.dumps([[0, 0], [1200, 0], [1200, 900], [0, 900]])))
    except HTTPException as e:
        assert e.status_code == 400 and "비율" in e.detail, e.detail
    else:
        raise AssertionError("픽셀 좌표는 거부해야 한다")
    _reset()


def test_broken_json_is_refused():
    _reset()
    try:
        asyncio.run(main.set_calibration(corners="{망가진"))
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("깨진 JSON 은 거부해야 한다")
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
