"""기상 — 바깥 날씨를 이 온실 안의 판단으로 옮기는 층.

알로카시아 쪽은 **날씨를 일부러 안 봤다.** main.py 에 근거까지 적혀 있다 —
거실 선반은 냉난방이 걸려서 바깥 기온이 잘 안 넘어오고, 여름 기준 일수만 맞으면
충분하다는 판단이었다. 작물 온실은 그 전제가 다르다. 비닐하우스는 바깥 기온이
거의 그대로 들어오고, 베란다는 그 중간이다.

그래서 **얼마나 반영할지를 앱이 몰래 정하지 않는다.** 사용자가 재배 환경을
고르면 그 값(`외기 반영 계수`)만큼만 보정한다. 기본값은 `실내` 이고 계수는 0 이라,
설정을 안 건드리면 지금까지와 **완전히 똑같이** 동작한다.

왜 이렇게까지 조심하는가 — 실내는 바깥과 상관이 약하다는 근거가 여럿이다.
에어컨을 쓰는 주택 46가구에서 실내외 기온 상관은 평균 r=0.42 였고 가구별로
부호까지 갈렸다(−0.24 ~ 0.92). 서울 주거 1년 측정에서 실내 습도는 바깥 습도와
상관이 없었다. 그런 관계 위에 단일 계수를 코드에 박으면 상당수 사용자에게
계통오차가 된다. 계수를 사람이 선언하게 하는 게 정직하다.

두 가지를 계산한다.

  1. 물주기 보정   `water_adjust_days`   — 요즘이 그 계절 평년보다 얼마나
                                          메마른가(ET0 편차) → ±일
  2. 생장 보정     `growth_factor`       — 앞으로 올 날씨가 지금까지 잰 기간보다
                                          얼마나 따뜻한가 → 수확적기 배율

**둘 다 '편차' 로 쓴다. 절대값으로 쓰지 않는다.** 이게 이 파일에서 제일 중요한
결정이다.

  · 물주기: 작물별 달별 간격(`crops.py` 의 by_month)이 이미 계절성을 담고 있다.
    실제로 서울의 달별 ET0 와 그 표의 상관이 r≈0.95 다. 여기에 ET0 절대값을 또
    곱하면 계절을 두 번 세는 것이다. 그래서 **평년 대비 편차**만 얹는다.
  · 수확: `harvest.trend` 의 하루 증가량은 **그 온실에서 실제로 찍은 사진**의
    기울기라, 그동안 겪은 온도가 이미 들어 있다. 거기에 적산온도를 곱하면 역시
    두 번이다. 그래서 **잰 기간의 날씨 대비 앞으로 올 날씨의 비율**만 쓴다.

안 쓰는 것도 분명히 해 둔다.

  · **강수** — 지붕 아래 화분에는 비가 한 방울도 안 떨어진다. '어제 비 왔으니
    물주기 미룸' 은 대부분의 관수 서비스가 기본으로 하는 계산인데, 여기서는
    장마철 내내 물을 밀어 화분을 말리는 규칙이 된다. 노지에서만 본다.
  · **바깥 토양수분·지온** — 노지 격자의 흙 값이지 화분 상토가 아니다. 화분은
    부피가 작고 근권이 막혀 있어 마르는 속도가 아예 다르다. 화면에 참고로
    보여 주기만 하고 물주기 계산에는 안 넣는다(노지 재배는 예외).
  · **일사·풍속** — 실내 광량은 placement.py 가 다루는 조명이 정하고, 실내
    공기는 정지해 있다. 바깥 값과 인과 관계가 없다.

의존성 0. crops·watering·harvest 와 같은 이유로 네트워크도 안 탄다 — 받아 오는
일은 providers 가 하고, 여기서는 **받아 온 숫자를 해석**만 한다.
"""

