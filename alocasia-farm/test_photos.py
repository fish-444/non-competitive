"""원본 사진 보관 스모크 테스트 (네트워크 불필요)

실행:  python3 test_photos.py

지금까지는 박스를 그린 520px 썸네일만 남기고 원본은 버렸다. 그래서 모델이
좋아져도 옛 사진을 다시 분석할 수 없었다.
"""

import io
import os
import tempfile

os.environ["FARM_DB"] = ""
_TMP = tempfile.mkdtemp()
os.environ["PHOTO_DIR"] = _TMP

from PIL import Image, ImageDraw                     # noqa: E402
from fastapi import HTTPException                    # noqa: E402

import main                                          # noqa: E402

main.PHOTO_DIR = _TMP


def _jpeg(w=800, h=600):
    im = Image.new("RGB", (w, h), (35, 28, 22))
    d = ImageDraw.Draw(im)
    d.ellipse([w // 3, h // 3, w * 2 // 3, h * 2 // 3], fill=(40, 120, 55))
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=88)
    return b.getvalue()


def test_the_original_is_written_to_disk():
    raw = _jpeg()
    rel = main.archive_photo(raw, "scan")
    assert rel and rel.endswith(".jpg"), rel
    assert main.read_photo(rel) == raw, "저장한 바이트 그대로 읽혀야 한다"


def test_photos_are_split_by_month():
    """한 폴더에 수천 장이 쌓이면 열기도 백업하기도 나빠진다."""
    import time
    rel = main.archive_photo(_jpeg(), "scan")
    assert rel.startswith(time.strftime("%Y-%m") + "/"), rel


def test_two_photos_never_collide():
    a = main.archive_photo(_jpeg(), "scan")
    b = main.archive_photo(_jpeg(), "scan")
    assert a != b, (a, b)


def test_turning_the_archive_off_keeps_working():
    """PHOTO_DIR 를 비우면 안 남기되, 분석은 그대로 돌아야 한다."""
    old = main.PHOTO_DIR
    main.PHOTO_DIR = ""
    try:
        assert main.archive_photo(_jpeg(), "scan") == ""
    finally:
        main.PHOTO_DIR = old


def test_an_empty_upload_is_not_archived():
    assert main.archive_photo(b"", "scan") == ""


# ── 경로를 벗어나는 요청 막기 ────────────────────────────────────────────
def test_a_path_climbing_out_is_refused():
    """../ 로 빠져나가 farm_env.bat 같은 걸 읽어 가면 안 된다."""
    for bad in ("../farm_env.bat", "../../etc/passwd", "..%2F..%2Fmain.py",
                "/etc/passwd", "2026-01/../../main.py"):
        try:
            main.read_photo(bad)
        except HTTPException as e:
            assert e.status_code == 404, (bad, e.status_code)
        else:
            raise AssertionError(f"막았어야 한다: {bad}")


def test_a_missing_photo_is_404():
    try:
        main.read_photo("2026-01/없는사진.jpg")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 사진은 404 여야 한다")


def test_an_empty_reference_is_404():
    for bad in ("", None):
        try:
            main.read_photo(bad)
        except HTTPException as e:
            assert e.status_code == 404
        else:
            raise AssertionError("빈 경로는 404 여야 한다")


# ── 보관본으로 다시 분석 ─────────────────────────────────────────────────
def test_rescan_uses_the_archived_original():
    """모델이 좋아졌을 때 다시 찍지 않고 옛 사진에 적용할 수 있어야 한다."""
    rel = main.archive_photo(_jpeg(), "plant")
    main.PLANTS["p1"] = {"id": "p1", "name": "t", "pos": "A1", "x": 0, "z": 0,
                         "rot": 0, "photo": rel, "manual": True}
    out = main.rescan_from_archive("p1")
    assert out["photo"] == rel, "사진은 그대로, 판정만 새로"
    assert "leaf_count" in out, out
    assert "manual" not in out, "새 탐지값으로 덮었으면 손수정 표시는 지운다"
    assert out["growth_log"][-1]["src"] == "rescan", out["growth_log"]
    main.PLANTS.clear()


def test_rescan_without_an_archived_photo_explains_itself():
    main.PLANTS["p2"] = {"id": "p2", "name": "t", "pos": "A2", "x": 0, "z": 0, "rot": 0}
    try:
        main.rescan_from_archive("p2")
    except HTTPException as e:
        assert e.status_code == 400 and "원본" in e.detail, e.detail
    else:
        raise AssertionError("보관본이 없으면 400 이어야 한다")
    main.PLANTS.clear()


def test_rescan_of_an_unknown_plant_is_404():
    main.PLANTS.clear()
    try:
        main.rescan_from_archive("없는것")
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
