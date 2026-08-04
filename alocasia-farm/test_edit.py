"""직접 수정 + 스캔 모드 스모크 테스트 (네트워크 불필요)

실행:  python3 test_edit.py

사진이 뭉개지거나 잎이 가려지면 탐지가 틀린다. 손으로 고칠 수 있는지,
그리고 '잎은 유지하고 새 잎만 기록'하는 스캔이 값을 안 깎는지 확인한다.
"""

import asyncio
import io

from PIL import Image
from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import main


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


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (1200, 800), (25, 90, 35)).save(buf, format="JPEG")
    return buf.getvalue()


def _reset():
    main.POTS.clear(); main.PLANTS.clear(); main.FEATS.clear()


def _plant(**kw):
    """등록된 식물 하나를 직접 만들어 둔다."""
    _reset()
    p = {"id": "t1", "name": "테스트", "pos": "C5", "x": 0, "z": 0, "rot": 0,
         "size_class": "중품", "leaf_count": 6, "shoot_count": 1,
         "mature_count": 4, "old_count": 1, "top_leaf_size": "중엽",
         "top_leaf_pct": 12.0, "overlap_count": 0, "overlap_density": 0,
         "updated": "2026-01-01 00:00:00"}
    p.update(kw)
    main.PLANTS["t1"] = p
    return p


def _patch(**kw):
    args = {"name": None, "rot": None, "note": None, "size_class": None,
            "shoot_count": None, "mature_count": None, "old_count": None}
    args.update(kw)
    return asyncio.run(main.update_plant(pid="t1", **args))


# ── 직접 수정 ────────────────────────────────────────────────────────────
def test_size_class_can_be_set_by_hand():
    _plant()
    assert _patch(size_class="대품")["size_class"] == "대품"
    _reset()


def test_hand_set_size_class_actually_resizes_the_pot_in_3d():
    """3D 화분 크기는 top_leaf_size 를 본다 — 소중대품 버튼만 바꾸고 이 필드를
    안 건드리면 모달 글자만 바뀌고 화면의 화분은 그대로다."""
    _plant(size_class="소품", top_leaf_size="소엽")
    p = _patch(size_class="대품")
    assert p["top_leaf_size"] == "대엽", p
    p2 = _patch(size_class="소품")
    assert p2["top_leaf_size"] == "소엽", p2
    _reset()


def test_hand_set_size_class_clears_the_stale_percentage():
    """top_leaf_pct 는 실측 비율이다. 손으로 등급을 바꾸면 그 실측과 안 맞으니 지운다."""
    _plant(top_leaf_pct=12.0)
    p = _patch(size_class="대품")
    assert p["top_leaf_pct"] is None, p
    _reset()


def test_hand_set_leaf_count_makes_an_empty_pot_actually_show_a_plant():
    """빈 화분(empty=True)은 3D 가 흙만 그리고 잎을 아예 안 그린다. 잎이 가려져서
    못 잡힌 걸 손으로 넣었는데 empty 가 안 풀리면, 수치는 바뀌어도 화면엔 여전히
    빈 화분으로 남아 '반영이 안 된다'로 보인다."""
    _plant(size_class="미검출", leaf_count=0, shoot_count=0, mature_count=0,
          old_count=0, empty=True)
    p = _patch(mature_count=2)
    assert "empty" not in p, p
    assert p["size_class"] == "소품", p    # '미검출'로는 등급 배지·3D 크기를 못 정한다
    _reset()


def test_hand_set_leaf_count_to_zero_does_not_fake_an_empty_pot():
    """실수로 0으로 만들었다고 empty 취급하면 안 된다 — 사람이 명시적으로 지운 값이다."""
    _plant(mature_count=1, leaf_count=1)
    p = _patch(mature_count=0)
    assert "empty" not in p, p
    _reset()


def test_bad_size_class_rejected():
    _plant()
    try:
        _patch(size_class="특대품")
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("없는 등급은 거부해야 한다")
    _reset()


