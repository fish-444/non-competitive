"""farm_bridge.py 단위 테스트 — 알로카시아팜 백업 환산.

    pytest -q

환산이 조용히 틀리면 시뮬레이터는 멀쩡한 숫자를 내면서 다른 선반을 계산한다.
특히 단위와 좌표계가 위험하다 — cm/m, 반각/전체각, (x,높이,깊이)/(x,깊이,높이).
"""

import json
import math

import pytest

import farm_bridge as fb


def _plant(**kw):
    base = {"id": "p1", "name": "테스트", "pos": "A1", "size_class": "중품",
            "canopy_cm": 30.0, "leaf_max_cm": 15.0, "leaf_count": 8}
    base.update(kw)
    return base


def _backup(tmp_path, plants, pots):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({
        "kind": "alocasia-farm-backup", "version": 1,
        "state": {"plants": plants, "pots": pots}}, ensure_ascii=False),
        encoding="utf-8")
    return str(path)


# ── 백업 읽기 ─────────────────────────────────────────────────────────────
def test_reads_a_backup(tmp_path):
    path = _backup(tmp_path, {"p1": _plant()}, [{"slot": "A1", "u": .3, "v": .5}])
    plants, pots = fb.load_backup(path)
    assert list(plants) == ["p1"] and pots[0]["slot"] == "A1"


def test_a_foreign_json_is_rejected(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"kind": "다른앱"}', encoding="utf-8")
    with pytest.raises(ValueError, match="백업 파일이 아닙니다"):
        fb.load_backup(str(path))


def test_a_backup_without_pots_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="화분 자리"):
        fb.load_backup(_backup(tmp_path, {"p1": _plant()}, []))


# ── 최신 실측값 ───────────────────────────────────────────────────────────
def test_top_level_fields_win_over_the_growth_log():
    p = _plant(canopy_cm=30.0, growth_log=[{"on": "2026-01-01", "canopy_cm": 10.0}])
    assert fb.measurements(p)["canopy_cm"] == 30.0


def test_the_growth_log_fills_in_what_the_top_level_lacks():
    """옛 백업은 최상위가 비고 기록만 있다 — 값을 통째로 잃으면 안 된다."""
    p = {"id": "p1", "pos": "A1",
         "growth_log": [{"on": "2026-01-01", "canopy_cm": 12.0},
                        {"on": "2026-06-01", "canopy_cm": 22.0, "leaf_count": 9}]}
    m = fb.measurements(p)
    assert m["canopy_cm"] == 22.0                 # 마지막 기록
    assert m["leaf_count"] == 9


def test_no_measurements_at_all_gives_nones():
    assert all(v is None for v in fb.measurements({"id": "p1"}).values())


# ── LAI ───────────────────────────────────────────────────────────────────
def test_lai_is_leaf_area_over_ground_area():
    """정의 그대로인지 손으로 계산해 맞춰 본다."""
    got = fb.estimate_lai(leaf_count=10, leaf_max_cm=20.0, canopy_radius_cm=20.0)
    mean_leaf = fb.MEAN_OVER_MAX_LEAF * 20.0
    expect = 10 * fb.LEAF_AREA_FACTOR * mean_leaf ** 2 / (math.pi * 400.0)
    assert got == pytest.approx(expect)


def test_more_leaves_means_more_lai():
    a = fb.estimate_lai(5, 15.0, 15.0)
    b = fb.estimate_lai(10, 15.0, 15.0)
    assert b == pytest.approx(2 * a)


def test_a_wider_canopy_with_the_same_leaves_means_less_lai():
    """같은 잎이 넓게 퍼지면 겹침이 줄어 덜 가린다."""
    tight = fb.estimate_lai(8, 15.0, 12.0)
    wide = fb.estimate_lai(8, 15.0, 24.0)
    assert wide < tight


