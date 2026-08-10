"""수확 예측 스모크 테스트 (네트워크 불필요)

실행:  python3 test_harvest.py

생장 이력의 기울기로 수확적기와 생산량을 낸다. 여기서 제일 중요한 건 맞히는
것보다 **모를 때 모른다고 하는 것**이다 — 근거 없는 날짜가 달력에 박히면
사람은 그걸 믿고 준비한다.
"""

from datetime import date, timedelta

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import crops                                     # noqa: E402
import harvest                                   # noqa: E402
import main                                      # noqa: E402

TODAY = date(2026, 8, 10)


def log(pairs, field="canopy_cm", start_days_ago=None):
    """[(며칠 전, 값)] → growth_log. 며칠 전은 TODAY 기준."""
    rows = []
    for ago, val in pairs:
        rows.append({"on": (TODAY - timedelta(days=ago)).isoformat(),
                     "src": "scan", field: val})
    rows.sort(key=lambda r: r["on"])
    return rows


def grew(crop="lettuce", canopy=None, leaves=None):
    """캐노피·잎이 같은 날짜들에 함께 찍힌 이력을 만든다."""
    rows = {}
    for ago, val in (canopy or []):
        rows.setdefault(ago, {})["canopy_cm"] = val
    for ago, val in (leaves or []):
        rows.setdefault(ago, {})["leaf_count"] = val
    growth = [{"on": (TODAY - timedelta(days=ago)).isoformat(), "src": "scan", **vals}
              for ago, vals in sorted(rows.items(), reverse=True)]
    return {"id": "p1", "name": "테스트", "pos": "A1", "crop": crop,
            "growth_log": growth}


# ── 추세 ─────────────────────────────────────────────────────────────────
def test_a_steady_climb_gives_its_slope():
    """하루 0.5cm 씩 자란 기록이면 기울기도 0.5 여야 한다."""
    t = harvest.trend(log([(12, 8.0), (8, 10.0), (4, 12.0), (0, 14.0)]), today=TODAY)
    assert t["per_day"] == 0.5, t
    assert t["r2"] == 1.0, t
    assert t["now"] == 14.0, t


def test_one_bad_measurement_does_not_flip_the_trend():
    """마지막 사진에서 잎이 가려져 작게 잡혀도 '줄어든다'가 되면 안 된다.

    두 점 차이로 봤다면 −1.5cm 라 수확적기가 통째로 뒤집힌다.
    """
    t = harvest.trend(log([(16, 8.0), (12, 10.0), (8, 12.0), (4, 14.0), (0, 12.5)]),
                      today=TODAY)
    assert t["per_day"] > 0, t


def test_a_single_measurement_has_no_slope():
    t = harvest.trend(log([(3, 10.0)]), today=TODAY)
    assert t["points"] == 1 and t["per_day"] is None, t
    assert t["now"] == 10.0, t                   # 크기는 알지만 속도는 모른다


def test_measurements_crammed_into_two_days_have_no_slope():
    """사흘은 벌어져야 기울기로 본다 — 하루 이틀 사이는 잡음이다."""
    t = harvest.trend(log([(1, 10.0), (0, 12.0)]), today=TODAY)
    assert t["per_day"] is None, t


def test_only_the_recent_window_counts():
    """반년 전 봄에 쑥쑥 크던 기록이 지금 속도를 부풀리면 안 된다."""
    old_and_new = log([(300, 1.0), (200, 30.0), (10, 12.0), (0, 13.0)])
    t = harvest.trend(old_and_new, today=TODAY)
    assert t["points"] == 2, t
    assert 0 < t["per_day"] < 1, t


def test_a_stale_measurement_is_pushed_forward_to_today():
    """지난주에 잰 값을 '지금 크기'로 쓰면 그 사이 자란 만큼이 빠진다."""
    t = harvest.trend(log([(20, 6.0), (10, 11.0)]), today=TODAY)
    assert t["last"] == 11.0, t
    assert t["now"] == 16.0, t                   # 하루 0.5cm × 10일


