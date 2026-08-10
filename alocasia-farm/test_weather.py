"""기상 보정 스모크 테스트 (네트워크 불필요)

실행:  python3 test_weather.py

여기서 제일 중요한 건 **기본값이 예전과 똑같은 것**이다. 위치를 안 넣었거나
재배 환경이 실내면 기상 자료가 있어도 물주기·수확 예측이 한 톨도 안 움직여야
한다. 그 다음이 '반영하기로 한 만큼만 반영하는가' 다.

받아 오는 일(providers/weather_*.py)은 여기서 안 건드린다 — 이 파일은 **받아 온
숫자를 어떻게 해석하는가**만 본다. 네트워크를 타는 부분은 가짜 관측으로 대신한다.
"""

from datetime import date, datetime, timedelta

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

import crops                                     # noqa: E402
import harvest                                   # noqa: E402
import main                                      # noqa: E402
import watering                                  # noqa: E402
import weather                                   # noqa: E402
from providers import weather_kma                # noqa: E402

TODAY = date(2026, 8, 10)


def obs(et0_recent=5.0, et0_normal=4.0, t_max=30.0, t_min=20.0,
        ahead_max=None, ahead_min=None, rain=0.0, days_back=40, days_ahead=10):
    """가짜 관측. 최근 7일과 그 앞 한 달을 다른 값으로 채운다."""
    daily = []
    for back in range(days_back, 0, -1):
        d = TODAY - timedelta(days=back)
        recent = back < 7
        daily.append({"on": d.isoformat(), "t_max": t_max, "t_min": t_min,
                      "et0": et0_recent if recent else et0_normal,
                      "rain_mm": rain if back <= 2 else 0.0})
    daily.append({"on": TODAY.isoformat(), "t_max": t_max, "t_min": t_min,
                  "et0": et0_recent, "rain_mm": rain})
    for ahead in range(1, days_ahead + 1):
        d = TODAY + timedelta(days=ahead)
        daily.append({"on": d.isoformat(),
                      "t_max": ahead_max if ahead_max is not None else t_max,
                      "t_min": ahead_min if ahead_min is not None else t_min,
                      "et0": et0_recent, "rain_mm": 0.0})
    return {"source": "테스트", "daily": daily,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "current": {"temp_c": 27.0, "humidity_pct": 60,
                        "soil_moisture": 0.22, "soil_temp_c": 26.0}}


def growth_log(pairs):
    return [{"on": (TODAY - timedelta(days=ago)).isoformat(), "src": "scan",
             "canopy_cm": cm, "leaf_count": lf} for ago, cm, lf in sorted(pairs, reverse=True)]


def _reset():
    main.PLANTS.clear(); main.POTS.clear(); main.SITE.clear(); main.WEATHER.clear()
    main.LEAVES.clear(); main.LEAF_FIXES.clear(); main.ENVIRONMENT.clear()


# ── 재배 환경 ─────────────────────────────────────────────────────────────
def test_the_default_site_is_indoor_and_ignores_weather():
    """설정을 안 건드리면 예전 그대로 — 이게 이 기능의 첫 번째 약속이다."""
    assert weather.site()["key"] == "indoor"
    assert weather.site()["coupling"] == 0.0
    assert weather.site("없는값")["key"] == "indoor"


def test_the_sites_get_stronger_as_they_go_outside():
    order = ["indoor", "veranda", "greenhouse", "outdoor"]
    got = [weather.site(k)["coupling"] for k in order]
    assert got == sorted(got), got
    assert got[0] == 0.0 and got[-1] == 1.0, got


def test_only_the_open_ground_gets_rained_on():
    """지붕이 있으면 화분에 비가 안 떨어진다 — 강수는 무관 변수다."""
    assert weather.site("outdoor")["rain"] is True
    for covered in ("indoor", "veranda", "greenhouse"):
        assert weather.site(covered)["rain"] is False, covered


# ── 물주기 보정 ───────────────────────────────────────────────────────────
def test_indoor_never_moves_the_watering_interval():
    got = weather.water_adjust_days(obs(et0_recent=9.0, et0_normal=3.0), "indoor", TODAY)
    assert got["days"] == 0.0, got
    assert "실내" in got["why"], got


def test_a_dry_spell_pulls_the_watering_in():
    got = weather.water_adjust_days(obs(et0_recent=5.0, et0_normal=4.0),
                                    "greenhouse", TODAY)
    assert got["days"] < 0, got                  # 메마르니 더 자주


def test_a_damp_spell_pushes_the_watering_out():
    got = weather.water_adjust_days(obs(et0_recent=3.0, et0_normal=4.0),
                                    "greenhouse", TODAY)
    assert got["days"] > 0, got


