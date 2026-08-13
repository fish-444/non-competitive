"""CLI 실행.

    python main.py config.yaml
    python main.py config.yaml --compare config_b.yaml
    python main.py config.yaml --out results/
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

import light
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="실내 재배 공간 광 분포 시뮬레이터")
    ap.add_argument("config", help="설정 YAML")
    ap.add_argument("--compare", help="비교할 두 번째 설정 YAML")
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

    print("\n저장:")
    for p in made:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
