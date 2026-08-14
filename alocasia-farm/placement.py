"""배치 최적화 — 어느 화분에 어느 식물을 두면 잘 자라나

문제: 화분 자리는 고정이고 식물은 옮길 수 있다. 어떤 식물을 어느 자리에 두면
전체가 가장 잘 자라는가. 답이 자명하지 않은 이유는 **식물끼리 서로 영향을 주기**
때문이다 — 대품을 밝은 자리에 두면 그 그늘에 옆 소품이 들어간다.

두 가지를 계산한다:

  1. 조도    램버시안 광원. E = I₀·cos²θ/d², 빔 반각 밖은 0.
             I₀ 를 총 광량으로 되맞춰서, 빔을 좁히면 총량이 아니라 퍼짐만 변한다.
  2. 그늘    광원→잎 직선이 이웃 캐노피(원기둥)를 지나면 투과율을 곱한다.
             투과율 = exp(-k·LAI) (비어–람베르트). 잎이 몇 겹인지가 그늘을 정한다.

물리는 light-sim(../light-sim)과 **같은 식**이다. 그쪽은 numpy 로 5x10 격자를
돌리고 여기는 순수 파이썬으로 화분 수십 개를 돌린다 — 둘이 같은 답을 내는지는
test_placement.py 가 무작위 배치로 맞춰 본다.

좌표는 전부 실좌표 cm (`_cm`). 선반 60 x 40 cm 의 중앙이 원점이고,
y 는 높이다. 외부 의존성 없이 순수 파이썬으로만 계산한다.
"""

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
# 좌표계 주의: 여기서는 y 가 높이, z 가 앞뒤다 (light-sim 은 z 가 높이).
#
# 물리는 light-sim 과 같은 식을 쓴다. 예전에는 cos 을 한 번만 곱하고 광량을
# 정규화하지 않아서, 빔 각도를 바꾸면 총량이 같이 변해 버렸다(좁은 빔이 더
# 어두워졌다). 실제로는 같은 등을 좁게 모으면 가운데가 **더 밝아진다**.

def _peak_intensity(power: float, half_rad: float) -> float:
    """중심축 광도 I₀. 램버시안 배광 I(θ)=I₀cosθ 를 반각 θₘ 원뿔에서 적분하면
    Φ = I₀·π·sin²θₘ 이므로, 총 광량이 power 가 되게 되맞춘다.

    이게 있어야 빔 각도가 '퍼짐'만 바꾸고 총량은 안 바꾼다.
    """
    s = math.sin(half_rad)
    return power / (math.pi * s * s) if s > 0 else 0.0


def illuminance(x_cm: float, z_cm: float, lights: List[dict] = None,
                canopy_y_cm: float = None) -> float:
    """한 지점이 조명들로부터 받는 빛의 양 (상대값), 가리는 것이 없다고 볼 때.

    E = I₀·cosθ · cosθ / d² — 앞의 cos 은 램버시안 광원이 그 방향으로 덜
    내보내는 몫이고, 뒤의 cos 은 수평인 잎이 비스듬한 빛을 덜 받는 몫이다.
    스팟등이라 빔 반각(`angle`, 기본 30도) 밖은 0이다.
    """
    lights = DEFAULT_LIGHTS if lights is None else lights
    canopy_y_cm = CANOPY_Y_CM if canopy_y_cm is None else canopy_y_cm
    total = 0.0
    for lamp in lights:
        dx = lamp["x"] - x_cm
        dy = lamp["y"] - canopy_y_cm
        dz = lamp["z"] - z_cm
        d2 = dx * dx + dy * dy + dz * dz
        if d2 <= 0 or dy <= 0:            # 잎이 조명보다 높으면 못 받는다
            continue
        cos = dy / math.sqrt(d2)          # 잎이 위를 보고 있다고 본다
        half = math.radians(lamp.get("angle", DEFAULT_ANGLE))
        if cos < math.cos(half):          # 빔 원뿔 밖 — 스팟등이 안 비춘다
            continue
        total += _peak_intensity(lamp.get("power", 1.0), half) * cos * cos / d2
    return total


# --------------------------------------------------------------------------- 차폐
# 소산계수. 투과율 = exp(-k·LAI) (비어–람베르트). light-sim 의 extinction_k 와 같다.
EXTINCTION_K = float(os.environ.get("EXTINCTION_K", "0.7"))

