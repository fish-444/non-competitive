"""수확 — 언제 거둘 수 있고 얼마나 나오나.

이미 스캔할 때마다 개체별 측정 이력(`growth_log`)이 쌓이고 있었다. 지금까지는
그걸 모달에 꺾은선으로 그려 '얼마나 컸나'를 보여 주는 데만 썼는데, 같은 기록으로
앞을 볼 수 있다 — 자라는 속도를 알면 목표 크기까지 며칠 남았는지가 나온다.

    하루 증가량 = 지난 측정들의 기울기 (최소제곱)
    수확적기     = 오늘 + (목표 크기 − 지금 크기) / 하루 증가량
    생산량       = 그때의 잎 수 × 잎 한 장 무게   (잎을 따는 작물)

**왜 마지막 두 점의 차이가 아니라 기울기인가.** 탐지는 사진마다 들쭉날쭉하다.
잎이 가려져 캐노피가 1cm 작게 잡힌 날 하나가 마지막 점이면, 두 점 차이로는
'줄어들었다'가 되고 수확적기가 통째로 뒤집힌다. 여러 점에 선을 맞추면 그 한 번의
튐이 묻힌다. 그리고 얼마나 잘 맞는 선인지(r²)를 같이 낼 수 있어서, **믿을
만한 예측인지를 숫자로 말할 수 있다** — 이게 두 점 차이로는 안 되는 일이다.

이 파일이 지키는 선:

  · **기록이 모자라면 날짜를 만들지 않는다.** 점 두 개, 그것도 하루 이틀 사이면
    기울기가 아니라 잡음이다. 근거 없는 날짜를 달력에 박느니 '아직 모름'이 낫다.
  · **너무 먼 날짜는 안 찍는다.** 선형 외삽은 코앞에서만 쓸 만하다. 이 속도면
    반 년 뒤라는 계산이 나오면 그건 예측이 아니라 산수다(MAX_HORIZON_DAYS).
  · **안 자라면 안 자란다고 한다.** 기울기가 0 이하면 수확적기를 못 낸다. 그건
    실패가 아니라 신호다 — 빛이 모자라거나 물을 잘못 주고 있다는 뜻이니까.
  · **열매는 못 본다고 밝힌다.** 탐지기는 잎과 캐노피만 잡는다. 토마토 생산량은
    포기 크기로 에두른 추정이라 `rough` 로 표시해서 내보낸다. 잎채소는 잎 수를
    실제로 세고 있으므로 그 표시가 없다.

의존성은 crops 뿐이다. placement·watering 과 같은 이유 — main 을 안 부르므로
FastAPI 없이 테스트할 수 있다.
"""

import os
from datetime import date, timedelta

import crops

# 추세를 볼 창. 이보다 오래된 측정은 안 쓴다. 자라는 속도는 계절·포기 나이에 따라
# 달라져서, 석 달 전 봄에 쑥쑥 크던 기록까지 넣으면 지금 속도가 부풀려진다.
WINDOW_DAYS = int(os.environ.get("HARVEST_WINDOW_DAYS", "45"))

# 예측을 시작할 최소 조건. 점이 둘뿐이거나 하루 이틀 사이면 기울기가 아니라 잡음이다.
MIN_POINTS = 2
MIN_SPAN_DAYS = 3

# 이 너머는 날짜를 안 찍는다. 선형 외삽이 쓸 만한 거리의 한계다.
MAX_HORIZON_DAYS = int(os.environ.get("HARVEST_HORIZON_DAYS", "120"))

# 온실 전체 예상 생산량을 낼 때 기본으로 내다보는 기간.
FARM_WINDOW_DAYS = 30

CONFIDENCE = ("낮음", "보통", "높음")


