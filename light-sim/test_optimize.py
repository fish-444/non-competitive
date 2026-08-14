"""optimize.py 단위 테스트 — 목적함수, 이웃해, SA.

    pytest -q

SA 는 무작위라 "정답" 을 박을 수 없다. 대신 **어겨서는 안 되는 성질**을 건다:
화분이 사라지거나 늘지 않을 것, 같은 칸에 둘이 겹치지 않을 것, 같은 시드면 같은
답일 것, 그리고 시작 배치보다 나빠지지 않을 것. 이게 깨지면 아무리 좋은 점수가
나와도 그 배치는 실제로 놓을 수 없는 배치다.
"""

import math
import random

import numpy as np
import pytest

from geometry import Config, Grid, Light, Pot, SAParams, Space
from optimize import (anneal, anneal_multi, best_of, calibrate_temperature, evaluate,
                      format_grid, layout_grid, score_of, spread, _free_cells, _swapped)


def _cfg(pots, rows=3, cols=4, lights=None):
    return Config(space=Space(2.0, 1.5, 2.0),
                  grid=Grid(rows=rows, cols=cols, row_spacing=0.3, col_spacing=0.3),
                  lights=lights or [Light(position=(1.0, 0.75, 1.8), ppf=600, beam_angle=120)],
                  pots=pots, photoperiod_hours=16.0, extinction_k=0.7, label="t",
                  sa=SAParams(iterations=300, seeds=2))


def _mixed(rows=3, cols=4, n=9):
    """키가 제각각인 배치 — 재배치할 여지가 있어야 최적화가 할 일이 생긴다."""
    cells = [(r, c) for r in range(rows) for c in range(cols)][:n]
    return [Pot(grid_position=cell, plant_height=0.15 + 0.12 * (i % 5),
                canopy_radius=0.10 + 0.01 * (i % 3),
                leaf_area_index=1.0 + 0.5 * (i % 4))
            for i, cell in enumerate(cells)]


# ── 목적함수 ──────────────────────────────────────────────────────────────
def test_score_is_just_cv_when_the_mean_has_no_weight():
    ppfd = np.array([[100.0, 200.0, np.nan]])
    s, cv, mean = score_of(ppfd, w_cv=1.0, w_mean=0.0)
    assert s == pytest.approx(cv)
    assert mean == pytest.approx(150.0)


def test_the_mean_enters_as_a_reciprocal_so_bigger_is_better():
    """평균이 클수록 점수가 작아져야 한다 — 두 항이 같은 방향을 봐야 더할 수 있다."""
    dim = np.array([[100.0, 200.0]])
    bright = dim * 2.0                       # CV 는 그대로, 평균만 두 배
    s_dim, _, _ = score_of(dim, w_cv=1.0, w_mean=100.0)
    s_bright, _, _ = score_of(bright, w_cv=1.0, w_mean=100.0)
    assert s_bright < s_dim


def test_weights_actually_trade_off():
    """CV 는 낮지만 어두운 배치 vs CV 는 높지만 밝은 배치 — 가중치가 순위를 뒤집는다."""
    even_dim = np.array([[100.0, 100.0]])         # CV 0,    평균 100
    uneven_bright = np.array([[300.0, 500.0]])    # CV 0.25, 평균 400
    only_cv = (score_of(even_dim, 1.0, 0.0)[0], score_of(uneven_bright, 1.0, 0.0)[0])
    with_mean = (score_of(even_dim, 1.0, 100.0)[0], score_of(uneven_bright, 1.0, 100.0)[0])
    assert only_cv[0] < only_cv[1]                # 균일도만 보면 어두운 쪽 승
    assert with_mean[0] > with_mean[1]            # 총량을 얹으면 뒤집힌다


def test_an_empty_layout_scores_infinity():
    """화분이 없으면 비교 대상이 아니다 — SA 가 절대 고르지 않게 무한대."""
    s, _, _ = score_of(np.array([[np.nan, np.nan]]), 1.0, 0.0)
    assert s == float("inf")


