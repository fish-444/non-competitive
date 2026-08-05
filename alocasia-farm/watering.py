"""다음 물주기가 언제인지 — 달력에 예정일을 찍기 위한 계산.

지금까지 물주기는 '준 날을 적는 것'뿐이었고, 판단이라곤 WATER_DRY_DAYS(기본 3일)
하나를 넘겼는지 보는 게 전부였다. 그 3이라는 숫자에는 근거가 없다.

여기서는 두 가지를 섞는다.

  1. **형이 실제로 준 간격** — 이 온실, 이 포기의 진짜 리듬이다. 가장 믿을 만하다.
     다만 기록이 적을 때는 우연에 휘둘린다(두 번 준 게 마침 8일 간격이면 8일이
     되어 버린다).
  2. **품종·계절 프로필** — 외부 자료에서 온 '보통 이 정도' 값. 기록이 없을 때
     기댈 곳이고, 기록이 적을 때 극단으로 튀는 걸 잡아 준다.

둘을 어떻게 섞느냐가 핵심이다. 기록 수 n 이 늘수록 형의 리듬 쪽으로 옮겨간다:

    간격 = (n × 내_중앙값 + PRIOR × 프로필) / (n + PRIOR)

기록이 0이면 순수하게 프로필, 기록이 쌓이면 프로필의 영향이 자연히 사라진다.
"어느 쪽을 쓸까" 를 고르는 대신 저울질하게 만든 것이라, 자료가 늘어도 코드를
안 고쳐도 된다.
"""

import json
import os
import statistics
from datetime import date, timedelta
from typing import List, Optional

# 프로필을 얼마나 세게 믿을지. 이 숫자만큼의 '가상 기록'으로 친다.
# 3 이면 실제로 세 번 준 시점에 내 기록과 프로필이 반반이 된다.
PRIOR_STRENGTH = float(os.environ.get("WATER_PRIOR", "3"))

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
#   어차피 기록이 몇 번 쌓이면 형의 실제 리듬 쪽으로 옮겨가므로(blended_interval),
#   이 값이 정확하지 않아도 시간이 지나면 영향이 사라진다.
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


def blended_interval(log: List[str], when: date, profile: dict = None) -> tuple:
    """(간격, 근거설명) — 내 기록과 프로필을 기록 수로 저울질해 섞는다."""
    prof = profile_interval(when, profile)
    gaps = own_intervals(log)
    if not gaps:
        src = (PROFILE if profile is None else profile).get("source")
        return prof, (f"{src} 기준" if src else "기본값")

    mine = statistics.median(gaps)
    n = len(gaps)
    mixed = (n * mine + PRIOR_STRENGTH * prof) / (n + PRIOR_STRENGTH)
    if n >= 6:
        why = f"내 기록 {n}회 (중앙값 {mine:.0f}일)"
    else:
        why = f"내 기록 {n}회 (중앙값 {mine:.0f}일) + 프로필 {prof:.0f}일"
    return mixed, why


def recommend(plant: dict, today: date = None, profile: dict = None) -> dict:
    """다음에 물 줄 날. 기록이 하나도 없으면 예정일을 만들지 않는다.

    한 번도 안 준 포기에 '오늘부터 4일 뒤' 라고 찍으면 근거 없는 날짜가 달력에
    박힌다. 마지막으로 준 날이 있어야 거기서부터 셀 수 있다.
    """
    today = today or date.today()
    log = plant.get("water_log") or []
    last = plant.get("last_watered")
    interval, why = blended_interval(log, today, profile)
    interval = max(MIN_INTERVAL, min(MAX_INTERVAL, interval))

    out = {"interval_days": round(interval, 1), "basis": why,
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
