"""실측값으로 모델을 검증한다.

    python validate.py config.yaml 측정값.csv
    python validate.py config.yaml 측정값.csv --out results --worst 8

광량계를 몇 군데 대 보고 그 자리의 예측값과 맞춰 본다. 맞나 안 맞나보다
**어떻게 틀리는지**가 중요하다 — 전체가 일정 비율로 낮으면 반사를 안 넣은 탓이고
(Phase 1 은 벽·천장 반사가 없어 구조적으로 낮게 나온다), 특정 자리만 틀리면
그 자리의 캐노피나 광원 위치를 잘못 적은 것이다. 그래서 하나의 점수 대신
편향·기울기·잔차 지도를 같이 낸다.

CSV 는 첫 줄이 머리글이고, '#' 로 시작하는 줄은 건너뛴다. 필요한 열:

    x, y, z, ppfd          측정 지점의 실제 좌표(m)와 실측 PPFD(µmol/m²/s)
    row, col, z, ppfd      격자 칸으로 적어도 된다 (화분 자리에서 쟀을 때)
    label                  (선택) 지점 이름. 없으면 P1, P2, ... 로 붙는다
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np

import visualize                      # 한글 글꼴 설정을 위해 (import 하면서 잡힌다)
from geometry import Config, Pot, load_config, pot_xy
from light import ppfd_at


@dataclass
class Measurement:
    """측정 한 점."""
    label: str
    x: float
    y: float
    z: float
    measured: float


# --------------------------------------------------------------------------- 읽기
_NEEDED = "x/y 또는 row/col, 그리고 z 와 ppfd 열이 필요합니다"


def _num(row: dict, key: str, line: int) -> float:
    raw = (row.get(key) or "").strip()
    if raw == "":
        raise ValueError(f"{line}번째 줄: '{key}' 값이 비어 있습니다.")
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{line}번째 줄: '{key}' 를 숫자로 못 읽었습니다 ({raw!r}).")


def load_measurements(path: str, cfg: Config) -> List[Measurement]:
    """측정 CSV → Measurement 목록. 좌표는 x/y 로도, 격자 칸으로도 적을 수 있다.

    격자 칸을 받는 이유: 실제로는 화분 자리에 광량계를 놓고 재는 일이 대부분인데,
    그때마다 줄자로 xy 를 재게 하면 그 자체가 오차가 된다. row/col 로 적으면
    시뮬레이터가 쓰는 것과 **같은 좌표 계산**을 거치므로 그 오차가 사라진다.
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines))
    if not rows:
        raise ValueError(f"{path} 에 데이터 줄이 없습니다.")

    cols = {(c or "").strip().lower() for c in rows[0]}
    by_xy = {"x", "y"} <= cols
    by_rc = {"row", "col"} <= cols
    if not (by_xy or by_rc) or "ppfd" not in cols:
        raise ValueError(f"{path}: {_NEEDED}. 받은 열: {sorted(cols)}")

    out = []
    for i, raw in enumerate(rows, start=2):
        row = {(k or "").strip().lower(): v for k, v in raw.items()}
        if by_xy:
            x, y = _num(row, "x", i), _num(row, "y", i)
        else:
            r, c = int(_num(row, "row", i)), int(_num(row, "col", i))
            if not (0 <= r < cfg.grid.rows and 0 <= c < cfg.grid.cols):
                raise ValueError(f"{i}번째 줄: 격자 칸 ({r}, {c}) 가 "
                                 f"{cfg.grid.rows}x{cfg.grid.cols} 를 벗어납니다.")
            x, y = pot_xy(Pot((r, c), 0.0, 0.0, 0.0), cfg.grid, cfg.space)
        label = (row.get("label") or "").strip() or f"P{i - 1}"
        out.append(Measurement(label=label, x=x, y=y, z=_num(row, "z", i),
                               measured=_num(row, "ppfd", i)))
    return out


# --------------------------------------------------------------------------- 예측
def _sensor_inside(m: Measurement, pot: Pot, cx: float, cy: float) -> bool:
    """광량계가 그 캐노피 **안** 이거나 꼭대기에 놓였는가."""
    dx, dy = m.x - cx, m.y - cy
    return (dx * dx + dy * dy <= pot.canopy_radius ** 2 * (1 + 1e-9)
            and m.z <= pot.plant_height + 1e-9)


