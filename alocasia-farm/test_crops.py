"""작물 스모크 테스트 (네트워크 불필요)

실행:  python3 test_crops.py

'무엇을 심었는가'가 물주기 간격·크기 등급·필요 광량을 어떻게 가르는지 본다.
가장 중요한 건 **기존 화분이 안 흔들리는 것**이다 — crop 이 없는 옛 기록은
전부 알로카시아로 읽혀서 예전과 똑같은 값이 나와야 한다.
"""

import asyncio
import io
from datetime import date

from PIL import Image
from fastapi import HTTPException

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import crops                                     # noqa: E402
import main                                      # noqa: E402
import placement                                 # noqa: E402
import watering                                  # noqa: E402


class _Upload:
    content_type = "image/jpeg"

    def __init__(self, raw):
        self._raw = raw

    async def read(self):
        return self._raw


def _photo():
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (40, 90, 50)).save(buf, format="JPEG")
    return _Upload(buf.getvalue())


def _reset():
    main.PLANTS.clear(); main.POTS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear(); main.ENVIRONMENT.clear()


def _add(name="테스트", crop=None, pos="A1"):
    return asyncio.run(main.add_plant(name=name, file=_photo(), pos=pos, crop=crop))


def _patch(pid, **kw):
    """update_plant 를 파이썬에서 직접 부른다 — Form 기본값이 안 통하므로 전부 넘긴다."""
    args = {"name": None, "rot": None, "note": None, "size_class": None,
            "shoot_count": None, "mature_count": None, "old_count": None,
            "soil": None, "crop": None}
    args.update(kw)
    return asyncio.run(main.update_plant(pid=pid, **args))


# ── 작물표 읽기 ───────────────────────────────────────────────────────────
def test_a_pot_without_a_crop_is_the_default_one():
    """옛 farm.db 에는 crop 이 아예 없다 — 알로카시아로 읽혀야 한다."""
    assert crops.key_of({}) == crops.DEFAULT
    assert crops.key_of({"crop": None}) == crops.DEFAULT
    assert crops.of({})["name"] == "알로카시아"


def test_an_unknown_crop_is_read_as_the_default_one():
    """백업을 손으로 고쳐 이상한 값이 섞여도 조회가 터지면 안 된다."""
    assert crops.key_of({"crop": "용과"}) == crops.DEFAULT
    assert crops.get("용과")["key"] == crops.DEFAULT
    assert crops.get(None)["key"] == crops.DEFAULT
    assert crops.get(12)["key"] == crops.DEFAULT


def test_every_crop_has_the_four_numbers_the_app_reads():
    for key, c in crops.CROPS.items():
        assert c["key"] == key, key
        assert len(c["canopy_cm"]) == 2 and c["canopy_cm"][0] < c["canopy_cm"][1], key
        assert len(c["leaf_cm"]) == 2 and c["leaf_cm"][0] < c["leaf_cm"][1], key
        assert c["light"] > 0 and c["height_ratio"] > 0, key
        assert c["radius_from"] in ("leaf", "canopy"), key


def test_the_listing_carries_what_the_picker_needs():
    rows = crops.listing()
    assert [r["key"] for r in rows] == list(crops.KEYS)
    assert all(r["name"] and r["kind"] and r["note"] for r in rows)
    # 기본 작물은 물주기를 작물표에 안 적는다(PROFILE 이 이미 그 값이다)
    default = next(r for r in rows if r["key"] == crops.DEFAULT)
    assert default["interval_days"] is None


# ── 등급 ─────────────────────────────────────────────────────────────────
def test_the_same_canopy_is_graded_differently_per_crop():
    """캐노피 21cm — 알로카시아면 아직 중품, 상추면 다 큰 대품."""
    assert crops.canopy_grade(21.0) == "중품"
    assert crops.canopy_grade(21.0, "lettuce") == "대품"