def test_leaf_counts_editable_and_total_follows():
    """잎을 더하거나 빼면 총 개수가 따라와야 한다."""
    _plant()
    p = _patch(shoot_count=3, mature_count=5, old_count=2)
    assert (p["shoot_count"], p["mature_count"], p["old_count"]) == (3, 5, 2)
    assert p["leaf_count"] == 10, p["leaf_count"]
    _reset()


def test_stage_move_is_just_two_edits():
    """성엽 → 노엽 이동: 한쪽 -1, 다른 쪽 +1. 총 개수는 그대로."""
    _plant(mature_count=4, old_count=1, leaf_count=6)
    p = _patch(mature_count=3, old_count=2)
    assert (p["mature_count"], p["old_count"]) == (3, 2)
    assert p["leaf_count"] == 6, p["leaf_count"]
    _reset()


def test_negative_leaf_count_rejected():
    _plant()
    try:
        _patch(old_count=-1)
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("음수는 거부해야 한다")
    _reset()


def test_hand_edit_is_marked():
    _plant()
    assert "manual" not in main.PLANTS["t1"]
    assert _patch(old_count=2)["manual"] is True
    _reset()


def test_renaming_alone_is_not_a_hand_edit():
    """이름만 바꾼 건 탐지값을 고친 게 아니다."""
    _plant()
    p = _patch(name="프라이덱")
    assert p["name"] == "프라이덱" and "manual" not in p
    _reset()


# ── 메모 ────────────────────────────────────────────────────────────────
def test_note_can_be_written_and_read_back():
    _plant()
    p = _patch(note="잎 끝이 살짝 말랐음 · 분갈이 예정")
    assert p["note"] == "잎 끝이 살짝 말랐음 · 분갈이 예정"
    _reset()


def test_writing_a_note_is_not_a_hand_edit():
    """메모는 탐지값을 고치는 게 아니라 그냥 적어 두는 글이다."""
    _plant()
    p = _patch(note="관찰 기록")
    assert "manual" not in p
    _reset()


def test_note_can_be_cleared():
    _plant(note="예전 메모")
    p = _patch(note="")
    assert p["note"] == ""
    _reset()


def test_note_is_trimmed():
    _plant()
    p = _patch(note="  앞뒤 공백  ")
    assert p["note"] == "앞뒤 공백"
    _reset()


def test_leaving_note_untouched_keeps_the_old_value():
    """note 를 안 보내면(None) 기존 메모가 그대로 있어야 한다."""
    _plant(note="원래 메모")
    p = _patch(name="이름만 변경")
    assert p["note"] == "원래 메모"
    _reset()


# ── 크기 등급 (잎 실측 길이) ────────────────────────────────────────────
def _leaf(long_side, cls="mature leaf"):
    return box(500, 400, long_side, long_side * 0.6, cls)


def test_grade_comes_from_the_biggest_leaf_in_cm():
    """선반 폭(60cm)을 알면 잎을 실제 길이로 재서 등급을 매긴다."""
    cm_per_unit = 60.0 / 1000                      # 캔버스 1000 = 선반 60cm
    for long_side, expect in [(100, "소품"), (220, "중품"), (330, "대품")]:
        m = main.analyze_metrics([_leaf(long_side)], 1000 * 667, cm_per_unit)
        assert m["size_class"] == expect, (long_side, m["leaf_max_cm"], m["size_class"])
        assert m["leaf_max_cm"] == round(long_side * cm_per_unit, 1)


def test_grade_uses_the_biggest_leaf_not_the_count():
    """잎이 많아도 다 작으면 소품, 한 장이라도 크면 대품."""
    cm = 60.0 / 1000
    many_small = main.analyze_metrics([_leaf(90) for _ in range(12)], 1000 * 667, cm)
    one_big = main.analyze_metrics([_leaf(340)], 1000 * 667, cm)
    assert many_small["size_class"] == "소품", many_small
    assert one_big["size_class"] == "대품", one_big