def test_lai_is_clamped_to_something_physical():
    assert fb.estimate_lai(1, 1.0, 30.0) == fb.LAI_MIN
    assert fb.estimate_lai(400, 30.0, 5.0) == fb.LAI_MAX


def test_lai_is_none_without_the_inputs():
    assert fb.estimate_lai(None, 15.0, 15.0) is None
    assert fb.estimate_lai(8, None, 15.0) is None
    assert fb.estimate_lai(8, 15.0, 0.0) is None


# ── 크기 환산 ─────────────────────────────────────────────────────────────
def test_the_canopy_radius_is_half_the_measured_canopy():
    r, _, _, notes = fb.plant_size(_plant(canopy_cm=30.0), {})
    assert r == pytest.approx(15.0)
    assert "캐노피=실측" in notes


def test_leaf_length_stands_in_when_the_canopy_was_not_measured():
    """잎자루가 사방으로 뻗으니 잎 길이가 곧 우산 반지름이다 (placement.py 와 같은 규칙)."""
    r, _, _, notes = fb.plant_size(_plant(canopy_cm=None, leaf_max_cm=13.0), {})
    assert r == pytest.approx(13.0)
    assert "캐노피=잎길이" in notes


def test_the_grade_is_the_last_resort():
    r, h, _, notes = fb.plant_size(
        {"size_class": "대품", "canopy_cm": None, "leaf_max_cm": None}, {})
    assert (r, h) == fb.GRADE_SHAPE["대품"]
    assert "캐노피=등급추정" in notes and "키=등급추정" in notes


def test_a_measured_height_beats_every_estimate():
    """키는 사진으로 못 재니 실측이 들어오면 무조건 그쪽이다."""
    _, h, _, notes = fb.plant_size(_plant(), {"height_cm": 41.0})
    assert h == pytest.approx(41.0)
    assert "키=실측" in notes


def test_an_unmeasured_height_is_flagged_as_an_estimate():
    _, _, _, notes = fb.plant_size(_plant(), {})
    assert "키=실측" not in notes


def test_overrides_reach_lai_and_canopy_too():
    r, _, lai, notes = fb.plant_size(_plant(), {"canopy_cm": 50.0, "lai": 2.75})
    assert r == pytest.approx(25.0) and lai == pytest.approx(2.75)
    assert "LAI=실측" in notes


# ── 조명 환산 ─────────────────────────────────────────────────────────────
def test_the_half_angle_is_doubled_into_a_full_beam_angle():
    """알로카시아팜의 angle 은 반각, light-sim 의 beam_angle 은 전체각이다.

    그냥 넘기면 빔이 절반으로 좁아져 가장자리가 통째로 어두워진다.
    """
    lights = fb.shelf_lights(ppf_each=200.0, height_cm=47.0, half_angle_deg=30.0)
    assert all(L["beam_angle"] == pytest.approx(60.0) for L in lights)


def test_the_lights_land_in_metres_with_depth_and_height_swapped():
    """placement.py 는 (x, 높이, 앞뒤), light-sim 은 (x, 앞뒤, 높이) 다."""
    lights = fb.shelf_lights(200.0, 47.0, 30.0, rail_margin_cm=8.0)
    assert len(lights) == 3
    for L in lights:
        x, y, z = L["position"]
        assert z == pytest.approx(0.47)                     # 높이가 세 번째
        assert 0 <= x <= fb.SHELF_W_CM / 100
        assert 0 <= y <= fb.SHELF_D_CM / 100
    xs = sorted(L["position"][0] for L in lights)
    assert xs[0] == pytest.approx(0.08) and xs[2] == pytest.approx(0.52)   # 좌우 레일


# ── 격자 ──────────────────────────────────────────────────────────────────
def test_the_grid_is_big_enough_for_every_pot():
    for n in range(1, 40):
        r, c = fb.choose_grid(n, None, None)
        assert r * c >= n


def test_an_explicit_grid_that_is_too_small_is_rejected():
    with pytest.raises(ValueError, match="안 들어갑니다"):
        fb.choose_grid(12, rows=2, cols=3)