def test_the_default_grading_is_unchanged():
    """작물을 안 주면 예전 기준치(환경변수 포함) 그대로."""
    assert main.grade_by_canopy_cm(main.CANOPY_SMALL_CM) == "소품"
    assert main.grade_by_canopy_cm(main.CANOPY_SMALL_CM + 0.1) == "중품"
    assert main.grade_by_canopy_cm(main.CANOPY_LARGE_CM + 0.1) == "대품"
    assert main.grade_by_leaf_cm(main.LEAF_SMALL_CM) == "소품"
    assert main.grade_by_leaf_cm(main.LEAF_LARGE_CM + 0.1) == "대품"


def test_metrics_grade_with_the_crop_thresholds():
    """analyze_metrics 가 받은 작물 기준으로 등급을 매긴다."""
    leaf = {"cls": "mature", "conf": .9, "x1": 0, "y1": 0, "x2": 40, "y2": 20,
            "area": 800}
    canopy = {"cls": "canopy", "conf": .9, "x1": 0, "y1": 0, "x2": 210, "y2": 100,
              "area": 21000}
    cm_per_unit = 0.1                            # 캐노피 긴 변 210 → 21cm
    alo = main.analyze_metrics([leaf, canopy], 10 ** 6, cm_per_unit)
    let = main.analyze_metrics([leaf, canopy], 10 ** 6, cm_per_unit, crop="lettuce")
    assert alo["canopy_cm"] == let["canopy_cm"] == 21.0, (alo, let)
    assert alo["size_class"] == "중품", alo
    assert let["size_class"] == "대품", let


def test_regrade_rescores_a_stored_measurement():
    """작물을 바꾸면 다시 안 찍어도 등급이 그 작물 기준으로 바뀐다."""
    p = {"canopy_cm": 21.0, "size_class": "중품", "top_leaf_size": "중엽"}
    p["crop"] = "lettuce"
    main.regrade(p)
    assert p["size_class"] == "대품", p
    assert p["top_leaf_size"] == "대엽", p        # 3D 크기도 같이 따라간다


def test_regrade_without_a_measurement_leaves_the_grade_alone():
    """실측이 없으면 다시 잴 근거가 없다 — 손으로 넣은 등급을 지운다면 손해다."""
    p = {"crop": "lettuce", "size_class": "대품", "leaf_count": 4}
    main.regrade(p)
    assert p["size_class"] == "대품", p


def test_regrade_falls_back_to_the_leaf_when_there_is_no_canopy():
    p = {"crop": "arugula", "leaf_max_cm": 9.0, "size_class": "소품"}
    main.regrade(p)
    assert p["size_class"] == "대품", p           # 루꼴라는 잎 8cm 초과가 대품


def test_regrade_does_not_invent_a_size_for_an_empty_pot():
    """잎을 아예 못 잡은 화분의 '없음' 을 등급으로 바꿔 쓰면 안 된다."""
    p = {"crop": "lettuce", "canopy_cm": 21.0, "top_leaf_size": "없음"}
    main.regrade(p)
    assert p["top_leaf_size"] == "없음", p


# ── 물주기 ───────────────────────────────────────────────────────────────
def test_a_crop_with_its_own_profile_waters_on_its_own_rhythm():
    """상추는 알로카시아보다 자주 마른다 — 같은 달에 간격이 더 짧아야 한다."""
    when = date(2026, 8, 10)
    alo, _ = watering.plan_interval({}, when)
    let, why = watering.plan_interval({"crop": "lettuce"}, when)
    assert let < alo, (let, alo)
    assert "잎채소" in why, why


def test_the_default_crop_still_uses_the_shared_profile():
    """알로카시아는 water_profile.json(또는 DEFAULT_PROFILE) 그대로 — 두 벌이 되면 안 된다."""
    assert crops.get()["water"] is None
    assert watering.profile_for({}) is watering.PROFILE
    assert watering.profile_for({"crop": crops.DEFAULT}) is watering.PROFILE


def test_an_explicit_profile_still_wins():
    """테스트·미리보기로 직접 넘긴 프로필이 작물 프로필을 이긴다."""
    prof = {"source": "직접", "base_interval_days": 11}
    got, why = watering.plan_interval({"crop": "lettuce"}, date(2026, 8, 10), prof)
    assert got == 11, got
    assert "직접" in why, why