def test_a_shrinking_plant_reports_a_negative_slope():
    t = harvest.trend(log([(10, 14.0), (5, 12.0), (0, 10.0)]), today=TODAY)
    assert t["per_day"] < 0, t


def test_confidence_grows_with_the_record():
    thin = harvest.trend(log([(4, 10.0), (0, 12.0)]), today=TODAY)
    thick = harvest.trend(log([(20, 6.0), (15, 8.0), (10, 10.0), (5, 12.0), (0, 14.0)]),
                          today=TODAY)
    assert thin["confidence"] == "낮음", thin
    assert thick["confidence"] == "높음", thick


def test_junk_rows_are_skipped_not_crashed():
    """손으로 고친 백업에 뭐가 섞여 있어도 조회가 터지면 안 된다."""
    rows = [{"on": "2026-08-01", "canopy_cm": 10.0}, {"on": "말도안되는날", "canopy_cm": 11.0},
            {"on": "2026-08-05", "canopy_cm": "글자"}, "줄이아님", {"canopy_cm": 12.0},
            {"on": "2026-08-08", "canopy_cm": 13.0}]
    assert len(harvest.points(rows, "canopy_cm")) == 2
    assert harvest.trend(rows, today=TODAY)["per_day"] is not None


# ── 수확적기 ──────────────────────────────────────────────────────────────
def test_it_predicts_the_day_the_crop_reaches_its_size():
    """상추 기준 18cm, 지금 14cm, 하루 0.5cm → 8일 뒤."""
    got = harvest.forecast(grew(canopy=[(12, 8.0), (8, 10.0), (4, 12.0), (0, 14.0)]), TODAY)
    assert got["harvestable"] and got["days_until"] == 8, got
    assert got["ready_on"] == (TODAY + timedelta(days=8)).isoformat(), got
    assert got["ready_now"] is False, got


def test_a_plant_already_past_its_size_is_ready_today():
    got = harvest.forecast(grew(canopy=[(8, 17.0), (0, 20.0)],
                                leaves=[(8, 9), (0, 12)]), TODAY)
    assert got["ready_now"] is True, got
    assert got["days_until"] == 0 and got["ready_on"] == TODAY.isoformat(), got


def test_a_big_plant_needs_no_slope_to_say_harvest_now():
    """다 컸으면 '지금 거두세요' 에 기울기는 필요 없다 — 측정 한 번이어도 답한다."""
    got = harvest.forecast(grew(canopy=[(0, 22.0)], leaves=[(0, 11)]), TODAY)
    assert got["ready_now"] is True, got
    assert got["yield_g"] == 24, got             # (11 − 5장) × 4g


def test_a_plant_that_stopped_growing_gets_no_date():
    """안 자라는 건 실패가 아니라 신호다 — 날짜 대신 살펴보라고 말한다."""
    got = harvest.forecast(grew(canopy=[(10, 14.0), (5, 13.0), (0, 12.0)]), TODAY)
    assert got["ready_on"] is None, got
    assert "안 커지고" in got["why"], got


def test_a_crawling_plant_gets_no_date_either():
    """이 속도면 반 년 뒤라는 계산은 예측이 아니라 산수다."""
    got = harvest.forecast(grew(canopy=[(40, 8.0), (0, 8.4)]), TODAY)
    assert got["ready_on"] is None, got
    assert str(harvest.MAX_HORIZON_DAYS) in got["why"], got


def test_a_pot_with_one_measurement_gets_no_date():
    got = harvest.forecast(grew(canopy=[(0, 10.0)]), TODAY)
    assert got["ready_on"] is None, got
    assert got["harvestable"] is True, got       # 거두는 작물이긴 하다
    assert "다시 스캔" in got["why"], got


