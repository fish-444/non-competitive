"""작물 — 이 온실에 무엇이 심겨 있는가.

지금까지 앱은 **알로카시아 하나만 키운다**고 못 박혀 있었다. 물주기 간격(습생·거실),
크기 등급 기준치(캐노피 12/22cm), 필요 광량, 폭 대비 키 — 전부 알로카시아 수치가
상수로 박혀 있어서, 같은 선반에 상추를 한 포기 올리면

  · 물주기 예정일이 5일 뒤로 찍히고 (상추는 이틀이면 마른다)
  · 캐노피 15cm 짜리 다 큰 상추가 '중품' 으로 (알로카시아 기준이라)
  · 배치 최적화가 상추를 그늘로 보내도 점수가 안 깎였다 (필요 광량이 같아서)

셋 다 코드가 틀린 게 아니라 **어느 작물인지 몰라서** 나는 오차다. 그래서
화분마다 작물을 적고, 작물마다 다른 값을 여기 한곳에 모았다.

작물마다 다른 건 결국 네 가지다.

  1. 물을 얼마나 자주 주는가        `water`          → watering.recommend
  2. 얼마나 커야 큰 포기인가        `canopy_cm`/`leaf_cm` → main.grade_by_*
  3. 빛이 얼마나 필요한가           `light`          → placement._need_light
  4. 폭에 비해 얼마나 키가 큰가     `height_ratio`   → placement.plant_shape

탐지기는 안 건드린다. 로보플로우 워크플로는 알로카시아 잎·캐노피로 학습된
것이라 상추 사진에서 잎을 덜 잡을 수 있지만, 그건 모델을 바꿔야 하는 문제이지
작물 정보로 메울 수 있는 게 아니다. 여기서 정하는 건 **잡힌 박스를 어떻게
해석하는가**뿐이다.

⚠ 아래 수치는 원예 통념에서 잡은 **잠정값**이다(`provisional`). watering.py 의
DEFAULT_PROFILE 과 같은 처지 — 실제 재배 기록이 쌓이면 그 값으로 갈아야 한다.
알로카시아만은 예외로, 이미 쓰던 값(환경변수 포함)을 그대로 물려받는다.

의존성 0. placement.py 와 같은 이유다 — main 을 안 부르므로 어디서든 불러 쓸 수
있고, 테스트에서 FastAPI 없이 검사할 수 있다.
"""

import os

# 기본 작물. 이 저장소는 알로카시아 온실에서 출발했고, 이미 등록된 화분에는
# crop 필드가 없다 — 그것들이 전부 알로카시아로 읽혀야 기존 기록이 안 흔들린다.
DEFAULT = "alocasia"

# 알로카시아 등급 기준치는 예전부터 환경변수로 조절할 수 있었다. 작물별 값으로
# 옮기면서 그 통로를 막으면, 이미 자기 사진에 맞춰 값을 조정해 둔 사람의 등급이
# 통째로 바뀐다. 그래서 기본 작물만 환경변수를 계속 읽는다.
_LEAF_SMALL_CM = float(os.environ.get("LEAF_SMALL_CM", "8"))      # 이하 → 소품
_LEAF_LARGE_CM = float(os.environ.get("LEAF_LARGE_CM", "16"))     # 초과 → 대품
_CANOPY_SMALL_CM = float(os.environ.get("CANOPY_SMALL_CM", "12"))
_CANOPY_LARGE_CM = float(os.environ.get("CANOPY_LARGE_CM", "22"))


def _water(source: str, by_month: dict) -> dict:
    """달별 물주기 간격(일). watering.profile_interval 이 읽는 형식 그대로."""
    return {"source": source, "provisional": True,
            "base_interval_days": round(sum(by_month.values()) / 12, 1),
            "by_month": {str(m): d for m, d in sorted(by_month.items())}}


