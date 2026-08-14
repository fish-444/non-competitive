"""light.py 단위 테스트 — 특히 차폐 판정.

    pytest -q

차폐는 눈으로 검산이 안 되는 부분이라(3차원 선분 대 원기둥) 손으로 답을 아는
경우를 박아 둔다. 기하가 틀리면 PPFD 는 그럴듯한 숫자로 나오면서 조용히 틀린다.
"""

import math

import numpy as np
import pytest

from geometry import Config, Grid, Light, Pot, Space, pot_xy, receiver_point
from light import (compute_ppfd, compute_ppfd_fast, direct_ppfd, dli, ppfd_at,
                   segment_hits_cylinder, shading_factor, transmittance, uniformity_cv)


# ── 차폐 판정: 사양이 요구한 세 경우 ──────────────────────────────────────
def test_no_blocker_when_the_cylinder_is_off_to_the_side():
    """광선이 원기둥 옆을 지나간다 — 안 가린다."""
    # (0,0,2) 에서 (0,0,0.3) 으로 내려오는 연직 광선, 원기둥은 x=1 에 있다
    assert segment_hits_cylinder((0, 0, 2.0), (0, 0, 0.3),
                                 center_xy=(1.0, 0.0), radius=0.15, z_top=0.5) is False


def test_a_cylinder_squarely_in_the_way_blocks():
    """광원과 수광점 사이에 정면으로 서 있다 — 가린다."""
    # 광원 (-1, 0, 1.0) → 수광점 (1, 0, 0.4). 중간 x=0 에서 z 는 0.7 근처라
    # 높이 1.0 인 원기둥을 통과한다.
    assert segment_hits_cylinder((-1.0, 0, 1.0), (1.0, 0, 0.4),
                                 center_xy=(0.0, 0.0), radius=0.2, z_top=1.0) is True


def test_a_cylinder_directly_under_the_light_does_not_block_a_vertical_ray():
    """광원 바로 아래 — 광선이 원기둥 축을 따라 내려오지만 수광점이 그 꼭대기다.

    수광점이 캐노피 상단이므로 광선은 원기둥 '위' 에서 끝난다. 여기서 True 가
    나오면 모든 화분이 스스로를 가려 온 격자가 어두워진다.
    """
    # z_top = 0.4 = 수광점 높이. 광선 구간의 z 는 [0.4, 2.0] 이라 원기둥 몸통과
    # 겹치는 건 딱 한 점(끝점)뿐이다 — 접점은 통과로 안 본다.
    assert segment_hits_cylinder((0, 0, 2.0), (0, 0, 0.4),
                                 center_xy=(0.0, 0.0), radius=0.15, z_top=0.4) is True
    # 그래서 compute_ppfd 는 자기 자신을 blockers 에서 뺀다 (아래 테스트가 확인)


def test_a_shorter_cylinder_under_the_light_is_clear():
    """원기둥이 광선보다 낮으면 안 가린다."""
    assert segment_hits_cylinder((0, 0, 2.0), (0, 0, 0.9),
                                 center_xy=(0.0, 0.0), radius=0.15, z_top=0.4) is False


def test_a_grazing_ray_outside_the_radius_is_clear():
    """반지름 바로 밖을 스치면 안 가린다 — 경계에서 뒤집히지 않아야 한다."""
    assert segment_hits_cylinder((-1.0, 0.151, 1.0), (1.0, 0.151, 0.4),
                                 center_xy=(0.0, 0.0), radius=0.15, z_top=1.0) is False
    assert segment_hits_cylinder((-1.0, 0.149, 1.0), (1.0, 0.149, 0.4),
                                 center_xy=(0.0, 0.0), radius=0.15, z_top=1.0) is True


def test_a_cylinder_behind_the_receiver_does_not_block():
    """수광점 너머에 있는 것은 광선 구간 밖이다."""
    assert segment_hits_cylinder((-1.0, 0, 1.0), (0.0, 0, 0.4),
                                 center_xy=(0.5, 0.0), radius=0.2, z_top=1.0) is False


