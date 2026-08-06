"""다음 물주기가 언제인지 — 달력에 예정일을 찍기 위한 계산.

지금까지 물주기는 '준 날을 적는 것'뿐이었고, 판단이라곤 WATER_DRY_DAYS(기본 3일)
하나를 넘겼는지 보는 게 전부였다. 그 3이라는 숫자에는 근거가 없다.

계산은 두 줄이면 끝난다.

    간격     = 프로필(그 달) + 흙 상태 보정(-1 / 0 / +1)
    예정일   = 마지막으로 준 날 + 간격

**기준은 프로필**(관수 데이터에서 뽑은 그 달의 값)이고, 화분마다 흙이 마르는
속도가 다른 것은 하루씩 당기거나 미뤄서 맞춘다. 화분 크기·흙 배합·놓인 자리에
따라 실제로 하루 정도씩 갈리는데, 그걸 사람이 보고 고르는 게 제일 정확하다.

예정일은 **마지막으로 준 날**에서만 센다. 과거 기록 전체를 평균 내지 않는다 —
지난달에 며칠 간격으로 줬든, 다음에 언제 줘야 하는지는 마지막으로 준 날이
기준이어야 한다.

형이 실제로 준 간격은 계산에 넣지 않고 **비교용으로 보여만 준다**. 프로필과
많이 다르면 프로필을 고치거나 흙 상태를 바꾸라는 신호다.
"""

import json
import os
import statistics
from datetime import date, timedelta
from typing import List

# 흙이 마르는 속도 — 화분마다 다르다. 프로필 값에서 며칠을 더하거나 뺄지.
# 데이터셋이 관수 환경을 건조/일반/과습으로 나눈 것과 같은 이름을 쓴다.
SOIL_ADJUST = {"건조": -1, "일반": 0, "과습": +1}
SOIL_DEFAULT = "일반"
SOIL_LABEL = {"건조": "빨리 마름", "일반": "보통", "과습": "잘 안 마름"}

# 프로필도 기록도 없을 때 쓸 최후의 값.
# main.WATER_DRY_DAYS 의 기본값과 일부러 같게 뒀다. 이 기능을 켠다고 기존 마름
# 판정이 하루 밀리면 안 된다 — 새로 들어온 건 '예정일' 이지 '기준' 이 아니다.
FALLBACK_DAYS = float(os.environ.get("WATER_FALLBACK_DAYS",
                                     os.environ.get("WATER_DRY_DAYS", "3")))

# 외부 자료로 만든 프로필 파일. 없으면 DEFAULT_PROFILE 로 돈다.
PROFILE_PATH = os.environ.get("WATER_PROFILE", "water_profile.json")

# 알로카시아는 **습생(수분을 좋아하는 무리)** 이고, 두는 곳은 **거실** 기준이다.
# 베란다는 바깥 기온·바람을 그대로 받아 훨씬 빨리 마르므로 값이 다르다.
#
# ⚠ 아래 달별 값은 원예 통념에서 잡은 **잠정값**이지 데이터셋에서 뽑은 수치가
#   아니다. AI Hub '원예식물(화분류) 물주기 생육 데이터' 에서 습생·거실 조건의
#   실제 관수 간격을 계산해 water_profile.json 으로 덮어쓰면 이 값은 안 쓰인다.
#   화분마다 다른 부분은 흙 상태(건조/일반/과습)로 하루씩 맞춘다.
DEFAULT_PROFILE = {
    "source": "잠정값 (습생·거실)",
    "provisional": True,
    "group": "습생",
    "place": "거실",
    "base_interval_days": 5,
    # 여름엔 빨리 마르고 자라느라 물을 더 쓴다. 겨울엔 생장이 멎어 훨씬 천천히 마른다.
    "by_month": {"1": 8, "2": 8, "3": 6, "4": 5, "5": 4, "6": 3,
                 "7": 3, "8": 3, "9": 4, "10": 5, "11": 6, "12": 8},
}

# 사람이 준 간격이라 해도 이 범위를 벗어나면 오타나 몰아서 적은 기록으로 본다.
MIN_INTERVAL, MAX_INTERVAL = 1.0, 30.0


def _load_profile() -> dict:
    """물주기 프로필을 읽는다. 없으면 빈 dict — 그때는 기본값으로 돈다.

    형식(직접 만들거나 외부 데이터셋에서 뽑아 채운다):

        {"source": "어디서 온 값인지",
         "base_interval_days": 4,
         "by_month": {"1": 7, "7": 3, "8": 3}}

    by_month 는 있는 달만 적으면 되고, 없는 달은 base_interval_days 를 쓴다.
    계절에 따라 물 마르는 속도가 몇 배씩 달라지므로 달별 값이 있으면 훨씬 낫다.
    """
    try:
        with open(PROFILE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_PROFILE)
    return data if isinstance(data, dict) else dict(DEFAULT_PROFILE)