# 잎 면적 상수 — farm_bridge.py 의 것과 같은 값이어야 한다. 다르면 같은 포기가
# 앱에서와 시뮬레이터에서 다른 그늘을 만든다.
LEAF_AREA_FACTOR = 0.42        # 잎 면적 ÷ (긴 변)². 하트형 잎 기준
MEAN_OVER_MAX_LEAF = 0.75      # 평균 잎 ÷ 가장 큰 잎
LAI_MIN, LAI_MAX = 0.2, 6.0


def plant_lai(plant: dict, radius_cm: float) -> float:
    """잎 개수와 잎 크기로 LAI. 못 내면 잠정값.

    LAI 는 정의가 그대로 계산식이다 — 잎 면적의 합 ÷ 그 포기가 덮는 지면 면적.
    예전에는 '원이 겹친 넓이'로 그늘을 쟀는데, 그건 잎이 몇 겹인지를 못 담는다.
    잎 세 장짜리 어린 포기와 열두 장 빽빽한 포기가 같은 그늘을 만들어 버린다.
    """
    n = plant.get("leaf_count")
    leaf_cm = plant.get("leaf_max_cm")
    if not n or not leaf_cm or radius_cm <= 0:
        return 1.2                                  # 잠정값
    mean_leaf = MEAN_OVER_MAX_LEAF * float(leaf_cm)
    area = LEAF_AREA_FACTOR * mean_leaf * mean_leaf
    ground = math.pi * radius_cm * radius_cm
    return max(LAI_MIN, min(LAI_MAX, int(n) * area / ground))


def _segment_hits_cylinder(p0, p1, center_xz, radius_cm: float, top_cm: float) -> bool:
    """선분 p0→p1 이 바닥에 선 유한 원기둥을 지나는가. p 는 (x, y=높이, z).

    원기둥이 연직이라 xz 평면에서는 원, 높이로는 [0, top] 구간이다. 그래서 xz
    에서 원과 만나는 구간을 먼저 구하고, 그 동안 높이가 원기둥 안에 드는지 본다.
    """
    if radius_cm <= 0 or top_cm <= 0:
        return False
    x0, y0, z0 = p0
    dx, dy, dz = p1[0] - x0, p1[1] - y0, p1[2] - z0
    cx, cz = center_xz
    fx, fz = x0 - cx, z0 - cz

    a = dx * dx + dz * dz
    if a <= 1e-12:                          # 연직 광선 — xz 로 안 움직인다
        if fx * fx + fz * fz > radius_cm * radius_cm:
            return False
        lo, hi = 0.0, 1.0
    else:
        b = 2.0 * (fx * dx + fz * dz)
        c = fx * fx + fz * fz - radius_cm * radius_cm
        disc = b * b - 4.0 * a * c
        if disc < 0:
            return False                    # 원을 아예 스치지 않는다
        sq = math.sqrt(disc)
        lo = max((-b - sq) / (2.0 * a), 0.0)
        hi = min((-b + sq) / (2.0 * a), 1.0)
        if lo > hi:
            return False                    # 원과 만나는 구간이 선분 밖이다
    ya, yb = y0 + dy * lo, y0 + dy * hi
    return min(ya, yb) <= top_cm and max(ya, yb) >= 0.0


def shaded_illuminance(x_cm: float, y_cm: float, z_cm: float,
                       blockers, lights: List[dict] = None,
                       k: float = None) -> float:
    """가림까지 넣은 조도. blockers = [(x_cm, z_cm, r_cm, h_cm, lai)].

    광원마다 직달광을 구하고, 그 광선이 지나는 캐노피들의 투과율을 곱해 더한다.
    겹겹이 지나면 투과율이 곱해진다 — 빛이 층층이 통과하기 때문이다.
    """
    lights = DEFAULT_LIGHTS if lights is None else lights
    k = EXTINCTION_K if k is None else k
    total = 0.0
    for lamp in lights:
        direct = illuminance(x_cm, z_cm, [lamp], y_cm)
        if direct <= 0:
            continue
        p0 = (lamp["x"], lamp["y"], lamp["z"])
        p1 = (x_cm, y_cm, z_cm)
        for (bx, bz, br, bh, blai) in blockers:
            if _segment_hits_cylinder(p0, p1, (bx, bz), br, bh):
                direct *= math.exp(-k * max(0.0, blai))
        total += direct
    return total