# --------------------------------------------------------------------------- 추세
def points(growth_log, field: str) -> list:
    """이력에서 (날짜, 값) 만 골라 시간순으로. 못 읽는 줄은 조용히 버린다.

    이력은 farm.db 에서 그대로 올라온 값이라 무엇이든 들어 있을 수 있다 —
    캐노피를 못 잡은 날은 None 이고, 손으로 고친 백업에는 문자열이 섞이기도 한다.
    여기서 한 번 걸러 두면 아래 계산은 숫자만 본다.
    """
    out = []
    for row in growth_log or []:
        if not isinstance(row, dict):
            continue
        on, val = row.get("on"), row.get(field)
        if val is None or not isinstance(on, str):
            continue
        try:
            when = date.fromisoformat(on)
            out.append((when, float(val)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda t: t[0])
    return out


def _fit(pts: list) -> tuple:
    """(하루 증가량, r²) — 최소제곱 직선의 기울기.

    r² 는 '점들이 그 직선에 얼마나 붙어 있나'다. 1 에 가까우면 꾸준히 자란 것이고,
    0 에 가까우면 오르내리기만 한 것이라 기울기를 믿을 근거가 없다.
    """
    n = len(pts)
    base = pts[0][0]
    xs = [(when - base).days for when, _ in pts]
    ys = [val for _, val in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:                      # 전부 같은 날 — 기울기를 낼 수 없다
        return None, None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx
    # 값이 한 번도 안 변했으면(syy=0) 기울기 0 짜리 완벽한 직선이다.
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 1.0
    return slope, r2


def _confidence(n: int, span_days: int, r2: float) -> str:
    """이 추세를 얼마나 믿을 만한가 — 점 수·기간·직선 적합도를 함께 본다.

    셋 중 하나만 봐서는 안 된다. 점이 열 개라도 사흘 사이에 몰려 있으면 기울기가
    흔들리고, 기간이 길어도 점이 둘이면 그건 그냥 두 점 차이다.
    """
    if n >= 5 and span_days >= 14 and r2 >= 0.7:
        return "높음"
    if n >= 3 and span_days >= 7 and r2 >= 0.3:
        return "보통"
    return "낮음"


def trend(growth_log, field: str = "canopy_cm", today: date = None) -> dict:
    """생장 추세 — 하루에 얼마나 늘고 있나.

    `now` 는 마지막 측정에서 오늘까지 기울기만큼 밀어 둔 **오늘의 추정값**이다.
    지난주에 잰 값을 '지금 크기'로 쓰면 그 사이 자란 만큼이 통째로 빠진다.
    """
    today = today or date.today()
    pts = points(growth_log, field)
    if pts:
        cutoff = today - timedelta(days=WINDOW_DAYS)
        recent = [p for p in pts if p[0] >= cutoff]
        pts = recent if len(recent) >= MIN_POINTS else pts[-MIN_POINTS:]

    out = {"field": field, "points": len(pts), "per_day": None, "r2": None,
           "span_days": 0, "first_on": None, "last_on": None,
           "last": None, "now": None, "confidence": None}
    if not pts:
        return out

    (first_on, _), (last_on, last_val) = pts[0], pts[-1]
    span = (last_on - first_on).days
    out.update({"span_days": span, "first_on": first_on.isoformat(),
                "last_on": last_on.isoformat(), "last": round(last_val, 2),
                "now": round(last_val, 2)})
    if len(pts) < MIN_POINTS or span < MIN_SPAN_DAYS:
        return out

    slope, r2 = _fit(pts)
    if slope is None:
        return out
    out["per_day"] = round(slope, 3)
    out["r2"] = round(r2, 3)
    out["confidence"] = _confidence(len(pts), span, r2)
    # 마지막으로 잰 날 이후로도 계속 자랐다고 본다 — 뒤로는 밀지 않는다.
    ahead = max(0, (today - last_on).days)
    out["now"] = round(max(0.0, last_val + slope * ahead), 2)
    return out


# --------------------------------------------------------------------------- 예측
def _result(why: str, spec: dict = None, **extra) -> dict:
    """예측 한 건. `why` 는 근거이자 못 낸 이유다 — 둘 다 사람이 읽을 한 줄이라
    자리를 나누지 않는다(물주기의 `basis` 와 같은 취급)."""
    out = {"harvestable": bool(spec), "mode": (spec or {}).get("mode"),
           "why": why, "ready_on": None, "days_until": None, "ready_now": False,
           "yield_g": None, "rough": False, "confidence": None,
           "canopy_per_day": None, "leaf_per_day": None, "points": 0}
    out.update(extra)
    return out


def _yield_g(spec: dict, mode: str, canopy_cm, leaf_count) -> tuple:
    """(예상 생산량 g, 에두른 추정인가).

    잎을 따는 작물은 **세고 있는 잎 수**에서 바로 나온다. 남길 잎(속잎)을 빼는 건
    다 뽑는 게 아니라 겉잎만 따서 계속 기르기 때문이다.

    열매는 탐지가 안 된다. 포기가 기준 크기의 몇 배인지로 한 번 거둘 양을 늘리고
    줄이는 게 전부라, 부른 쪽에서 'rough' 를 반드시 같이 보여 줘야 한다.
    """
    if mode == crops.HARVEST_LEAF:
        if leaf_count is None:
            return None, False
        pickable = max(0.0, leaf_count - spec["keep_leaves"])
        return round(pickable * spec["g_per_leaf"]), False
    if mode == crops.HARVEST_FRUIT:
        if not canopy_cm:
            return None, True
        # 기준 크기에서 두 배까지만 쳐 준다. 캐노피가 세 배라고 열매가 세 배
        # 달리지는 않을뿐더러, 애초에 열매를 안 보고 하는 추정이다.
        scale = min(2.0, canopy_cm / spec["ready_canopy_cm"])
        return round(spec["g_per_cycle"] * scale), True
    return None, False


def forecast(plant: dict, today: date = None, growth_factor: float = 1.0) -> dict:
    """이 화분의 수확적기와 예상 생산량.

    캐노피 추세로 '언제'를 잡고, 잎 추세로 '얼마나'를 잡는다. 둘을 따로 재는 건
    수확적기를 정하는 건 포기가 다 벌어졌는지(캐노피)인데, 실제로 손에 들어오는
    양은 잎 수라서다 — 같은 18cm 라도 잎이 여덟 장이냐 열두 장이냐가 다르다.

    `growth_factor` 는 weather.growth_factor 가 낸 배율이다 — 앞으로 올 날씨가
    **잰 기간보다** 얼마나 자라기 좋은가. 기본값 1.0 이라 안 주면 예전과 똑같다.

    이 배율은 **날짜를 만들어 내지 못한다.** 아래 두 거절(안 자란다 / 너무 멀다)은
    배율을 곱하기 **전** 의 실측 기울기로 판정한다. 날씨가 좋아진다고 원래 안
    나왔을 날짜가 나오면 그건 보정이 아니라 규칙 우회다.
    """
    today = today or date.today()
    spec = crops.harvest_of(plant)
    log = (plant or {}).get("growth_log") or []

    if not spec:
        return _result(f"{crops.name_of(plant)}는 거두지 않는 작물이에요 (관상)")

    mode = spec["mode"]
    canopy = trend(log, "canopy_cm", today)
    leaves = trend(log, "leaf_count", today)
    common = {"canopy_per_day": canopy["per_day"], "leaf_per_day": leaves["per_day"],
              "points": canopy["points"], "confidence": canopy["confidence"],
              "canopy_now": canopy["now"], "leaf_now": leaves["now"],
              "target_cm": spec["ready_canopy_cm"], "cycle_days": spec.get("cycle_days")}

    now_cm = canopy["now"]
    if now_cm is None:
        return _result("아직 잰 적이 없어요 — 스캔하면 여기에 수확 예측이 뜹니다",
                      spec, **common)

    # 이미 다 컸으면 추세가 없어도 답할 수 있다. '지금 거두세요' 에 기울기는 필요 없다.
    if now_cm >= spec["ready_canopy_cm"]:
        leaf_now = leaves["now"]
        if mode == crops.HARVEST_LEAF and leaf_now is None:
            leaf_now = float(spec["ready_leaf_count"])
        g, rough = _yield_g(spec, mode, now_cm, leaf_now)
        return _result(f"이미 기준 {spec['ready_canopy_cm']:.0f}cm 를 넘겼어요 "
                      f"(지금 {now_cm:.1f}cm)", spec,
                      ready_on=today.isoformat(), days_until=0, ready_now=True,
                      yield_g=g, rough=rough, **common)

    if canopy["per_day"] is None:
        need = MIN_POINTS if canopy["points"] < MIN_POINTS else None
        why = ("측정이 한 번뿐이라 아직 속도를 못 냅니다 — 며칠 뒤 다시 스캔해 주세요"
               if need else
               f"측정이 {canopy['span_days']}일치뿐이라 아직 속도를 못 냅니다 "
               f"({MIN_SPAN_DAYS}일은 벌어져야 해요)")
        return _result(why, spec, **common)

    if canopy["per_day"] <= 0:
        return _result("포기가 안 커지고 있어요 — 빛·물·자리를 먼저 살펴 주세요 "
                      f"(하루 {canopy['per_day']:+.2f}cm)", spec, **common)

    raw_days = (spec["ready_canopy_cm"] - now_cm) / canopy["per_day"]
    # 거절 판정은 **실측 기울기 그대로** 본다 — 날씨 배율을 곱한 뒤에 보면
    # 원래 '너무 멀다' 로 거절됐을 화분이 배율 덕에 통과해 버린다.
    if raw_days > MAX_HORIZON_DAYS:
        return _result(f"이 속도면 {MAX_HORIZON_DAYS}일 넘게 걸려요 — 날짜를 찍기엔 너무 멉니다",
                      spec, **common)

    try:
        factor = float(growth_factor or 1.0)
    except (TypeError, ValueError):
        factor = 1.0
    factor = factor if factor > 0 else 1.0
    days = raw_days / factor
    common["growth_factor"] = round(factor, 3)
    common["days_without_weather"] = max(0, round(raw_days))

    days = max(0, round(days))
    ready = today + timedelta(days=days)
    # 그날의 잎 수 — 잎도 자라고 있으면 그만큼 더 딸 수 있다.
    leaf_then = leaves["now"]
    if leaf_then is not None and leaves["per_day"]:
        leaf_then = max(0.0, leaf_then + leaves["per_day"] * days)
    if mode == crops.HARVEST_LEAF and leaf_then is None:
        leaf_then = float(spec["ready_leaf_count"])
    g, rough = _yield_g(spec, mode, spec["ready_canopy_cm"], leaf_then)

    why = f"하루 {canopy['per_day']:+.2f}cm 로 {spec['ready_canopy_cm']:.0f}cm 까지"
    moved = common["days_without_weather"] - days
    # 배율이 1.0 이 아니어도 반올림하면 같은 날인 경우가 있다. 그때 '날씨로 0일'
    # 이라고 적으면 아무 말도 아니면서 보정이 있었던 것처럼 읽힌다.
    if moved:
        why += f" · 날씨로 {abs(moved)}일 {'당김' if moved > 0 else '미룸'} (×{factor:.2f})"
    return _result(why,
                  spec, ready_on=ready.isoformat(), days_until=days,
                  yield_g=g, rough=rough, leaf_at_harvest=(round(leaf_then, 1)
                                                          if leaf_then is not None else None),
                  **common)


def farm_forecast(plants, today: date = None, window_days: int = None,
                  growth_factor_of=None) -> dict:
    """온실 전체 — 언제 무엇을 얼마나 거두나.

    화분 하나씩 보면 '이건 12일 뒤 40g' 이지만, 정작 알고 싶은 건 '이번 달에
    얼마나 나오나' 와 '오늘 딸 게 있나' 다. 그래서 날짜별로 묶어서 돌려준다.

    `growth_factor_of(plant) -> 배율` 을 주면 화분마다 날씨 배율을 물어본다.
    함수로 받는 건 이 모듈이 기상 자료를 직접 안 보기 때문이다 — 날씨를 받아
    오는 쪽(main)이 어떻게 구하는지는 여기서 알 필요가 없다. 안 주면 배율 1.0
    이라 패널과 모달이 서로 다른 날짜를 말하지 않는다.
    """
    today = today or date.today()
    window_days = FARM_WINDOW_DAYS if window_days is None else window_days
    rows, by_date, total_g, ready_now = [], {}, 0, []

    for p in plants:
        got = forecast(p, today, growth_factor_of(p) if growth_factor_of else 1.0)
        if not got["harvestable"]:
            continue
        row = {"plant_id": p.get("id"), "name": p.get("name"), "pos": p.get("pos"),
               "crop": crops.key_of(p), "crop_name": crops.name_of(p),
               "mode": got["mode"], "ready_on": got["ready_on"],
               "days_until": got["days_until"], "ready_now": got["ready_now"],
               "yield_g": got["yield_g"], "rough": got["rough"],
               "confidence": got["confidence"], "why": got["why"]}
        rows.append(row)
        if got["ready_now"]:
            ready_now.append(row)
        if got["ready_on"] and got["days_until"] is not None \
                and got["days_until"] <= window_days:
            g = got["yield_g"] or 0
            total_g += g
            slot = by_date.setdefault(got["ready_on"], {"date": got["ready_on"],
                                                        "plants": 0, "yield_g": 0})
            slot["plants"] += 1
            slot["yield_g"] += g

    rows.sort(key=lambda r: (r["days_until"] is None, r["days_until"], r["pos"] or ""))
    return {"window_days": window_days, "total_g": total_g,
            "ready_now": len(ready_now), "plants": rows,
            "days": [by_date[k] for k in sorted(by_date)]}