# --------------------------------------------------------------------------- 작물표
# 순서가 화면에 나오는 순서다. 관상(원래 키우던 것) → 잎채소 → 허브 → 열매채소.
#
# height_ratio 는 '잎우산 반지름 대비 키'다. 그늘 계산이 이걸로 누가 누구를
# 덮는지 정한다. 로제트로 낮게 퍼지는 상추(0.8)는 옆을 안 가리지만, 위로 서는
# 방울토마토(2.6)는 옆 화분을 통째로 그늘에 넣는다.
#
# radius_from 은 잎우산 반지름을 무엇에서 재느냐다.
#   "leaf"   — 잎 긴 변이 곧 반지름. 잎자루가 사방으로 뻗는 알로카시아가 그렇다.
#   "canopy" — 캐노피(포기 전체 폭)의 절반. 잎이 작고 가지가 벌어지는 작물은
#              잎 한 장 길이로 포기 폭을 잴 수 없어서 이쪽이 맞다.
# 알로카시아만 "leaf" 인 건 원래 그렇게 재고 있었기 때문이다 — 바꾸면 이미
# 나와 있는 배치 점수가 통째로 움직인다.
CROPS = {
    "alocasia": {
        "key": "alocasia", "name": "알로카시아", "kind": "관상",
        "canopy_cm": [_CANOPY_SMALL_CM, _CANOPY_LARGE_CM],
        "leaf_cm": [_LEAF_SMALL_CM, _LEAF_LARGE_CM],
        # 물주기는 water_profile.json(또는 watering.DEFAULT_PROFILE)이 이미
        # 알로카시아 기준(습생·거실)이다. 여기 또 적으면 두 벌이 갈라진다.
        "water": None,
        "light": 1.0,            # 기준점. 나머지 작물은 이 값의 배수다.
        "height_ratio": 2.2, "radius_from": "leaf",
        # 잎우산 반지름·키의 등급별 기본값. 실측이 없을 때만 쓴다.
        "grade_shape": {"소품": [7.0, 14.0], "중품": [13.0, 28.0], "대품": [20.0, 45.0]},
        "note": "숲 바닥에서 크는 관엽 — 직사광에 잎이 탄다",
    },
    "lettuce": {
        "key": "lettuce", "name": "상추", "kind": "잎채소",
        "canopy_cm": [10.0, 20.0], "leaf_cm": [6.0, 12.0],
        "water": _water("잠정값 (잎채소·실내선반)",
                        {1: 4, 2: 4, 3: 3, 4: 2, 5: 2, 6: 2,
                         7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 4}),
        "light": 1.3, "height_ratio": 0.8, "radius_from": "canopy",
        "note": "뿌리가 얕아 자주 마른다 · 낮게 퍼져 옆을 안 가린다",
    },
    "bokchoy": {
        "key": "bokchoy", "name": "청경채", "kind": "잎채소",
        "canopy_cm": [10.0, 20.0], "leaf_cm": [6.0, 12.0],
        "water": _water("잠정값 (잎채소·실내선반)",
                        {1: 4, 2: 4, 3: 3, 4: 2, 5: 2, 6: 2,
                         7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 4}),
        "light": 1.3, "height_ratio": 0.9, "radius_from": "canopy",
        "note": "상추와 같은 리듬 · 잎이 두꺼워 조금 덜 마른다",
    },
    "arugula": {
        "key": "arugula", "name": "루꼴라", "kind": "잎채소",
        "canopy_cm": [8.0, 16.0], "leaf_cm": [4.0, 8.0],
        "water": _water("잠정값 (잎채소·실내선반)",
                        {1: 4, 2: 4, 3: 3, 4: 3, 5: 2, 6: 2,
                         7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 4}),
        "light": 1.3, "height_ratio": 0.8, "radius_from": "canopy",
        "note": "포기가 작아 등급 기준치도 작다",
    },
    "basil": {
        "key": "basil", "name": "바질", "kind": "허브",
        "canopy_cm": [10.0, 20.0], "leaf_cm": [3.0, 6.0],
        "water": _water("잠정값 (허브·실내선반)",
                        {1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 2,
                         7: 2, 8: 2, 9: 3, 10: 3, 11: 4, 12: 5}),
        "light": 1.5, "height_ratio": 1.4, "radius_from": "canopy",
        "note": "잎은 작은데 포기는 넓게 벌어진다 — 캐노피로 재야 맞는다",
    },
    "strawberry": {
        "key": "strawberry", "name": "딸기", "kind": "열매채소",
        "canopy_cm": [12.0, 22.0], "leaf_cm": [5.0, 9.0],
        "water": _water("잠정값 (열매채소·실내선반)",
                        {1: 5, 2: 5, 3: 4, 4: 3, 5: 3, 6: 2,
                         7: 2, 8: 2, 9: 3, 10: 4, 11: 4, 12: 5}),
        "light": 1.6, "height_ratio": 0.9, "radius_from": "canopy",
        "note": "열매를 달려면 빛이 많이 필요하다 · 키는 안 큰다",
    },
    "tomato": {
        "key": "tomato", "name": "방울토마토", "kind": "열매채소",
        "canopy_cm": [14.0, 28.0], "leaf_cm": [5.0, 10.0],
        "water": _water("잠정값 (열매채소·실내선반)",
                        {1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 2,
                         7: 2, 8: 2, 9: 3, 10: 3, 11: 4, 12: 5}),
        "light": 1.8, "height_ratio": 2.6, "radius_from": "canopy",
        "note": "이 선반에서 제일 빛을 많이 먹고, 옆 화분을 가장 크게 가린다",
    },
    "pepper": {
        "key": "pepper", "name": "고추", "kind": "열매채소",
        "canopy_cm": [12.0, 24.0], "leaf_cm": [5.0, 9.0],
        "water": _water("잠정값 (열매채소·실내선반)",
                        {1: 6, 2: 6, 3: 5, 4: 4, 5: 3, 6: 2,
                         7: 2, 8: 2, 9: 3, 10: 4, 11: 5, 12: 6}),
        "light": 1.7, "height_ratio": 2.0, "radius_from": "canopy",
        "note": "토마토보다 물을 덜 먹지만 빛은 비슷하게 필요하다",
    },
}

