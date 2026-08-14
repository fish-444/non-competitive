"""CLI 실행.

    python main.py config.yaml
    python main.py config.yaml --compare config_b.yaml
    python main.py config.yaml --optimize
    python main.py config.yaml --out results/
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import replace

import numpy as np

import light
import optimize
import visualize
from geometry import load_config, pot_xy


def write_csv(cfg, res, path: str) -> None:
    """화분별 한 줄. 격자 좌표와 실제 위치를 같이 적어 다른 도구로 넘기기 쉽게."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row", "col", "x_m", "y_m", "plant_height_m", "canopy_radius_m",
                    "lai", "ppfd_umol_m2_s", "dli_mol_m2_day"])
        for pot in sorted(cfg.pots, key=lambda p: (p.row, p.col)):
            x, y = pot_xy(pot, cfg.grid, cfg.space)
            w.writerow([pot.row, pot.col, round(x, 3), round(y, 3),
                        pot.plant_height, pot.canopy_radius, pot.leaf_area_index,
                        round(float(res["ppfd"][pot.row, pot.col]), 1),
                        round(float(res["dli"][pot.row, pot.col]), 2)])


def report(res) -> str:
    return (f"  화분 {res['n_pots']}개\n"
            f"  PPFD   평균 {res['mean']:7.1f}  최소 {res['min']:7.1f}  "
            f"최대 {res['max']:7.1f}  µmol/m²/s\n"
            f"  균일도 CV {res['cv']:.3f}   (작을수록 고름)")


