"""알로카시아팜 백업 → light-sim 설정.

    python farm_bridge.py ../alocasia-farm/farm-backup.json -o shelf.yaml
    python main.py shelf.yaml --optimize

지금까지는 화분의 키·캐노피·LAI 를 손으로 적었다. 그런데 알로카시아팜이 사진에서
이미 재고 있다 — 특히 **LAI 는 잎 면적 ÷ 지면 면적**이라 잎 개수와 잎 크기를
아는 순간 계산되는 값이다. 차폐를 지배하는 게 LAI 라서, 여기가 추측값이면
최적화 결과도 같이 추측이 된다.

세 값이 어디서 오는지:

    canopy_radius   canopy_cm / 2          사진에서 직접 잰 값
    leaf_area_index leaf_count 와 leaf_max_cm 로 계산   (아래 LAI 문단)
    plant_height    size_class / leaf_max_cm 로 **추정**  ← 유일하게 약한 값

키는 탑다운 사진으로 못 잰다. 알로카시아팜이 등급으로 어림잡는 값을 그대로
가져오되, --heights 로 실측을 넣으면 그쪽을 쓴다. 화분당 한 번 줄자로 재 두면
오래 쓴다 — 키는 빨리 안 변한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- 상수
# 선반 치수(cm). 알로카시아팜 main.py 의 _W, _D 와 같아야 한다.
SHELF_W_CM, SHELF_D_CM = 60.0, 40.0

# 등급별 (잎우산 반지름 cm, 키 cm) — placement.py 의 GRADE_SHAPE 와 같은 값.
# 두 곳이 갈라지면 같은 식물이 앱에서와 시뮬레이터에서 다른 크기가 된다.
GRADE_SHAPE = {"소품": (7.0, 14.0), "중품": (13.0, 28.0), "대품": (20.0, 45.0)}
FALLBACK_SHAPE = (10.0, 20.0)
HEIGHT_PER_RADIUS = 2.2               # 알로카시아는 잎보다 키가 크다 (placement.py)

# LAI 계산에 쓰는 잎 모양 상수. 실측으로 갈아 끼울 수 있게 이름을 붙여 둔다.
LEAF_AREA_FACTOR = 0.42               # 잎 면적 ÷ (긴 변)². 하트형 잎 기준
MEAN_OVER_MAX_LEAF = 0.75             # 평균 잎 ÷ 가장 큰 잎. leaf_max_cm 은 최대값이라
LAI_MIN, LAI_MAX = 0.2, 6.0           # 계산이 튀어도 물리적으로 말이 되는 범위로 자른다


# --------------------------------------------------------------------------- 읽기
def load_backup(path: str) -> Tuple[Dict[str, dict], List[dict]]:
    """백업 JSON → (plants, pots). 형식이 아니면 바로 세운다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("kind") != "alocasia-farm-backup":
        raise ValueError(f"{path} 는 알로카시아팜 백업 파일이 아닙니다 "
                         "(앱의 '백업 내려받기' 로 만든 .json 을 주세요).")
    state = data.get("state") or {}
    plants, pots = state.get("plants") or {}, state.get("pots") or []
    if not pots:
        raise ValueError("백업에 화분 자리(pots)가 없습니다. 앱에서 화분 위치를 "
                         "먼저 잡아 주세요.")
    return plants, pots


