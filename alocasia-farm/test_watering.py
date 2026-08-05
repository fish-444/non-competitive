"""물주기 추천 스모크 테스트 (네트워크 불필요)

실행:  python3 test_watering.py

핵심은 '내 기록'과 '프로필'을 기록 수로 저울질하는 부분이다. 기록이 없으면
프로필대로, 쌓이면 내 리듬으로 옮겨가야 한다.
"""

import os
from datetime import date

os.environ["FARM_DB"] = ""

import watering                                  # noqa: E402

PROF = {"source": "테스트 프로필", "base_interval_days": 6, "by_month": {"8": 3}}


def plant(log, last=None):
    return {"water_log": list(log), "last_watered": last or (log[-1] if log else None)}


def test_no_records_falls_back_to_the_profile():
    """한 번도 안 준 포기는 기댈 게 프로필뿐이다."""
    got, why = watering.blended_interval([], date(2026, 8, 5), PROF)
    assert got == 3, got                         # 8월은 by_month 가 이긴다
    assert "테스트 프로필" in why, why


def test_a_month_without_its_own_number_uses_the_base():
    got, _ = watering.blended_interval([], date(2026, 1, 5), PROF)
    assert got == 6, got


def test_without_any_profile_it_uses_the_fallback():
    got, why = watering.blended_interval([], date(2026, 8, 5), {})
    assert got == watering.FALLBACK_DAYS, got
    assert why == "기본값", why


def test_own_rhythm_takes_over_as_records_pile_up():
    """기록이 늘수록 프로필에서 멀어지고 내 간격으로 수렴해야 한다."""
    when = date(2026, 8, 20)
    few = plant(["2026-08-01", "2026-08-09"])                   # 8일 간격 1개
    many = plant([f"2026-08-{d:02d}" for d in range(1, 20, 8)]  # 8일 간격 여러 개
                 + ["2026-09-05", "2026-09-13", "2026-10-01", "2026-10-09"])
    a, _ = watering.blended_interval(few["water_log"], when, PROF)
    b, _ = watering.blended_interval(many["water_log"], when, PROF)
    assert 3 < a < 8, a                          # 프로필 3 과 내 간격 8 사이
    assert a < b < 8, (a, b)                     # 기록이 많을수록 8 에 가까워진다


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
    assert r["next_water"] == "2026-08-10", r     # 3일 간격 → 8/7 + 3
    assert r["days_until"] == 2 and not r["overdue"], r


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
