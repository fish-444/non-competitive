"""자료구조와 좌표계.

좌표계는 오른손, 미터 단위:
    x  공간의 폭 방향 (열, col 이 늘어나는 쪽)
    y  공간의 깊이 방향 (행, row 가 늘어나는 쪽)
    z  위쪽. 바닥이 z=0

격자는 공간 한가운데에 놓는다. 화분은 격자 좌표(row, col)로만 적고,
실제 xy 는 격자 간격에서 계산한다 — 화분을 옮기는 실험이 설정 파일에서
숫자 두 개만 바꾸는 일이 되도록.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import yaml


@dataclass
class Space:
    """재배 공간의 겉치수(m)."""
    width: float          # x
    depth: float          # y
    height: float         # z


@dataclass
class Light:
    """광원 하나. 아래를 향한 램버시안 배광으로 본다.

    ppf 는 광원이 내보내는 총 광량자속(µmol/s)이고, beam_angle 은 빛이 퍼지는
    전체 각(도)이다. 반각이 beam_angle/2.
    """
    position: Tuple[float, float, float]
    ppf: float
    beam_angle: float

    @property
    def half_angle_rad(self) -> float:
        return math.radians(self.beam_angle) / 2.0

    @property
    def peak_intensity(self) -> float:
        """중심축 광도 I₀ (µmol/s/sr).

        램버시안 배광 I(θ)=I₀cosθ 를 반각 θₘ 원뿔 안에서 적분하면
        Φ = I₀·π·sin²θₘ 이므로, 총 광량자속이 ppf 가 되게 I₀ 를 되맞춘다.
        빔이 좁을수록 같은 ppf 가 좁은 곳에 몰려 I₀ 가 커진다.
        """
        s = math.sin(self.half_angle_rad)
        if s <= 0:
            return 0.0
        return self.ppf / (math.pi * s * s)


@dataclass
class Pot:
    """화분 하나. 캐노피는 반지름 canopy_radius, 높이 plant_height 인 원기둥."""
    grid_position: Tuple[int, int]        # (row, col), 0부터
    plant_height: float
    canopy_radius: float
    leaf_area_index: float

    @property
    def row(self) -> int:
        return self.grid_position[0]

    @property
    def col(self) -> int:
        return self.grid_position[1]


@dataclass
class Grid:
    """격자 간격(m)과 크기."""
    rows: int
    cols: int
    row_spacing: float
    col_spacing: float


@dataclass
class SAParams:
    """모의 담금질(simulated annealing) 설정.

    목적함수는 score = w_cv·CV + w_mean·(1/평균PPFD) 이고 **작을수록 좋다**.
    기본은 w_mean=0, 즉 균일도만 본다 — 농가에서는 총량보다 고르게 자라는 쪽이
    값을 받기 때문이다. 총 광량도 같이 보려면 w_mean 을 올린다.

    두 항은 크기가 많이 다르다. CV 는 0.1~0.3, 1/평균PPFD 는 0.005 언저리다.
    w_mean 을 1 로 두면 사실상 CV 만 보는 것과 같고, 진짜로 저울질을 하려면
    w_mean 은 수십~수백이어야 한다.
    """
    initial_temp: float = 0.0             # 0 이하면 자동 보정 (calibrate_temperature)
    cooling_rate: float = 0.9993          # 매 iteration 마다 T ← T·이 값
    iterations: int = 6000
    seeds: int = 5                        # 지역 최적 확인용 반복 실행 횟수
    w_cv: float = 1.0
    w_mean: float = 0.0


@dataclass
class Config:
    space: Space
    grid: Grid
    lights: List[Light] = field(default_factory=list)
    pots: List[Pot] = field(default_factory=list)
    photoperiod_hours: float = 16.0
    extinction_k: float = 0.7             # 소산계수. 3번 사양의 k
    label: str = "layout"
    sa: SAParams = field(default_factory=SAParams)


def pot_xy(pot: Pot, grid: Grid, space: Space) -> Tuple[float, float]:
    """격자 좌표 → 바닥 평면의 실제 위치(m). 격자를 공간 한가운데에 놓는다.

    간격이 (cols-1)·col_spacing 만큼 벌어지므로, 그 폭을 공간 중앙에 맞춘다.
    """
    x = space.width / 2.0 + (pot.col - (grid.cols - 1) / 2.0) * grid.col_spacing
    y = space.depth / 2.0 + (pot.row - (grid.rows - 1) / 2.0) * grid.row_spacing
    return x, y


def receiver_point(pot: Pot, grid: Grid, space: Space) -> Tuple[float, float, float]:
    """수광점 = 캐노피 상단 중심. 잎이 가장 많이 받는 지점을 대표값으로 쓴다."""
    x, y = pot_xy(pot, grid, space)
    return x, y, pot.plant_height


# --------------------------------------------------------------------------- 설정 파일
def load_config(path: str) -> Config:
    """YAML → Config. 없는 값은 기본값으로 두되, 격자를 벗어난 화분은 거부한다."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    s = raw.get("space") or {}
    space = Space(width=float(s["width"]), depth=float(s["depth"]),
                  height=float(s["height"]))

    g = raw.get("grid") or {}
    grid = Grid(rows=int(g.get("rows", 5)), cols=int(g.get("cols", 10)),
                row_spacing=float(g["row_spacing"]), col_spacing=float(g["col_spacing"]))

    lights = []
    for i, L in enumerate(raw.get("lights") or []):
        pos = L["position"]
        if len(pos) != 3:
            raise ValueError(f"lights[{i}].position 은 [x, y, z] 세 값이어야 합니다.")
        lights.append(Light(position=(float(pos[0]), float(pos[1]), float(pos[2])),
                            ppf=float(L["ppf"]), beam_angle=float(L["beam_angle"])))

    pots = []
    for i, P in enumerate(raw.get("pots") or []):
        rc = P["grid_position"]
        row, col = int(rc[0]), int(rc[1])
        if not (0 <= row < grid.rows and 0 <= col < grid.cols):
            raise ValueError(
                f"pots[{i}] 의 격자 위치 ({row}, {col}) 가 "
                f"{grid.rows}x{grid.cols} 격자를 벗어납니다.")
        pots.append(Pot(grid_position=(row, col),
                        plant_height=float(P["plant_height"]),
                        canopy_radius=float(P["canopy_radius"]),
                        leaf_area_index=float(P["leaf_area_index"])))

    seen = {}
    for p in pots:
        if p.grid_position in seen:
            raise ValueError(f"격자 위치 {p.grid_position} 에 화분이 둘입니다.")
        seen[p.grid_position] = p

    o = raw.get("optimize") or {}
    d = SAParams()
    sa = SAParams(initial_temp=float(o.get("initial_temp", d.initial_temp)),
                  cooling_rate=float(o.get("cooling_rate", d.cooling_rate)),
                  iterations=int(o.get("iterations", d.iterations)),
                  seeds=int(o.get("seeds", d.seeds)),
                  w_cv=float(o.get("w_cv", d.w_cv)),
                  w_mean=float(o.get("w_mean", d.w_mean)))
    if not 0.0 < sa.cooling_rate < 1.0:
        raise ValueError("optimize.cooling_rate 는 0 과 1 사이여야 합니다 "
                         f"(받은 값 {sa.cooling_rate}). 1 이면 식지 않습니다.")
    if sa.iterations < 1 or sa.seeds < 1:
        raise ValueError("optimize.iterations 와 optimize.seeds 는 1 이상이어야 합니다.")

    return Config(space=space, grid=grid, lights=lights, pots=pots,
                  photoperiod_hours=float(raw.get("photoperiod_hours", 16.0)),
                  extinction_k=float(raw.get("extinction_k", 0.7)),
                  label=str(raw.get("label", "layout")), sa=sa)