# ── 이웃해 ────────────────────────────────────────────────────────────────
def test_a_swap_keeps_every_pot_exactly_once():
    """화분이 사라지거나 복제되면 안 된다 — 점수만 좋고 놓을 수 없는 배치가 된다."""
    cfg = _cfg(_mixed())
    cells = _free_cells(cfg)
    rng = random.Random(0)
    pots = list(cfg.pots)
    before = sorted((p.plant_height, p.canopy_radius, p.leaf_area_index) for p in pots)
    for _ in range(300):
        cand = _swapped(pots, cells, rng)
        if cand is None:
            continue
        pots = cand
        assert len(pots) == len(cfg.pots)
        assert sorted((p.plant_height, p.canopy_radius, p.leaf_area_index)
                      for p in pots) == before
        assert len({p.grid_position for p in pots}) == len(pots)   # 한 칸에 둘 금지


def test_a_swap_can_move_a_pot_into_an_empty_cell():
    """빈 칸을 못 쓰면 화분이 칸보다 적을 때 탐색 공간의 절반이 닫힌다."""
    cfg = _cfg([Pot((0, 0), 0.3, 0.1, 1.0)], rows=1, cols=3)
    cells = _free_cells(cfg)
    seen = set()
    rng = random.Random(1)
    for _ in range(200):
        cand = _swapped(cfg.pots, cells, rng)
        if cand:
            seen.add(cand[0].grid_position)
    assert seen == {(0, 1), (0, 2)}          # 빈 칸 두 곳 모두에 가 봤다


def test_swapping_two_empty_cells_is_rejected():
    cfg = _cfg([Pot((0, 0), 0.3, 0.1, 1.0)], rows=1, cols=3)
    rng = random.Random(2)
    assert _swapped(cfg.pots, [(0, 1), (0, 2)], rng) is None


# ── 온도 보정 ─────────────────────────────────────────────────────────────
def test_the_calibrated_temperature_is_positive_and_scales_with_the_objective():
    """목적함수 크기가 달라지면 온도도 같이 따라와야 한다 — 고정값이면 못 따라온다."""
    cfg = _cfg(_mixed())
    t_cv = calibrate_temperature(cfg, SAParams(w_cv=1.0, w_mean=0.0), random.Random(0))
    t_big = calibrate_temperature(cfg, SAParams(w_cv=50.0, w_mean=0.0), random.Random(0))
    assert t_cv > 0
    assert t_big == pytest.approx(t_cv * 50.0, rel=1e-9)


def test_calibration_does_not_blow_up_when_nothing_can_change():
    """화분이 모두 똑같으면 교환해도 점수가 안 변한다 — 0 으로 나누면 안 된다."""
    same = [Pot((0, c), 0.3, 0.12, 2.0) for c in range(4)]
    t = calibrate_temperature(_cfg(same, rows=1), SAParams(), random.Random(0))
    assert t > 0 and math.isfinite(t)


# ── SA ────────────────────────────────────────────────────────────────────
def test_the_same_seed_gives_the_same_answer():
    cfg = _cfg(_mixed())
    a, b = anneal(cfg, seed=7), anneal(cfg, seed=7)
    assert a.score == b.score
    assert [p.grid_position for p in a.pots] == [p.grid_position for p in b.pots]


def test_different_seeds_explore_differently():
    cfg = _cfg(_mixed())
    a, b = anneal(cfg, seed=0), anneal(cfg, seed=1)
    assert not np.array_equal(a.history, b.history)


def test_annealing_never_returns_something_worse_than_the_start():
    """시작 배치를 늘 후보에 두므로 최악이 현상 유지다. 이게 깨지면 쓸 수 없다."""
    cfg = _cfg(_mixed())
    for seed in range(4):
        run = anneal(cfg, seed=seed)
        assert run.score <= run.initial_score + 1e-12


def test_annealing_actually_improves_a_deliberately_bad_layout():
    """키 큰 포기를 광원 아래 몰아 둔 배치 — 고칠 여지가 확실히 있다."""
    pots = ([Pot((1, c), 1.10, 0.14, 3.0) for c in range(4)]        # 가운데 줄에 큰 놈들
            + [Pot((0, c), 0.18, 0.14, 1.0) for c in range(4)]
            + [Pot((2, c), 0.18, 0.14, 1.0) for c in range(4)])
    cfg = _cfg(pots)
    run = anneal(cfg, seed=0, params=SAParams(iterations=1200))
    assert run.score < run.initial_score * 0.95


