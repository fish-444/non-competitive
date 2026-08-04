"""배치 최적화 — 어느 화분에 어느 식물을 두면 잘 자라나

문제: 화분 자리는 고정이고 식물은 옮길 수 있다. 어떤 식물을 어느 자리에 두면
전체가 가장 잘 자라는가. 답이 자명하지 않은 이유는 **식물끼리 서로 영향을 주기**
때문이다 — 대품을 밝은 자리에 두면 그 그늘에 옆 소품이 들어간다.

두 가지를 계산한다:

  1. 조도    조명에서 오는 빛. 거리²반비례 × 입사각 cos, 빔 각도 밖은 0.
  2. 그늘    키 큰 이웃의 잎우산이 덮는 만큼 깎인다 (원-원 겹침 넓이).

좌표는 전부 실좌표 cm (`_cm`). 선반 60 x 40 cm 의 중앙이 원점이고,
y 는 높이다. 외부 의존성 없이 순수 파이썬으로만 계산한다.
"""

import functools
import math
import os
from typing import List

# --------------------------------------------------------------------------- 환경
# 조명은 실제로 좌측·우측 레일에 3개 달려 있다(2개+1개) — 실측 위치를 넣기
# 전까지는 화분 자리를 처음 표시할 때 찍었던 세 지점을 그대로 쓴다(선반 위 47cm).
# 레일에 고정돼 있으니 좌우(x)는 못 옮기고, 레일을 따라(z) 위치만 조절한다.
SHELF_W_CM = float(os.environ.get("SHELF_W_CM", "60"))
RAIL_MARGIN_CM = float(os.environ.get("RAIL_MARGIN_CM", "8"))     # 벽에서 레일까지
LIGHT_COUNT = 3


def rail_x(side: str, w_cm: float = None, margin_cm: float = None) -> float:
    """레일(좌/우)의 x 좌표. 조명은 이 값에서 벗어날 수 없다."""
    w_cm = SHELF_W_CM if w_cm is None else w_cm
    margin_cm = RAIL_MARGIN_CM if margin_cm is None else margin_cm
    x = w_cm / 2 - margin_cm
    return -x if side == "left" else x


DEFAULT_LIGHTS = [{"side": "left", "x": rail_x("left"), "y": 47.0, "z": 17.0,
                   "power": 1.0, "angle": 30.0},
                  {"side": "left", "x": rail_x("left"), "y": 47.0, "z": -13.0,
                   "power": 1.0, "angle": 30.0},
                  {"side": "right", "x": rail_x("right"), "y": 47.0, "z": 2.0,
                   "power": 1.0, "angle": 30.0}]
DEFAULT_ANGLE = float(os.environ.get("LIGHT_ANGLE", "30"))    # 빔 반각(도) — 스팟등 기준

# 잎이 모인 높이(cm). 빛이 실제로 닿아 광합성하는 지점.
CANOPY_Y_CM = float(os.environ.get("CANOPY_Y_CM", "18"))

# 크기 등급별 기본 몸집 — 잎을 실측(leaf_max_cm)했으면 그쪽이 우선이다.
# 잎우산 반지름 ≈ 잎 긴 변 길이 (잎자루가 사방으로 뻗는 알로카시아 기준).
GRADE_SHAPE = {"소품": (7.0, 14.0), "중품": (13.0, 28.0), "대품": (20.0, 45.0)}
FALLBACK_SHAPE = (10.0, 20.0)          # 미검출 등


def plant_shape(plant: dict) -> tuple:
    """식물 → (잎우산 반지름 cm, 키 cm). 실측이 있으면 실측을 쓴다."""
    radius_cm, height_cm = GRADE_SHAPE.get(plant.get("size_class"), FALLBACK_SHAPE)
    measured = plant.get("leaf_max_cm")
    if measured:
        radius_cm = float(measured)
        height_cm = radius_cm * 2.2       # 알로카시아는 잎보다 키가 크다
    return radius_cm, height_cm


# --------------------------------------------------------------------------- 빛
def illuminance(x_cm: float, z_cm: float, lights: List[dict] = None,
                canopy_y_cm: float = None) -> float:
    """한 지점이 조명들로부터 받는 빛의 양 (상대값).

    거리²에 반비례하고, 위에서 내리꽂을수록(입사각 cos) 잘 받는다.
    스팟등이라 빔 반각(`angle`, 기본 30도) 밖으로 벗어나면 0이다.
    """
    lights = DEFAULT_LIGHTS if lights is None else lights
    canopy_y_cm = CANOPY_Y_CM if canopy_y_cm is None else canopy_y_cm
    total = 0.0
    for lamp in lights:
        dx = lamp["x"] - x_cm
        dy = lamp["y"] - canopy_y_cm
        dz = lamp["z"] - z_cm
        d2 = dx * dx + dy * dy + dz * dz
        if d2 <= 0:
            continue
        cos = dy / math.sqrt(d2)          # 잎이 위를 보고 있다고 본다
        if cos <= 0:
            continue
        half = math.radians(lamp.get("angle", DEFAULT_ANGLE))
        if cos < math.cos(half):          # 빔 원뿔 밖 — 스팟등이 안 비춘다
            continue
        total += lamp.get("power", 1.0) * cos / d2
    return total