def test_a_pot_never_measured_says_so():
    got = harvest.forecast({"crop": "lettuce"}, TODAY)
    assert got["ready_on"] is None and got["canopy_now"] is None, got
    assert "잰 적이 없" in got["why"], got


def test_an_ornamental_is_not_harvested_at_all():
    """알로카시아 잎을 따는 건 수확이 아니라 손해다."""
    got = harvest.forecast(grew(crop="alocasia", canopy=[(8, 10.0), (0, 20.0)]), TODAY)
    assert got["harvestable"] is False, got
    assert got["ready_on"] is None and got["yield_g"] is None, got
    assert "알로카시아" in got["why"], got


def test_each_crop_reaches_its_own_size():
    """같은 14cm 라도 루꼴라는 다 컸고 방울토마토는 한참 멀었다."""
    canopy = [(8, 12.0), (0, 14.0)]
    quick = harvest.forecast(grew("arugula", canopy=canopy, leaves=[(8, 10), (0, 13)]), TODAY)
    slow = harvest.forecast(grew("tomato", canopy=canopy), TODAY)
    assert quick["ready_now"] is True, quick
    assert slow["ready_now"] is False and slow["days_until"] > 0, slow


# ── 생산량 ───────────────────────────────────────────────────────────────
def test_leaf_yield_comes_from_the_leaves_we_count():
    """상추: (수확 시점 잎 수 − 남길 5장) × 4g."""
    got = harvest.forecast(grew(canopy=[(12, 8.0), (8, 10.0), (4, 12.0), (0, 14.0)],
                                leaves=[(12, 4), (8, 6), (4, 8), (0, 10)]), TODAY)
    assert got["days_until"] == 8, got
    assert got["leaf_at_harvest"] == 14.0, got   # 하루 0.5장 × 8일
    assert got["yield_g"] == 36, got             # (14 − 5) × 4g
    assert got["rough"] is False, got            # 잎은 실제로 세고 있다


def test_the_leaves_we_keep_are_not_counted_as_yield():
    """겉잎만 따고 속잎은 남긴다 — 다 뽑는 게 아니다."""
    spec = crops.get("lettuce")["harvest"]
    g, _ = harvest._yield_g(spec, crops.HARVEST_LEAF, 18.0, spec["keep_leaves"])
    assert g == 0, g


def test_fruit_yield_is_flagged_as_a_rough_guess():
    """열매는 탐지가 안 된다 — 포기 크기로 에두른 추정이라고 밝혀야 한다."""
    got = harvest.forecast(grew("tomato", canopy=[(10, 18.0), (0, 24.0)]), TODAY)
    assert got["mode"] == crops.HARVEST_FRUIT, got
    assert got["yield_g"] and got["rough"] is True, got


def test_a_bigger_fruiting_plant_is_expected_to_give_more():
    small = harvest.forecast(grew("tomato", canopy=[(8, 24.0), (0, 26.0)]), TODAY)
    big = harvest.forecast(grew("tomato", canopy=[(8, 40.0), (0, 45.0)]), TODAY)
    assert big["yield_g"] > small["yield_g"], (big, small)


def test_the_fruit_estimate_does_not_run_away_with_size():
    """캐노피가 세 배라고 열매가 세 배 달리지는 않는다."""
    huge = harvest.forecast(grew("tomato", canopy=[(8, 90.0), (0, 100.0)]), TODAY)
    assert huge["yield_g"] == 240, huge          # 120g × 상한 2배


def test_a_leafy_crop_without_leaf_counts_falls_back_to_the_spec():
    """잎을 못 센 이력이면 그 작물의 기준 잎 수로라도 답한다."""
    got = harvest.forecast(grew(canopy=[(8, 12.0), (0, 16.0)]), TODAY)
    assert got["yield_g"] == 20, got             # (기준 10장 − 5장) × 4g