def test_the_returned_layout_is_a_real_permutation_of_the_input():
    cfg = _cfg(_mixed())
    run = anneal(cfg, seed=3)
    key = lambda p: (p.plant_height, p.canopy_radius, p.leaf_area_index)
    assert sorted(map(key, run.pots)) == sorted(map(key, cfg.pots))
    assert len({p.grid_position for p in run.pots}) == len(run.pots)
    for p in run.pots:
        assert 0 <= p.row < cfg.grid.rows and 0 <= p.col < cfg.grid.cols


def test_the_reported_score_matches_a_fresh_evaluation():
    """기록된 점수와 그 배치를 다시 재 본 점수가 달라지면 어딘가 새고 있는 것이다."""
    cfg = _cfg(_mixed())
    run = anneal(cfg, seed=5)
    s, cv, mean = evaluate(cfg, run.pots, cfg.sa)
    assert s == pytest.approx(run.score)
    assert cv == pytest.approx(run.cv) and mean == pytest.approx(run.mean_ppfd)


def test_the_history_has_one_entry_per_iteration_plus_the_start():
    cfg = _cfg(_mixed())
    run = anneal(cfg, seed=0, params=SAParams(iterations=250))
    assert run.history.shape == (251,)
    assert run.history[0] == run.initial_score


def test_the_best_curve_only_goes_down():
    """수렴 그래프에 쓰는 곡선 — 현재 점수는 오르내려도 최고 기록은 단조롭다."""
    run = anneal(_cfg(_mixed()), seed=0)
    curve = run.best_curve
    assert np.all(np.diff(curve) <= 1e-12)
    assert curve[-1] == pytest.approx(run.score)


def test_a_hot_start_accepts_uphill_moves():
    """온도가 높으면 나빠지는 이동도 받아야 한다 — 안 그러면 그냥 greedy 다."""
    cfg = _cfg(_mixed())
    hot = anneal(cfg, seed=0, params=SAParams(initial_temp=10.0, cooling_rate=0.99999,
                                              iterations=400))
    cold = anneal(cfg, seed=0, params=SAParams(initial_temp=1e-9, cooling_rate=0.9993,
                                               iterations=400))
    assert hot.uphill > 0
    assert cold.uphill == 0


# ── 여러 시드 ─────────────────────────────────────────────────────────────
def test_multi_seed_runs_each_seed_once():
    runs = anneal_multi(_cfg(_mixed()), SAParams(iterations=120), seeds=4)
    assert [r.seed for r in runs] == [0, 1, 2, 3]


def test_best_of_picks_the_lowest_score():
    runs = anneal_multi(_cfg(_mixed()), SAParams(iterations=120), seeds=3)
    assert best_of(runs).score == min(r.score for r in runs)


def test_spread_reports_zero_when_every_seed_lands_together():
    cfg = _cfg(_mixed())
    one = anneal(cfg, seed=0, params=SAParams(iterations=120))
    sp = spread([one, one, one])
    assert sp["cv_std"] == pytest.approx(0.0)
    assert "지역 최적" in sp["verdict"]


def test_spread_flags_a_wide_scatter():
    """편차가 크면 '아직 덜 식었다' 고 말해 줘야 한다 — 조용히 넘어가면 안 된다."""
    class Fake:
        def __init__(self, cv):
            self.cv, self.score = cv, cv
    sp = spread([Fake(0.10), Fake(0.20), Fake(0.30)])
    assert sp["cv_rel_std"] > 0.05
    assert "갈린다" in sp["verdict"]


# ── 출력 ──────────────────────────────────────────────────────────────────
def test_the_layout_table_marks_empty_cells():
    cfg = _cfg([Pot((0, 0), 0.42, 0.1, 1.0)], rows=1, cols=3)
    table = layout_grid(cfg, cfg.pots)
    assert table == [["42", "·", "·"]]


def test_the_layout_table_can_show_lai_instead():
    cfg = _cfg([Pot((0, 0), 0.42, 0.1, 2.5)], rows=1, cols=3)
    assert layout_grid(cfg, cfg.pots, "lai")[0][0] == "2.5"


def test_the_printed_grid_lines_up():
    text = format_grid([["5", "40"], ["7", "8"]])
    rows = text.splitlines()
    assert len(rows) == 3                                  # 머리글 + 두 줄
    assert len({len(r) for r in rows}) == 1                # 폭이 다 같다