# 최적화는 같은 (반지름, 반지름, 거리) 조합을 수천 번 다시 묻는다 — 자리도 몸집도
# 값의 가짓수가 적어서 캐시가 거의 다 맞는다.
@functools.lru_cache(maxsize=200_000)
def _circle_overlap(r1_cm: float, r2_cm: float, d_cm: float) -> float:
    """두 원이 겹치는 넓이. 그늘이 잎우산을 얼마나 덮는지 재는 데 쓴다."""
    if d_cm >= r1_cm + r2_cm:
        return 0.0
    if d_cm <= abs(r1_cm - r2_cm):
        return math.pi * min(r1_cm, r2_cm) ** 2
    a1 = math.acos(max(-1.0, min(1.0, (d_cm * d_cm + r1_cm ** 2 - r2_cm ** 2) / (2 * d_cm * r1_cm))))
    a2 = math.acos(max(-1.0, min(1.0, (d_cm * d_cm + r2_cm ** 2 - r1_cm ** 2) / (2 * d_cm * r2_cm))))
    return (r1_cm ** 2 * (a1 - math.sin(2 * a1) / 2)
            + r2_cm ** 2 * (a2 - math.sin(2 * a2) / 2))


# --------------------------------------------------------------------------- 점수
def _need_light(r_cm: float) -> float:
    """잎이 넓을수록 빛을 많이 써야 한다 (잎면적에 대략 비례)."""
    return max(0.35, min(1.0, (r_cm / 20.0) ** 1.5))


def geometry(spots: List[dict], lights=None) -> dict:
    """자리에만 딸린 값을 미리 잰다 — 식물을 바꿔 놓아도 안 변하는 것들.

    최적화는 배치를 수천 번 채점하는데, 조도·자리 간 거리는 자리가 안 움직이는
    한 그대로다. 매번 다시 재면 50개 배치에 몇 초가 걸린다.
    """
    n = len(spots)
    raw = [illuminance(s["x_cm"], s["z_cm"], lights) for s in spots]
    brightest = max(raw, default=0.0) or 1.0
    lit = [v / brightest for v in raw]                 # 0~1, 제일 밝은 자리가 1
    dist = [[math.dist((spots[i]["x_cm"], spots[i]["z_cm"]),
                       (spots[j]["x_cm"], spots[j]["z_cm"]))
             for j in range(n)] for i in range(n)]
    return {"n": n, "lit": lit, "dist": dist}


def _measure(geo: dict, radii: List[float], heights: List[float]) -> List[tuple]:
    """미리 잰 자리값 + 지금 놓인 식물 몸집 → (받은 빛, 그늘) 목록."""
    n = geo["n"]
    out = []
    for i in range(n):
        r_cm, h_cm, mine = radii[i], heights[i], math.pi * radii[i] ** 2
        covered = 0.0
        if mine > 0:
            for j in range(n):
                if j == i or heights[j] <= h_cm:
                    continue
                overlap = _circle_overlap(r_cm, radii[j], geo["dist"][i][j])
                if overlap:
                    covered += overlap * min(1.0, (heights[j] - h_cm) / 20.0)
        shade = min(1.0, covered / mine) if mine > 0 else 0.0
        out.append((geo["lit"][i] * (1 - shade), shade))
    return out


def score_layout(spots: List[dict], lights=None, geo: dict = None) -> dict:
    """배치 하나를 채점. spots = [{x_cm, z_cm, r_cm, h_cm, plant}] .

    점수는 '받은 빛 / 필요한 빛'을 1에서 자른 값이다. 넘치게 받아도 더 좋아지지
    않는다 — 알로카시아는 직사광에 잎이 타므로 과잉은 이득이 아니다.
    """
    if not spots:
        return {"score": 0.0, "spots": []}
    geo = geo or geometry(spots, lights)
    radii = [s["r_cm"] for s in spots]
    heights = [s["h_cm"] for s in spots]
    lit = _measure(geo, radii, heights)

    out, totals = [], []
    for i, s in enumerate(spots):
        got_light, shade = lit[i]
        need_l = _need_light(s["r_cm"])
        light_ok = min(1.0, got_light / need_l) if need_l else 1.0
        totals.append(light_ok)
        out.append({"slot": s["slot"], "plant_id": s["plant"].get("id"),
                    "name": s["plant"].get("name"),
                    "light": round(got_light * 100), "shade": round(shade * 100),
                    "score": round(light_ok * 100), "need_light": round(need_l * 100)})
    return {"score": round(sum(totals) / len(totals) * 100, 1), "spots": out}