def test_giving_only_one_dimension_fills_in_the_other():
    assert fb.choose_grid(12, rows=3, cols=None) == (3, 4)
    assert fb.choose_grid(12, rows=None, cols=6) == (2, 6)


def test_snapping_reads_the_shelf_row_by_row():
    """깊이로 줄을 나누고 줄 안에서 가로로 세운다 — 사람이 선반 보는 순서."""
    placed = [{"u": .8, "v": .1}, {"u": .2, "v": .1},
              {"u": .8, "v": .9}, {"u": .2, "v": .9}]
    fb.snap_to_grid(placed, rows=2, cols=2)
    assert (placed[1]["row"], placed[1]["col"]) == (0, 0)    # 앞줄 왼쪽
    assert (placed[0]["row"], placed[0]["col"]) == (0, 1)    # 앞줄 오른쪽
    assert (placed[3]["row"], placed[3]["col"]) == (1, 0)
    assert (placed[2]["row"], placed[2]["col"]) == (1, 1)


def test_every_pot_gets_a_cell_and_no_cell_gets_two():
    rng_pts = [{"u": (i * 0.13) % 1.0, "v": (i * 0.29) % 1.0} for i in range(11)]
    fb.snap_to_grid(rng_pts, rows=3, cols=4)
    cells = [(p["row"], p["col"]) for p in rng_pts]
    assert len(cells) == len(set(cells)) == 11


def test_a_partial_last_row_is_allowed():
    pts = [{"u": i / 5, "v": i / 5} for i in range(5)]
    fb.snap_to_grid(pts, rows=2, cols=3)
    assert sorted(p["row"] for p in pts) == [0, 0, 0, 1, 1]


def test_grid_xy_matches_the_simulator_centring_rule():
    """geometry.pot_xy 와 같은 규칙이어야 위치가 어긋나지 않는다."""
    from geometry import Grid, Pot, Space, pot_xy
    rows, cols, rs, cs = 3, 4, 12.0, 15.0
    for r in range(rows):
        for c in range(cols):
            gx, gy = fb.grid_xy_cm(r, c, rows, cols, rs, cs)
            sx, sy = pot_xy(Pot((r, c), 0, 0, 0),
                            Grid(rows, cols, rs / 100, cs / 100),
                            Space(fb.SHELF_W_CM / 100, fb.SHELF_D_CM / 100, 1.0))
            assert (gx / 100, gy / 100) == pytest.approx((sx, sy))