def predict(cfg: Config, points: Sequence[Measurement]) -> Tuple[np.ndarray, int]:
    """각 측정 지점의 예측 PPFD. (값, 캐노피 안에 놓인 지점 수) 를 돌려준다.

    광량계가 놓인 그 화분은 가리는 것에서 뺀다. 안 그러면 캐노피 꼭대기에 센서를
    올렸을 때 선분이 제 원기둥 끝점에 닿아 스스로를 가린 것으로 잡힌다 —
    compute_ppfd 가 화분 자신을 빼는 것과 같은 이유다. 나머지 화분은 다 센다.
    """
    xy = [(p, pot_xy(p, cfg.grid, cfg.space)) for p in cfg.pots]
    values, inside_count = [], 0
    for m in points:
        blockers = [(p, c) for p, c in xy if not _sensor_inside(m, p, *c)]
        if len(blockers) != len(xy):
            inside_count += 1
        values.append(ppfd_at((m.x, m.y, m.z), cfg.lights, blockers, cfg.extinction_k))
    return np.array(values, dtype=float), inside_count


# --------------------------------------------------------------------------- 지표
def metrics(pred: np.ndarray, meas: np.ndarray) -> dict:
    """예측력 지표 묶음.

    R² 는 **1:1 선 기준**이다 (1 - Σ(예측-실측)² / Σ(실측-실측평균)²). 회귀선을
    새로 맞춘 r² 이 아니다 — 그건 "비례하나" 만 보므로 모델이 전부 30% 낮아도
    1.0 이 나온다. 여기서 알고 싶은 건 "그 값이 맞나" 라서 1:1 이 맞다.
    음수도 나올 수 있는데, 그건 그냥 실측 평균을 답이라 하느니만 못하다는 뜻이다.

    편향(bias)과 기울기를 따로 내는 이유: 반사를 안 넣어 생기는 구조적 저평가는
    '기울기 > 1' 로 나타나고, 광원 세기를 잘못 적은 것도 마찬가지다. 반면 특정
    지점만 틀리면 이 둘은 멀쩡한 채 RMSE 만 커진다. 나누어 봐야 원인이 갈린다.
    """
    n = int(pred.size)
    err = pred - meas                                   # + 면 과대평가
    ss_res = float((err ** 2).sum())
    ss_tot = float(((meas - meas.mean()) ** 2).sum())
    mean_meas = float(meas.mean())

    out = {
        "n": n,
        "rmse": math.sqrt(ss_res / n),
        "mae": float(np.abs(err).mean()),
        "bias": float(err.mean()),
        "max_abs_err": float(np.abs(err).max()),
        "mean_measured": mean_meas,
        "mean_predicted": float(pred.mean()),
        "r2": 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "slope": float("nan"),
        "intercept": float("nan"),
    }
    out["rmse_pct"] = out["rmse"] / mean_meas * 100 if mean_meas > 0 else float("nan")
    out["mape"] = float(np.abs(err[meas > 0] / meas[meas > 0]).mean() * 100) \
        if (meas > 0).any() else float("nan")

    # 실측 = 기울기·예측 + 절편. 기울기 1.2 면 "모델이 20% 낮게 본다".
    if n >= 2 and float(pred.std()) > 1e-12:
        out["slope"], out["intercept"] = (float(v) for v in np.polyfit(pred, meas, 1))
    return out


def worst_points(points: Sequence[Measurement], pred: np.ndarray, meas: np.ndarray,
                 n: int = 5) -> List[int]:
    """오차 절대값이 큰 순서로 최대 n개의 인덱스."""
    return list(np.argsort(np.abs(pred - meas))[::-1][:min(n, len(points))])


def wall_distance(points: Sequence[Measurement], cfg: Config) -> np.ndarray:
    """각 지점에서 가장 가까운 벽까지의 거리(m)."""
    return np.array([min(p.x, cfg.space.width - p.x,
                         p.y, cfg.space.depth - p.y) for p in points], dtype=float)