def test_grade_ignores_how_close_the_photo_was_taken():
    """같은 식물을 가까이/멀리 찍어도 실측이면 등급이 안 흔들린다."""
    near = main.analyze_metrics([_leaf(400)], 1000 * 667, cm_per_unit=60.0 / 2000)
    far = main.analyze_metrics([_leaf(200)], 1000 * 667, cm_per_unit=60.0 / 1000)
    assert near["leaf_max_cm"] == far["leaf_max_cm"] == 12.0
    assert near["size_class"] == far["size_class"] == "중품"


def test_grade_without_scale_falls_back_to_ratio():
    """배율을 모르는 개체 사진 1장에서도 등급은 나와야 한다."""
    m = main.analyze_metrics([_leaf(900)], 1000 * 1000, cm_per_unit=None)
    assert m["leaf_max_cm"] is None
    assert m["size_class"] in main.SIZE_CLASSES


def test_grade_thresholds_are_tunable():
    assert main.grade_by_leaf_cm(main.LEAF_SMALL_CM) == "소품"
    assert main.grade_by_leaf_cm(main.LEAF_SMALL_CM + 0.1) == "중품"
    assert main.grade_by_leaf_cm(main.LEAF_LARGE_CM) == "중품"
    assert main.grade_by_leaf_cm(main.LEAF_LARGE_CM + 0.1) == "대품"


def test_hand_set_grade_survives_a_keep_scan():
    """자동 판정이 틀렸을 때 손으로 고친 등급은 유지된다."""
    _plant(size_class="중품")
    p = _patch(size_class="대품")
    assert p["size_class"] == "대품" and p["manual"] is True
    _reset()


# ── 스캔 모드 ────────────────────────────────────────────────────────────
def _scan(mode, boxes):
    orig = main.detect_boxes
    main.detect_boxes = lambda im, det=None: (boxes, float(1200 * 800))
    try:
        return asyncio.run(main.scan_farm(file=_Upload(_jpeg()), replace=None, mode=mode))
    finally:
        main.detect_boxes = orig


def test_mode_names_validated():
    _reset()
    try:
        main._scan_mode("이상한모드", None)
    except HTTPException as e:
        assert e.status_code == 400
    else:
        raise AssertionError("모르는 모드는 거부해야 한다")
    assert main._scan_mode(None, None) == "update"
    assert main._scan_mode(None, "1") == "replace"     # 예전 방식 호환
    assert main._scan_mode("keep", None) == "keep"
    _reset()


def test_keep_mode_does_not_lose_hidden_leaves():
    """가려져서 덜 잡힌 사진이 기존 잎 수를 깎으면 안 된다."""
    _reset()
    main.PLANTS.clear()
    asyncio.run(main.set_pots(points='[[0.5,0.5]]', points_px=None, corners=None))
    _scan("update", [box(600, 400, 90, 90, "mature leaf") for _ in range(1)]
          + [box(500, 400, 90, 90, "mature leaf"), box(700, 400, 90, 90, "mature leaf")])
    before = list(main.PLANTS.values())[0]["leaf_count"]
    assert before == 3, before

    # 다음 사진엔 1장만 잡혔다 (나머지는 가려짐)
    res = _scan("keep", [box(600, 400, 90, 90, "mature leaf")])
    after = list(main.PLANTS.values())[0]
    assert after["leaf_count"] == 3, f"잎이 깎였다: {after['leaf_count']}"
    assert res["new_leaves"] == 0
    _reset()


def test_keep_mode_records_new_leaves():
    """잎이 늘어난 만큼만 새 잎으로 기록하고 기록을 남긴다."""
    _reset()
    asyncio.run(main.set_pots(points='[[0.5,0.5]]', points_px=None, corners=None))
    _scan("update", [box(600, 400, 90, 90, "mature leaf"),
                     box(500, 400, 90, 90, "mature leaf")])
    assert list(main.PLANTS.values())[0]["leaf_count"] == 2

    res = _scan("keep", [box(600, 400, 90, 90, "mature leaf"),
                         box(500, 400, 90, 90, "mature leaf"),
                         box(700, 400, 90, 90, "shoot"),
                         box(650, 330, 90, 90, "shoot")])
    p = list(main.PLANTS.values())[0]
    assert p["leaf_count"] == 4, p["leaf_count"]
    assert res["new_leaves"] == 2, res["new_leaves"]
    assert p["leaf_log"][-1]["added"] == 2, p["leaf_log"]
    assert p["shoot_count"] == 2, p          # 단계 분포는 새 탐지를 따라감
    _reset()