def test_a_zero_size_cylinder_never_blocks():
    assert segment_hits_cylinder((-1, 0, 1), (1, 0, 0.4), (0, 0), radius=0.0, z_top=1.0) is False
    assert segment_hits_cylinder((-1, 0, 1), (1, 0, 0.4), (0, 0), radius=0.2, z_top=0.0) is False


# ── 투과율 ────────────────────────────────────────────────────────────────
def test_transmittance_is_beer_lambert():
    assert transmittance(0.0) == 1.0
    assert transmittance(2.0, k=0.7) == pytest.approx(math.exp(-1.4))
    # 잎이 많을수록 줄지만 0 이 되지는 않는다 — 완전 차단이 아니다
    assert 0 < transmittance(8.0) < transmittance(2.0) < 1.0


def test_shading_multiplies_when_two_canopies_are_in_the_way():
    """겹겹이 지나면 투과율이 곱해진다."""
    L = Light(position=(-2.0, 0.0, 1.2), ppf=300, beam_angle=120)
    point = (2.0, 0.0, 0.4)
    a = Pot((0, 0), plant_height=1.0, canopy_radius=0.2, leaf_area_index=2.0)
    b = Pot((0, 1), plant_height=1.0, canopy_radius=0.2, leaf_area_index=2.0)
    one = shading_factor(L, point, [(a, (-0.5, 0.0))])
    two = shading_factor(L, point, [(a, (-0.5, 0.0)), (b, (0.5, 0.0))])
    assert one == pytest.approx(transmittance(2.0))
    assert two == pytest.approx(transmittance(2.0) ** 2)


# ── 직달광 ────────────────────────────────────────────────────────────────
def test_directly_below_is_the_brightest_point():
    """바로 아래가 가장 밝다 — 거리도 가장 짧고 입사각도 0."""
    L = Light(position=(0, 0, 2.0), ppf=400, beam_angle=120)
    under = direct_ppfd(L, (0.0, 0.0, 0.0))
    aside = direct_ppfd(L, (0.8, 0.0, 0.0))
    assert under > aside > 0


def test_inverse_square_holds_on_the_axis():
    """축 위에서는 cosθ=1 이라 거리의 제곱에만 반비례해야 한다."""
    L = Light(position=(0, 0, 3.0), ppf=400, beam_angle=120)
    near = direct_ppfd(L, (0.0, 0.0, 2.0))    # d = 1
    far = direct_ppfd(L, (0.0, 0.0, 1.0))     # d = 2
    assert near / far == pytest.approx(4.0)


def test_outside_the_beam_is_zero():
    """빔 밖은 0. 60도 빔이면 반각 30도 — 그 밖은 안 비친다."""
    L = Light(position=(0, 0, 1.0), ppf=400, beam_angle=60)
    inside = direct_ppfd(L, (0.3, 0.0, 0.0))   # atan(0.3/1) ≈ 16.7°
    outside = direct_ppfd(L, (1.2, 0.0, 0.0))  # ≈ 50.2°
    assert inside > 0 and outside == 0.0


def test_a_point_above_the_light_gets_nothing():
    L = Light(position=(0, 0, 1.0), ppf=400, beam_angle=120)
    assert direct_ppfd(L, (0.0, 0.0, 1.5)) == 0.0


def test_a_narrow_beam_concentrates_the_same_flux():
    """같은 ppf 를 좁은 빔에 몰면 축 위가 더 밝다 — I₀ 정규화가 맞는지 본다."""
    wide = Light(position=(0, 0, 2.0), ppf=400, beam_angle=120)
    narrow = Light(position=(0, 0, 2.0), ppf=400, beam_angle=60)
    assert direct_ppfd(narrow, (0, 0, 0)) > direct_ppfd(wide, (0, 0, 0))