import os
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------- 재배 환경
# 바깥 날씨가 이 화분까지 얼마나 넘어오는가. 이 계수 하나가 아래 보정 전체의
# 세기를 정한다. 0 이면 기상 데이터를 받아 와도 계산은 지금과 똑같다.
#
# `rain` 은 화분이 비를 맞는가다 — 지붕이 있으면 강수는 무관 변수다.
SITES = {
    "indoor": {"key": "indoor", "name": "실내 (냉난방)", "coupling": 0.0, "rain": False,
               "note": "거실·방 선반. 바깥 날씨가 거의 안 넘어옵니다 — 반영하지 않아요"},
    "veranda": {"key": "veranda", "name": "베란다·창가", "coupling": 0.45, "rain": False,
                "note": "바깥 기온을 절반쯤 따라갑니다. 비는 안 맞아요"},
    "greenhouse": {"key": "greenhouse", "name": "비닐하우스·유리온실", "coupling": 0.8,
                   "rain": False,
                   "note": "바깥 기온이 거의 그대로 들어옵니다. 비는 지붕이 막아요"},
    "outdoor": {"key": "outdoor", "name": "노지 (한데)", "coupling": 1.0, "rain": True,
                "note": "바깥 날씨를 그대로 받습니다. 비가 오면 물주기를 미뤄요"},
}
SITE_DEFAULT = "indoor"          # 설정을 안 건드리면 예전 그대로

# 보정의 최대 폭. 근거가 편차 하나뿐인 계산이라 크게 흔들면 안 된다.
# 흙 상태 보정(±1일)과 같은 크기로 잡았다 — 사람이 고른 값보다 세지 않게.
MAX_WATER_ADJUST = float(os.environ.get("WEATHER_MAX_ADJUST_DAYS", "2"))

# 생장 배율의 한계. 날씨가 아무리 좋아도 두 배로 크지는 않고, 이 배율로 원래
# 안 나왔을 날짜를 만들어 내면 안 된다.
GROWTH_FACTOR_MIN, GROWTH_FACTOR_MAX = 0.6, 1.6

# 평년 대비 편차를 볼 때 '요즘' 의 길이(일).
RECENT_DAYS = 7

# 기저온도(°C) — 이 온도 아래에서는 사실상 안 자란다고 본다. 작물군별 통념값이다.
# 정확한 작물별 값은 문헌마다 갈리고(계산법도 °F/단일사인 등으로 다르다), 여기서는
# 그 차이가 배율 하나에 묻히는 수준이라 세 갈래로만 나눴다.
BASE_TEMP_C = {"잎채소": 4.0, "허브": 10.0, "열매채소": 10.0, "관상": 10.0}
BASE_TEMP_DEFAULT = 8.0


def site(key=None) -> dict:
    """재배 환경. 모르는 값이면 기본(실내) — 조회가 터지면 안 된다."""
    if isinstance(key, str):
        found = SITES.get(key)
        if found:
            return found
    return SITES[SITE_DEFAULT]


def is_known_site(key) -> bool:
    return isinstance(key, str) and key in SITES


def listing() -> list:
    """화면에 뿌릴 재배 환경 목록."""
    return [{"key": s["key"], "name": s["name"], "note": s["note"],
             "coupling": s["coupling"], "rain": s["rain"]} for s in SITES.values()]


# --------------------------------------------------------------------------- 관측 읽기
def _nums(values) -> list:
    out = []
    for v in values or []:
        try:
            if v is None:
                continue
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _mean(values):
    got = _nums(values)
    return sum(got) / len(got) if got else None