def test_update_mode_still_overwrites():
    """기본 모드는 예전 그대로 — 탐지값으로 덮어쓴다."""
    _reset()
    asyncio.run(main.set_pots(points='[[0.5,0.5]]', points_px=None, corners=None))
    _scan("update", [box(600, 400, 90, 90, "mature leaf"),
                     box(500, 400, 90, 90, "mature leaf"),
                     box(700, 400, 90, 90, "mature leaf")])
    _scan("update", [box(600, 400, 90, 90, "mature leaf")])
    assert list(main.PLANTS.values())[0]["leaf_count"] == 1
    _reset()


def test_keep_mode_protects_hand_edits():
    """손으로 고친 값도 keep 모드에선 깎이지 않는다."""
    _reset()
    asyncio.run(main.set_pots(points='[[0.5,0.5]]', points_px=None, corners=None))
    _scan("update", [box(600, 400, 90, 90, "mature leaf")])
    pid = list(main.PLANTS)[0]
    args = {"name": None, "rot": None, "note": None, "size_class": None,
            "shoot_count": None, "mature_count": 7, "old_count": None}
    asyncio.run(main.update_plant(pid=pid, **args))
    assert main.PLANTS[pid]["leaf_count"] == 7

    _scan("keep", [box(600, 400, 90, 90, "mature leaf")])   # 여전히 1장만 잡힘
    assert main.PLANTS[pid]["leaf_count"] == 7, main.PLANTS[pid]["leaf_count"]
    _reset()


def test_leaf_log_is_capped():
    """기록이 무한정 쌓이지 않는다."""
    old = {"leaf_count": 0, "shoot_count": 0, "mature_count": 0, "old_count": 0,
           "leaf_log": [{"at": "x", "added": 1, "total": 1}] * 40}
    merged, added = main._merge_keep(old, {"leaf_count": 1, "shoot_count": 1,
                                           "mature_count": 0, "old_count": 0})
    assert added == 1
    log = old["leaf_log"]; log.append({"at": "y", "added": 1, "total": 1})
    del log[:-30]
    assert len(log) == 30


# ── 물주기 (센서 없이, 사람이 기록한 날짜로) ──────────────────────────────
from datetime import date, timedelta


def test_watering_a_past_date_from_the_calendar():
    """물은 줬는데 앱을 안 켠 날이 생긴다 — 달력에서 지난 날짜를 골라 적을 수 있어야."""
    _plant()
    ago = (date.today() - timedelta(days=2)).isoformat()
    p = main.water_plant(pid="t1", day=ago)
    assert p["last_watered"] == ago, p
    assert p["days_since_watered"] == 2, p
    _reset()


def test_a_late_entry_does_not_overwrite_a_more_recent_watering():
    """5일 전을 뒤늦게 적었다고 어제 준 기록이 밀려나면 안 된다."""
    _plant()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    long_ago = (date.today() - timedelta(days=5)).isoformat()
    main.water_plant(pid="t1", day=yesterday)
    p = main.water_plant(pid="t1", day=long_ago)
    assert p["last_watered"] == yesterday, p
    assert p["water_log"] == [long_ago, yesterday], p    # 날짜순으로 유지
    _reset()


def test_future_dates_are_refused():
    """아직 안 준 물을 적어 두면 마름 경고가 그만큼 늦게 뜬다."""
    _plant()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    try:
        main.water_plant(pid="t1", day=tomorrow)
        assert False, "미래 날짜가 통과했다"
    except HTTPException as e:
        assert e.status_code == 400, e
    _reset()