def wall_trend(points: Sequence[Measurement], pred: np.ndarray, meas: np.ndarray,
               cfg: Config) -> float:
    """잔차와 '벽까지의 거리' 의 상관계수. 없으면 NaN.

    벽 반사는 Phase 1 이 통째로 빠뜨린 성분이고, 그 효과는 **벽에 가까울수록 크다**.
    그래서 오차가 벽 거리와 상관되면 원인이 좁혀진다 — 전체를 일정 배율로 올려서
    맞출 문제가 아니라 반사 모형을 넣어야 하는 문제라는 뜻이다. 부호까지 봐야
    하므로 절대값이 아니라 부호 있는 잔차로 잰다.
    """
    if len(points) < 4:
        return float("nan")
    d, err = wall_distance(points, cfg), pred - meas
    if float(d.std()) < 1e-9 or float(err.std()) < 1e-12:
        return float("nan")
    return float(np.corrcoef(d, err)[0, 1])


def diagnose(m: dict, cfg: Config, wall_r: float = float("nan")) -> List[str]:
    """지표를 읽어 '무엇이 의심스러운지' 를 문장으로. 판단은 사람이 한다."""
    notes = []
    rel_bias = m["bias"] / m["mean_measured"] if m["mean_measured"] > 0 else 0.0

    if rel_bias < -0.08:
        notes.append(
            f"모델이 전반적으로 {-rel_bias * 100:.0f}% 낮게 본다. Phase 1 은 벽·천장 "
            "반사가 없어 원래 하한이라 예상된 방향이다 — 재배실 반사는 보통 10~30%다.")
    elif rel_bias > 0.08:
        notes.append(
            f"모델이 전반적으로 {rel_bias * 100:.0f}% 높게 본다. 반사가 없는데도 "
            "높다면 광원의 ppf 나 beam_angle, 설치 높이를 의심할 만하다.")
    else:
        notes.append(f"전체 편향은 {rel_bias * 100:+.1f}% 로 작다.")

    # 벽 거리와의 상관을 기울기보다 먼저 본다. 기울기 하나로는 원인이 안 갈린다 —
    # 가장자리(대개 어두운 곳)만 더 모자라도 기울기는 1보다 작아지기 때문이다.
    if not math.isnan(wall_r) and abs(wall_r) > 0.5:
        if wall_r > 0:
            notes.append(
                f"오차가 벽 거리와 상관된다 (r={wall_r:+.2f}) — 벽에 가까운 지점일수록 "
                "더 모자란다. 반사가 빠진 자리에 정확히 들어맞는 모양이라, 전체를 "
                "한 배율로 올려서는 안 맞는다.")
        else:
            notes.append(
                f"오차가 벽 거리와 상관된다 (r={wall_r:+.2f}) — 안쪽일수록 더 모자란다. "
                "반사로는 설명이 안 되는 방향이니 광원 위치나 배광을 다시 보라.")

    if not math.isnan(m["slope"]):
        if m["slope"] > 1.12:
            notes.append(f"기울기 {m['slope']:.2f} — 밝은 자리일수록 더 많이 모자란다. "
                         "일정 비율로 빠지는 성분(반사·광원 세기)이 있다는 뜻이다.")
        elif m["slope"] < 0.88:
            extra = ("" if abs(wall_r) > 0.5 else
                     " 빔각이 실제보다 좁게 적혔는지 확인해 볼 만하다.")
            notes.append(f"기울기 {m['slope']:.2f} — 어두운 자리가 예측보다 덜 어둡다. "
                         f"측정값의 폭이 예측보다 좁다는 뜻이다.{extra}")

    spread = m["rmse"] - abs(m["bias"])
    if spread > 0.12 * m["mean_measured"]:
        notes.append("편향을 걷어내도 흩어짐이 크다. 일괄 보정으로는 안 맞춰지는 "
                     "지점별 오차다 — 위 '오차가 큰 지점' 의 자리를 보라.")
    if not math.isnan(m["r2"]) and m["r2"] < 0:
        notes.append("R² 가 음수다. 1:1 선 기준이라, 지금 예측을 쓰느니 실측 평균값을 "
                     "일괄로 쓰는 편이 오차가 작다는 뜻이다 — 보정이 먼저다.")
    if m["n"] < 5:
        notes.append(f"측정점이 {m['n']}개뿐이라 지표를 크게 믿을 수 없다.")
    return notes


