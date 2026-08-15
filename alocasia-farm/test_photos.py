"""원본 사진 보관 스모크 테스트 (네트워크 불필요)

실행:  python3 test_photos.py

지금까지는 박스를 그린 520px 썸네일만 남기고 원본은 버렸다. 그래서 모델이
좋아져도 옛 사진을 다시 분석할 수 없었다.
"""

import io
import os
import tempfile

import pytest

os.environ["FARM_DB"] = ""
_TMP = tempfile.mkdtemp()
os.environ["PHOTO_DIR"] = _TMP

from PIL import Image, ImageDraw                     # noqa: E402
from fastapi import HTTPException                    # noqa: E402

import main                                          # noqa: E402


@pytest.fixture(autouse=True)
def _use_the_temp_photo_dir():
    """이 파일의 테스트가 도는 동안만 임시 보관함을 쓴다.

    conftest 가 매 테스트 앞에서 PHOTO_DIR 을 "" 로 되돌린다 — 보관을 실제로
    확인하는 이 파일은 여기서 다시 잡는다. main.get_photo_dir() 이 부를 때마다
    읽으므로 환경변수만 세우면 된다.
    """
    os.environ["PHOTO_DIR"] = _TMP
    yield


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
    old = os.environ.get("PHOTO_DIR")
    os.environ["PHOTO_DIR"] = ""
    try:
        assert main.archive_photo(_jpeg(), "scan") == ""
    finally:
        if old is None:
            os.environ.pop("PHOTO_DIR", None)
        else:
            os.environ["PHOTO_DIR"] = old


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


# ── 개체 사진은 화분마다 / 전체 사진은 한 번만 ───────────────────────────
def test_a_pots_own_photos_pile_up_in_its_album():
    p = {"id": "a1"}
    main._add_plant_photo(p, "2026-08/plant_1.jpg")
    main._add_plant_photo(p, "2026-08/plant_2.jpg")
    assert [r["rel"] for r in p["photo_log"]] == ["2026-08/plant_1.jpg", "2026-08/plant_2.jpg"]
    assert p["photo"] == "2026-08/plant_2.jpg", "최신이 대표 사진"


def test_a_full_scan_is_stored_once_not_per_pot():
    """전체 탑뷰 한 장이 화분 9개를 담았다고 사진이 9번 쌓이면 안 된다."""
    main.SCANS.clear()
    main._add_scan_photo("2026-08/scan_1.jpg", "sc_x", 9)
    assert len(main.SCANS) == 1, main.SCANS
    assert main.SCANS[0]["plants"] == 9 and main.SCANS[0]["kind"] == "scan"
    main.SCANS.clear()


def test_a_full_scan_never_lands_in_a_pots_album():
    """개체 사진이 전체 사진에 덮여 사라지면 안 된다 — 다른 통에 담는다."""
    main.PLANTS.clear(); main.SCANS.clear()
    p = {"id": "a2"}
    main._add_plant_photo(p, "2026-08/plant_1.jpg")
    main._add_scan_photo("2026-08/scan_1.jpg", "sc_y", 3)
    assert [r["rel"] for r in p["photo_log"]] == ["2026-08/plant_1.jpg"]
    assert p["photo"] == "2026-08/plant_1.jpg", "전체 스캔이 개체 대표 사진을 덮으면 안 된다"
    main.SCANS.clear()


def test_albums_do_not_grow_without_bound():
    p = {"id": "a3"}
    for i in range(main.PHOTO_KEEP + 20):
        main._add_plant_photo(p, f"2026-08/plant_{i}.jpg")
    assert len(p["photo_log"]) == main.PHOTO_KEEP


def test_the_scan_list_does_not_grow_without_bound():
    main.SCANS.clear()
    for i in range(main.SCAN_KEEP + 15):
        main._add_scan_photo(f"2026-08/scan_{i}.jpg", f"sc_{i}", 1)
    assert len(main.SCANS) == main.SCAN_KEEP
    main.SCANS.clear()


def test_nothing_is_recorded_when_archiving_is_off():
    p = {"id": "a4"}
    main._add_plant_photo(p, "")
    main.SCANS.clear()
    main._add_scan_photo("", "sc_z", 2)
    assert "photo_log" not in p and main.SCANS == []


def test_the_lists_come_back_newest_first():
    main.SCANS.clear()
    main._add_scan_photo("2026-08/scan_a.jpg", "sc_a", 1)
    main._add_scan_photo("2026-08/scan_b.jpg", "sc_b", 2)
    assert main.list_scans()["rows"][0]["id"] == "sc_b"

    main.PLANTS["a5"] = {"id": "a5"}
    main._add_plant_photo(main.PLANTS["a5"], "2026-08/plant_a.jpg")
    main._add_plant_photo(main.PLANTS["a5"], "2026-08/plant_b.jpg")
    assert main.list_plant_photos("a5")["rows"][0]["rel"] == "2026-08/plant_b.jpg"
    main.PLANTS.clear(); main.SCANS.clear()


def test_photos_of_an_unknown_plant_is_404():
    main.PLANTS.clear()
    try:
        main.list_plant_photos("없는것")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 식물은 404 여야 한다")


# ── 보관본으로 다시 분석 ─────────────────────────────────────────────────
def test_rescan_uses_the_archived_original():
    """모델이 좋아졌을 때 다시 찍지 않고 옛 사진에 적용할 수 있어야 한다."""
    rel = main.archive_photo(_jpeg(), "plant")
    main.PLANTS["p1"] = {"id": "p1", "name": "t", "pos": "A1", "x": 0, "z": 0,
                         "rot": 0, "manual": True}
    main._add_plant_photo(main.PLANTS["p1"], rel)
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