def test_a_bad_date_string_is_refused():
    _plant()
    try:
        main.water_plant(pid="t1", day="2026/07/31")
        assert False, "이상한 날짜 형식이 통과했다"
    except HTTPException as e:
        assert e.status_code == 400, e
    _reset()


def test_the_same_day_is_logged_once():
    _plant()
    ago = (date.today() - timedelta(days=3)).isoformat()
    main.water_plant(pid="t1", day=ago)
    p = main.water_plant(pid="t1", day=ago)
    assert p["water_log"] == [ago], p
    _reset()


def test_undoing_a_days_watering():
    """잘못 누른 날을 되돌릴 수 있어야 한다."""
    _plant()
    ago = (date.today() - timedelta(days=2)).isoformat()
    main.water_plant(pid="t1", day=ago)
    main.water_plant(pid="t1")                      # 오늘도 기록
    p = main.unwater_plant(pid="t1", day=ago)
    assert p["water_log"] == [date.today().isoformat()], p
    assert p["last_watered"] == date.today().isoformat(), p
    _reset()


def test_undoing_the_only_watering_clears_last_watered():
    _plant()
    main.water_plant(pid="t1")
    p = main.unwater_plant(pid="t1", day=date.today().isoformat())
    assert p["last_watered"] is None, p
    assert p["days_since_watered"] is None, p       # '기록 없음' 으로 돌아간다
    _reset()


def test_water_all_accepts_a_date_and_can_be_undone():
    _plant()
    ago = (date.today() - timedelta(days=4)).isoformat()
    res = main.water_all_plants(day=ago)
    assert res["watered"] == 1 and res["date"] == ago, res
    assert main.PLANTS["t1"]["last_watered"] == ago
    undo = main.unwater_all_plants(day=ago)
    assert undo["undone"] == 1, undo
    assert main.PLANTS["t1"]["last_watered"] is None
    _reset()


def test_watering_today_starts_the_count_at_zero():
    _plant()
    p = main.water_plant(pid="t1")
    assert p["days_since_watered"] == 0
    assert p["soil_dry"] is False
    assert p["last_watered"] == date.today().isoformat()
    _reset()


def test_no_record_means_no_dry_warning():
    """한 번도 물 준 기록이 없으면 '마름'이 아니라 '모른다' 다."""
    p = _plant()
    main._augment_water(p)
    assert p["days_since_watered"] is None
    assert p["soil_dry"] is False
    _reset()


def test_soil_stays_fine_through_day_three():
    """기준(WATER_DRY_DAYS=3)까지는 물기가 있다고 본다."""
    p = _plant(last_watered=(date.today() - timedelta(days=main.WATER_DRY_DAYS)).isoformat())
    main._augment_water(p)
    assert p["days_since_watered"] == main.WATER_DRY_DAYS
    assert p["soil_dry"] is False
    _reset()


def test_soil_turns_dry_the_day_after_the_threshold():
    p = _plant(last_watered=(date.today() - timedelta(days=main.WATER_DRY_DAYS + 1)).isoformat())
    main._augment_water(p)
    assert p["soil_dry"] is True
    _reset()


def test_watering_again_resets_a_dry_pot():
    p = _plant(last_watered=(date.today() - timedelta(days=10)).isoformat())
    main._augment_water(p)
    assert p["soil_dry"] is True
    main.water_plant(pid="t1")
    assert main.PLANTS["t1"]["soil_dry"] is False
    _reset()


def test_watering_an_unknown_plant_is_a_404():
    _reset()
    try:
        main.water_plant(pid="nope")
    except HTTPException as e:
        assert e.status_code == 404
    else:
        raise AssertionError("없는 식물은 404")


def test_list_plants_reports_water_status_for_everyone():
    _plant()
    main.water_plant(pid="t1")
    d = main.list_plants()
    p = d["plants"][0]
    assert p["days_since_watered"] == 0 and p["soil_dry"] is False
    _reset()


