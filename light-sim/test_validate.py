"""validate.py 단위 테스트 — CSV 읽기, 예측, 지표.

    pytest -q

지표는 손으로 답을 아는 작은 배열로 건다. 검증 스크립트가 틀리면 멀쩡한 모델을
버리거나 틀린 모델을 믿게 되므로, 여기가 조용히 틀리는 게 제일 나쁘다.
"""

import math

import numpy as np
import pytest

from geometry import Config, Grid, Light, Pot, Space
from validate import (Measurement, diagnose, load_measurements, metrics, predict,
                      wall_distance, wall_trend, worst_points)


def _cfg(pots=None, lights=None):
    return Config(space=Space(2.0, 1.0, 2.0),
                  grid=Grid(rows=2, cols=3, row_spacing=0.3, col_spacing=0.3),
                  lights=lights or [Light(position=(1.0, 0.5, 1.8), ppf=500, beam_angle=140)],
                  pots=pots or [], label="v")


def _csv(tmp_path, text):
    p = tmp_path / "m.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── CSV 읽기 ──────────────────────────────────────────────────────────────
def test_reads_explicit_coordinates(tmp_path):
    path = _csv(tmp_path, "label,x,y,z,ppfd\nA,0.5,0.4,0.3,210\nB,1.5,0.6,0.3,180\n")
    got = load_measurements(path, _cfg())
    assert [m.label for m in got] == ["A", "B"]
    assert (got[0].x, got[0].y, got[0].z, got[0].measured) == (0.5, 0.4, 0.3, 210.0)


def test_reads_grid_cells_and_places_them_like_the_simulator(tmp_path):
    """row/col 로 적으면 시뮬레이터와 **같은** 좌표 계산을 타야 한다.

    줄자로 xy 를 재 적으면 그 자체가 오차다. 화분 자리에서 쟀다면 칸으로 적는 게
    정확하다 — 그래서 pot_xy 와 같은 값이 나와야 한다.
    """
    path = _csv(tmp_path, "row,col,z,ppfd\n0,1,0.3,200\n")
    m = load_measurements(path, _cfg())[0]
    assert (m.x, m.y) == pytest.approx((1.0, 0.35))     # 2x3 격자의 (0,1)


def test_labels_are_filled_in_when_missing(tmp_path):
    path = _csv(tmp_path, "x,y,z,ppfd\n0.5,0.4,0.3,210\n0.6,0.4,0.3,205\n")
    assert [m.label for m in load_measurements(path, _cfg())] == ["P1", "P2"]


def test_comment_lines_are_skipped(tmp_path):
    path = _csv(tmp_path, "# 이건 합성 데이터\n# 두 번째 주석\nx,y,z,ppfd\n0.5,0.4,0.3,210\n")
    assert len(load_measurements(path, _cfg())) == 1


def test_a_missing_column_is_reported_clearly(tmp_path):
    path = _csv(tmp_path, "x,y,z\n0.5,0.4,0.3\n")
    with pytest.raises(ValueError, match="ppfd"):
        load_measurements(path, _cfg())


def test_a_bad_number_names_the_line_and_column(tmp_path):
    path = _csv(tmp_path, "x,y,z,ppfd\n0.5,0.4,0.3,아니오\n")
    with pytest.raises(ValueError, match="ppfd"):
        load_measurements(path, _cfg())


def test_a_grid_cell_outside_the_grid_is_rejected(tmp_path):
    path = _csv(tmp_path, "row,col,z,ppfd\n0,9,0.3,200\n")
    with pytest.raises(ValueError, match="벗어납니다"):
        load_measurements(path, _cfg())


def test_an_empty_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="데이터 줄이 없습니다"):
        load_measurements(_csv(tmp_path, "x,y,z,ppfd\n"), _cfg())