PROFILE = _load_profile()


def profile_interval(when: date, profile: dict = None) -> float:
    """그 달에 프로필이 말하는 간격(일)."""
    p = PROFILE if profile is None else profile
    by_month = p.get("by_month") or {}
    for key in (str(when.month), f"{when.month:02d}"):
        try:
            v = float(by_month[key])
            if v > 0:
                return v
        except (KeyError, TypeError, ValueError):
            continue
    try:
        v = float(p.get("base_interval_days"))
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return FALLBACK_DAYS


def own_intervals(log: List[str]) -> List[float]:
    """물 준 날짜 목록 → 연속한 두 날 사이의 간격들.

    같은 날 두 번 적힌 것(간격 0)과 터무니없이 긴 간격은 뺀다. 후자는 보통
    한동안 안 적다가 몰아서 적은 경우라, 진짜 물주기 리듬이 아니다.
    """
    # 문자열 아닌 값이 섞이면 정렬부터 터진다 — 날짜로 읽히는 것만 남긴다.
    days = []
    for s in sorted({x for x in (log or []) if isinstance(x, str)}):
        try:
            days.append(date.fromisoformat(s))
        except (TypeError, ValueError):
            continue
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return [float(g) for g in gaps if MIN_INTERVAL <= g <= MAX_INTERVAL]


def soil_of(plant: dict) -> str:
    """그 화분에 지정된 흙 상태. 안 골랐으면 '일반'."""
    v = (plant or {}).get("soil")
    return v if v in SOIL_ADJUST else SOIL_DEFAULT


def plan_interval(plant: dict, when: date, profile: dict = None) -> tuple:
    """(간격, 근거설명) — 프로필에 흙 상태만큼 더하거나 뺀다."""
    prof = profile_interval(when, profile)
    soil = soil_of(plant)
    adj = SOIL_ADJUST[soil]
    interval = max(MIN_INTERVAL, min(MAX_INTERVAL, prof + adj))

    src = (PROFILE if profile is None else profile).get("source") or "기본값"
    why = f"{src} {prof:.0f}일"
    if adj:
        why += f" {adj:+d}일 (흙 {soil}·{SOIL_LABEL[soil]})"
    return interval, why


def recommend(plant: dict, today: date = None, profile: dict = None) -> dict:
    """다음에 물 줄 날. 기록이 하나도 없으면 예정일을 만들지 않는다.

    한 번도 안 준 포기에 '오늘부터 4일 뒤' 라고 찍으면 근거 없는 날짜가 달력에
    박힌다. 마지막으로 준 날이 있어야 거기서부터 셀 수 있다.
    """
    today = today or date.today()
    log = plant.get("water_log") or []
    last = plant.get("last_watered")
    interval, why = plan_interval(plant, today, profile)

    # 형이 실제로 준 간격 — 계산에는 안 쓰고 비교용으로만 얹는다.
    gaps = own_intervals(log)
    own = round(statistics.median(gaps), 1) if gaps else None

    out = {"interval_days": round(interval, 1), "basis": why,
           "soil": soil_of(plant), "own_interval_days": own,
           "next_water": None, "days_until": None, "overdue": False}
    if not last:
        return out
    try:
        base = date.fromisoformat(last)
    except (TypeError, ValueError):
        return out

    nxt = base + timedelta(days=round(interval))
    out["next_water"] = nxt.isoformat()
    out["days_until"] = (nxt - today).days
    out["overdue"] = nxt < today
    return out


def upcoming(plants, month: str, today: date = None, profile: dict = None) -> dict:
    """그 달(YYYY-MM)에 물 줄 예정인 날짜 → 화분 수. 달력에 옅게 찍는 데 쓴다.

    이미 지난 예정일은 넣지 않는다 — 지난 날짜 칸에는 '실제로 준 기록' 만
    보여야 한다. 안 그러면 준 것과 줬어야 했던 것이 섞여 읽힌다.
    """
    today = today or date.today()
    due: dict = {}
    for p in plants:
        r = recommend(p, today, profile)
        d = r["next_water"]
        if d and d.startswith(month) and d >= today.isoformat():
            due[d] = due.get(d, 0) + 1
    return due