def load_overrides(path: Optional[str]) -> Dict[str, dict]:
    """실측 덮어쓰기 CSV → {키: {필드: 값}}. 자리(slot)나 이름으로 찾는다.

    열: slot 또는 name, 그리고 height_cm / canopy_cm / lai 중 있는 것.
    키는 사진으로 못 재니 이 파일이 정확도의 마지막 한 칸이다.
    """
    if not path:
        return {}
    out: Dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in f if not r.lstrip().startswith("#")]
    for i, raw in enumerate(csv.DictReader(rows), start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        key = row.get("slot") or row.get("name")
        if not key:
            raise ValueError(f"{path} {i}번째 줄: slot 또는 name 열이 필요합니다.")
        vals = {}
        for field in ("height_cm", "canopy_cm", "lai"):
            if row.get(field):
                try:
                    vals[field] = float(row[field])
                except ValueError:
                    raise ValueError(f"{path} {i}번째 줄: {field} 를 숫자로 못 읽었습니다.")
        out[key] = vals
    return out


# --------------------------------------------------------------------------- 환산
def estimate_lai(leaf_count, leaf_max_cm, canopy_radius_cm: float) -> Optional[float]:
    """잎 개수와 잎 크기로 LAI 를 낸다. 못 내면 None.

    LAI 는 정의가 그대로 계산식이다 — **잎 면적의 합 ÷ 그 포기가 덮는 지면 면적**.

        잎 한 장 면적 ≈ LEAF_AREA_FACTOR x (평균 잎 긴변)²
        평균 잎 ≈ MEAN_OVER_MAX_LEAF x leaf_max_cm    (leaf_max_cm 은 '가장 큰' 잎)
        지면 면적 = π x 캐노피반지름²

    leaf_max_cm 을 모든 잎에 그대로 쓰면 LAI 가 부풀어 차폐를 과대평가한다.
    그래서 평균 대 최대 비를 한 번 곱한다. 이 두 상수는 실측으로 갈아 끼울
    자리이므로 이름을 붙여 두었다.
    """
    if not leaf_count or not leaf_max_cm or canopy_radius_cm <= 0:
        return None
    mean_leaf = MEAN_OVER_MAX_LEAF * float(leaf_max_cm)
    leaf_area = LEAF_AREA_FACTOR * mean_leaf * mean_leaf
    ground = math.pi * canopy_radius_cm * canopy_radius_cm
    return max(LAI_MIN, min(LAI_MAX, int(leaf_count) * leaf_area / ground))


MEASURED_FIELDS = ("canopy_cm", "leaf_max_cm", "leaf_count", "size_class")


def measurements(plant: dict) -> dict:
    """식물의 최신 실측값. 최상위 필드가 비면 growth_log 의 마지막 기록을 쓴다.

    앱은 사진을 분석할 때마다 최상위 필드를 갱신하고 growth_log 에도 한 줄
    남긴다. 그런데 옛 백업이나 손으로 만든 기록에는 최상위가 비어 있고 기록만
    있는 경우가 있다 — 그때 값을 통째로 잃는 대신 마지막 기록으로 메운다.
    """
    log = [e for e in (plant.get("growth_log") or []) if isinstance(e, dict)]
    last = log[-1] if log else {}
    out = {}
    for f in MEASURED_FIELDS:
        v = plant.get(f)
        out[f] = last.get(f) if v in (None, "") else v
    return out


def plant_size(plant: dict, override: dict) -> Tuple[float, float, float, List[str]]:
    """식물 → (캐노피 반지름 cm, 키 cm, LAI, 출처 메모).

    캐노피는 canopy_cm(사진에서 직접 잰 퍼짐)을 먼저 쓴다. placement.py 는
    leaf_max_cm 을 반지름으로 쓰는데, 그건 잎 한 장 길이라 포기 전체 퍼짐보다
    작다 — 캐노피를 직접 쟀으면 그 값이 맞다.
    """
    notes = []
    m = measurements(plant)
    grade = GRADE_SHAPE.get(m.get("size_class"), FALLBACK_SHAPE)

    canopy_cm = override.get("canopy_cm") or m.get("canopy_cm")
    if canopy_cm:
        radius_cm = float(canopy_cm) / 2.0
        notes.append("캐노피=실측")
    elif m.get("leaf_max_cm"):
        radius_cm = float(m["leaf_max_cm"])              # 잎자루가 사방으로 뻗는다
        notes.append("캐노피=잎길이")
    else:
        radius_cm = grade[0]
        notes.append("캐노피=등급추정")

    if override.get("height_cm"):
        height_cm = float(override["height_cm"])
        notes.append("키=실측")
    elif m.get("leaf_max_cm"):
        height_cm = float(m["leaf_max_cm"]) * HEIGHT_PER_RADIUS
        notes.append("키=잎길이추정")
    else:
        height_cm = grade[1]
        notes.append("키=등급추정")

    if override.get("lai"):
        lai = float(override["lai"])
        notes.append("LAI=실측")
    else:
        lai = estimate_lai(m.get("leaf_count"), m.get("leaf_max_cm"), radius_cm)
        if lai is None:
            lai = 1.5
            notes.append("LAI=기본값")
        else:
            notes.append("LAI=잎수계산")
    return radius_cm, height_cm, lai, notes


# --------------------------------------------------------------------------- 격자
def choose_grid(n: int, rows: Optional[int], cols: Optional[int]) -> Tuple[int, int]:
    """화분 수에 맞는 격자 크기. 선반이 가로로 길어 열을 더 준다."""
    if rows and cols:
        if rows * cols < n:
            raise ValueError(f"{rows}x{cols} 격자에는 화분 {n}개가 안 들어갑니다.")
        return rows, cols
    if rows:
        return rows, math.ceil(n / rows)
    if cols:
        return math.ceil(n / cols), cols
    aspect = SHELF_W_CM / SHELF_D_CM
    r = max(1, round(math.sqrt(n / aspect)))
    return r, math.ceil(n / r)


def snap_to_grid(placed: List[dict], rows: int, cols: int) -> None:
    """실제 (u,v) 위치를 격자 칸에 앉힌다. placed 에 row/col 을 채워 넣는다.

    light-sim 은 규칙적인 격자를 쓰는데 사진에서 잡힌 화분 위치는 조금씩 어긋난다.
    선반을 읽듯이 앉힌다 — 깊이(v)로 줄을 나누고, 줄 안에서 가로(u)로 세운다.
    사람이 선반을 정리하는 순서와 같아서 결과가 눈으로 납득이 된다.

    격자가 실제 배치를 얼마나 왜곡했는지는 snap_error_cm 으로 같이 남긴다 —
    이 값이 크면 애초에 격자로 볼 배치가 아니라는 뜻이다.
    """
    by_depth = sorted(placed, key=lambda p: (p["v"], p["u"]))
    n, i = len(by_depth), 0
    for r in range(rows):
        # 남은 화분을 남은 줄에 고르게 나눈다. 올림이라 앞줄부터 채워져
        # 덜 찬 줄은 맨 뒤로 간다 — round 를 쓰면 2.5 가 2 로 떨어져(은행가 반올림)
        # 덜 찬 줄이 앞으로 온다.
        take = min(cols, n - i) if r == rows - 1 else min(cols, math.ceil((n - i) / (rows - r)))
        row_items = sorted(by_depth[i:i + take], key=lambda p: p["u"])
        for c, item in enumerate(row_items):
            item["row"], item["col"] = r, c
        i += take
        if i >= n:
            break

    for p in placed:
        if "row" not in p:                     # 안 앉은 게 있으면 안 된다
            raise RuntimeError("격자 배정에서 빠진 화분이 있습니다.")


def grid_xy_cm(row: int, col: int, rows: int, cols: int,
               row_spacing_cm: float, col_spacing_cm: float) -> Tuple[float, float]:
    """격자 칸 → 선반 위 cm 좌표 (geometry.pot_xy 와 같은 규칙: 가운데 정렬)."""
    x = SHELF_W_CM / 2 + (col - (cols - 1) / 2) * col_spacing_cm
    y = SHELF_D_CM / 2 + (row - (rows - 1) / 2) * row_spacing_cm
    return x, y


# --------------------------------------------------------------------------- 조명
def shelf_lights(ppf_each: float, height_cm: float, half_angle_deg: float,
                 rail_margin_cm: float = 8.0) -> List[dict]:
    """알로카시아팜의 레일 조명 3개를 light-sim 광원으로.

    좌표계가 다르다 — placement.py 는 (x=좌우, y=높이, z=앞뒤), light-sim 은
    (x=좌우, y=앞뒤, z=높이). y 와 z 가 바뀐다.

    각도는 더 조심해야 한다: placement.py 의 angle 은 **반각**이고 light-sim 의
    beam_angle 은 **전체각**이라 두 배로 넘겨야 한다. 그냥 넘기면 빔이 절반으로
    좁아져 가장자리가 통째로 어두워진다.
    """
    x_rail = SHELF_W_CM / 2 - rail_margin_cm
    spots = [(-x_rail, 17.0), (-x_rail, -13.0), (x_rail, 2.0)]   # DEFAULT_LIGHTS
    return [{"position": [round((SHELF_W_CM / 2 + x) / 100, 4),
                          round((SHELF_D_CM / 2 + z) / 100, 4),
                          round(height_cm / 100, 4)],
             "ppf": ppf_each,
             "beam_angle": half_angle_deg * 2.0} for x, z in spots]


# --------------------------------------------------------------------------- 쓰기
def build(plants: Dict[str, dict], pots: List[dict], overrides: Dict[str, dict],
          rows: Optional[int], cols: Optional[int]) -> dict:
    """백업 데이터 → 설정에 넣을 값 묶음."""
    by_slot = {p.get("slot"): p for p in pots if p.get("slot")}
    placed = []
    for plant in plants.values():
        slot = plant.get("pos")
        pot = by_slot.get(slot)
        if pot is None:
            continue                            # 선반에 안 올라간 식물
        ov = overrides.get(slot) or overrides.get(plant.get("name") or "") or {}
        radius_cm, height_cm, lai, notes = plant_size(plant, ov)
        placed.append({"name": plant.get("name") or slot, "slot": slot,
                       "u": float(pot.get("u", 0.5)), "v": float(pot.get("v", 0.5)),
                       "radius_cm": radius_cm, "height_cm": height_cm,
                       "lai": lai, "notes": notes})
    if not placed:
        raise ValueError("선반 위에 놓인 식물이 없습니다 (식물의 pos 가 화분 slot 과 "
                         "이어져 있는지 확인해 주세요).")

    rows, cols = choose_grid(len(placed), rows, cols)
    snap_to_grid(placed, rows, cols)

    # 격자 간격은 실제 화분들이 퍼져 있는 폭에 맞춘다 — 선반 전체를 채우는 게
    # 아니라 지금 놓인 만큼만 쓰도록.
    span_u = max(p["u"] for p in placed) - min(p["u"] for p in placed)
    span_v = max(p["v"] for p in placed) - min(p["v"] for p in placed)
    col_sp = (span_u * SHELF_W_CM / (cols - 1)) if cols > 1 and span_u > 0 else 12.0
    row_sp = (span_v * SHELF_D_CM / (rows - 1)) if rows > 1 and span_v > 0 else 12.0

    for p in placed:
        gx, gy = grid_xy_cm(p["row"], p["col"], rows, cols, row_sp, col_sp)
        p["snap_error_cm"] = math.dist((p["u"] * SHELF_W_CM, p["v"] * SHELF_D_CM),
                                       (gx, gy))
    return {"placed": placed, "rows": rows, "cols": cols,
            "row_spacing_cm": row_sp, "col_spacing_cm": col_sp}


def to_yaml(built: dict, label: str, ppf_each: float, light_height_cm: float,
            half_angle_deg: float, photoperiod: float, k: float) -> str:
    """설정 YAML 문자열. pyyaml 로 덤프하지 않고 직접 쓴다 — 주석을 남기려고."""
    rows, cols = built["rows"], built["cols"]
    lights = shelf_lights(ppf_each, light_height_cm, half_angle_deg)
    lines = [
        "# 알로카시아팜 백업에서 자동으로 만든 설정입니다.",
        "# 앱에서 잰 값이 바뀌면 farm_bridge.py 를 다시 돌리세요 (손으로 고치면 덮입니다).",
        "#",
        "#   canopy_radius   canopy_cm / 2        사진 실측",
        "#   leaf_area_index leaf_count 로 계산    (잎면적 ÷ 지면면적)",
        "#   plant_height    등급/잎길이 추정      ← --heights 로 실측을 넣으면 정확해집니다",
        "",
        f"label: {label}",
        "",
        "space:",
        f"  width: {SHELF_W_CM / 100:g}          # 선반 가로 {SHELF_W_CM:g} cm",
        f"  depth: {SHELF_D_CM / 100:g}          # 선반 세로 {SHELF_D_CM:g} cm",
        f"  height: {max(light_height_cm + 10, 60) / 100:g}",
        "",
        "grid:",
        f"  rows: {rows}",
        f"  cols: {cols}",
        f"  row_spacing: {built['row_spacing_cm'] / 100:.4f}",
        f"  col_spacing: {built['col_spacing_cm'] / 100:.4f}",
        "",
        f"photoperiod_hours: {photoperiod:g}",
        f"extinction_k: {k:g}",
        "",
        "# 레일 조명 3개. ppf 는 등의 사양서 값(µmol/s)을 넣으세요 — 모르면 상대값이라",
        "# 절대 PPFD 는 못 믿지만, 균일도(CV)와 배치 최적화는 그대로 유효합니다.",
        "lights:",
    ]
    for L in lights:
        lines += [f"  - position: [{L['position'][0]}, {L['position'][1]}, {L['position'][2]}]",
                  f"    ppf: {L['ppf']:g}",
                  f"    beam_angle: {L['beam_angle']:g}"]

    lines += ["", "pots:"]
    for p in sorted(built["placed"], key=lambda q: (q["row"], q["col"])):
        lines += [
            f"  # {p['name']} ({p['slot']}) — {', '.join(p['notes'])}",
            f"  - grid_position: [{p['row']}, {p['col']}]",
            f"    plant_height: {p['height_cm'] / 100:.3f}",
            f"    canopy_radius: {p['radius_cm'] / 100:.3f}",
            f"    leaf_area_index: {p['lai']:.2f}",
        ]

    lines += ["", "optimize:", "  w_cv: 1.0", "  w_mean: 0.0", "  initial_temp: 0",
              "  cooling_rate: 0.9993", "  iterations: 4000", "  seeds: 5", ""]
    return "\n".join(lines)


def uncovered_pots(built: dict, light_height_cm: float, half_angle_deg: float,
                   rail_margin_cm: float = 8.0) -> List[dict]:
    """어떤 조명 빔 원뿔에도 안 들어가는 화분들.

    스팟등은 반각 밖으로 안 비친다. 조명 3개가 60x40 선반을 다 덮는다는 보장이
    없어서, 계산을 돌리기 전에 기하만으로 먼저 짚어 준다 — PPFD 가 0 으로 나온
    뒤에 원인을 찾는 것보다 여기서 말해 주는 편이 낫다.
    """
    lights = shelf_lights(1.0, light_height_cm, half_angle_deg, rail_margin_cm)
    half = math.radians(half_angle_deg)
    out = []
    for p in built["placed"]:
        gx, gy = grid_xy_cm(p["row"], p["col"], built["rows"], built["cols"],
                            built["row_spacing_cm"], built["col_spacing_cm"])
        px, py, pz = gx / 100, gy / 100, p["height_cm"] / 100
        lit = False
        for L in lights:
            lx, ly, lz = L["position"]
            dz = lz - pz
            if dz <= 0:
                continue
            d = math.dist((px, py, pz), (lx, ly, lz))
            if d > 0 and math.acos(min(1.0, dz / d)) <= half:
                lit = True
                break
        if not lit:
            out.append(p)
    return out


def clearance_warnings(built: dict, light_height_cm: float) -> List[str]:
    """캐노피가 조명에 너무 가깝거나 조명보다 높은 포기를 잡아낸다.

    조명보다 키가 큰 포기는 계산상 빛을 **0** 으로 받는다 (광원보다 위에 있는
    수광점이라). 조명 바로 밑까지 자란 포기는 반대로 역제곱이 발산해 말도 안 되게
    밝게 나온다. 둘 다 '모델이 틀렸다' 가 아니라 **실제로 배치가 잘못됐다** 는
    신호다 — 사진만 보는 앱도, 설정만 보는 시뮬레이터도 혼자서는 못 잡는다.
    """
    warns = []
    over = [p for p in built["placed"] if p["height_cm"] >= light_height_cm]
    near = [p for p in built["placed"]
            if light_height_cm > p["height_cm"] >= light_height_cm - 10.0]
    if over:
        names = ", ".join(f"{p['name']}({p['height_cm']:.0f}cm)" for p in over[:5])
        warns.append(
            f"조명({light_height_cm:.0f}cm)보다 큰 포기 {len(over)}개: {names}"
            f"{' …' if len(over) > 5 else ''}\n"
            "     이 포기들은 계산상 빛을 0 으로 받습니다. 조명을 올리거나, 키 추정이"
            " 과하면 --heights 로 실측을 넣으세요.")
    if near:
        names = ", ".join(f"{p['name']}({p['height_cm']:.0f}cm)" for p in near[:5])
        warns.append(
            f"조명에서 10cm 안쪽까지 자란 포기 {len(near)}개: {names}"
            f"{' …' if len(near) > 5 else ''}\n"
            "     역제곱이라 이 자리 PPFD 는 크게 부풀어 보입니다. 잎이 탈 수도 있는"
            " 거리라 실제로도 확인해 보세요.")
    return warns


def report(built: dict) -> str:
    placed = sorted(built["placed"], key=lambda p: (p["row"], p["col"]))
    errs = [p["snap_error_cm"] for p in placed]
    lines = [f"\n[불러옴] 식물 {len(placed)}개 → {built['rows']}x{built['cols']} 격자 "
             f"(간격 {built['col_spacing_cm']:.1f} x {built['row_spacing_cm']:.1f} cm)",
             "",
             "  자리   이름            캐노피r   키     LAI    출처",
             ]
    for p in placed:
        lines.append(f"  r{p['row']}c{p['col']}   {p['name'][:12]:<12} "
                     f"{p['radius_cm']:6.1f}  {p['height_cm']:5.1f}  {p['lai']:5.2f}  "
                     f"{', '.join(p['notes'])}")
    lines.append(f"\n  격자로 옮기며 생긴 위치 오차: 평균 {sum(errs) / len(errs):.1f} cm, "
                 f"최대 {max(errs):.1f} cm")
    if max(errs) > 6.0:
        lines.append("  ※ 오차가 큽니다 — 실제 배치가 격자 모양이 아닐 수 있습니다. "
                     "--rows/--cols 로 격자를 맞춰 보세요.")

    guessed = [p["name"] for p in placed if "키=실측" not in p["notes"]]
    if guessed:
        lines.append(f"\n  ※ 키가 추정값인 포기 {len(guessed)}개: {', '.join(guessed[:6])}"
                     f"{' …' if len(guessed) > 6 else ''}")
        lines.append("     탑다운 사진으로는 키를 못 잽니다. 줄자로 한 번 재서 "
                     "--heights CSV(slot,height_cm)로 넣으면 정확해집니다.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="알로카시아팜 백업 → light-sim 설정")
    ap.add_argument("backup", help="알로카시아팜 백업 JSON")
    ap.add_argument("-o", "--out", default="shelf.yaml", help="쓸 설정 파일")
    ap.add_argument("--heights", help="실측 덮어쓰기 CSV (slot/name, height_cm, canopy_cm, lai)")
    ap.add_argument("--rows", type=int, help="격자 행 수 (기본: 화분 수로 정함)")
    ap.add_argument("--cols", type=int, help="격자 열 수")
    ap.add_argument("--ppf", type=float, default=100.0,
                    help="조명 하나의 광량자속 µmol/s (기본 100 = 상대값)")
    ap.add_argument("--light-height", type=float, default=47.0, help="선반에서 조명까지 cm")
    ap.add_argument("--beam-half-angle", type=float, default=30.0,
                    help="빔 반각(도). 알로카시아팜과 같은 뜻 — 전체각은 이 값의 2배")
    ap.add_argument("--label", default="선반", help="설정 이름")
    ap.add_argument("--photoperiod", type=float, default=16.0)
    ap.add_argument("--k", type=float, default=0.7, help="소산계수")
    a = ap.parse_args(argv)

    try:
        plants, pots = load_backup(a.backup)
        overrides = load_overrides(a.heights)
        built = build(plants, pots, overrides, a.rows, a.cols)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1

    print(report(built))
    warns = clearance_warnings(built, a.light_height)
    dark = uncovered_pots(built, a.light_height, a.beam_half_angle)
    if dark:
        names = ", ".join(f"{p['name']}(r{p['row']}c{p['col']})" for p in dark[:6])
        warns.append(
            f"어떤 조명 빔에도 안 들어가는 자리 {len(dark)}개: {names}"
            f"{' …' if len(dark) > 6 else ''}\n"
            f"     스팟등 반각 {a.beam_half_angle:g}도로는 선반 "
            f"{SHELF_W_CM:g}x{SHELF_D_CM:g}cm 를 다 못 덮습니다. 직달광이 0 이라 "
            "PPFD 최소값도 0 으로 나옵니다.\n"
            "     조명을 올리거나(빔이 넓게 퍼짐), 넓은 각도의 등으로 바꾸거나, "
            "화분을 안쪽으로 모으세요.")
    if warns:
        print("\n[경고]")
        for w in warns:
            print(f"  - {w}")
    text = to_yaml(built, a.label, a.ppf, a.light_height, a.beam_half_angle,
                   a.photoperiod, a.k)
    if os.path.dirname(a.out):
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"\n저장: {a.out}")
    if a.ppf == 100.0:
        print("  ※ --ppf 를 안 줘서 조명 세기를 상대값 100 으로 뒀습니다. "
              "절대 PPFD/DLI 는 못 믿습니다.")
        print("     다만 균일도(CV)와 배치 최적화는 세기에 안 흔들립니다 — "
              "전체를 같은 배로 곱해도 CV 는 그대로라서요.")
    print(f"\n  python main.py {a.out} --optimize")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