# ── 예측 ──────────────────────────────────────────────────────────────────
def test_the_sensor_is_not_shaded_by_the_plant_it_sits_on():
    """캐노피 꼭대기에 올린 광량계가 그 캐노피에 가려지면 안 된다.

    선분이 제 원기둥 끝점에 닿아 '통과' 로 잡히는 경우다. compute_ppfd 가 화분
    자신을 빼는 것과 같은 이유로, 센서가 얹힌 화분도 빼야 한다.
    """
    pot = Pot((0, 1), plant_height=0.4, canopy_radius=0.15, leaf_area_index=4.0)
    cfg = _cfg([pot])
    on_top = Measurement("A", 1.0, 0.35, 0.4, 0.0)      # (0,1) 바로 위
    values, inside = predict(cfg, [on_top])
    assert inside == 1
    assert values[0] > 0
    # 화분이 아예 없을 때와 같은 값이어야 한다
    bare, _ = predict(_cfg([]), [on_top])
    assert values[0] == pytest.approx(bare[0])


def test_a_neighbouring_plant_still_shades_the_sensor():
    """자기 화분만 빼는 것이지, 옆 화분까지 빼면 차폐를 통째로 잃는다."""
    here = Pot((0, 1), 0.4, 0.15, 4.0)
    tall = Pot((0, 0), 1.5, 0.15, 4.0)
    side = [Light(position=(0.2, 0.35, 1.6), ppf=500, beam_angle=170)]
    sensor = Measurement("A", 1.0, 0.35, 0.4, 0.0)
    alone, _ = predict(_cfg([here], side), [sensor])
    with_tall, _ = predict(_cfg([here, tall], side), [sensor])
    assert with_tall < alone


def test_a_sensor_outside_every_canopy_counts_none_as_inside():
    cfg = _cfg([Pot((0, 0), 0.4, 0.10, 2.0)])
    far = Measurement("A", 1.9, 0.9, 0.3, 0.0)
    _, inside = predict(cfg, [far])
    assert inside == 0


# ── 지표 ──────────────────────────────────────────────────────────────────
def test_a_perfect_prediction_scores_one():
    v = np.array([100.0, 200.0, 300.0])
    m = metrics(v, v)
    assert m["r2"] == pytest.approx(1.0)
    assert m["rmse"] == pytest.approx(0.0) and m["mae"] == pytest.approx(0.0)
    assert m["bias"] == pytest.approx(0.0)
    assert m["slope"] == pytest.approx(1.0)


def test_rmse_and_mae_are_what_they_say():
    pred = np.array([110.0, 190.0])
    meas = np.array([100.0, 200.0])
    m = metrics(pred, meas)
    assert m["mae"] == pytest.approx(10.0)
    assert m["rmse"] == pytest.approx(10.0)
    assert m["bias"] == pytest.approx(0.0)          # +10 과 -10 이 상쇄
    assert m["max_abs_err"] == pytest.approx(10.0)


def test_rmse_punishes_one_big_miss_more_than_mae():
    """이게 뒤집히면 RMSE 를 볼 이유가 없다."""
    even = metrics(np.array([110.0, 110.0]), np.array([100.0, 100.0]))
    spiky = metrics(np.array([120.0, 100.0]), np.array([100.0, 100.0]))
    assert even["mae"] == pytest.approx(spiky["mae"])
    assert spiky["rmse"] > even["rmse"]


def test_bias_keeps_its_sign():
    low = metrics(np.array([90.0, 180.0]), np.array([100.0, 200.0]))
    assert low["bias"] < 0                          # 과소평가는 음수


def test_r2_is_against_the_one_to_one_line_not_a_fitted_line():
    """전부 30% 낮은 예측 — 상관은 완벽하지만 값은 다 틀렸다.

    회귀선을 새로 맞춘 r² 이면 1.0 이 나온다. 검증에서 알고 싶은 건 '비례하나'
    가 아니라 '그 값이 맞나' 라서 1:1 기준이어야 한다.
    """
    meas = np.array([100.0, 200.0, 300.0])
    m = metrics(meas * 0.7, meas)
    assert m["r2"] < 0.5
    assert m["slope"] == pytest.approx(1.0 / 0.7)   # 기울기는 비례를 잡아낸다
    assert np.corrcoef(meas * 0.7, meas)[0, 1] == pytest.approx(1.0)


def test_r2_can_go_negative():
    """실측 평균을 쓰느니만 못한 예측 — 음수가 정상이고, 숨기면 안 된다."""
    m = metrics(np.array([300.0, 100.0]), np.array([100.0, 300.0]))
    assert m["r2"] < 0


