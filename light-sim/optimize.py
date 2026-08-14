"""화분 배치 최적화 — 모의 담금질(simulated annealing).

키와 캐노피가 제각각이라 **누구를 어디에 놓느냐**로 차폐가 달라진다. 키 큰 포기가
광원 아래 한복판에 몰리면 뒤가 다 그늘이 되고, 가장자리(원래 어두운 곳)로 보내면
그 그늘이 이미 어두운 데로 간다. 그 재배치를 자동으로 찾는다.

전수탐색은 화분 50개면 50! ≈ 3e64 가지라 논외다. SA 는 그중 iterations 개만
보되, 처음엔 나빠지는 쪽도 받아들여(온도) 언덕을 넘어 다니다가 식으면서
가까운 골짜기로 내려앉는다. 최적을 보장하진 않지만 '지금 배치보다 낫다' 는
확실히 준다 — 시작점을 항상 후보에 넣기 때문이다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple

import numpy as np

from geometry import Config, Light, Pot, SAParams
from light import compute_ppfd_fast, uniformity_cv

# 점수 차가 이보다 작으면 '같은 배치' 로 본다.
# 똑같이 생긴 화분 둘을 맞바꾸면 배치는 사실상 그대로인데 부동소수점 반올림 때문에
# Δ 가 1e-17 쯤으로 남는다. 이걸 진짜 악화로 세면 (1) 온도가 0 이나 마찬가지인데도
# exp(-1e-17/T) ≈ 1 이라 다 받아들여지고 (2) '언덕 넘기' 횟수가 잡음으로 부푼다.
# 실제로 의미 있는 개선은 1e-4 단위라 이 문턱에 걸릴 일이 없다.
_TIE = 1e-12


@dataclass
class SARun:
    """SA 한 판의 결과."""
    seed: int
    pots: List[Pot]                 # 찾은 배치
    score: float                    # 그 배치의 목적함수 값 (작을수록 좋다)
    cv: float
    mean_ppfd: float
    history: np.ndarray             # iteration 마다의 **현재** 점수
    initial_score: float
    initial_temp: float
    accepted: int                   # 받아들인 이동 횟수
    uphill: int                     # 그중 더 나쁜데도 받아들인 횟수
    lights: List[Light] = field(default_factory=list)   # 찾은 조명 위치
    light_moves: int = 0            # 받아들인 이동 중 광원을 옮긴 것

    @property
    def best_curve(self) -> np.ndarray:
        """지금까지의 최고 기록. history 의 누적 최솟값이다.

        더 나쁜 해도 받아들이므로 history 는 오르락내리락한다. 수렴을 보려면
        '여태 찾은 것 중 최고' 를 봐야 단조롭게 내려가는 곡선이 나온다.
        """
        return np.minimum.accumulate(self.history)


# --------------------------------------------------------------------------- 목적함수
def score_of(ppfd: np.ndarray, w_cv: float, w_mean: float) -> Tuple[float, float, float]:
    """(점수, CV, 평균PPFD). 점수 = w_cv·CV + w_mean·(1/평균PPFD), 작을수록 좋다.

    평균을 **역수**로 넣는 이유: 두 항이 같은 방향(작을수록 좋음)을 봐야 그냥
    더할 수 있다. 평균은 클수록 좋으므로 뒤집는다.
    """
    v = ppfd[~np.isnan(ppfd)]
    if v.size == 0:
        return float("inf"), float("nan"), float("nan")
    mean = float(v.mean())
    cv = uniformity_cv(ppfd)
    if mean <= 0 or math.isnan(cv):
        return float("inf"), cv, mean
    return w_cv * cv + w_mean / mean, cv, mean


def evaluate(cfg: Config, pots: Sequence[Pot], p: SAParams,
             lights: Optional[Sequence[Light]] = None):
    """배치 하나를 매긴다. cfg 는 그대로 두고 화분(과 조명)만 갈아 끼운다."""
    swap = {"pots": list(pots)}
    if lights is not None:
        swap["lights"] = list(lights)
    return score_of(compute_ppfd_fast(replace(cfg, **swap)), p.w_cv, p.w_mean)


# --------------------------------------------------------------------------- 이웃해
def _swapped(pots: Sequence[Pot], cells: Sequence[Tuple[int, int]],
             rng: random.Random) -> Optional[List[Pot]]:
    """화분 두 개의 자리를 맞바꾼 배치. 빈 칸으로 옮기는 것도 같은 연산이다.

    격자 칸 둘을 고르는 것으로 보면 '화분끼리 교환' 과 '빈 칸으로 이동' 이
    한 가지 이동이 된다 — 화분이 칸보다 적을 때 빈 칸을 못 쓰면 탐색 공간의
    절반이 닫힌다. 둘 다 비었으면 배치가 안 바뀌므로 버린다(None).
    """
    n = len(cells)
    i, j = rng.randrange(n), rng.randrange(n)
    if i == j:
        return None
    a, b = cells[i], cells[j]
    at = {p.grid_position: k for k, p in enumerate(pots)}
    ka, kb = at.get(a), at.get(b)
    if ka is None and kb is None:
        return None                              # 빈 칸끼리 — 아무 일도 안 일어난다
    out = list(pots)
    if ka is not None:
        out[ka] = replace(out[ka], grid_position=b)
    if kb is not None:
        out[kb] = replace(out[kb], grid_position=a)
    return out


def _free_cells(cfg: Config) -> List[Tuple[int, int]]:
    """화분이 놓일 수 있는 칸 전부 — 격자 전체."""
    return [(r, c) for r in range(cfg.grid.rows) for c in range(cfg.grid.cols)]


def _movable(lights: Sequence[Light]) -> List[Tuple[int, int]]:
    """(광원 번호, 움직일 수 있는 축) 쌍 목록. 이게 비면 조명은 못 옮긴다."""
    return [(i, ax) for i, L in enumerate(lights)
            if L.move for ax in L.move.free_axes]


def _moved_light(lights: Sequence[Light], knobs: Sequence[Tuple[int, int]],
                 step: float, rng: random.Random) -> Optional[List[Light]]:
    """광원 하나를 한 축으로 조금 옮긴 배치. 범위 밖은 잘라 낸다.

    화분은 칸이 정해져 있어 '맞바꾸기' 로 끝나지만 조명은 연속이라 걸음 폭이
    필요하다. 폭은 밖에서 온도에 맞춰 줄여 준다 — 뜨거울 땐 성큼성큼 훑고
    식으면 잘게 다듬는다. 폭을 고정하면 끝까지 큰 걸음이라 미세 조정이 안 된다.

    범위 밖으로 나가면 되돌리지 않고 **자른다**. 되돌리면 경계에 답이 있을 때
    (대개 '조명을 최대한 올려라' 가 그렇다) 영영 못 닿는다.
    """
    if not knobs:
        return None
    i, axis = knobs[rng.randrange(len(knobs))]
    lo, hi = lights[i].move.bounds(axis)
    pos = list(lights[i].position)
    moved = min(hi, max(lo, pos[axis] + rng.gauss(0.0, step)))
    if abs(moved - pos[axis]) < 1e-12:
        return None                              # 이미 경계에 붙어 있다
    pos[axis] = moved
    out = list(lights)
    out[i] = replace(out[i], position=(pos[0], pos[1], pos[2]))
    return out


# --------------------------------------------------------------------------- 온도 보정
def calibrate_temperature(cfg: Config, p: SAParams, rng: random.Random,
                          samples: int = 60) -> float:
    """무작위 교환의 점수 변화폭으로 초기 온도를 정한다.

    T₀ 를 고정 숫자로 박으면 목적함수를 바꾸는 순간 무너진다 — w_mean 을 키우면
    점수가 통째로 다른 자릿수가 되고, T₀ 가 너무 낮으면 처음부터 언덕을 못 넘어
    그냥 greedy 가 되고 너무 높으면 끝까지 무작위로 걷는다. 그래서 실제 교환을
    몇 번 해 보고 '평범하게 나빠지는 정도' 를 절반쯤 받아들이도록 맞춘다:
    exp(-Δ/T₀) = 0.5  →  T₀ = 평균Δ / ln2.
    """
    cells = _free_cells(cfg)
    knobs = _movable(cfg.lights) if p.move_lights else []
    base, _, _ = evaluate(cfg, cfg.pots, p)
    deltas = []
    for _ in range(samples):
        if knobs and rng.random() < p.light_move_prob:
            lit = _moved_light(cfg.lights, knobs, p.light_step, rng)
            s = evaluate(cfg, cfg.pots, p, lit)[0] if lit else None
        else:
            cand = _swapped(cfg.pots, cells, rng)
            s = evaluate(cfg, cand, p)[0] if cand else None
        if s is not None and math.isfinite(s) and s > base:
            deltas.append(s - base)
    if not deltas:
        return 1e-6                              # 바뀌는 게 없다 — 온도가 의미 없다
    return float(np.mean(deltas)) / math.log(2.0)


# --------------------------------------------------------------------------- SA 본체
def anneal(cfg: Config, seed: int = 0, params: Optional[SAParams] = None) -> SARun:
    """모의 담금질 한 판. 같은 seed 면 항상 같은 결과가 나온다.

    받아들이는 규칙은 메트로폴리스 판정이다 — 좋아지면 무조건, 나빠지면
    exp(-Δ/T) 확률로. T 가 높을 때는 거의 다 받아 넓게 돌아다니고, 식으면
    좋아지는 이동만 남아 골짜기에 자리를 잡는다.
    """
    p = params or cfg.sa
    rng = random.Random(seed)
    cells = _free_cells(cfg)
    knobs = _movable(cfg.lights) if p.move_lights else []

    temp = p.initial_temp
    if temp <= 0:
        temp = calibrate_temperature(cfg, p, random.Random(seed + 10_000))
    temp0 = temp

    cur_pots, cur_lights = list(cfg.pots), list(cfg.lights)
    cur, cur_cv, cur_mean = evaluate(cfg, cur_pots, p, cur_lights)
    best_pots, best_lights = list(cur_pots), list(cur_lights)
    best, best_cv, best_mean = cur, cur_cv, cur_mean

    history = np.empty(p.iterations + 1, dtype=float)
    history[0] = cur
    accepted = uphill = light_moves = 0

    for i in range(p.iterations):
        # 걸음 폭을 온도와 같이 줄인다 — 뜨거울 땐 성큼성큼, 식으면 잘게 다듬는다.
        # 밑을 깔아 두는 건 끝에서 폭이 0 이 되어 아무것도 안 움직이는 걸 막으려고.
        step = p.light_step * max(0.05, temp / temp0 if temp0 > 0 else 1.0)
        move_light = bool(knobs) and rng.random() < p.light_move_prob
        if move_light:
            cand_lights = _moved_light(cur_lights, knobs, step, rng)
            cand_pots = cur_pots if cand_lights is not None else None
        else:
            cand_pots = _swapped(cur_pots, cells, rng)
            cand_lights = cur_lights

        if cand_pots is not None and cand_lights is not None:
            s, cv, mean = evaluate(cfg, cand_pots, p, cand_lights)
            delta = s - cur
            worse = delta > _TIE
            # T 가 0 에 가까워지면 exp 가 언더플로한다 — 나빠지는 건 그냥 거절
            take = (not worse) or (temp > _TIE and rng.random() < math.exp(-delta / temp))
            if take:
                cur_pots, cur_lights = cand_pots, cand_lights
                cur, cur_cv, cur_mean = s, cv, mean
                accepted += 1
                if move_light:
                    light_moves += 1
                if worse:
                    uphill += 1
                if cur < best:
                    best_pots, best_lights = list(cur_pots), list(cur_lights)
                    best, best_cv, best_mean = cur, cur_cv, cur_mean
        temp *= p.cooling_rate
        history[i + 1] = cur

    return SARun(seed=seed, pots=best_pots, lights=best_lights, score=best,
                 cv=best_cv, mean_ppfd=best_mean, history=history,
                 initial_score=history[0], initial_temp=temp0, accepted=accepted,
                 uphill=uphill, light_moves=light_moves)


def anneal_multi(cfg: Config, params: Optional[SAParams] = None,
                 seeds: Optional[int] = None) -> List[SARun]:
    """시드를 바꿔 여러 판 돌린다. 지역 최적에 갇혔는지 보려면 이게 필요하다.

    한 판만 돌리면 그게 좋은 답인지 운 좋게 걸린 골짜기인지 알 수 없다. 시드별
    결과가 서로 붙어 있으면 그 언저리가 진짜 바닥이고, 흩어져 있으면 아직
    덜 식은 것이다(반복을 늘리거나 온도를 올려야 한다).
    """
    p = params or cfg.sa
    n = seeds if seeds is not None else p.seeds
    return [anneal(cfg, seed=s, params=p) for s in range(n)]


def spread(runs: Sequence[SARun]) -> dict:
    """시드별 결과의 흩어진 정도. 상대 표준편차로 '갇혔는지' 를 판정한다."""
    cvs = np.array([r.cv for r in runs], dtype=float)
    scores = np.array([r.score for r in runs], dtype=float)
    mean = float(cvs.mean())
    std = float(cvs.std())
    rel = std / mean if mean > 0 else float("nan")
    if rel < 0.02:
        verdict = "시드를 바꿔도 거의 같은 곳에 닿는다 — 지역 최적 걱정은 적다"
    elif rel < 0.05:
        verdict = "대체로 일관된다 — 시드 사이 차이가 크지 않다"
    else:
        verdict = "시드마다 갈린다 — iterations 를 늘리거나 initial_temp 를 올려 보세요"
    return {"cv_mean": mean, "cv_std": std, "cv_min": float(cvs.min()),
            "cv_max": float(cvs.max()), "cv_rel_std": rel,
            "score_mean": float(scores.mean()), "score_std": float(scores.std()),
            "verdict": verdict}


def best_of(runs: Sequence[SARun]) -> SARun:
    return min(runs, key=lambda r: r.score)


# --------------------------------------------------------------------------- 경계 진단
def at_bounds(cfg: Config, run: SARun, rel_tol: float = 0.05) -> List[Tuple[int, str, str]]:
    """최적해에서 범위 끝에 붙어 버린 (광원 번호, 축, '최소'/'최대') 목록.

    문턱을 **범위의 비율**로 잡는다. SA 는 무작위 걸음이라 경계에 딱 떨어지는
    일이 드물다 — 0.926 까지 갈 수 있는데 0.914 에서 멈췄다면 그건 "여기가
    최적" 이 아니라 "끝까지 밀고 싶은데 못 간 것" 이다. 절대값 1mm 로 재면
    이걸 다 놓치고 경고가 영영 안 뜬다.
    """
    out = []
    for i, (before, after) in enumerate(zip(cfg.lights, run.lights)):
        if not before.move:
            continue
        for axis, name in enumerate("xyz"):
            span = before.move.bounds(axis)
            if span is None:
                continue
            lo, hi = span
            tol = max((hi - lo) * rel_tol, 1e-6)
            v = after.position[axis]
            if v <= lo + tol:
                out.append((i, name, "최소"))
            elif v >= hi - tol:
                out.append((i, name, "최대"))
    return out


def light_notes(cfg: Config, run: SARun, p: SAParams) -> List[str]:
    """조명 최적화 결과를 읽을 때 알아야 할 것들.

    가장 중요한 경고가 여기 있다: **균일도만 보면 조명을 무조건 높이는 게 정답이
    된다.** 멀어질수록 빛은 고르게 퍼지니까 — 극단적으로는 무한히 올리면 모두가
    똑같이 어두워져 CV 가 0 이 된다. 수학적으로 맞고 농사로는 틀린 답이다.
    그래서 높이가 상한에 붙으면 그 사실을 반드시 말해 줘야 한다.
    """
    notes = []
    stuck = at_bounds(cfg, run)
    high = [i for i, ax, end in stuck if ax == "z" and end == "최대"]

    if high and p.w_mean == 0:
        notes.append(
            f"조명 {len(high)}개가 허용 높이의 **꼭대기**에 붙었습니다. 균일도만 보면 "
            "당연한 결과입니다 — 멀수록 빛이 고르게 퍼지고, 끝까지 밀면 모두가 똑같이 "
            "어두워져 CV 가 0 이 됩니다.\n"
            "     수학은 맞지만 농사로는 틀린 답입니다. w_mean 을 올려 총 광량을 "
            "같이 보거나, move.z 의 상한을 실제로 올릴 수 있는 높이로 낮추세요.")
    elif high:
        notes.append(f"조명 {len(high)}개가 허용 높이의 꼭대기에 붙었습니다. "
                     "더 올릴 수 있다면 move.z 상한을 늘려 다시 돌려 보세요.")

    other = [(i, ax, end) for i, ax, end in stuck if not (ax == "z" and end == "최대")]
    if other:
        where = ", ".join(f"조명{i}의 {ax}({end})" for i, ax, end in other[:5])
        notes.append(f"범위 끝에 닿은 곳: {where}. 실제로 더 움직일 수 있다면 "
                     "범위를 넓혀 다시 돌려 볼 만합니다.")

    if p.move_lights and run.light_moves == 0:
        notes.append("조명을 옮긴 이동이 하나도 안 받아들여졌습니다 — 지금 위치가 "
                     "이미 좋거나, move 범위가 너무 좁습니다.")
    return notes


def light_table(cfg: Config, run: SARun) -> str:
    """조명이 어디서 어디로 갔는지. 안 움직인 축은 조용히 둔다."""
    lines = ["  조명    x(m)              y(m)              z(m)"]
    for i, (before, after) in enumerate(zip(cfg.lights, run.lights)):
        cells = []
        for axis in range(3):
            a, b = before.position[axis], after.position[axis]
            cells.append(f"{a:.3f}" if abs(b - a) < 1e-4 else f"{a:.3f} -> {b:.3f}")
        lines.append(f"   {i:>2}    " + "  ".join(f"{c:<16}" for c in cells))
    return "\n".join(lines)


# --------------------------------------------------------------------------- 보기 좋게
def layout_grid(cfg: Config, pots: Sequence[Pot], what: str = "height") -> List[List[str]]:
    """배치를 격자 모양 문자열 표로. 빈 칸은 가운뎃점.

    키(cm)를 기본으로 보여 준다 — 차폐를 만드는 게 결국 키라서, 최적화가 키 큰
    포기를 어디로 보냈는지가 한눈에 보여야 결과를 납득할 수 있다.
    """
    table = [["·"] * cfg.grid.cols for _ in range(cfg.grid.rows)]
    for p in pots:
        if what == "height":
            table[p.row][p.col] = f"{p.plant_height * 100:.0f}"
        elif what == "lai":
            table[p.row][p.col] = f"{p.leaf_area_index:.1f}"
        else:
            table[p.row][p.col] = f"{p.canopy_radius * 100:.0f}"
    return table


def format_grid(table: Sequence[Sequence[str]], indent: str = "  ") -> str:
    """문자열 표를 열 맞춰 찍는다."""
    cols = len(table[0]) if table else 0
    w = max([len(c) for row in table for c in row] + [len(str(cols - 1))] + [1])
    head = indent + "     " + " ".join(f"{('c' + str(c)):>{w}}" for c in range(cols))
    lines = [head]
    for r, row in enumerate(table):
        lines.append(indent + f"r{r:<4}" + " ".join(f"{v:>{w}}" for v in row))
    return "\n".join(lines)