# ── 조립 ──────────────────────────────────────────────────────────────────
def _built(n=6, **plant_kw):
    plants, pots = {}, []
    for i in range(n):
        slot = f"A{i}"
        pots.append({"slot": slot, "u": 0.1 + 0.15 * (i % 4), "v": 0.2 + 0.4 * (i // 4)})
        plants[f"p{i}"] = _plant(id=f"p{i}", name=f"식물{i}", pos=slot, **plant_kw)
    return fb.build(plants, pots, {}, None, None)


def test_build_places_every_plant_that_has_a_pot():
    assert len(_built(6)["placed"]) == 6


def test_a_plant_without_a_pot_is_skipped():
    plants = {"p1": _plant(pos="A1"), "p2": _plant(id="p2", pos="없는자리")}
    built = fb.build(plants, [{"slot": "A1", "u": .5, "v": .5}], {}, None, None)
    assert len(built["placed"]) == 1


def test_a_shelf_with_nobody_on_it_is_rejected():
    with pytest.raises(ValueError, match="놓인 식물이 없습니다"):
        fb.build({"p1": _plant(pos="없음")}, [{"slot": "A1", "u": .5, "v": .5}],
                 {}, None, None)


def test_the_snap_error_is_recorded_for_every_pot():
    """격자가 실제 배치를 얼마나 왜곡했는지 안 남기면 격자를 믿을 근거가 없다."""
    built = _built(6)
    assert all(p["snap_error_cm"] >= 0 for p in built["placed"])


# ── 경고 ──────────────────────────────────────────────────────────────────
def test_a_plant_taller_than_the_lamp_is_warned_about():
    """조명보다 큰 포기는 계산상 빛이 0 이다 — 조용히 넘어가면 안 된다."""
    built = _built(2, leaf_max_cm=30.0)               # 키 = 30 x 2.2 = 66 cm
    warns = " ".join(fb.clearance_warnings(built, light_height_cm=47.0))
    assert "조명(47cm)보다 큰 포기" in warns


def test_a_comfortable_shelf_gets_no_clearance_warning():
    built = _built(2, leaf_max_cm=8.0)                # 키 = 17.6 cm
    assert fb.clearance_warnings(built, light_height_cm=60.0) == []


def test_a_plant_grown_right_up_to_the_lamp_is_warned_about():
    built = _built(2, leaf_max_cm=20.0)               # 키 = 44 cm
    warns = " ".join(fb.clearance_warnings(built, light_height_cm=50.0))
    assert "10cm 안쪽" in warns


def test_a_narrow_beam_leaves_corners_uncovered():
    """스팟등 반각이 좁으면 선반을 다 못 덮는다 — PPFD 0 의 원인을 미리 짚는다."""
    built = _built(8, leaf_max_cm=8.0)
    assert fb.uncovered_pots(built, 47.0, half_angle_deg=8.0)


def test_a_wide_beam_covers_everything():
    built = _built(8, leaf_max_cm=8.0)
    assert fb.uncovered_pots(built, 47.0, half_angle_deg=80.0) == []


# ── YAML 출력 ─────────────────────────────────────────────────────────────
def test_the_written_yaml_loads_back_into_the_simulator(tmp_path):
    """이게 이 모듈의 계약이다 — 나온 파일이 그대로 돌아가야 한다."""
    from geometry import load_config
    built = _built(6, leaf_max_cm=10.0)
    path = tmp_path / "shelf.yaml"
    path.write_text(fb.to_yaml(built, "선반", 200.0, 60.0, 30.0, 16.0, 0.7),
                    encoding="utf-8")
    cfg = load_config(str(path))
    assert len(cfg.pots) == 6
    assert len(cfg.lights) == 3
    assert cfg.label == "선반"
    assert cfg.space.width == pytest.approx(fb.SHELF_W_CM / 100)
    assert all(L.beam_angle == pytest.approx(60.0) for L in cfg.lights)


def test_the_written_yaml_carries_centimetres_into_metres(tmp_path):
    from geometry import load_config
    built = _built(2, canopy_cm=30.0)
    path = tmp_path / "s.yaml"
    path.write_text(fb.to_yaml(built, "t", 100.0, 47.0, 30.0, 16.0, 0.7),
                    encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.pots[0].canopy_radius == pytest.approx(0.15, abs=1e-3)   # 30cm 지름


def test_the_yaml_says_where_each_number_came_from(tmp_path):
    """주석으로 출처를 남긴다 — 추정값을 실측으로 오해하면 안 된다."""
    text = fb.to_yaml(_built(2), "t", 100.0, 47.0, 30.0, 16.0, 0.7)
    assert "키=잎길이추정" in text


# ── 덮어쓰기 CSV ──────────────────────────────────────────────────────────
def test_overrides_load_by_slot_and_name(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("# 줄자 실측\nslot,height_cm\nA1,33\nA2,41\n", encoding="utf-8")
    got = fb.load_overrides(str(p))
    assert got["A1"]["height_cm"] == 33.0 and got["A2"]["height_cm"] == 41.0


def test_an_override_row_without_a_key_is_rejected(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("height_cm\n33\n", encoding="utf-8")
    with pytest.raises(ValueError, match="slot 또는 name"):
        fb.load_overrides(str(p))


def test_no_override_file_means_no_overrides():
    assert fb.load_overrides(None) == {}