# --------------------------------------------------------------------------- 점수
def _need_light(r_cm: float) -> float:
    """잎이 넓을수록 빛을 많이 써야 한다 (잎면적에 대략 비례)."""
    return max(0.35, min(1.0, (r_cm / 20.0) ** 1.5))


def geometry(spots: List[dict], lights=None) -> dict:
    """자리에만 딸린 값을 미리 잰다 — 식물을 바꿔 놓아도 안 변하는 것들.

    최적화는 배치를 수천 번 채점하는데 자리 좌표는 안 변한다. 조도는 이제
    **잎 높이에 따라 달라진다**(키 큰 포기는 조명에 가깝다) — 그래서 밝기 기준을
    자리 하나가 아니라 자리 x 키 조합의 최댓값으로 잡는다.

    고정 높이 하나로 재면 그보다 키 큰 포기가 100%를 넘어 버린다. 조합의
    최댓값을 쓰면 0~100%로 떨어지고, 식물이 자리를 바꿔도 기준이 안 흔들려
    최적화 중의 점수끼리 견줄 수 있다.
    """
    n = len(spots)
    pos = [(s["x_cm"], s["z_cm"]) for s in spots]
    heights = [s.get("h_cm") or CANOPY_Y_CM for s in spots] or [CANOPY_Y_CM]
    top = max((illuminance(x, z, lights, h) for x, z in pos for h in heights),
              default=0.0) or 1.0
    return {"n": n, "pos": pos, "top": top, "lights": lights}


def _lit_at(geo: dict, i: int, h_cm: float, blockers) -> float:
    """i번 자리, 잎 높이 h_cm 에서 받는 빛(0~1). 가리는 것까지 넣는다."""
    x_cm, z_cm = geo["pos"][i]
    return shaded_illuminance(x_cm, h_cm, z_cm, blockers, geo["lights"]) / geo["top"]


def _measure(geo: dict, radii: List[float], heights: List[float],
             lais: List[float] = None) -> List[tuple]:
    """미리 잰 자리값 + 지금 놓인 식물 몸집 → (받은 빛, 그늘) 목록.

    그늘은 '가렸을 때 / 안 가렸을 때'의 비로 낸다. 예전처럼 원이 겹친 넓이로
    재면 잎이 몇 겹인지를 못 담아, 성긴 어린 포기와 빽빽한 포기가 같은 그늘을
    만든다. 이제는 LAI 가 지배한다.
    """
    n = geo["n"]
    if lais is None:
        lais = [1.2] * n
    cyl = [(geo["pos"][j][0], geo["pos"][j][1], radii[j], heights[j], lais[j])
           for j in range(n)]
    out = []
    for i in range(n):
        h_cm = heights[i]
        # 자기 자신은 뺀다 — 수광점이 제 캐노피 꼭대기라 세면 다 어두워진다.
        blockers = [cyl[j] for j in range(n) if j != i]
        got = _lit_at(geo, i, h_cm, blockers)
        bare = _lit_at(geo, i, h_cm, ())
        shade = 1.0 - (got / bare) if bare > 0 else 0.0
        out.append((got, max(0.0, min(1.0, shade))))
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
    lais = [s.get("lai") or plant_lai(s["plant"], s["r_cm"]) for s in spots]
    lit = _measure(geo, radii, heights, lais)

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
                      "r_cm": r_cm, "h_cm": h_cm, "lai": plant_lai(p, r_cm),
                      "plant": p})
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
    shapes = [(s["r_cm"], s["h_cm"], s.get("lai") or plant_lai(s["plant"], s["r_cm"]))
              for s in spots]
    # 필요한 빛은 식물에 딸린 값이라 자리를 옮겨도 그대로다
    needs = [_need_light(shapes[k][0]) for k in range(n)]

    def rate(order):
        radii = [shapes[order[i]][0] for i in range(n)]
        heights = [shapes[order[i]][1] for i in range(n)]
        lais = [shapes[order[i]][2] for i in range(n)]
        lit = _measure(geo, radii, heights, lais)
        total = sum(min(1.0, lit[i][0] / needs[order[i]]) for i in range(n))
        return round(total / n * 100, 1)

    def laid_out(order):
        return [{**spots[i], "plant": plants[order[i]],
                 "r_cm": shapes[order[i]][0], "h_cm": shapes[order[i]][1],
                 "lai": shapes[order[i]][2]}
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