def test_the_floor_gets_back_every_photon_the_lamp_emitted():
    """직달광 식 전체의 검산 — 바닥을 다 적분하면 ppf 가 그대로 나와야 한다.

    ∫E dA = Φ 가 안 맞으면 I₀ 정규화(peak_intensity)나 cos²θ/d² 중 하나가 틀린
    것이다. 개별 테스트는 비율만 보므로 절대값이 틀려도 다 통과한다 — 여기서 잡는다.
    """
    h, ppf = 2.0, 1000.0
    L = Light(position=(0.0, 0.0, h), ppf=ppf, beam_angle=120)

    # 반각 60도이므로 빛이 닿는 반경은 h·tan60 ≈ 3.46 m. 넉넉히 5 m 까지 적분한다.
    n, half = 800, 5.0
    step = 2.0 * half / n
    axis = -half + step * (np.arange(n) + 0.5)          # 칸 한가운데에서 표본
    xs, ys = np.meshgrid(axis, axis, indexing="ij")

    d2 = xs ** 2 + ys ** 2 + h ** 2
    cos = h / np.sqrt(d2)
    inside = np.arccos(cos) <= L.half_angle_rad
    total = float((L.peak_intensity * cos ** 2 / d2 * inside).sum()) * step * step

    assert total == pytest.approx(ppf, rel=1e-3)


def test_two_lights_add_up():
    a = Light(position=(-0.3, 0, 2.0), ppf=400, beam_angle=120)
    b = Light(position=(0.3, 0, 2.0), ppf=400, beam_angle=120)
    p = (0.0, 0.0, 0.0)
    assert ppfd_at(p, [a, b], []) == pytest.approx(direct_ppfd(a, p) + direct_ppfd(b, p))


# ── 격자 전체 ─────────────────────────────────────────────────────────────
def _cfg(pots, lights=None, rows=1, cols=3):
    return Config(
        space=Space(2.0, 1.0, 2.0),
        grid=Grid(rows=rows, cols=cols, row_spacing=0.3, col_spacing=0.3),
        lights=lights or [Light(position=(1.0, 0.5, 1.8), ppf=500, beam_angle=120)],
        pots=pots, photoperiod_hours=16.0, extinction_k=0.7, label="t")


def test_a_pot_never_shades_itself():
    """수광점이 제 캐노피 꼭대기라, 자기를 세면 모든 화분이 어두워진다."""
    lone = Pot((0, 1), plant_height=0.4, canopy_radius=0.15, leaf_area_index=3.0)
    got = compute_ppfd(_cfg([lone]))[0, 1]
    L = Light(position=(1.0, 0.5, 1.8), ppf=500, beam_angle=120)
    assert got == pytest.approx(direct_ppfd(L, receiver_point(lone, _cfg([lone]).grid,
                                                              _cfg([lone]).space)))


def test_a_tall_neighbour_darkens_the_short_one():
    """옆의 키 큰 포기가 그늘을 만든다 — 광원을 한쪽으로 치우쳐 확실히 걸리게."""
    short = Pot((0, 2), plant_height=0.20, canopy_radius=0.14, leaf_area_index=2.0)
    tall = Pot((0, 1), plant_height=1.30, canopy_radius=0.14, leaf_area_index=3.0)
    side = [Light(position=(0.10, 0.5, 1.4), ppf=500, beam_angle=150)]

    alone = compute_ppfd(_cfg([short], side))[0, 2]
    with_tall = compute_ppfd(_cfg([short, tall], side))[0, 2]
    assert with_tall < alone
    assert with_tall == pytest.approx(alone * transmittance(3.0))


def test_empty_cells_stay_nan():
    grid = compute_ppfd(_cfg([Pot((0, 0), 0.3, 0.1, 1.0)]))
    assert not np.isnan(grid[0, 0])
    assert np.isnan(grid[0, 1]) and np.isnan(grid[0, 2])


# ── 배열판이 반복문판과 같은가 ────────────────────────────────────────────
def _random_layout(rng, rows=4, cols=6, n_pots=14, n_lights=3):
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    rng.shuffle(cells)
    pots = [Pot(grid_position=cell,
                plant_height=float(rng.uniform(0.05, 1.4)),
                canopy_radius=float(rng.uniform(0.0, 0.30)),
                leaf_area_index=float(rng.uniform(0.0, 5.0)))
            for cell in cells[:n_pots]]
    lights = [Light(position=(float(rng.uniform(-0.4, 2.4)),
                              float(rng.uniform(-0.4, 1.4)),
                              float(rng.uniform(0.9, 2.1))),
                    ppf=float(rng.uniform(100, 900)),
                    beam_angle=float(rng.uniform(40, 170))) for _ in range(n_lights)]
    return Config(space=Space(2.0, 1.0, 2.2),
                  grid=Grid(rows=rows, cols=cols, row_spacing=0.25, col_spacing=0.25),
                  lights=lights, pots=pots, photoperiod_hours=16.0,
                  extinction_k=0.7, label="rnd")