def test_the_correction_scales_with_the_site():
    """같은 날씨라도 비닐하우스가 베란다보다 크게 움직인다."""
    weather_now = obs(et0_recent=6.0, et0_normal=4.0)
    veranda = weather.water_adjust_days(weather_now, "veranda", TODAY)["days"]
    house = weather.water_adjust_days(weather_now, "greenhouse", TODAY)["days"]
    assert abs(house) > abs(veranda) > 0, (house, veranda)


def test_the_correction_is_capped():
    """근거가 편차 하나뿐인 계산이라 크게 흔들면 안 된다."""
    wild = weather.water_adjust_days(obs(et0_recent=40.0, et0_normal=1.0),
                                     "outdoor", TODAY)
    assert abs(wild["days"]) <= weather.MAX_WATER_ADJUST, wild


def test_rain_only_counts_in_the_open_ground():
    wet = obs(et0_recent=4.0, et0_normal=4.0, rain=20.0)
    outdoor = weather.water_adjust_days(wet, "outdoor", TODAY)
    house = weather.water_adjust_days(wet, "greenhouse", TODAY)
    assert outdoor["days"] > 0 and outdoor["rain_mm"] == 60.0, outdoor
    assert house["days"] == 0.0 and house["rain_mm"] is None, house


def test_without_enough_history_it_does_not_guess():
    thin = weather.water_adjust_days(obs(days_back=4), "greenhouse", TODAY)
    assert thin["days"] == 0.0 and "모자라" in thin["why"], thin


def test_no_observation_means_no_correction():
    assert weather.water_adjust_days({}, "outdoor", TODAY)["days"] == 0.0
    assert weather.water_adjust_days(None, "outdoor", TODAY)["days"] == 0.0


def test_junk_rows_do_not_crash_the_correction():
    bad = obs()
    bad["daily"] += [{"on": "말도안됨", "et0": 3}, {"et0": 3}, "줄이아님",
                     {"on": "2026-08-09", "et0": "글자"}]
    assert isinstance(weather.water_adjust_days(bad, "greenhouse", TODAY)["days"], float)


# ── 생장 보정 ─────────────────────────────────────────────────────────────
def test_indoor_never_scales_the_growth():
    got = weather.growth_factor(obs(t_max=20.0, ahead_max=35.0), crops.get("lettuce"),
                                "2026-08-01", "2026-08-09", "indoor", TODAY)
    assert got["factor"] == 1.0, got


def test_a_warm_spell_ahead_speeds_growth_up():
    got = weather.growth_factor(obs(t_max=22.0, t_min=14.0, ahead_max=32.0, ahead_min=24.0),
                                crops.get("lettuce"), "2026-08-01", "2026-08-09",
                                "greenhouse", TODAY)
    assert got["factor"] > 1.0, got
    assert got["gdd_ahead"] > got["gdd_past"], got


def test_a_cold_spell_ahead_slows_growth_down():
    got = weather.growth_factor(obs(t_max=32.0, t_min=24.0, ahead_max=20.0, ahead_min=12.0),
                                crops.get("lettuce"), "2026-08-01", "2026-08-09",
                                "greenhouse", TODAY)
    assert got["factor"] < 1.0, got


def test_the_growth_factor_is_clamped():
    got = weather.growth_factor(obs(t_max=6.0, t_min=5.0, ahead_max=40.0, ahead_min=30.0),
                                crops.get("lettuce"), "2026-08-01", "2026-08-09",
                                "outdoor", TODAY)
    assert got["factor"] <= weather.GROWTH_FACTOR_MAX, got


def test_each_crop_group_has_its_own_base_temperature():
    """바질·토마토는 10°C 아래에서 사실상 안 큰다 — 상추와 같은 자로 재면 안 된다."""
    assert weather.base_temp_of(crops.get("lettuce")) < weather.base_temp_of(crops.get("basil"))
    assert weather.gdd(12.0, 8.0, 4.0) == 6.0
    assert weather.gdd(12.0, 8.0, 10.0) == 0.0   # 기저 아래는 0, 음수가 아니다


def test_a_period_the_weather_does_not_cover_gets_no_factor():
    got = weather.growth_factor(obs(), crops.get("lettuce"),
                                "2020-01-01", "2020-01-10", "greenhouse", TODAY)
    assert got["factor"] == 1.0 and "못 덮어" in got["why"], got


# ── 기존 계산에 먹이기 ────────────────────────────────────────────────────
def test_watering_is_unchanged_when_no_weather_is_passed():
    """네 번째 인자를 안 주면 예전과 한 톨도 안 달라야 한다."""
    plant = {"crop": "lettuce", "soil": "일반"}
    before, why = watering.plan_interval(plant, TODAY)
    after, _ = watering.plan_interval(plant, TODAY, None, 0.0)
    assert before == after, (before, after)
    assert "날씨" not in why, why