def test_the_soil_adjustment_still_applies_on_top_of_the_crop():
    when = date(2026, 1, 10)
    plain, _ = watering.plan_interval({"crop": "pepper"}, when)
    dry, why = watering.plan_interval({"crop": "pepper", "soil": "건조"}, when)
    assert dry == plain - 1, (dry, plain)
    assert "건조" in why, why


def test_the_next_watering_date_follows_the_crop():
    """같은 날 물을 줬어도 상추가 알로카시아보다 먼저 돌아온다."""
    today = date(2026, 8, 10)
    log = {"water_log": ["2026-08-09"], "last_watered": "2026-08-09"}
    alo = watering.recommend(dict(log), today)
    let = watering.recommend(dict(log, crop="lettuce"), today)
    assert let["next_water"] < alo["next_water"], (let, alo)


# ── 배치 ─────────────────────────────────────────────────────────────────
def test_a_fruiting_crop_needs_more_light_than_the_default_one():
    same_r = 13.0
    assert (placement._need_light(same_r, {"crop": "tomato"})
            > placement._need_light(same_r, {"crop": "lettuce"})
            > placement._need_light(same_r, {}))


def test_the_default_crop_needs_exactly_what_it_used_to():
    """배수 1.0 이라 예전 값과 같아야 한다 — 알로카시아 배치 점수가 움직이면 안 된다."""
    for r_cm in (5.0, 13.0, 20.0, 40.0):
        assert placement._need_light(r_cm, {}) == placement._need_light(r_cm)


def test_a_tall_crop_shades_more_than_a_flat_one():
    """같은 폭이라도 토마토는 위로 서고 상추는 낮게 퍼진다."""
    _, tomato_h = placement.plant_shape({"crop": "tomato", "canopy_cm": 20.0})
    _, lettuce_h = placement.plant_shape({"crop": "lettuce", "canopy_cm": 20.0})
    assert tomato_h > lettuce_h, (tomato_h, lettuce_h)


def test_a_bushy_crop_is_measured_by_its_canopy_not_a_leaf():
    """바질은 잎이 작고 포기가 넓다 — 잎 길이로 재면 몸집이 터무니없이 작아진다."""
    r_cm, _ = placement.plant_shape({"crop": "basil", "canopy_cm": 20.0,
                                     "leaf_max_cm": 4.0})
    assert r_cm == 10.0, r_cm


def test_the_default_crop_is_still_measured_by_its_leaf():
    r_cm, h_cm = placement.plant_shape({"leaf_max_cm": 24.0, "canopy_cm": 30.0})
    assert r_cm == 24.0, r_cm
    assert h_cm == 24.0 * 2.2, h_cm


def test_grade_shape_falls_back_to_the_crop_thresholds():
    """실측이 없어도 등급만으로 그 작물다운 몸집이 나와야 한다."""
    small, _ = placement.plant_shape({"crop": "lettuce", "size_class": "소품"})
    large, _ = placement.plant_shape({"crop": "lettuce", "size_class": "대품"})
    assert small < large, (small, large)
    assert small == crops.get("lettuce")["canopy_cm"][0] / 2, small


def test_the_optimizer_prefers_the_bright_spot_for_the_hungry_crop():
    """빛 요구가 다른 두 포기를 놓으면, 더 필요한 쪽이 밝은 자리로 간다."""
    _reset()
    lights = [{"side": "left", "x": placement.rail_x("left"), "y": 47.0, "z": 0.0,
               "power": 1.0, "angle": 60.0}]
    bright, dark = (-20.0, 0.0), (25.0, 15.0)
    tomato = {"id": "t", "name": "토마토", "crop": "tomato", "canopy_cm": 20.0,
              "size_class": "중품"}
    lettuce = {"id": "l", "name": "상추", "crop": "lettuce", "canopy_cm": 20.0,
               "size_class": "중품"}
    # 일부러 거꾸로 놓는다 — 토마토가 어두운 자리
    spots = []
    for slot, (x_cm, z_cm), p in (("A1", bright, lettuce), ("B5", dark, tomato)):
        r_cm, h_cm = placement.plant_shape(p)
        spots.append({"slot": slot, "x_cm": x_cm, "z_cm": z_cm,
                      "r_cm": r_cm, "h_cm": h_cm, "plant": p})
    out = placement.optimize(spots, lights)
    assert out["gain"] > 0, out
    assert [m["plant_id"] for m in out["moves"]], out
    moved = {m["plant_id"]: m["to"] for m in out["moves"]}
    assert moved.get("t") == "A1", out            # 토마토가 밝은 자리로


