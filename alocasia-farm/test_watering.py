"""물주기 추천 스모크 테스트 (네트워크 불필요)

실행:  python3 test_watering.py

기준은 프로필(그 달의 값)이고, 흙 상태로 하루씩 당기거나 미룬다. 예정일은
마지막으로 준 날에서만 센다 — 과거 기록을 평균 내지 않는다.
"""

import os
from datetime import date

os.environ["FARM_DB"] = ""

import watering                                  # noqa: E402

PROF = {"source": "테스트 프로필", "base_interval_days": 6, "by_month": {"8": 3}}


def plant(log, last=None):
    return {"water_log": list(log), "last_watered": last or (log[-1] if log else None)}


def test_the_profile_is_the_baseline():
    """기준은 프로필 — 과거 기록을 평균 내지 않는다."""
    got, why = watering.plan_interval(plant([]), date(2026, 8, 5), PROF)
    assert got == 3, got                         # 8월은 by_month 가 이긴다
    assert "테스트 프로필" in why, why


def test_a_month_without_its_own_number_uses_the_base():
    got, _ = watering.plan_interval(plant([]), date(2026, 1, 5), PROF)
    assert got == 6, got


def test_without_any_profile_it_uses_the_fallback():
    got, why = watering.plan_interval(plant([]), date(2026, 8, 5), {})
    assert got == watering.FALLBACK_DAYS, got
    assert "기본값" in why, why


def test_past_records_never_move_the_interval():
    """8일 간격으로 오래 줘 왔어도 간격은 프로필대로다 — 누적 평균이 아니다."""
    long_history = plant([f"2026-06-{d:02d}" for d in range(1, 30, 8)]
                         + ["2026-07-05", "2026-07-13", "2026-07-21"])
    a, _ = watering.plan_interval(plant([]), date(2026, 8, 20), PROF)
    b, _ = watering.plan_interval(long_history, date(2026, 8, 20), PROF)
    assert a == b == 3, (a, b)


def test_the_soil_choice_moves_it_one_day_each_way():
    when = date(2026, 8, 5)                      # 프로필 3일
    dry, _ = watering.plan_interval({"soil": "건조"}, when, PROF)
    mid, _ = watering.plan_interval({"soil": "일반"}, when, PROF)
    wet, _ = watering.plan_interval({"soil": "과습"}, when, PROF)
    assert (dry, mid, wet) == (2, 3, 4), (dry, mid, wet)


def test_an_unknown_soil_value_is_treated_as_normal():
    assert watering.soil_of({"soil": "아무거나"}) == "일반"
    assert watering.soil_of({}) == "일반"
    assert watering.soil_of(None) == "일반"


def test_the_soil_choice_shows_up_in_the_reason():
    _, why = watering.plan_interval({"soil": "과습"}, date(2026, 8, 5), PROF)
    assert "과습" in why and "+1" in why, why


def test_my_own_interval_is_reported_but_not_used():
    """실제로 준 간격은 비교용으로만 보여 준다 — 계산에는 안 들어간다."""
    p = plant(["2026-08-01", "2026-08-09", "2026-08-17"])        # 8일 간격
    r = watering.recommend(p, date(2026, 8, 18), PROF)
    assert r["own_interval_days"] == 8.0, r
    assert r["interval_days"] == 3, r                            # 프로필 그대로
    assert r["next_water"] == "2026-08-20", r                    # 8/17 + 3


def test_same_day_written_twice_is_not_a_zero_gap():
    assert watering.own_intervals(["2026-08-01", "2026-08-01", "2026-08-05"]) == [4.0]


def test_a_months_long_gap_is_not_a_rhythm():
    """한동안 안 적다가 몰아 적은 것은 물주기 리듬이 아니다."""
    assert watering.own_intervals(["2026-01-01", "2026-08-01", "2026-08-05"]) == [4.0]


def test_broken_dates_are_skipped():
    assert watering.own_intervals(["", None, "어제", "2026-08-01", "2026-08-04"]) == [3.0]