# --------------------------------------------------------------------------- 그림
def figure(points: Sequence[Measurement], pred: np.ndarray, meas: np.ndarray,
           m: dict, cfg: Config, worst: Sequence[int], path: Optional[str] = None):
    """산점도 + 잔차 지도 + 잔차 대 예측값.

    산점도만으로는 '어디서' 틀리는지 알 수 없다. 잔차를 실제 공간 좌표 위에
    찍어야 가장자리에서 밀리는지, 광원 아래에서 밀리는지가 보인다.
    """
    err = pred - meas
    fig = plt.figure(figsize=(14.0, 5.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.15, 1.0], wspace=.28)

    # ── 1. 예측 대 실측 ──────────────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 0])
    hi = float(max(pred.max(), meas.max())) * 1.08
    lo = min(0.0, float(min(pred.min(), meas.min())) * 0.95)
    ax.plot([lo, hi], [lo, hi], color="#444", linestyle="--", linewidth=1.1,
            label="1:1 (완벽한 예측)", zorder=2)
    if not math.isnan(m["slope"]):
        xs = np.array([lo, hi])
        ax.plot(m["slope"] * xs + m["intercept"], xs, color="#d9534f", linewidth=1.2,
                label=f"맞춘 직선 (기울기 {m['slope']:.2f})", zorder=3)
    ax.scatter(pred, meas, s=46, c="#2f7ab8", edgecolor="white", linewidth=.7, zorder=4)
    for i in worst:
        ax.scatter([pred[i]], [meas[i]], s=110, facecolor="none",
                   edgecolor="#d9534f", linewidth=1.7, zorder=5)
        ax.annotate(points[i].label, (pred[i], meas[i]), textcoords="offset points",
                    xytext=(7, -10), fontsize=8, color="#a33")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("예측 PPFD (µmol/m²/s)"); ax.set_ylabel("실측 PPFD (µmol/m²/s)")
    ax.set_title(f"예측 대 실측  (R² {m['r2']:.3f}, RMSE {m['rmse']:.1f})",
                 fontsize=10.5, pad=9)
    ax.grid(alpha=.25, linewidth=.7)
    ax.legend(fontsize=8, loc="lower right", framealpha=.92)

    # ── 2. 잔차 지도 — 공간 어디서 틀리는가 ──────────────────────────────
    ax = fig.add_subplot(gs[0, 1])
    span = float(np.abs(err).max()) or 1.0
    ax.add_patch(plt.Rectangle((0, 0), cfg.space.width, cfg.space.depth,
                               fill=False, edgecolor="#bbb", linewidth=1.1))
    for p in cfg.pots:
        px, py = pot_xy(p, cfg.grid, cfg.space)
        # 채우면 캐노피끼리 겹쳐 한 덩어리가 된다 — 윤곽선만
        ax.add_patch(plt.Circle((px, py), p.canopy_radius, fill=False,
                                edgecolor="#ccd4da", linewidth=.8, zorder=1))
    for L in cfg.lights:
        ax.scatter([L.position[0]], [L.position[1]], marker="*", s=170, c="#f0a500",
                   edgecolor="#8a6000", linewidth=.6, zorder=3, label="_광원")
    sc = ax.scatter([p.x for p in points], [p.y for p in points], c=err,
                    cmap="RdBu_r", vmin=-span, vmax=span, s=95, zorder=4,
                    edgecolor="#333", linewidth=.7)
    for i in worst:
        ax.annotate(points[i].label, (points[i].x, points[i].y),
                    textcoords="offset points", xytext=(8, 6), fontsize=8, color="#222")
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.set_title("잔차 지도 (예측 - 실측)   ★ 광원, 회색 원 캐노피", fontsize=10.5, pad=9)
    fig.colorbar(sc, ax=ax, shrink=.84, label="Δ µmol/m²/s")

    # ── 3. 잔차 대 예측값 — 밝은 데서 더 틀리는가 ────────────────────────
    ax = fig.add_subplot(gs[0, 2])
    ax.axhline(0, color="#444", linestyle="--", linewidth=1.1)
    ax.axhline(m["bias"], color="#d9534f", linewidth=1.2,
               label=f"편향 {m['bias']:+.1f}")
    ax.scatter(pred, err, s=46, c="#2f7ab8", edgecolor="white", linewidth=.7, zorder=3)
    for i in worst:
        ax.scatter([pred[i]], [err[i]], s=110, facecolor="none", edgecolor="#d9534f",
                   linewidth=1.7, zorder=4)
    ax.set_xlabel("예측 PPFD (µmol/m²/s)"); ax.set_ylabel("잔차 (예측 - 실측)")
    ax.set_title("잔차 대 밝기", fontsize=10.5, pad=9)
    ax.grid(alpha=.25, linewidth=.7)
    ax.legend(fontsize=8, framealpha=.92)

    fig.suptitle(f"모델 검증 — {cfg.label},  측정점 {m['n']}개", fontsize=12)
    # gridspec + colorbar 조합이라 tight_layout 은 못 쓴다 (경고만 내고 틀어진다)
    fig.subplots_adjust(left=.055, right=.985, top=.86, bottom=.12, wspace=.28)
    if path:
        fig.savefig(path, dpi=150)
        plt.close(fig)
    return fig


