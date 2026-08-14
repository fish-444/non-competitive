"""히트맵. 격자 그대로 5×10 으로 그리고 셀 안에 수치를 적는다.

숫자를 셀에 넣는 이유: 색만으로는 "어디가 어둡나" 는 보여도 "얼마나 어둡나" 를
못 읽는다. 배치를 바꿔 가며 비교하려면 값이 필요하다.
"""

from __future__ import annotations

import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")                       # 창 없는 환경에서도 저장은 되게
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


# 그림 제목·범례에 한글이 들어간다. 글꼴을 안 정해 주면 네모(두부)로 나온다.
# 있는 것 중 첫 번째를 쓰고, 하나도 없으면 알려 준 뒤 기본 글꼴로 간다.
_KOREAN_FONTS = ("Malgun Gothic", "AppleGothic", "Apple SD Gothic Neo",
                 "NanumGothic", "NanumBarunGothic", "Noto Sans CJK KR",
                 "Noto Sans KR", "WenQuanYi Zen Hei", "Unifont")


def use_korean_font() -> str:
    """쓸 수 있는 한글 글꼴을 골라 matplotlib 에 물린다. 고른 이름을 돌려준다."""
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in _KOREAN_FONTS:
        if name in have:
            plt.rcParams["font.family"] = name
            # 한글 글꼴은 유니코드 마이너스(U+2212)가 없는 경우가 많다 — ASCII 로.
            plt.rcParams["axes.unicode_minus"] = False
            return name
    print("[알림] 한글 글꼴을 못 찾아 그림의 한글이 깨질 수 있습니다.")
    return ""


use_korean_font()
# 글꼴에 'normal' 굵기가 없으면 matplotlib 이 매번 알린다. 결과와 무관해 조용히 시킨다.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


def _annotate(ax, im, data: np.ndarray, fmt: str) -> None:
    """셀마다 값을 적는다. 글씨 색은 **그 칸의 실제 배경색 밝기**로 정한다.

    "값이 중앙보다 크면 검게" 같은 규칙은 발산형 색(RdBu 등)에서 거꾸로 먹는다 —
    가운데가 가장 밝고 양끝이 어둡기 때문이다. 그래서 색을 직접 샘플링한다.
    """
    rows, cols = data.shape
    for r in range(rows):
        for c in range(cols):
            v = data[r, c]
            if np.isnan(v):
                ax.text(c, r, "·", ha="center", va="center", color="#999", fontsize=9)
                continue
            red, green, blue, _ = im.cmap(im.norm(v))
            lum = 0.2126 * red + 0.7152 * green + 0.0722 * blue    # 상대 휘도
            ax.text(c, r, format(v, fmt), ha="center", va="center",
                    fontsize=7.5, color=("#111" if lum > 0.55 else "#f5f5f5"))


def heatmap(data: np.ndarray, title: str, cbar_label: str, fmt: str = ".0f",
            path: Optional[str] = None, vmin: Optional[float] = None,
            vmax: Optional[float] = None, cmap: str = "viridis"):
    """격자 히트맵 하나를 그려 저장한다."""
    rows, cols = data.shape
    v = data[~np.isnan(data)]
    lo = vmin if vmin is not None else (float(v.min()) if v.size else 0.0)
    hi = vmax if vmax is not None else (float(v.max()) if v.size else 1.0)
    if hi <= lo:
        hi = lo + 1.0

    fig, ax = plt.subplots(figsize=(1.05 * cols + 2.2, 0.86 * rows + 1.9))
    im = ax.imshow(data, cmap=cmap, vmin=lo, vmax=hi, aspect="equal")

    ax.set_xticks(range(cols), [str(c) for c in range(cols)])
    ax.set_yticks(range(rows), [str(r) for r in range(rows)])
    ax.set_xlabel("col"); ax.set_ylabel("row")
    ax.set_title(title, fontsize=11, pad=10)

    # 칸 경계 — 격자라는 걸 눈에 보이게
    ax.set_xticks(np.arange(-.5, cols, 1), minor=True)
    ax.set_yticks(np.arange(-.5, rows, 1), minor=True)
    ax.grid(which="minor", color="#ffffff", linewidth=.8)
    ax.tick_params(which="minor", length=0)

    _annotate(ax, im, data, fmt)
    fig.colorbar(im, ax=ax, shrink=.82, label=cbar_label)
    fig.tight_layout()

    if path:
        fig.savefig(path, dpi=150)
        plt.close(fig)
    return fig