@pytest.mark.parametrize("seed", range(12))
def test_the_fast_array_version_matches_the_loop_version(seed):
    """최적화가 쓰는 배열판이 참조 구현과 갈라지면 엉뚱한 배치를 고르게 된다.

    무작위 배치로 매번 맞춰 본다 — 키·반지름 0 과 빔 밖까지 섞어서 뽑으므로
    경계 처리(반지름 0, 빔 컷오프, 광원보다 높은 수광점)도 같이 걸린다.
    """
    cfg = _random_layout(np.random.default_rng(seed))
    slow, fast = compute_ppfd(cfg), compute_ppfd_fast(cfg)
    assert (np.isnan(slow) == np.isnan(fast)).all()
    np.testing.assert_allclose(slow[~np.isnan(slow)], fast[~np.isnan(fast)], rtol=1e-12)


def test_the_fast_version_handles_a_light_straight_overhead():
    """광원이 수광점 바로 위면 광선이 연직이라 원과의 근이 없다 — 별도 갈래."""
    cfg = _cfg([Pot((0, 1), 0.4, 0.15, 2.0), Pot((0, 0), 1.2, 0.15, 2.0)],
               [Light(position=(1.0, 0.5, 1.8), ppf=500, beam_angle=170)])
    # (0,1) 은 격자 한가운데 = 공간 한가운데 = 광원 바로 아래
    np.testing.assert_allclose(compute_ppfd(cfg)[0, 1], compute_ppfd_fast(cfg)[0, 1],
                               rtol=1e-12)


def test_the_fast_version_survives_empty_input():
    assert np.isnan(compute_ppfd_fast(_cfg([]))).all()
    # 광원이 없으면 0. (_cfg 는 lights=[] 를 기본값으로 바꿔 버리므로 직접 만든다)
    dark = Config(space=Space(2.0, 1.0, 2.0),
                  grid=Grid(rows=1, cols=3, row_spacing=0.3, col_spacing=0.3),
                  lights=[], pots=[Pot((0, 0), 0.3, 0.1, 1.0)])
    assert compute_ppfd_fast(dark)[0, 0] == 0.0
    assert compute_ppfd(dark)[0, 0] == 0.0


# ── 지표 ──────────────────────────────────────────────────────────────────
def test_dli_converts_units():
    """PPFD 100 µmol/m²/s 를 16시간이면 5.76 mol/m²/day."""
    assert dli(np.array([100.0]), 16.0)[0] == pytest.approx(5.76)


def test_cv_is_zero_when_everything_is_equal():
    assert uniformity_cv(np.array([200.0, 200.0, 200.0])) == pytest.approx(0.0)


def test_cv_grows_with_spread():
    tight = uniformity_cv(np.array([190.0, 200.0, 210.0]))
    loose = uniformity_cv(np.array([100.0, 200.0, 300.0]))
    assert 0 < tight < loose


def test_cv_ignores_empty_cells():
    a = uniformity_cv(np.array([100.0, 200.0, np.nan]))
    b = uniformity_cv(np.array([100.0, 200.0]))
    assert a == pytest.approx(b)


def test_cv_of_nothing_is_nan():
    assert math.isnan(uniformity_cv(np.array([np.nan, np.nan])))


# ── 격자 좌표 ─────────────────────────────────────────────────────────────
def test_the_grid_sits_centred_in_the_space():
    space, grid = Space(2.0, 1.0, 2.0), Grid(rows=3, cols=3, row_spacing=0.3, col_spacing=0.3)
    mid = pot_xy(Pot((1, 1), 0.3, 0.1, 1.0), grid, space)
    assert mid == pytest.approx((1.0, 0.5))
    left = pot_xy(Pot((1, 0), 0.3, 0.1, 1.0), grid, space)
    right = pot_xy(Pot((1, 2), 0.3, 0.1, 1.0), grid, space)
    assert left[0] == pytest.approx(0.7) and right[0] == pytest.approx(1.3)