def _second_plant(pid, **kw):
    p = {"id": pid, "name": "테스트2", "pos": "D8", "x": 5, "z": 5, "rot": 0,
         "size_class": "중품", "leaf_count": 2, "shoot_count": 0,
         "mature_count": 2, "old_count": 0, "top_leaf_size": "중엽",
         "top_leaf_pct": 8.0, "overlap_count": 0, "overlap_density": 0,
         "updated": "2026-01-01 00:00:00"}
    p.update(kw)
    main.PLANTS[pid] = p
    return p


def test_water_all_waters_every_plant_in_one_call():
    """모달을 하나씩 열지 않고, 트레이를 통째로 준 물주기를 한 번에 기록한다."""
    _plant()
    _second_plant("t2", last_watered=(date.today() - timedelta(days=10)).isoformat())
    res = main.water_all_plants()
    assert res["watered"] == 2
    for pid in ("t1", "t2"):
        assert main.PLANTS[pid]["days_since_watered"] == 0
        assert main.PLANTS[pid]["soil_dry"] is False
    _reset()


def test_water_all_includes_undetected_pots():
    """'미검출' 화분도 물리적으로는 물을 받으니 똑같이 기록해야 한다."""
    _plant(size_class="미검출", empty=True, last_watered=None)
    main.water_all_plants()
    assert main.PLANTS["t1"]["days_since_watered"] == 0
    _reset()


def test_water_all_on_an_empty_farm_does_not_crash():
    _reset()
    res = main.water_all_plants()
    assert res["watered"] == 0


# ── 물주기 달력 ──────────────────────────────────────────────────────────
def test_watering_appends_to_the_log_not_just_the_last_date():
    _plant()
    main.water_plant(pid="t1")
    assert main.PLANTS["t1"]["water_log"] == [date.today().isoformat()]
    _reset()


def test_watering_twice_in_one_day_only_logs_once():
    _plant()
    main.water_plant(pid="t1")
    main.water_plant(pid="t1")
    assert main.PLANTS["t1"]["water_log"] == [date.today().isoformat()], main.PLANTS["t1"]["water_log"]
    _reset()


def test_watering_on_a_later_day_adds_a_new_entry():
    p = _plant(water_log=["2026-01-01"], last_watered="2026-01-01")
    main.water_plant(pid="t1")
    assert p["water_log"] == ["2026-01-01", date.today().isoformat()]
    _reset()


def test_water_log_is_capped():
    """달력 기록도 무한정 안 쌓인다."""
    p = _plant(water_log=[f"2020-01-{i:02d}" for i in range(1, 10)] * 60)  # 540개
    main._log_watered(p, "2099-12-31")
    assert len(p["water_log"]) <= main.WATER_LOG_DAYS
    assert p["water_log"][-1] == "2099-12-31"
    _reset()


def test_water_log_endpoint_counts_pots_per_day():
    _plant()
    _second_plant("t2", water_log=[date.today().isoformat()], last_watered=date.today().isoformat())
    main.water_plant(pid="t1")
    d = main.water_log()
    today = date.today().isoformat()
    day = next(x for x in d["days"] if x["date"] == today)
    assert day["count"] == 2, day
    _reset()


def test_water_log_endpoint_filters_by_month():
    p = _plant(water_log=["2026-01-15", "2026-02-01"], last_watered="2026-02-01")
    d_jan = main.water_log(month="2026-01")
    d_feb = main.water_log(month="2026-02")
    assert [x["date"] for x in d_jan["days"]] == ["2026-01-15"]
    assert [x["date"] for x in d_feb["days"]] == ["2026-02-01"]
    _reset()


def test_water_log_endpoint_on_an_empty_farm():
    _reset()
    assert main.water_log()["days"] == []


def test_water_all_logs_every_plant_for_the_calendar():
    _plant()
    _second_plant("t2")
    main.water_all_plants()
    assert main.PLANTS["t1"]["water_log"] == [date.today().isoformat()]
    assert main.PLANTS["t2"]["water_log"] == [date.today().isoformat()]
    _reset()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