# --------------------------------------------------------------------------- 출력
def write_csv(points, pred, meas, path: str) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "x_m", "y_m", "z_m", "measured", "predicted",
                    "error", "abs_error", "error_pct"])
        for p, pr, ms in zip(points, pred, meas):
            e = pr - ms
            w.writerow([p.label, round(p.x, 3), round(p.y, 3), round(p.z, 3),
                        round(ms, 1), round(pr, 1), round(e, 1), round(abs(e), 1),
                        round(e / ms * 100, 1) if ms else ""])


def report(points, pred, meas, m: dict, worst: Sequence[int], inside: int) -> str:
    lines = [
        "",
        f"[검증] 측정점 {m['n']}개",
        f"  실측 평균   {m['mean_measured']:7.1f}   예측 평균 {m['mean_predicted']:7.1f}"
        f"   µmol/m²/s",
        f"  R² (1:1)    {m['r2']:7.3f}"
        + ("   ← 음수 = 실측 평균을 쓰느니만 못하다" if m["r2"] < 0 else ""),
        f"  RMSE        {m['rmse']:7.1f}   (실측 평균의 {m['rmse_pct']:.1f}%)",
        f"  평균절대오차 {m['mae']:7.1f}   (MAPE {m['mape']:.1f}%)",
        f"  편향         {m['bias']:+7.1f}   (+ 면 과대평가)",
    ]
    if not math.isnan(m["slope"]):
        lines.append(f"  맞춘 직선    실측 = {m['slope']:.3f} x 예측 "
                     f"{m['intercept']:+.1f}")
    if inside:
        lines.append(f"  ※ {inside}개 지점은 캐노피 안/위라 그 화분은 차폐에서 뺐다.")

    lines += ["", f"[오차가 큰 지점]  상위 {len(worst)}개"]
    lines.append("  지점        x     y     z      실측     예측      오차")
    for i in worst:
        p, e = points[i], pred[i] - meas[i]
        pct = f"{e / meas[i] * 100:+6.1f}%" if meas[i] else "      "
        lines.append(f"  {p.label:<8} {p.x:5.2f} {p.y:5.2f} {p.z:5.2f}  "
                     f"{meas[i]:7.1f}  {pred[i]:7.1f}  {e:+7.1f} {pct}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="시뮬레이션 값과 실측값을 맞춰 본다")
    ap.add_argument("config", help="설정 YAML")
    ap.add_argument("measured", help="실측 CSV (x,y,z,ppfd 또는 row,col,z,ppfd)")
    ap.add_argument("--out", default="results", help="결과를 쓸 폴더 (기본: results)")
    ap.add_argument("--worst", type=int, default=5, help="표시할 오차 큰 지점 수")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    try:
        points = load_measurements(a.measured, cfg)
    except ValueError as e:
        print(f"[중단] {e}", file=sys.stderr)
        return 1

    pred, inside = predict(cfg, points)
    meas = np.array([p.measured for p in points], dtype=float)
    m = metrics(pred, meas)
    worst = worst_points(points, pred, meas, a.worst)

    print(report(points, pred, meas, m, worst, inside))
    print("\n[읽기]")
    for note in diagnose(m, cfg, wall_trend(points, pred, meas, cfg)):
        print(f"  - {note}")

    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, f"{cfg.label}_검증")
    write_csv(points, pred, meas, base + ".csv")
    figure(points, pred, meas, m, cfg, worst, base + ".png")
    print(f"\n저장:\n  {base}.csv\n  {base}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