def daily_series(obs: dict, field: str) -> list:
    """관측 dict 의 일별 값 목록. 제공자가 무엇이든 모양은 같다.

    obs = {"daily": [{"on": "2026-08-10", "t_max": .., "t_min": .., "et0": ..,
                      "rain_mm": ..}, ...], ...}
    """
    out = []
    for row in (obs or {}).get("daily") or []:
        if not isinstance(row, dict):
            continue
        val, on = row.get(field), row.get("on")
        if val is None or not isinstance(on, str):
            continue
        try:
            out.append((date.fromisoformat(on), float(val)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda t: t[0])
    return out


def _window(series: list, start: date, end: date) -> list:
    return [v for d, v in series if start <= d <= end]


def gdd(t_max, t_min, base_c: float) -> float:
    """하루치 적산온도. 단순평균법 — (최고+최저)/2 − 기저온도, 음수는 0.

    단일사인법 같은 정교한 방식도 있지만, 여기서 쓰는 건 **두 기간의 비율**이라
    방식이 달라도 분자·분모에서 상당 부분 상쇄된다. 대신 계산법을 섞지는 않는다.
    """
    if t_max is None or t_min is None:
        return 0.0
    return max(0.0, (float(t_max) + float(t_min)) / 2 - base_c)


def base_temp_of(crop_profile: dict) -> float:
    """그 작물의 기저온도. 작물군(잎채소/허브/열매채소)으로 고른다."""
    kind = (crop_profile or {}).get("kind")
    return BASE_TEMP_C.get(kind, BASE_TEMP_DEFAULT)


# --------------------------------------------------------------------------- 물주기 보정
def water_adjust_days(obs: dict, site_key=None, today: date = None) -> dict:
    """요즘 날씨가 평년보다 메마른 만큼 물주기 간격을 당긴다(음수) / 미룬다(양수).

    기준은 **그 지역의 평년이 아니라 최근 한 달**이다. 진짜 평년값(30년 기후값)을
    받아 오려면 제공자마다 다른 통계 API 를 또 붙여야 하는데, 우리가 답하려는 건
    '지금이 이 계절치고 유난한가' 이므로 최근 한 달이면 충분하다. 작물표의 달별
    간격이 이미 '이 계절의 보통' 을 담고 있어서, 여기서는 그 위의 **편차**만 본다.

    돌려주는 `days` 는 watering.plan_interval 이 흙 상태 보정 옆에 더할 값이다.
    """
    conf = site(site_key)
    today = today or date.today()
    out = {"days": 0.0, "why": "", "site": conf["key"], "coupling": conf["coupling"],
           "et0_recent": None, "et0_normal": None, "rain_mm": None}
    if not obs or conf["coupling"] <= 0:
        # 실내 — 바깥 날씨를 안 본다. 데이터가 있어도 계산에 안 넣는다.
        out["why"] = ("실내라 바깥 날씨를 반영하지 않아요" if conf["coupling"] <= 0
                      else "기상 자료가 없어요")
        return out

    et0 = daily_series(obs, "et0")
    if len(et0) < RECENT_DAYS + 3:
        out["why"] = "기상 기록이 아직 모자라요"
        return out

    recent = _window(et0, today - timedelta(days=RECENT_DAYS - 1), today)
    normal = _window(et0, today - timedelta(days=30), today - timedelta(days=RECENT_DAYS))
    if len(recent) < 3 or len(normal) < 7:
        out["why"] = "기상 기록이 아직 모자라요"
        return out

    a, b = _mean(recent), _mean(normal)
    out["et0_recent"], out["et0_normal"] = round(a, 2), round(b, 2)
    if not b:
        out["why"] = "기상 기록이 아직 모자라요"
        return out

    # ET0 가 평년보다 20% 높으면 하루 당긴다 — 비율을 그대로 일수로 옮기지 않고
    # 완만하게 눌러 둔다. 근거가 편차 하나뿐인 계산이라 세게 흔들면 안 된다.
    ratio = a / b
    raw = -(ratio - 1.0) / 0.2
    days = raw * conf["coupling"]

    # 노지만 비를 센다. 지붕 아래 화분에는 비가 안 떨어진다.
    rained = None
    if conf["rain"]:
        rain = daily_series(obs, "rain_mm")
        got = _window(rain, today - timedelta(days=2), today)
        rained = round(sum(got), 1) if got else 0.0
        out["rain_mm"] = rained
        if rained >= 10:
            days += 1.0
        elif rained >= 3:
            days += 0.5

    days = max(-MAX_WATER_ADJUST, min(MAX_WATER_ADJUST, days))
    days = round(days * 2) / 2                    # 반나절 단위 — 그 이상은 못 믿는다
    out["days"] = days

    pct = round((ratio - 1.0) * 100)
    how = "메마름" if pct > 0 else ("눅눅함" if pct < 0 else "평년 수준")
    why = f"최근 {RECENT_DAYS}일 증발량이 지난달보다 {pct:+d}% ({how})"
    if conf["coupling"] < 1.0:
        why += f" · {conf['name']} 반영 {int(conf['coupling'] * 100)}%"
    if rained:
        why += f" · 최근 비 {rained}mm"
    out["why"] = why
    return out


# --------------------------------------------------------------------------- 생장 보정
def growth_factor(obs: dict, crop_profile: dict, measured_from: str, measured_to: str,
                  site_key=None, today: date = None) -> dict:
    """앞으로 올 날씨가 **잰 기간보다** 얼마나 자라기 좋은가 — 수확적기 배율.

    harvest 의 하루 증가량은 그 온실에서 실제로 찍은 사진의 기울기라, 그동안 겪은
    온도가 **이미 들어 있다**. 거기에 적산온도를 곱하면 온도를 두 번 세는 셈이다.
    그래서 절대값이 아니라 비율을 쓴다 — 추울 때 잰 기울기라면 따뜻해지는 만큼
    빨라지고, 그 반대도 마찬가지다.

    배율은 좁게 자른다(0.6~1.6). 이 값으로 원래 안 나왔을 날짜를 만들어 내면
    보정이 아니라 우회다.
    """
    conf = site(site_key)
    today = today or date.today()
    out = {"factor": 1.0, "why": "", "site": conf["key"], "coupling": conf["coupling"],
           "gdd_past": None, "gdd_ahead": None}
    if not obs or conf["coupling"] <= 0:
        out["why"] = ("실내라 바깥 날씨를 반영하지 않아요" if conf["coupling"] <= 0
                      else "기상 자료가 없어요")
        return out

    hi, lo = daily_series(obs, "t_max"), daily_series(obs, "t_min")
    if not hi or not lo:
        out["why"] = "기온 기록이 없어요"
        return out
    lows = dict(lo)
    base_c = base_temp_of(crop_profile)
    per_day = {d: gdd(v, lows[d], base_c) for d, v in hi if d in lows}

    try:
        start = date.fromisoformat(measured_from)
        end = date.fromisoformat(measured_to)
    except (TypeError, ValueError):
        out["why"] = "측정 기간을 알 수 없어요"
        return out

    past = [v for d, v in per_day.items() if start <= d <= end]
    ahead = [v for d, v in per_day.items() if d > today]
    if len(past) < 3 or len(ahead) < 3:
        out["why"] = "기온 기록이 그 기간을 못 덮어요"
        return out

    a, b = _mean(ahead), _mean(past)
    out["gdd_past"], out["gdd_ahead"] = round(b, 1), round(a, 1)
    if not b:
        out["why"] = "잰 기간이 너무 추워 비교할 수 없어요"
        return out

    # 계수만큼만 1.0 쪽으로 되돌린다 — 실내면 배율이 아예 1.0 이 된다.
    factor = 1.0 + (a / b - 1.0) * conf["coupling"]
    factor = max(GROWTH_FACTOR_MIN, min(GROWTH_FACTOR_MAX, factor))
    out["factor"] = round(factor, 3)

    pct = round((factor - 1.0) * 100)
    if pct == 0:
        out["why"] = f"앞으로 날씨가 잰 기간과 비슷해요 (기저 {base_c:.0f}°C)"
    else:
        out["why"] = (f"앞으로 {abs(pct)}% {'따뜻' if pct > 0 else '선선'}해요 — "
                      f"잰 기간 적산온도 {b:.1f} → 앞으로 {a:.1f} (기저 {base_c:.0f}°C)")
    if conf["coupling"] < 1.0:
        out["why"] += f" · {conf['name']} 반영 {int(conf['coupling'] * 100)}%"
    return out


# --------------------------------------------------------------------------- 지금 날씨
def now_summary(obs: dict, today: date = None) -> dict:
    """화면 맨 위에 한 줄로 띄울 '지금 바깥' — 계산에는 안 쓴다."""
    today = today or date.today()
    cur = (obs or {}).get("current") or {}
    hi = dict(daily_series(obs, "t_max")).get(today)
    lo = dict(daily_series(obs, "t_min")).get(today)
    return {"temp_c": cur.get("temp_c"), "humidity_pct": cur.get("humidity_pct"),
            "soil_moisture": cur.get("soil_moisture"), "soil_temp_c": cur.get("soil_temp_c"),
            "t_max": hi, "t_min": lo, "at": cur.get("at"),
            "source": (obs or {}).get("source"), "place": (obs or {}).get("place")}


def stale_hours(obs: dict, now: datetime = None) -> float:
    """받아 온 지 몇 시간 됐나. 오래된 값을 지금 날씨인 양 보여 주면 안 된다."""
    at = (obs or {}).get("fetched_at")
    if not isinstance(at, str):
        return float("inf")
    try:
        got = datetime.fromisoformat(at)
    except ValueError:
        return float("inf")
    now = now or datetime.now()
    return max(0.0, (now - got).total_seconds() / 3600)