def test_next_date_counts_from_the_last_watering():
    p = plant(["2026-08-01", "2026-08-04", "2026-08-07"])
    r = watering.recommend(p, date(2026, 8, 8), PROF)
    assert r["next_water"] == "2026-08-10", r     # 마지막 8/7 + 프로필 3일
    assert r["days_until"] == 2 and not r["overdue"], r


def test_the_last_watering_is_what_counts_not_the_older_ones():
    """예전에 드문드문 줬어도, 다음 날짜는 마지막으로 준 날에서 센다."""
    p = plant(["2026-05-01", "2026-06-20", "2026-08-07"])
    r = watering.recommend(p, date(2026, 8, 8), PROF)
    assert r["next_water"] == "2026-08-10", r


def test_a_plant_past_its_date_is_flagged():
    p = plant(["2026-08-01", "2026-08-04"])
    r = watering.recommend(p, date(2026, 8, 20), PROF)
    assert r["overdue"] is True and r["days_until"] < 0, r


def test_a_plant_never_watered_gets_no_date():
    """한 번도 안 준 포기에 근거 없는 날짜를 달력에 박으면 안 된다."""
    r = watering.recommend({"water_log": [], "last_watered": None}, date(2026, 8, 5), PROF)
    assert r["next_water"] is None and r["days_until"] is None, r
    assert r["interval_days"] == 3, r             # 간격 자체는 알려 준다


def test_the_calendar_only_gets_dates_still_ahead():
    """지난 칸에는 '실제로 준 기록' 만 보여야 한다 — 놓친 예정일이 섞이면 안 된다."""
    soon = plant(["2026-08-01", "2026-08-04", "2026-08-07"])     # 다음 8/10
    late = plant(["2026-07-01", "2026-07-04", "2026-07-07"])     # 이미 지남
    due = watering.upcoming([soon, late], "2026-08", date(2026, 8, 8), PROF)
    assert due == {"2026-08-10": 1}, due


def test_two_plants_due_the_same_day_are_counted_together():
    a = plant(["2026-08-01", "2026-08-04", "2026-08-07"])
    b = plant(["2026-08-01", "2026-08-04", "2026-08-07"])
    due = watering.upcoming([a, b], "2026-08", date(2026, 8, 8), PROF)
    assert due == {"2026-08-10": 2}, due


def test_the_default_profile_is_the_wet_group_in_a_living_room():
    """알로카시아는 습생이고 두는 곳은 거실 — 베란다는 훨씬 빨리 마른다."""
    d = watering.DEFAULT_PROFILE
    assert d["group"] == "습생" and d["place"] == "거실", d
    assert d["provisional"] is True, "데이터셋에서 뽑기 전까지는 잠정값임을 표시해 둔다"


def test_the_default_profile_waters_more_often_in_summer():
    summer = watering.profile_interval(date(2026, 7, 15), watering.DEFAULT_PROFILE)
    winter = watering.profile_interval(date(2026, 1, 15), watering.DEFAULT_PROFILE)
    assert summer < winter, (summer, winter)
    assert all(watering.MIN_INTERVAL <= watering.profile_interval(date(2026, m, 15),
                                                                 watering.DEFAULT_PROFILE)
               <= watering.MAX_INTERVAL for m in range(1, 13))


def test_a_profile_file_wins_over_the_built_in_default():
    """데이터셋으로 만든 water_profile.json 을 넣으면 잠정값은 안 쓰인다."""
    got = watering.profile_interval(date(2026, 1, 15), {"base_interval_days": 2})
    assert got == 2, got


def test_an_absurd_interval_never_reaches_the_calendar():
    """프로필이 잘못 적혀도 몇 달 뒤 같은 날짜가 나오면 안 된다."""
    r = watering.recommend(plant(["2026-08-07"]), date(2026, 8, 8),
                           {"base_interval_days": 9999})
    assert r["interval_days"] <= watering.MAX_INTERVAL, r


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