# ── 온실 전체 ─────────────────────────────────────────────────────────────
def test_the_farm_plan_groups_by_day_and_totals_the_grams():
    a = grew(canopy=[(12, 8.0), (8, 10.0), (4, 12.0), (0, 14.0)],
             leaves=[(12, 4), (8, 6), (4, 8), (0, 10)])
    b = dict(grew("arugula", canopy=[(8, 8.0), (0, 12.0)], leaves=[(8, 8), (0, 12)]),
             id="p2", pos="A2")
    plan = harvest.farm_forecast([a, b], TODAY)
    assert plan["total_g"] > 0, plan
    assert len(plan["plants"]) == 2, plan
    assert sum(d["yield_g"] for d in plan["days"]) == plan["total_g"], plan
    assert plan["plants"][0]["days_until"] <= plan["plants"][1]["days_until"], plan


def test_the_farm_plan_leaves_out_what_is_not_harvested():
    ornamental = grew("alocasia", canopy=[(8, 10.0), (0, 20.0)])
    plan = harvest.farm_forecast([ornamental], TODAY)
    assert plan["plants"] == [] and plan["total_g"] == 0, plan


def test_the_farm_plan_counts_what_is_ready_today():
    ready = grew(canopy=[(8, 17.0), (0, 20.0)], leaves=[(8, 9), (0, 12)])
    plan = harvest.farm_forecast([ready], TODAY)
    assert plan["ready_now"] == 1, plan


def test_the_window_keeps_far_off_harvests_out_of_the_total():
    """이번 달 얼마나 나오나에, 두 달 뒤 것이 섞이면 안 된다."""
    slow = grew("tomato", canopy=[(20, 8.0), (0, 12.0)])
    near = harvest.farm_forecast([slow], TODAY, window_days=7)
    far = harvest.farm_forecast([slow], TODAY, window_days=120)
    assert near["total_g"] == 0, near
    assert far["total_g"] > 0, far
    assert len(near["plants"]) == 1, near        # 목록에는 남는다, 합계에서만 빠진다


# ── 엔드포인트 ────────────────────────────────────────────────────────────
def _reset():
    main.PLANTS.clear(); main.POTS.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear(); main.ENVIRONMENT.clear()


def test_the_history_endpoint_carries_the_forecast():
    _reset()
    main.PLANTS["p1"] = grew(canopy=[(12, 8.0), (8, 10.0), (4, 12.0), (0, 14.0)])
    got = main.plant_history("p1")
    assert got["forecast"]["harvestable"] is True, got
    assert got["forecast"]["ready_on"], got


def test_the_plant_forecast_endpoint_answers_for_one_pot():
    _reset()
    main.PLANTS["p1"] = grew(canopy=[(8, 17.0), (0, 20.0)], leaves=[(8, 9), (0, 12)])
    got = main.plant_forecast("p1")
    assert got["id"] == "p1" and got["ready_now"] is True, got


def test_the_farm_endpoint_clamps_a_silly_window():
    _reset()
    assert main.harvest_plan(days=0)["window_days"] == 1
    assert main.harvest_plan(days=10_000)["window_days"] == 365


def test_the_plant_list_carries_a_short_harvest_hint():
    """리스트 딱지는 '언제·얼마나' 세 줄이면 된다 — 근거는 모달이 따로 부른다."""
    _reset()
    main.PLANTS["p1"] = grew(canopy=[(8, 17.0), (0, 20.0)], leaves=[(8, 9), (0, 12)])
    row = main.list_plants()["plants"][0]
    assert row["harvest_ready"] is True, row
    assert row["harvest_g"] and row["harvest_on"], row


def test_an_ornamental_gets_no_harvest_hint_in_the_list():
    _reset()
    main.PLANTS["p1"] = grew("alocasia", canopy=[(8, 10.0), (0, 20.0)])
    row = main.list_plants()["plants"][0]
    assert row["harvest_on"] is None and row["harvest_ready"] is False, row


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