def test_the_weather_correction_lands_in_the_interval_and_the_reason():
    plant = {"crop": "lettuce"}
    plain, _ = watering.plan_interval(plant, TODAY)
    moved, why = watering.plan_interval(plant, TODAY, None, 1.5)
    assert moved == plain + 1.5, (moved, plain)
    assert "날씨" in why, why


def test_the_soil_choice_and_the_weather_stack():
    """흙 상태는 그 화분의 성질이고 날씨는 바깥 사정이라 서로 대체하지 않는다.

    간격이 넉넉한 프로필로 잰다 — 여름 상추(2일)로는 최소 간격 1일에 먼저 걸려서
    두 보정이 겹치는지가 안 보인다.
    """
    prof = {"source": "테스트", "base_interval_days": 8}
    plain = watering.plan_interval({"soil": "일반"}, TODAY, prof)[0]
    dry_soil = watering.plan_interval({"soil": "건조"}, TODAY, prof)[0]
    both = watering.plan_interval({"soil": "건조"}, TODAY, prof, -1.5)[0]
    assert dry_soil == plain - 1, (dry_soil, plain)
    assert both == dry_soil - 1.5, (both, dry_soil)


def test_the_interval_never_falls_below_the_floor():
    """여름 상추처럼 이미 짧은 간격은 날씨로도 하루 밑으로 못 내려간다."""
    got = watering.plan_interval({"crop": "lettuce", "soil": "건조"}, TODAY, None, -5.0)[0]
    assert got == watering.MIN_INTERVAL, got


def test_the_calendar_and_the_modal_get_the_same_correction():
    """한쪽만 보정받으면 모달과 달력이 서로 다른 날짜를 말한다."""
    plant = {"crop": "lettuce", "water_log": ["2026-08-08"], "last_watered": "2026-08-08"}
    rec = watering.recommend(dict(plant), TODAY, None, 2.0)
    due = watering.upcoming([dict(plant)], "2026-08", TODAY, None, 2.0)
    assert rec["next_water"] in due, (rec, due)


def test_harvest_is_unchanged_at_factor_one():
    plant = {"crop": "lettuce", "growth_log": growth_log([(12, 8.0, 4), (8, 10.0, 6),
                                                          (4, 12.0, 8), (0, 14.0, 10)])}
    plain = harvest.forecast(plant, TODAY)
    same = harvest.forecast(plant, TODAY, 1.0)
    assert plain["days_until"] == same["days_until"], (plain, same)
    assert "날씨" not in plain["why"], plain


def test_a_warm_forecast_brings_the_harvest_closer():
    plant = {"crop": "lettuce", "growth_log": growth_log([(12, 8.0, 4), (8, 10.0, 6),
                                                          (4, 12.0, 8), (0, 14.0, 10)])}
    plain = harvest.forecast(plant, TODAY)
    warm = harvest.forecast(plant, TODAY, 1.4)
    assert warm["days_until"] < plain["days_until"], (warm, plain)
    assert warm["days_without_weather"] == plain["days_until"], warm
    assert "당김" in warm["why"], warm


def test_the_weather_cannot_manufacture_a_harvest_date():
    """원래 '너무 멀다' 로 거절됐을 화분이 날씨 덕에 통과하면 규칙 우회다."""
    crawling = {"crop": "tomato", "growth_log": growth_log([(40, 8.0, 3), (0, 8.4, 4)])}
    assert harvest.forecast(crawling, TODAY)["ready_on"] is None
    assert harvest.forecast(crawling, TODAY, 1.6)["ready_on"] is None


def test_the_weather_cannot_revive_a_plant_that_stopped_growing():
    stalled = {"crop": "lettuce", "growth_log": growth_log([(10, 14.0, 8), (0, 12.0, 7)])}
    got = harvest.forecast(stalled, TODAY, 1.6)
    assert got["ready_on"] is None and "안 커지고" in got["why"], got


# ── 기상청 격자 변환 ──────────────────────────────────────────────────────
def test_the_kma_grid_matches_the_official_example():
    """활용가이드의 검증값 — 126.929810, 37.488201 → (59, 125)."""
    assert weather_kma.to_grid(37.488201, 126.929810) == (59, 125)


def test_well_known_cities_land_on_their_grids():
    assert weather_kma.to_grid(37.5665, 126.9780) == (60, 127)     # 서울시청
    assert weather_kma.to_grid(35.1796, 129.0756) == (98, 76)      # 부산시청