def build_spots(plants: List[dict], pot_xz_cm) -> List[dict]:
    """등록된 식물 → 채점용 자리 목록. pot_xz_cm(slot) 이 실제 좌표를 준다."""
    spots = []
    for p in plants:
        xz = pot_xz_cm(p.get("pos"))
        if xz is None:
            continue
        r_cm, h_cm = plant_shape(p)
        spots.append({"slot": p.get("pos"), "x_cm": xz[0], "z_cm": xz[1],
                      "r_cm": r_cm, "h_cm": h_cm, "plant": p})
    return spots


def optimize(spots: List[dict], lights=None, rounds: int = 40) -> dict:
    """식물끼리 자리를 바꿔 가며 전체 점수를 올린다.

    자리는 못 옮기고 식물만 옮길 수 있으니, 답은 '식물의 순열'이다. 그늘이
    이웃에 걸려 있어서 자리마다 따로 최적을 고를 수 없다(이차 배정 문제).
    개체 수가 수십 개라 둘씩 바꿔 보는 언덕오르기로 충분하다.

    돌려주는 건 '무엇을 어디로 옮기라'는 목록이다 — 화분은 사람이 직접 옮긴다.
    """
    if len(spots) < 2:
        graded = score_layout(spots, lights)
        return {"before": graded["score"], "after": graded["score"],
                "gain": 0.0, "moves": [], "cycles": [], "layout": graded["spots"]}

    n = len(spots)
    geo = geometry(spots, lights)
    order = list(range(n))                   # order[i] = i번 자리에 놓인 식물의 원래 번호
    plants = [s["plant"] for s in spots]
    shapes = [(s["r_cm"], s["h_cm"]) for s in spots]
    # 필요한 빛은 식물에 딸린 값이라 자리를 옮겨도 그대로다
    needs = [_need_light(shapes[k][0]) for k in range(n)]

    def rate(order):
        radii = [shapes[order[i]][0] for i in range(n)]
        heights = [shapes[order[i]][1] for i in range(n)]
        lit = _measure(geo, radii, heights)
        total = sum(min(1.0, lit[i][0] / needs[order[i]]) for i in range(n))
        return round(total / n * 100, 1)

    def laid_out(order):
        return [{**spots[i], "plant": plants[order[i]],
                 "r_cm": shapes[order[i]][0], "h_cm": shapes[order[i]][1]}
                for i in range(n)]

    before = rate(order)
    best = before
    for _ in range(rounds):
        improved = False
        for i in range(n):
            for j in range(i + 1, n):
                order[i], order[j] = order[j], order[i]
                got = rate(order)
                if got > best + 1e-9:
                    best, improved = got, True
                else:
                    order[i], order[j] = order[j], order[i]
        if not improved:
            break

    # order[i] = i번 자리에 놓인 식물의 원래 번호 → dest[p] = p번 식물이 갈 자리
    dest = [0] * n
    for i, src in enumerate(order):
        dest[src] = i

    moves = [{"plant_id": plants[p].get("id"), "name": plants[p].get("name"),
              "from": spots[p]["slot"], "to": spots[dest[p]]["slot"]}
             for p in range(n) if dest[p] != p]

    # 둘씩 맞바꾸는 걸로 안 끝나는 경우가 있다 — A→B, B→C, C→A 처럼 돌아가는 고리다.
    # 고리째 보여 줘야 사람이 순서대로 옮길 수 있다.
    cycles, seen = [], set()
    for p in range(n):
        if p in seen or dest[p] == p:
            continue
        ring, cur = [], p
        while cur not in seen:
            seen.add(cur)
            ring.append(spots[cur]["slot"])
            cur = dest[cur]
        if len(ring) > 1:
            cycles.append(ring)

    return {"before": before, "after": best, "gain": round(best - before, 1),
            "moves": moves, "cycles": cycles,
            "layout": score_layout(laid_out(order), lights, geo)["spots"]}


def heatmap(w_cm: float, d_cm: float, cols: int, rows: int, lights=None) -> dict:
    """선반을 격자로 훑어 빛 세기를 재 온다. 3D 바닥에 깔아 보여 준다."""
    grid = []
    for r in range(rows):
        z_cm = -d_cm / 2 + d_cm * (r + 0.5) / rows
        row = [illuminance(-w_cm / 2 + w_cm * (c + 0.5) / cols, z_cm, lights)
               for c in range(cols)]
        grid.append(row)
    top = max((v for row in grid for v in row), default=1.0) or 1.0
    return {"cols": cols, "rows": rows,
            "light": [[round(v / top, 3) for v in row] for row in grid]}