def test_the_slope_says_how_much_the_model_is_missing():
    meas = np.array([120.0, 240.0, 360.0])
    assert metrics(meas / 1.25, meas)["slope"] == pytest.approx(1.25)


def test_metrics_survive_a_single_point():
    m = metrics(np.array([180.0]), np.array([200.0]))
    assert m["rmse"] == pytest.approx(20.0)
    assert math.isnan(m["r2"])                      # 분산이 0 이라 정의가 없다
    assert math.isnan(m["slope"])


# ── 오차가 큰 지점 ────────────────────────────────────────────────────────
def test_worst_points_are_sorted_by_absolute_error():
    pts = [Measurement(f"P{i}", 0.0, 0.0, 0.3, 0.0) for i in range(4)]
    pred = np.array([100.0, 100.0, 100.0, 100.0])
    meas = np.array([105.0, 130.0, 100.0, 80.0])    # 오차 -5, -30, 0, +20
    assert worst_points(pts, pred, meas, 2) == [1, 3]


def test_asking_for_more_worst_points_than_exist_is_fine():
    pts = [Measurement("P1", 0.0, 0.0, 0.3, 0.0)]
    assert len(worst_points(pts, np.array([1.0]), np.array([2.0]), 9)) == 1


# ── 벽 거리 진단 ──────────────────────────────────────────────────────────
def test_wall_distance_finds_the_nearest_of_four_walls():
    cfg = _cfg()                                    # 2.0 x 1.0 공간
    d = wall_distance([Measurement("A", 0.2, 0.5, 0.3, 0.0),
                       Measurement("B", 1.0, 0.1, 0.3, 0.0)], cfg)
    assert d == pytest.approx([0.2, 0.1])


def test_wall_trend_catches_errors_that_grow_near_the_walls():
    """반사가 빠지면 벽 가까운 곳이 더 모자란다 — 그 모양을 잡아내야 한다."""
    cfg = _cfg()
    pts = [Measurement(f"P{i}", x, 0.5, 0.3, 0.0)
           for i, x in enumerate([0.05, 0.25, 0.5, 0.75, 1.0])]
    meas = np.array([200.0, 200.0, 200.0, 200.0, 200.0])
    pred = np.array([150.0, 165.0, 180.0, 195.0, 200.0])   # 벽에 가까울수록 더 모자람
    assert wall_trend(pts, pred, meas, cfg) > 0.9


def test_wall_trend_is_nan_when_there_is_nothing_to_correlate():
    cfg = _cfg()
    pts = [Measurement("A", 0.5, 0.5, 0.3, 0.0), Measurement("B", 0.6, 0.5, 0.3, 0.0)]
    assert math.isnan(wall_trend(pts, np.array([1.0, 2.0]), np.array([1.0, 2.0]), cfg))


# ── 진단 문장 ─────────────────────────────────────────────────────────────
def test_a_low_model_is_blamed_on_the_missing_reflection():
    meas = np.array([200.0, 220.0, 240.0])
    notes = " ".join(diagnose(metrics(meas * 0.8, meas), _cfg()))
    assert "낮게 본다" in notes and "반사" in notes


def test_a_high_model_points_at_the_light_settings():
    meas = np.array([200.0, 220.0, 240.0])
    notes = " ".join(diagnose(metrics(meas * 1.25, meas), _cfg()))
    assert "높게 본다" in notes and "ppf" in notes


def test_a_good_fit_is_not_talked_out_of():
    meas = np.array([200.0, 220.0, 240.0, 210.0, 230.0])
    notes = " ".join(diagnose(metrics(meas * 1.01, meas), _cfg()))
    assert "편향은" in notes
    assert "낮게 본다" not in notes and "높게 본다" not in notes


def test_a_negative_r2_is_called_out():
    notes = " ".join(diagnose(metrics(np.array([300.0, 100.0]),
                                      np.array([100.0, 300.0])), _cfg()))
    assert "R² 가 음수" in notes


def test_too_few_points_gets_a_warning():
    notes = " ".join(diagnose(metrics(np.array([200.0]), np.array([200.0])), _cfg()))
    assert "크게 믿을 수 없다" in notes