def run_optimize(cfg, res, out_dir: str, seeds=None, iterations=None):
    """SA 로 배치를 다시 짜고, 결과를 찍고 그림을 저장한다. 만든 파일 목록을 돌려준다."""
    p = cfg.sa
    if seeds is not None:
        p = replace(p, seeds=seeds)
    if iterations is not None:
        p = replace(p, iterations=iterations)

    print(f"\n[최적화] 모의 담금질 — 시드 {p.seeds}개 x {p.iterations} iteration")
    print(f"  목적함수  {p.w_cv:g} x CV + {p.w_mean:g} x (1/평균PPFD)   (작을수록 좋음)")

    runs = optimize.anneal_multi(cfg, p)
    best = optimize.best_of(runs)
    sp = optimize.spread(runs)

    print(f"  초기 온도 {best.initial_temp:.5g}"
          f"{' (자동 보정)' if p.initial_temp <= 0 else ''}, 냉각률 {p.cooling_rate:g}")
    print("\n  시드      CV     평균PPFD       점수    받아들임(언덕넘기)")
    for r in runs:
        mark = " <- 채택" if r is best else ""
        print(f"   {r.seed:>2}   {r.cv:.4f}   {r.mean_ppfd:7.1f}   {r.score:9.5f}"
              f"   {r.accepted:5d} ({r.uphill}){mark}")
    print(f"\n  CV  평균 {sp['cv_mean']:.4f}  표준편차 {sp['cv_std']:.4f}  "
          f"최소 {sp['cv_min']:.4f}  최대 {sp['cv_max']:.4f}  "
          f"(상대편차 {sp['cv_rel_std'] * 100:.1f}%)")
    print(f"  → {sp['verdict']}")

    # 최종 수치는 **참조 구현**(compute_ppfd)으로 다시 낸다. 최적화는 빠른 배열판을
    # 쓰므로, 둘이 갈라지면 여기서 숫자가 어긋나 바로 드러난다.
    cfg_opt = replace(cfg, pots=best.pots, label=f"{cfg.label}_최적")
    res_opt = light.summarize(cfg_opt)

    def pct(new, old):
        return f"{(new - old) / old * 100:+.1f}%" if old else "  —  "

    print(f"\n[개선] 시작 → 최적 (시드 {best.seed})")
    print(f"  균일도 CV    {res['cv']:.4f} → {res_opt['cv']:.4f}   {pct(res_opt['cv'], res['cv'])}")
    print(f"  평균 PPFD   {res['mean']:7.1f} → {res_opt['mean']:7.1f}   {pct(res_opt['mean'], res['mean'])}")
    print(f"  최소 PPFD   {res['min']:7.1f} → {res_opt['min']:7.1f}   {pct(res_opt['min'], res['min'])}")
    print(f"  최대 PPFD   {res['max']:7.1f} → {res_opt['max']:7.1f}   {pct(res_opt['max'], res['max'])}")

    print("\n[배치 — 식물 키(cm)]  시작")
    print(optimize.format_grid(optimize.layout_grid(cfg, cfg.pots)))
    print("\n[배치 — 식물 키(cm)]  최적")
    print(optimize.format_grid(optimize.layout_grid(cfg_opt, best.pots)))

    base = os.path.join(out_dir, cfg_opt.label)
    write_csv(cfg_opt, res_opt, base + ".csv")
    visualize.heatmap(res_opt["ppfd"], f"PPFD — {cfg_opt.label}", "µmol/m²/s",
                      ".0f", base + "_ppfd.png")
    cmp_path = os.path.join(out_dir, f"compare_{cfg.label}_vs_최적.png")
    visualize.compare(res["ppfd"], res_opt["ppfd"], cfg.label, cfg_opt.label,
                      "µmol/m²/s", ".0f", cmp_path)
    conv_path = os.path.join(out_dir, f"{cfg.label}_수렴.png")
    ylabel = "CV" if p.w_mean == 0 else "목적함수 (작을수록 좋음)"
    visualize.convergence(runs, ylabel, conv_path)

    return [base + ".csv", base + "_ppfd.png", cmp_path, conv_path]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="실내 재배 공간 광 분포 시뮬레이터")
    ap.add_argument("config", help="설정 YAML")
    ap.add_argument("--compare", help="비교할 두 번째 설정 YAML")
    ap.add_argument("--optimize", action="store_true",
                    help="SA 로 화분 배치를 최적화한다 (설정의 optimize 항목을 쓴다)")
    ap.add_argument("--seeds", type=int, help="최적화 반복 실행 횟수 (설정값을 덮어쓴다)")
    ap.add_argument("--iterations", type=int, help="SA iteration 수 (설정값을 덮어쓴다)")
    ap.add_argument("--out", default="results", help="결과를 쓸 폴더 (기본: results)")
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)

    cfg = load_config(a.config)
    res = light.summarize(cfg)
    print(f"\n[{res['label']}]")
    print(report(res))

    base = os.path.join(a.out, res["label"])
    write_csv(cfg, res, base + ".csv")
    visualize.heatmap(res["ppfd"], f"PPFD — {res['label']}", "µmol/m²/s",
                      ".0f", base + "_ppfd.png")
    visualize.heatmap(res["dli"], f"DLI — {res['label']} "
                      f"(광주기 {cfg.photoperiod_hours:g}h)", "mol/m²/day",
                      ".1f", base + "_dli.png", cmap="magma")
    made = [base + ".csv", base + "_ppfd.png", base + "_dli.png"]

    if a.compare:
        cfg_b = load_config(a.compare)
        if (cfg_b.grid.rows, cfg_b.grid.cols) != (cfg.grid.rows, cfg.grid.cols):
            print("\n[중단] 격자 크기가 달라 비교할 수 없습니다.", file=sys.stderr)
            return 1
        res_b = light.summarize(cfg_b)
        print(f"\n[{res_b['label']}]")
        print(report(res_b))

        base_b = os.path.join(a.out, res_b["label"])
        write_csv(cfg_b, res_b, base_b + ".csv")
        cmp_path = os.path.join(a.out, f"compare_{res['label']}_vs_{res_b['label']}.png")
        visualize.compare(res["ppfd"], res_b["ppfd"], res["label"], res_b["label"],
                          "µmol/m²/s", ".0f", cmp_path)
        made += [base_b + ".csv", cmp_path]

        d_mean = res_b["mean"] - res["mean"]
        d_cv = res_b["cv"] - res["cv"]
        print(f"\n[비교] {res['label']} → {res_b['label']}")
        print(f"  평균 PPFD {d_mean:+.1f}   CV {d_cv:+.3f} "
              f"({'더 고름' if d_cv < 0 else '덜 고름' if d_cv > 0 else '같음'})")

    if a.optimize:
        made += run_optimize(cfg, res, a.out, a.seeds, a.iterations)

    print("\n저장:")
    for p in made:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