def test_the_forecast_base_time_falls_back_over_midnight():
    """00:00~02:09 에는 당일 0200 발표가 아직 없다 — 전날 2300 으로 돌아가야 한다."""
    assert weather_kma.fcst_base(datetime(2026, 8, 10, 1, 0)) == ("20260809", "2300")
    assert weather_kma.fcst_base(datetime(2026, 8, 10, 2, 5)) == ("20260809", "2300")
    assert weather_kma.fcst_base(datetime(2026, 8, 10, 2, 20)) == ("20260810", "0200")
    assert weather_kma.fcst_base(datetime(2026, 8, 10, 14, 30)) == ("20260810", "1400")


def test_the_current_base_time_waits_for_the_release():
    """정시 발표는 40분 이후에 나온다 — 그 전이면 이전 정시를 봐야 한다."""
    assert weather_kma.ncst_base(datetime(2026, 8, 10, 6, 10)) == ("20260810", "0500")
    assert weather_kma.ncst_base(datetime(2026, 8, 10, 6, 50)) == ("20260810", "0600")


def test_korean_rain_categories_are_read_not_crashed():
    """'강수없음' 같은 한글 범주가 온다 — float() 로 바로 캐스팅하면 비 오는 날 터진다."""
    assert weather_kma._num("강수없음") == 0.0
    assert weather_kma._num("1.0mm 미만") == 1.0
    assert weather_kma._num("30.0~50.0mm") == 30.0
    assert weather_kma._num("12.5") == 12.5
    assert weather_kma._num(None) is None
    assert weather_kma._num(-999) is None        # 결측 마스킹


# ── 엔드포인트 ────────────────────────────────────────────────────────────
def _set_site(**kw):
    args = {"lat": None, "lon": None, "site": None, "name": None}
    args.update(kw)
    import asyncio
    return asyncio.run(main.set_site(**args))


def test_the_app_starts_with_no_location_and_weather_off():
    _reset()
    got = main.get_site()
    assert got["configured"] is False, got
    assert got["site"] == "indoor", got
    assert main.get_weather()["configured"] is False


def test_setting_the_site_without_coordinates_keeps_weather_off():
    _reset()
    got = _set_site(site="greenhouse")
    assert got["site"] == "greenhouse" and got["configured"] is False, got
    assert main._water_weather_days() == 0.0


def test_a_bad_site_is_refused():
    _reset()
    from fastapi import HTTPException
    try:
        _set_site(site="옥상")
    except HTTPException as e:
        assert e.status_code == 400, e
    else:
        raise AssertionError("모르는 재배 환경이 통과했다")


def test_bad_coordinates_are_refused():
    _reset()
    from fastapi import HTTPException
    for lat, lon in (("999", "127"), ("37", "글자")):
        try:
            _set_site(lat=lat, lon=lon)
        except HTTPException as e:
            assert e.status_code == 400, e
        else:
            raise AssertionError(f"이상한 좌표가 통과했다: {lat},{lon}")


def test_clearing_the_site_turns_the_weather_back_off():
    _reset()
    main.SITE.update({"lat": 37.5, "lon": 127.0, "site": "greenhouse"})
    main.WEATHER.update(obs())
    got = main.clear_site()
    assert got["configured"] is False and not main.WEATHER, got


def test_the_stored_weather_feeds_the_watering_correction():
    _reset()
    main.SITE.update({"lat": 37.5, "lon": 127.0, "site": "greenhouse"})
    main.WEATHER.update(obs(et0_recent=6.0, et0_normal=4.0))
    main.WEATHER["for"] = "37.5,127.0"
    assert main._water_weather_days() < 0, main.WEATHER.get("for")


def test_an_indoor_site_feeds_no_correction_even_with_weather_stored():
    _reset()
    main.SITE.update({"lat": 37.5, "lon": 127.0, "site": "indoor"})
    main.WEATHER.update(obs(et0_recent=9.0, et0_normal=3.0))
    main.WEATHER["for"] = "37.5,127.0"
    assert main._water_weather_days() == 0.0


def test_stale_weather_is_reported_not_hidden():
    old = obs()
    old["fetched_at"] = (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")
    assert weather.stale_hours(old) > 8
    assert weather.stale_hours({}) == float("inf")
    assert weather.stale_hours({"fetched_at": "말도안됨"}) == float("inf")


def test_the_site_survives_a_backup_round_trip():
    _reset()
    main.SITE.update({"lat": 37.5, "lon": 127.0, "site": "greenhouse", "name": "옥상"})
    saved = main.backup_payload()
    _reset()
    main.restore_payload(saved)
    assert main.SITE["site"] == "greenhouse" and main.SITE["lat"] == 37.5


def test_the_weather_cache_is_not_carried_in_backups():
    """복원한 순간 남의 지역 며칠 전 날씨가 '지금 날씨' 로 들어앉으면 안 된다."""
    assert "weather" not in {k for k, _ in main.BACKUP_PARTS}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
