"""GreenLight-Gym 의 CasADi 동역학을 Gym 환경 없이 단독으로 꺼내 쓰는지 확인한다.

MPC 에 쓰려면 이산시간 동역학 x_{k+1} = f(x_k, u_k, d_k, p) 가 CasADi Function 으로
있어야 하고, 거기서 자코비안이 나와야 한다. 이 스크립트는 그 두 가지만 검증한다.
(MPC 자체는 아직 짜지 않는다.)

확인 항목
  1. define_model() 이 돌려주는 F 가 정말 casadi.Function 인지, 입출력 시그니처는 무엇인지
  2. GreenLightEnv 를 만들지 않고 F 를 직접 호출해 다음 상태가 나오는지
  3. 여러 스텝 굴려도 발산하지 않는지
  4. F.jacobian() 이 되는지 / 심볼릭 ca.jacobian 으로 A, B 가 뽑히는지
  5. (참고) 명시적 RK4 로 바꿔도 되는지 — 강성(stiff) 때문에 서브스텝이 얼마나 필요한지

실행
    python greenlight/check_casadi_dynamics.py --gl-gym-path /path/to/GreenLight-Gym
    GL_GYM_PATH=/path/to/GreenLight-Gym python greenlight/check_casadi_dynamics.py

GreenLight-Gym 은 이 저장소에 포함돼 있지 않다. 별도로 클론해서 경로를 넘겨라.
    git clone https://github.com/BartvLaatum/GreenLight-Gym.git
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import types

import numpy as np

# GreenLightEnv.yml / gl_gym/__init__.py 의 등록값과 같아야 한다.
NX = 28      # 상태
NU = 6       # 제어 (README 등에서 8개로 알려진 것과 다르다 — 실제 코드는 6개)
ND = 10      # 외란(날씨)
NPARAM = 208  # 모델 파라미터
DT = 900.0   # [s] 솔버 스텝

STATE_NAMES = [
    "co2Air", "co2Top", "tAir", "tTop", "tCan", "tCovIn", "tCovE", "tThScr",
    "tFlr", "tPipe", "tSoil1", "tSoil2", "tSoil3", "tSoil4", "tSoil5",
    "vpAir", "vpTop", "tLamp", "tIntLamp", "tGroPipe", "tBlScr", "tCan24",
    "cBuf", "cLeaf", "cStem", "cFruit", "tCanSum", "time",
]
CONTROL_NAMES = ["uBoil", "uCO2", "uThScr", "uVent", "uLamp", "uBlScr"]
DISTURBANCE_NAMES = [
    "iGlob", "tOut", "vpOut", "co2Out", "wind", "tSky", "tSoOut",
    "dli", "isDay", "isDaySmooth",
]


def _resolve_gl_gym(path: str | None) -> str:
    """gl_gym 패키지를 import 할 수 있게 sys.path 를 잡고, 쓰는 경로를 돌려준다."""
    candidates = [path, os.environ.get("GL_GYM_PATH")]
    for cand in candidates:
        if cand and os.path.isdir(os.path.join(cand, "gl_gym")):
            sys.path.insert(0, os.path.abspath(cand))
            return os.path.abspath(cand)

    try:  # 이미 pip 설치돼 있는 경우
        import gl_gym  # noqa: F401
        return os.path.dirname(os.path.dirname(os.path.abspath(gl_gym.__file__)))
    except ImportError:
        pass

    sys.exit(
        "gl_gym 을 찾지 못했다. --gl-gym-path 로 GreenLight-Gym 클론 경로를 넘기거나\n"
        "GL_GYM_PATH 환경변수를 설정해라."
    )


def _stub_gl_gym_init(root: str) -> bool:
    """gymnasium 을 끌어들이는 __init__.py 들을 건너뛰도록 빈 모듈을 미리 꽂는다.

    두 군데가 gymnasium 을 물고 온다.
      · gl_gym/__init__.py              -> gymnasium 으로 환경을 register 한다
      · gl_gym/environments/__init__.py -> GreenLightEnv 를 import 한다
    둘 다 자리에 빈 네임스페이스 모듈을 넣어두면 하위 모듈(models/, configs/,
    environments/utils.py)은 그대로 import 되고 gymnasium 은 필요 없어진다.
    gymnasium 이 설치돼 있으면 굳이 건드리지 않는다.
    """
    try:
        import gymnasium  # noqa: F401
        return False
    except ImportError:
        pass

    for name, rel in (("gl_gym", "gl_gym"),
                      ("gl_gym.environments", "gl_gym/environments")):
        pkg = types.ModuleType(name)
        pkg.__path__ = [os.path.join(root, *rel.split("/"))]
        sys.modules[name] = pkg
    return True


def build_reference_inputs(init_state):
    """네덜란드 초봄 낮 정도의 그럴듯한 x0, u, d, p 를 만든다.

    실제 날씨 CSV 를 읽지 않는다 — 임의 입력으로 함수가 도는지만 보는 게 목적이다.
    """
    d = np.array([
        350.0,   # iGlob   [W m-2]   낮 중간 정도의 일사
        10.0,    # tOut    [degC]
        1000.0,  # vpOut   [Pa]
        757.6,   # co2Out  [mg m-3]  10 degC 에서 400 ppm
        3.0,     # wind    [m s-1]
        -5.0,    # tSky    [degC]
        10.0,    # tSoOut  [degC]
        10.0,    # dli     [MJ m-2 d-1]
        1.0,     # isDay        [0/1]
        1.0,     # isDaySmooth  [0/1]
    ])
    # init_state 는 d[3](co2Out) 과 d[6](tSoOut) 만 쓴다.
    x0 = init_state(d)
    u = np.array([0.3, 0.2, 0.5, 0.1, 0.0, 0.0])  # 보일러/CO2/스크린/환기/램프/암막
    return x0, u, d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gl-gym-path", default=None, help="GreenLight-Gym 클론 경로")
    ap.add_argument("--rollout", type=int, default=96, help="굴려볼 스텝 수 (96 = 하루)")
    args = ap.parse_args()

    root = _resolve_gl_gym(args.gl_gym_path)
    stubbed = _stub_gl_gym_init(root)

    import casadi as ca
    from gl_gym.configs.default_params import init_default_params
    from gl_gym.environments.utils import init_state
    from gl_gym.models.GreenLight.utils import define_model

    print(f"gl_gym  : {root}")
    print(f"casadi  : {ca.__version__}")
    print(f"gymnasium 우회 stub 사용: {stubbed}")

    # ---------------------------------------------------------------- 1. 함수 생성
    print("\n=== 1. define_model() 로 CasADi Function 만들기 ===")
    F = define_model(nx=NX, nu=NU, nd=ND, n_params=NPARAM, dt=DT)
    print(f"type            : {type(F).__module__}.{type(F).__name__}")
    print(f"casadi.Function : {isinstance(F, ca.Function)}")
    print(f"name / n_in / n_out : {F.name()} / {F.n_in()} / {F.n_out()}")
    for i in range(F.n_in()):
        if F.numel_in(i):
            print(f"  in [{i}] {F.name_in(i):8s} {F.size_in(i)}")
    for i in range(F.n_out()):
        if F.numel_out(i):
            print(f"  out[{i}] {F.name_out(i):8s} {F.size_out(i)}")
    print("주의: 외란 d 와 파라미터 p 는 별도 인자가 아니라 vertcat(d, p) 로 합쳐서")
    print(f"      단일 'p' 인자({ND}+{NPARAM}={ND + NPARAM})로 들어간다.")

    # ---------------------------------------------------------------- 2. 단독 호출
    print("\n=== 2. Gym 환경 없이 한 스텝 적분 ===")
    p = np.asarray(init_default_params(NPARAM), dtype=np.float64)
    x0, u, d = build_reference_inputs(init_state)
    p_dyn = ca.vertcat(ca.DM(d), ca.DM(p))

    t0 = time.perf_counter()
    xf = F(x0=ca.DM(x0), u=ca.DM(u), p=p_dyn)["xf"].full().flatten()
    dt_eval = time.perf_counter() - t0

    print(f"적분 1스텝 소요: {dt_eval * 1e3:.2f} ms   (dt = {DT:.0f} s)")
    print(f"{'idx':>3} {'name':<10} {'x0':>14} {'x_next':>14} {'delta':>13}")
    for i, name in enumerate(STATE_NAMES):
        print(f"{i:3d} {name:<10} {x0[i]:14.4f} {xf[i]:14.4f} {xf[i] - x0[i]:13.5f}")
    print(f"모두 유한한가: {np.all(np.isfinite(xf))}")
    # time 상태는 하루 단위이므로 정확히 DT/86400 만큼 늘어야 한다 — 새너티 체크.
    print(f"time 증분 검증: {xf[27] - x0[27]:.8f} (기대 {DT / 86400:.8f})")

    # ---------------------------------------------------------------- 3. 롤아웃
    print(f"\n=== 3. {args.rollout} 스텝 롤아웃 (제어·외란 고정) ===")
    x = x0.copy()
    t0 = time.perf_counter()
    diverged = False
    for k in range(args.rollout):
        x = F(x0=ca.DM(x), u=ca.DM(u), p=p_dyn)["xf"].full().flatten()
        if not np.all(np.isfinite(x)):
            print(f"  스텝 {k} 에서 발산")
            diverged = True
            break
    elapsed = time.perf_counter() - t0
    if not diverged:
        print(f"{args.rollout} 스텝 {elapsed:.3f} s "
              f"({elapsed / args.rollout * 1e3:.2f} ms/step), 발산 없음")
        for i in (0, 2, 9, 15, 25, 27):
            print(f"  {STATE_NAMES[i]:<10} {x0[i]:12.3f} -> {x[i]:12.3f}")

    # ---------------------------------------------------------------- 4. 자코비안
    print("\n=== 4a. F.jacobian() ===")
    try:
        t0 = time.perf_counter()
        Fjac = F.jacobian()
        build = time.perf_counter() - t0
        idx = {Fjac.name_out(i): i for i in range(Fjac.n_out())}
        print(f"생성 성공 ({build:.2f} s). 관심 있는 블록만:")
        for nm in ("jac_xf_x0", "jac_xf_u", "jac_xf_p"):
            print(f"  {nm:<12} {Fjac.size_out(idx[nm])}")
        print("  (나머지 출력은 대수변수 z / adjoint 라 0x0 이다)")
    except Exception as exc:  # pragma: no cover
        print(f"실패: {type(exc).__name__}: {exc}")

    print("\n=== 4b. 심볼릭 ca.jacobian 으로 A, B 뽑기 (MPC 에서 실제로 쓸 형태) ===")
    try:
        xs = ca.MX.sym("x", NX)
        us = ca.MX.sym("u", NU)
        ps = ca.MX.sym("p", ND + NPARAM)
        xfs = F(x0=xs, u=us, p=ps)["xf"]
        JF = ca.Function(
            "JF", [xs, us, ps],
            [ca.jacobian(xfs, xs), ca.jacobian(xfs, us)],
            ["x", "u", "p"], ["A", "B"],
        )
        t0 = time.perf_counter()
        out = JF(x=ca.DM(x0), u=ca.DM(u), p=p_dyn)
        dt_jac = time.perf_counter() - t0
        A, B = out["A"].full(), out["B"].full()
        print(f"A {A.shape}, B {B.shape}, 평가 {dt_jac * 1e3:.1f} ms")
        print(f"유한한가: A={np.all(np.isfinite(A))}, B={np.all(np.isfinite(B))}")
        print("A 대각 (상태별 1스텝 감쇠):")
        for i in (0, 2, 9, 15, 25):
            print(f"  d{STATE_NAMES[i]}_next/d{STATE_NAMES[i]} = {A[i, i]: .5f}")
        print("B 열별 |합| (제어 민감도):")
        for j, name in enumerate(CONTROL_NAMES):
            print(f"  {name:<8} {np.abs(B[:, j]).sum():12.3f}")
    except Exception as exc:  # pragma: no cover
        import traceback
        traceback.print_exc()

    # ---------------------------------------------------------------- 5. RK4 강성
    print("\n=== 5. (참고) 명시적 RK4 로 대체 가능한가 — 강성 확인 ===")
    try:
        from gl_gym.models.GreenLight.ode import ODE

        sx = ca.SX.sym("x", NX)
        su = ca.SX.sym("u", NU)
        sd = ca.SX.sym("d", ND)
        sp = ca.SX.sym("p", NPARAM)
        f = ca.Function("f", [sx, su, sd, sp], [ODE(sx, su, sd, sp)])

        print(f"{'substeps':>9} {'h[s]':>8} {'max|err vs cvodes|':>20}")
        for M in (1, 15, 60, 150, 300, 900):
            h = DT / M
            xk = sx
            for _ in range(M):
                k1 = f(xk, su, sd, sp)
                k2 = f(xk + h / 2 * k1, su, sd, sp)
                k3 = f(xk + h / 2 * k2, su, sd, sp)
                k4 = f(xk + h * k3, su, sd, sp)
                xk = xk + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            Frk = ca.Function("Frk", [sx, su, sd, sp], [xk])
            xr = Frk(ca.DM(x0), ca.DM(u), ca.DM(d), ca.DM(p)).full().flatten()
            err = np.max(np.abs(xf - xr))
            print(f"{M:9d} {h:8.2f} {err:20.4e}")
        print("h 가 3 s 보다 크면 터진다 — 강성 시스템이다. MPC 에서 명시적 RK4 를 쓰려면")
        print("스텝당 300 서브스텝쯤 필요하고, 그럴 바엔 collocation / implicit 쪽이 낫다.")
    except Exception as exc:  # pragma: no cover
        import traceback
        traceback.print_exc()

    print("\n완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