KEYS = tuple(CROPS)


def get(key=None) -> dict:
    """작물 프로필. 모르는 키·빈 값이면 기본 작물(알로카시아).

    모르는 키를 막지 않고 기본값으로 접는 건, 이 함수가 **읽는 쪽 전부**에서
    불리기 때문이다. 옛 farm.db 나 손으로 고친 백업에 이상한 값이 하나 섞였다고
    목록 조회가 500 으로 떨어지면 안 된다. 값을 **받는** 자리(POST/PATCH)에서는
    is_known() 으로 따로 막는다.
    """
    if isinstance(key, str):
        found = CROPS.get(key)
        if found:
            return found
    return CROPS[DEFAULT]


def is_known(key) -> bool:
    """사람이 보낸 작물 키가 표에 있는가 — 입력 검증용."""
    return isinstance(key, str) and key in CROPS


def key_of(plant: dict) -> str:
    """그 화분의 작물 키. 안 적혀 있으면 기본 작물."""
    key = (plant or {}).get("crop")
    return key if is_known(key) else DEFAULT


def of(plant: dict) -> dict:
    """그 화분의 작물 프로필."""
    return get(key_of(plant))


def name_of(plant: dict) -> str:
    return of(plant)["name"]


def listing() -> list:
    """화면에 뿌릴 작물 목록. 고르는 데 필요한 것만 담는다."""
    return [{"key": c["key"], "name": c["name"], "kind": c["kind"],
             "note": c["note"],
             "canopy_cm": list(c["canopy_cm"]),
             "light": c["light"],
             "interval_days": (c["water"] or {}).get("base_interval_days")}
            for c in CROPS.values()]


# --------------------------------------------------------------------------- 등급
def _grade(cm: float, small_cm: float, large_cm: float) -> str:
    if cm <= small_cm:
        return "소품"
    return "중품" if cm <= large_cm else "대품"


def canopy_grade(canopy_cm: float, key=None) -> str:
    """캐노피(포기 전체 폭) 긴 변 → 크기 등급. 기준치는 작물마다 다르다."""
    small_cm, large_cm = get(key)["canopy_cm"]
    return _grade(canopy_cm, small_cm, large_cm)


def leaf_grade(leaf_cm: float, key=None) -> str:
    """가장 큰 잎의 긴 변 → 크기 등급. 캐노피를 못 잡았을 때 쓴다."""
    small_cm, large_cm = get(key)["leaf_cm"]
    return _grade(leaf_cm, small_cm, large_cm)