def convergence(runs, ylabel: str = "목적함수 (작을수록 좋음)",
                path: Optional[str] = None):
    """SA 수렴 그래프. 시드별 '여태 최고' 곡선과, 첫 시드의 탐색 흔적.

    최고 기록만 그리면 예쁘게 내려가는 계단이 나오지만 SA 가 실제로 언덕을
    넘고 있는지는 안 보인다. 첫 시드의 현재 점수를 옅게 깔아 그 요동을 같이
    보여 준다 — 요동이 처음부터 없으면 온도가 너무 낮은 것이고, 끝까지
    안 잦아들면 너무 높은 것이다.
    """
    fig, ax = plt.subplots(figsize=(9.2, 5.0))

    if runs:
        first = runs[0]
        ax.plot(first.history, color="#c7cdd6", linewidth=.7, zorder=1,
                label=f"시드 {first.seed} 의 현재 점수 (탐색 흔적)")
        ax.axhline(first.initial_score, color="#d9534f", linestyle="--", linewidth=1.1,
                   zorder=2, label=f"시작 배치 {first.initial_score:.4f}")

    cmap = plt.get_cmap("viridis")
    for i, r in enumerate(runs):
        ax.plot(r.best_curve, linewidth=1.6, zorder=3,
                color=cmap(0.08 + 0.78 * i / max(1, len(runs) - 1)),
                label=f"시드 {r.seed} -> {r.score:.4f}")

    ax.set_xlabel("iteration")
    ax.set_ylabel(ylabel)
    ax.set_title(f"SA 수렴 — 시드 {len(runs)}개", fontsize=11, pad=10)
    ax.grid(alpha=.25, linewidth=.7)
    ax.legend(fontsize=8, loc="upper right", framealpha=.92)
    fig.tight_layout()

    if path:
        fig.savefig(path, dpi=150)
        plt.close(fig)
    return fig


def compare(a: np.ndarray, b: np.ndarray, label_a: str, label_b: str,
            cbar_label: str, fmt: str = ".0f", path: Optional[str] = None):
    """두 배치를 위아래로 놓고, 아래에 차이(b−a)를 그린다.

    앞의 둘은 **같은 색 범위**로 그린다 — 각자 정규화하면 더 어두운 배치가
    똑같이 밝아 보여서 비교가 안 된다. 차이만 발산형 색으로 0을 가운데 둔다.
    """
    rows, cols = a.shape
    both = np.concatenate([a[~np.isnan(a)], b[~np.isnan(b)]])
    lo, hi = (float(both.min()), float(both.max())) if both.size else (0.0, 1.0)
    if hi <= lo:
        hi = lo + 1.0

    diff = b - a
    dv = diff[~np.isnan(diff)]
    span = float(np.abs(dv).max()) if dv.size else 1.0
    if span <= 0:
        span = 1.0

    fig, axes = plt.subplots(3, 1, figsize=(1.05 * cols + 2.6, 2.7 * rows + 2.4))
    for ax, data, title, cmap, lohi, f in (
            (axes[0], a, label_a, "viridis", (lo, hi), fmt),
            (axes[1], b, label_b, "viridis", (lo, hi), fmt),
            (axes[2], diff, f"차이 ({label_b} - {label_a})", "RdBu_r", (-span, span), "+.0f")):
        im = ax.imshow(data, cmap=cmap, vmin=lohi[0], vmax=lohi[1], aspect="equal")
        ax.set_xticks(range(cols), [str(c) for c in range(cols)])
        ax.set_yticks(range(rows), [str(r) for r in range(rows)])
        ax.set_title(title, fontsize=10.5, pad=8)
        ax.set_xticks(np.arange(-.5, cols, 1), minor=True)
        ax.set_yticks(np.arange(-.5, rows, 1), minor=True)
        ax.grid(which="minor", color="#ffffff", linewidth=.8)
        ax.tick_params(which="minor", length=0)
        _annotate(ax, im, data, f)
        fig.colorbar(im, ax=ax, shrink=.86,
                     label=(cbar_label if ax is not axes[2] else f"Δ {cbar_label}"))

    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
        plt.close(fig)
    return fig
