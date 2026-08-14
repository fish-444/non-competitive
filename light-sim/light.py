"""광 계산 — 직달광, 상호 차폐, PPFD/DLI/균일도.

Phase 1 이라 벽·천장 반사는 없다. 실내 재배실은 반사로 10~30% 가 더 들어오므로
여기 나오는 값은 **보수적인 하한**으로 읽어야 한다.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

import numpy as np

from geometry import Config, Light, Pot, receiver_point, pot_xy

Point = Tuple[float, float, float]


# --------------------------------------------------------------------------- 직달광
def direct_ppfd(light: Light, point: Point) -> float:
    """광원 하나가 수광점에 주는 PPFD(µmol/m²/s). 가리는 것이 없다고 볼 때.

    E = I₀·cosθ · cosθ / d² — 앞의 cosθ 는 램버시안 광원이 그 방향으로 덜 내보내는
    몫이고, 뒤의 cosθ 는 수평인 수광면이 비스듬한 빛을 덜 받는 몫(램버트 코사인 법칙)
    이다. 아래를 보는 광원과 수평 수광면에서는 두 각이 같아 cos²θ 가 된다.
    """
    lx, ly, lz = light.position
    px, py, pz = point
    dx, dy, dz = px - lx, py - ly, pz - lz

    if dz >= 0:
        return 0.0                      # 수광점이 광원보다 높다 — 빛이 안 닿는다

    d2 = dx * dx + dy * dy + dz * dz
    if d2 <= 1e-12:
        return 0.0                      # 같은 자리. 역제곱이 발산하므로 0 으로 둔다

    d = math.sqrt(d2)
    cos_theta = -dz / d                 # 연직 아래를 0도로 잰 천정각의 코사인
    if cos_theta <= 0:
        return 0.0
    if math.acos(min(1.0, cos_theta)) > light.half_angle_rad:
        return 0.0                      # 빔 밖

    return light.peak_intensity * cos_theta * cos_theta / d2


# --------------------------------------------------------------------------- 차폐
def segment_hits_cylinder(p0: Point, p1: Point, center_xy: Tuple[float, float],
                          radius: float, z_top: float) -> bool:
    """선분 p0→p1 이 바닥에 선 유한 원기둥을 지나는가.

    원기둥이 연직이라 xy 평면에서는 원, z 로는 [0, z_top] 구간이다. 그래서 xy 에서
    원과 만나는 구간을 먼저 구하고, 그 구간 동안 z 가 원기둥 높이 안에 드는지만 본다.
    """
    if radius <= 0 or z_top <= 0:
        return False

    x0, y0, z0 = p0
    x1, y1, z1 = p1
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    cx, cy = center_xy
    fx, fy = x0 - cx, y0 - cy

    a = dx * dx + dy * dy
    if a <= 1e-15:
        # 연직 선분 — xy 로는 안 움직인다. 원 안이면 z 구간만 본다.
        if fx * fx + fy * fy > radius * radius:
            return False
        lo, hi = (0.0, 1.0)
    else:
        b = 2.0 * (fx * dx + fy * dy)
        c = fx * fx + fy * fy - radius * radius
        disc = b * b - 4.0 * a * c
        if disc < 0:
            return False                # 원을 아예 스치지 않는다
        sq = math.sqrt(disc)
        t_in = (-b - sq) / (2.0 * a)
        t_out = (-b + sq) / (2.0 * a)
        lo, hi = max(t_in, 0.0), min(t_out, 1.0)
        if lo > hi:
            return False                # 원과 만나는 구간이 선분 밖이다

    # 그 구간에서 z 가 [0, z_top] 과 겹치는지. z 는 t 에 대해 1차라 양 끝만 보면 된다.
    za, zb = z0 + dz * lo, z0 + dz * hi
    return min(za, zb) <= z_top and max(za, zb) >= 0.0


def transmittance(lai: float, k: float = 0.7) -> float:
    """캐노피 한 겹을 지나며 남는 비율. 비어–람베르트(Beer–Lambert) 흡광.

    τ = exp(-k·LAI) — 잎이 겹칠수록 지수적으로 줄고, 완전히 막지는 않는다.
    """
    if lai <= 0:
        return 1.0
    return math.exp(-k * max(0.0, lai))


def shading_factor(light: Light, point: Point, blockers: Sequence[Tuple[Pot, Tuple[float, float]]],
                   k: float = 0.7) -> float:
    """광원→수광점 직선이 지나는 캐노피들의 투과율 곱. 아무것도 안 지나면 1.0.

    가린 캐노피가 여럿이면 투과율을 곱한다 — 빛이 겹겹이 통과하기 때문이다.
    """
    factor = 1.0
    for pot, (cx, cy) in blockers:
        if segment_hits_cylinder(light.position, point, (cx, cy),
                                 pot.canopy_radius, pot.plant_height):
            factor *= transmittance(pot.leaf_area_index, k)
    return factor


# --------------------------------------------------------------------------- 합산
def ppfd_at(point: Point, lights: Iterable[Light],
            blockers: Sequence[Tuple[Pot, Tuple[float, float]]], k: float = 0.7) -> float:
    """수광점 하나의 PPFD. 광원별 직달광에 차폐를 곱해 더한다.

    광원끼리는 서로 간섭하지 않으므로(비간섭성) 단순 합이 맞다.
    """
    return sum(direct_ppfd(L, point) * shading_factor(L, point, blockers, k)
               for L in lights)


def compute_ppfd(cfg: Config) -> np.ndarray:
    """격자 모양(rows × cols) PPFD 배열. 화분이 없는 칸은 NaN.

    차폐를 볼 때 자기 자신은 뺀다 — 수광점이 제 캐노피 꼭대기라 자기 원기둥과는
    끝점에서 만나고, 그걸 세면 모든 화분이 스스로를 가리게 된다.
    """
    grid, space = cfg.grid, cfg.space
    xy = {id(p): pot_xy(p, grid, space) for p in cfg.pots}

    out = np.full((grid.rows, grid.cols), np.nan, dtype=float)
    for pot in cfg.pots:
        point = receiver_point(pot, grid, space)
        blockers = [(q, xy[id(q)]) for q in cfg.pots if q is not pot]
        out[pot.row, pot.col] = ppfd_at(point, cfg.lights, blockers, cfg.extinction_k)
    return out


# --------------------------------------------------------------------------- 합산 (배열판)
def compute_ppfd_fast(cfg: Config) -> np.ndarray:
    """compute_ppfd 와 **같은 값**을 numpy 로 한 번에 계산한다.

    물리는 위와 똑같다. 다른 건 순서뿐 — (광원 M) × (수광점 P) × (가리는 것 P) 를
    파이썬 반복문 대신 배열 하나로 민다. 최적화가 이 함수를 수천 번 부르는데
    반복문판은 한 번에 6 ms 라 SA 한 판이 분 단위가 된다.

    같은 답이 나오는지는 test_light.py 가 무작위 배치로 매번 맞춰 본다 —
    빠른 쪽이 조용히 갈라지면 최적화가 엉뚱한 배치를 고르기 때문이다.
    """
    pots, lights = cfg.pots, cfg.lights
    out = np.full((cfg.grid.rows, cfg.grid.cols), np.nan, dtype=float)
    if not pots:
        return out
    if not lights:
        for pot in pots:
            out[pot.row, pot.col] = 0.0
        return out

    n = len(pots)
    xy = np.array([pot_xy(p, cfg.grid, cfg.space) for p in pots], dtype=float)   # (P,2)
    z_top = np.array([p.plant_height for p in pots], dtype=float)                # (P,)
    radius = np.array([p.canopy_radius for p in pots], dtype=float)
    tau = np.array([transmittance(p.leaf_area_index, cfg.extinction_k) for p in pots])

    R = np.column_stack([xy, z_top])                                            # (P,3) 수광점
    L = np.array([g.position for g in lights], dtype=float)                     # (M,3)
    I0 = np.array([g.peak_intensity for g in lights], dtype=float)              # (M,)
    cos_max = np.cos(np.array([g.half_angle_rad for g in lights], dtype=float))

    # ── 직달광: E = I₀·cos²θ/d². 빔 밖과 광원보다 높은 점은 0 ─────────────
    D = R[None, :, :] - L[:, None, :]                       # (M,P,3) 광원→수광점
    d2 = (D * D).sum(axis=2)                                # (M,P)
    d = np.sqrt(np.maximum(d2, 1e-24))
    cos_t = -D[:, :, 2] / d
    lit = (D[:, :, 2] < 0) & (d2 > 1e-12) & (cos_t >= cos_max[:, None]) & (cos_t > 0)
    direct = np.where(lit, I0[:, None] * cos_t * cos_t / np.maximum(d2, 1e-24), 0.0)

    # ── 차폐: 선분(광원 m → 수광점 p) 대 원기둥 q. 축 순서는 (M, P, Q) ────
    dx, dy, dz = D[:, :, 0:1], D[:, :, 1:2], D[:, :, 2:3]           # (M,P,1)
    fx = (L[:, 0][:, None] - xy[:, 0][None, :])[:, None, :]         # (M,1,Q) 광원 - 원기둥 중심
    fy = (L[:, 1][:, None] - xy[:, 1][None, :])[:, None, :]

    a = dx * dx + dy * dy                                   # (M,P,1)
    b = 2.0 * (fx * dx + fy * dy)                           # (M,P,Q)
    c = fx * fx + fy * fy - (radius * radius)[None, None, :]        # (M,1,Q)
    disc = b * b - 4.0 * a * c

    vertical = np.broadcast_to(a <= 1e-15, disc.shape)      # 연직 광선 — xy 로 안 움직인다
    sq = np.sqrt(np.maximum(disc, 0.0))
    safe_a = np.where(a <= 1e-15, 1.0, a)
    lo = np.maximum((-b - sq) / (2.0 * safe_a), 0.0)
    hi = np.minimum((-b + sq) / (2.0 * safe_a), 1.0)
    crosses = (disc >= 0) & (lo <= hi)
    # 연직이면 근을 못 쓴다 — 원 안이면 선분 전체가 후보 구간
    lo = np.where(vertical, 0.0, lo)
    hi = np.where(vertical, 1.0, hi)
    crosses = np.where(vertical, np.broadcast_to(c <= 0, disc.shape), crosses)

    zl = L[:, 2][:, None, None]
    za, zb = zl + dz * lo, zl + dz * hi
    hit = (crosses & (np.minimum(za, zb) <= z_top[None, None, :])
           & (np.maximum(za, zb) >= 0.0)
           & (radius > 0)[None, None, :] & (z_top > 0)[None, None, :])
    hit[:, np.arange(n), np.arange(n)] = False              # 자기 자신은 뺀다

    shading = np.prod(np.where(hit, tau[None, None, :], 1.0), axis=2)   # (M,P)

    for pot, v in zip(pots, (direct * shading).sum(axis=0)):
        out[pot.row, pot.col] = v
    return out


def dli(ppfd: np.ndarray, photoperiod_hours: float) -> np.ndarray:
    """DLI(mol/m²/day) = PPFD × 광주기. µmol→mol 이라 1e-6, 시간→초라 3600."""
    return ppfd * photoperiod_hours * 3600.0 / 1e6


def uniformity_cv(values: np.ndarray) -> float:
    """변동계수 CV = 표준편차/평균. 작을수록 고르다.

    평균으로 나누므로 밝기와 무관하게 '고른 정도'만 남는다 — 등급이 다른 배치끼리
    비교할 수 있다. 화분이 없는 칸(NaN)은 뺀다.
    """
    v = values[~np.isnan(values)]
    if v.size == 0:
        return float("nan")
    mean = float(v.mean())
    if mean <= 0:
        return float("nan")
    return float(v.std() / mean)


def summarize(cfg: Config) -> dict:
    """한 배치의 계산 결과 묶음. main 과 visualize 가 같이 쓴다."""
    ppfd = compute_ppfd(cfg)
    d = dli(ppfd, cfg.photoperiod_hours)
    v = ppfd[~np.isnan(ppfd)]
    return {
        "label": cfg.label,
        "ppfd": ppfd,
        "dli": d,
        "cv": uniformity_cv(ppfd),
        "mean": float(v.mean()) if v.size else float("nan"),
        "min": float(v.min()) if v.size else float("nan"),
        "max": float(v.max()) if v.size else float("nan"),
        "n_pots": int(v.size),
    }