def test_the_layout_says_which_crop_sits_where():
    plant = {"id": "x", "name": "바질", "crop": "basil", "canopy_cm": 16.0}
    r_cm, h_cm = placement.plant_shape(plant)
    graded = placement.score_layout([{"slot": "A1", "x_cm": 0.0, "z_cm": 0.0,
                                      "r_cm": r_cm, "h_cm": h_cm, "plant": plant}])
    assert graded["spots"][0]["crop"] == "basil"
    assert graded["spots"][0]["crop_name"] == "바질"


# ── 엔드포인트 ────────────────────────────────────────────────────────────
def test_the_crop_list_endpoint_serves_the_picker():
    d = main.list_crops()
    assert d["default"] == crops.DEFAULT
    assert [c["key"] for c in d["crops"]] == list(crops.KEYS)


def test_adding_a_plant_records_what_was_planted():
    _reset()
    p = _add(crop="basil")
    assert p["crop"] == "basil"
    assert main.PLANTS[p["id"]]["crop"] == "basil"


def test_adding_without_a_crop_stays_the_default_one():
    _reset()
    p = _add()
    assert p["crop"] == crops.DEFAULT


def test_an_unnamed_plant_is_named_after_its_crop():
    _reset()
    p = _add(name="   ", crop="tomato")
    assert "방울토마토" in p["name"], p["name"]


def test_a_typo_in_the_crop_is_refused_not_stored():
    """조용히 알로카시아로 저장되면, 사람은 상추로 골랐다고 믿는다."""
    _reset()
    try:
        _add(crop="상추")
    except HTTPException as e:
        assert e.status_code == 400 and "모르는 작물" in e.detail, e.detail
    else:
        raise AssertionError("모르는 작물이 통과했다")
    assert not main.PLANTS


def test_changing_the_crop_regrades_and_reschedules():
    _reset()
    p = _add(crop="alocasia")
    p.update({"canopy_cm": 21.0, "size_class": "중품", "top_leaf_size": "중엽",
              "water_log": ["2026-08-09"], "last_watered": "2026-08-09"})
    before = watering.recommend(p)["interval_days"]
    got = _patch(p["id"], crop="lettuce")
    assert got["crop"] == "lettuce"
    assert got["crop_name"] == "상추"
    assert got["size_class"] == "대품", got       # 상추 기준으로 다시 매겨졌다
    assert got["interval_days"] < before, (got["interval_days"], before)


def test_changing_the_crop_is_not_a_hand_edit():
    """무엇을 심었는지 적는 것은 탐지값을 고치는 게 아니다 (흙 상태와 같은 취급)."""
    _reset()
    p = _add()
    got = _patch(p["id"], crop="basil")
    assert not got.get("manual"), got


def test_patching_an_unknown_crop_is_refused():
    _reset()
    p = _add(crop="basil")
    try:
        _patch(p["id"], crop="없는작물")
    except HTTPException as e:
        assert e.status_code == 400, e
    else:
        raise AssertionError("모르는 작물이 통과했다")
    assert main.PLANTS[p["id"]]["crop"] == "basil"     # 원래 값이 남아 있다


def test_listing_plants_fills_in_the_crop_for_old_records():
    """crop 이 없던 시절의 기록도 화면에서는 이름이 붙어 나와야 한다."""
    _reset()
    main.PLANTS["old"] = {"id": "old", "name": "예전", "pos": "A1",
                          "size_class": "중품", "leaf_count": 3}
    row = next(p for p in main.list_plants()["plants"] if p["id"] == "old")
    assert row["crop"] == crops.DEFAULT
    assert row["crop_name"] == "알로카시아"


def test_the_crop_survives_a_backup_round_trip():
    _reset()
    p = _add(crop="strawberry")
    saved = main.backup_payload()
    _reset()
    main.restore_payload(saved)
    assert main.PLANTS[p["id"]]["crop"] == "strawberry"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
