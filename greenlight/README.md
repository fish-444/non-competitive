# GreenLight-Gym 동역학을 MPC 에 쓸 수 있는가 — 조사 결과

결론부터: **쓸 수 있다.** 이산시간 동역학이 `casadi.Function` 으로 이미 만들어져 있고,
Gym 환경 객체를 만들지 않고 직접 호출되며, 자코비안도 나온다.

조사 대상은 [BartvLaatum/GreenLight-Gym](https://github.com/BartvLaatum/GreenLight-Gym)
(= GreenLight-Gym2, 패키지명 `gl-gym`, 버전 0.3.1, 커밋 `8350306`).
아래 수치는 전부 그 코드를 실제로 돌려서 얻은 것이다.

검증 스크립트: [`check_casadi_dynamics.py`](check_casadi_dynamics.py)

```bash
git clone https://github.com/BartvLaatum/GreenLight-Gym.git
pip install casadi 'numpy<2.0' scipy pandas     # gymnasium 은 없어도 된다 (§1 주의 3)
python greenlight/check_casadi_dynamics.py --gl-gym-path ./GreenLight-Gym
```

---

## 1. CasADi Function 이 어디서 생성되는가

| | |
| --- | --- |
| 파일 | `gl_gym/models/GreenLight/utils.py` |
| 함수 | `define_model(nx, nu, nd, n_params, dt)` |
| 돌려주는 것 | `casadi.Function` (이름 `"F"`), CVODES integrator |
| 우변 ODE | `gl_gym/models/GreenLight/ode.py` → `ODE(x, u, d, p)` |
| 보조변수 239개 | `gl_gym/models/GreenLight/aux_states.py` → `update(x, u, d, p)` |
| 호출부 | `gl_gym/environments/greenlight_env.py:98` (`self.F = define_model(...)`) |
| 실제 사용 | `greenlight_env.py:245` — `self.F(x0=..., u=..., p=...)` |

생성 코드 전체(`utils.py`)는 이게 다다:

```python
x = ca.SX.sym("x", nx); u = ca.SX.sym("u", nu)
d = ca.SX.sym("d", nd); p = ca.SX.sym("p", n_params)
dxdt = ODE(x, u, d, p)
input_args_sym = ca.vertcat(d, p)          # <-- d 와 p 를 하나로 합친다
int_opts = {"abstol": 1e-4, "reltol": 1e-4, "max_num_steps": 7e4}
F = ca.integrator("F", "cvodes",
                  {"x": x, "u": u, "p": input_args_sym, "ode": dxdt},
                  0.0, dt, int_opts)
```

### 주의할 점 세 가지

1. **`d` 와 `p` 는 별도 인자가 아니다.** `ca.vertcat(d, p)` 로 합쳐져 단일 `p` 인자
   (10 + 208 = **218**차원)로 들어간다. 호출할 때 `p=ca.vertcat(d_k, p_model)` 로 줘야 한다.
2. **CVODES 가변스텝 적분기다.** 명시적 RK4 이산화가 아니다. 자코비안은 나오지만
   내부적으로 sensitivity 방정식을 푼다 (§4 참조).
3. **`__init__.py` 두 개가 gymnasium 을 물고 온다.** `gl_gym/__init__.py` (환경 register) 와
   `gl_gym/environments/__init__.py` (`GreenLightEnv` import) 다. 나머지 하위 패키지
   (`models/`, `models/GreenLight/`, `configs/`)의 `__init__.py` 는 비어 있다.
   그래서 저 두 자리에 빈 네임스페이스 모듈을 미리 꽂아두면 **gymnasium 을 아예 설치하지 않고도
   동역학이 돈다** — 스크립트의 `_stub_gl_gym_init()` 이 그 처리를 하고, gymnasium 을 막은 채
   실행해서 결과가 동일함을 확인했다. **Gym 환경 객체는 어느 경로에서도 만들어지지 않는다.**

### 시그니처

```
F.n_in()  = 7   실제 쓰는 것: x0 (28,1) | p (218,1) | u (6,1)     나머지는 0크기 (z0, adjoint)
F.n_out() = 7   실제 쓰는 것: xf (28,1)                            나머지는 0크기 (zf, qf, adj_*)
```

호출:

```python
res  = F(x0=ca.DM(x), u=ca.DM(u), p=ca.vertcat(ca.DM(d), ca.DM(p_model)))
xnext = res["xf"].full().flatten()
```

---

## 2. 단독 호출 최소 예제

[`check_casadi_dynamics.py`](check_casadi_dynamics.py) 에 들어 있다. 핵심만 추리면:

```python
from gl_gym.models.GreenLight.utils import define_model
from gl_gym.configs.default_params import init_default_params
from gl_gym.environments.utils import init_state
import casadi as ca, numpy as np

F = define_model(nx=28, nu=6, nd=10, n_params=208, dt=900.0)
p = np.asarray(init_default_params(208), dtype=np.float64)
d = np.array([350., 10., 1000., 757.6, 3., -5., 10., 10., 1., 1.])
x0 = init_state(d)                       # 28차원 초기상태 (d[3], d[6] 만 참조)
u = np.array([0.3, 0.2, 0.5, 0.1, 0., 0.])

xf = F(x0=ca.DM(x0), u=ca.DM(u), p=ca.vertcat(ca.DM(d), ca.DM(p)))["xf"].full().flatten()
```

실행 결과 (요약):

```
적분 1스텝 소요: 1.43 ms   (dt = 900 s)
  co2Air    757.60 ->   799.51    (uCO2=0.2 로 주입 중)
  tAir       16.50 ->    18.01    (uBoil=0.3 으로 가열 중)
  tPipe      16.50 ->    19.48
  vpAir    1681.91 ->  1903.34
  cFruit  55338.00 -> 55340.81
  time        0.00 ->   0.010417  (= 900/86400, 정확히 일치)
모두 유한한가: True
```

96스텝(=하루) 롤아웃 0.027 s (0.28 ms/step), 발산 없음.
실제 Amsterdam 2010 날씨 + 간단한 휴리스틱 제어로 **60일 5,808스텝도 안정적으로 완주**했다.

---

## 3. 상태 28 / 제어 6 / 외란 10

> **먼저 정정할 것: 제어는 8개가 아니라 6개다.**
> `gl_gym/configs/envs/GreenLightEnv.yml` 의 `nu: 6`, `gl_gym/__init__.py` 의 등록 kwargs
> `"nu": 6`, `aux_states.py:96` 의 docstring "Control vector with 6 elements", 그리고
> 업스트림 README "The agent controls 6 greenhouse actuators" 가 모두 6으로 일치한다.
> `aux_states.py` 안에 `u[8]`, `u[9]`, `u[10]` 이 보이긴 하는데 **전부 주석 처리된 줄**이다
> (차광 스크린 `uShScr` 과 측면 환기 `uSide` 잔재 — 223, 697, 714, 721, 912행).
> 살아 있는 코드는 `u[0]`~`u[5]` 만 쓴다.

범위 열의 출처 표기:
**[코드]** 코드·주석·설정파일에 명시 · **[관측]** 위 60일 시뮬레이션에서 측정 ·
**[추측]** 내 추론 (코드 근거 없음)

### 3.1 상태 x (28개)

이름은 `gl_gym/environments/utils.py:12` `init_state()` 의 주석에서, 단위는
`ode.py` 의 각 `dxdt[i]` 주석에서 가져왔다.

| i | 이름 | 물리적 의미 | 단위 | 초기값 [코드] | 관측 min~max [관측] |
|---|------|-------------|------|--------|-----------|
| 0 | `co2Air` | 주 공간(캐노피 하부) CO2 농도 | mg m⁻³ | `d[3]` (≈758) | 755 ~ 2705 |
| 1 | `co2Top` | 상부 공간(스크린 위) CO2 농도 | mg m⁻³ | `= x[0]` | 754 ~ 2704 |
| 2 | `tAir` | 온실 내 공기 온도 | °C | 16.5 | 7.8 ~ 31.4 |
| 3 | `tTop` | 스크린 위 공기 온도 | °C | 16.5 | 2.3 ~ 31.2 |
| 4 | `tCan` | 캐노피(작물) 온도 | °C | 20.5 | 8.3 ~ 32.4 |
| 5 | `tCovIn` | 피복재 내측 온도 | °C | 16.5 | −3.0 ~ 30.8 |
| 6 | `tCovE` | 피복재 외측 온도 | °C | 16.5 | −3.4 ~ 31.0 |
| 7 | `tThScr` | 보온 스크린 온도 | °C | 16.5 | 6.7 ~ 16.5 |
| 8 | `tFlr` | 바닥 온도 | °C | 16.5 | 14.3 ~ 29.8 |
| 9 | `tPipe` | 난방 배관 온도 | °C | 16.5 | 16.5 ~ 62.2 |
| 10 | `tSoil1` | 토양 1층 온도 (두께 0.04 m, `p[27]`) | °C | 16.5 | 14.2 ~ 28.1 |
| 11 | `tSoil2` | 토양 2층 (0.08 m, `p[28]`) | °C | 보간 | 13.3 ~ 25.4 |
| 12 | `tSoil3` | 토양 3층 (0.16 m, `p[29]`) | °C | 보간 | 10.8 ~ 22.1 |
| 13 | `tSoil4` | 토양 4층 (0.32 m, `p[30]`) | °C | 보간 | 8.0 ~ 19.2 |
| 14 | `tSoil5` | 토양 5층 (0.64 m, `p[31]`) | °C | `d[6]` | 5.1 ~ 15.1 |
| 15 | `vpAir` | 주 공간 수증기압 | Pa | RH 90% 상당 | 716 ~ 3057 |
| 16 | `vpTop` | 상부 공간 수증기압 | Pa | `= x[15]` | 635 ~ 3036 |
| 17 | `tLamp` | 상부(토프) 램프 온도 | °C | 16.5 | 7.8 ~ 31.3 |
| 18 | `tIntLamp` | 인터라이트 램프 온도 | °C | 16.5 | 상수 16.5 ※ |
| 19 | `tGroPipe` | 그로우 파이프(작물 사이 배관) 온도 | °C | 16.5 | 12.5 ~ 24.6 |
| 20 | `tBlScr` | 암막 스크린 온도 | °C | 16.5 | 상수 16.5 ※ |
| 21 | `tCan24` | 최근 24시간 평균 캐노피 온도 | °C | `= x[4]` | 14.2 ~ 21.2 |
| 22 | `cBuf` | 완충 저장 탄수화물 | mg{CH2O} m⁻² | 0 | −61 ~ 1.60e4 |
| 23 | `cLeaf` | 잎 탄수화물 | mg{CH2O} m⁻² | 9.5283e4 | 9.37e4 ~ 9.81e4 |
| 24 | `cStem` | 줄기 탄수화물 | mg{CH2O} m⁻² | 2.5107e5 | 2.50e5 ~ 2.96e5 |
| 25 | `cFruit` | 과실 탄수화물 (← 수확량) | mg{CH2O} m⁻² | 5.5338e4 | 5.53e4 ~ 6.45e5 |
| 26 | `tCanSum` | 적산온도 (생육단계 지표) | °C·day | 3.0978e3 | 3098 ~ 4118 |
| 27 | `time` | 시뮬레이션 시작 후 경과 시간 | day | 0 | 0 ~ 60.5 |

※ `tIntLamp` 이 상수인 건 기본 파라미터에서 인터라이트가 꺼져 있기 때문이다
(`p[188] = intLamps = 0`). `tBlScr` 이 상수인 건 내 테스트 제어가 `uBlScr = 0` 이었기 때문이고,
암막을 쓰면 움직인다.

MPC 제약에 직접 쓸 만한 것 — 설정파일 `GreenLightEnv.yml` 의 `constraints` 블록 **[코드]**:

| 물리량 | 하한 | 상한 | 상태에서 얻는 법 |
|--------|------|------|------------------|
| CO2 | 300 ppm | 1600 ppm | `co2dens2ppm(x[2], x[0]*1e-6)` |
| 온도 | 15 °C | 34 °C | `x[2]` 그대로 |
| 상대습도 | 50 % | 85 % | `vaporPres2rh(x[2], x[15])` |

`co2Air` 는 **ppm 이 아니라 mg m⁻³** 다. 대략 400 ppm ≈ 758 mg m⁻³, 1600 ppm ≈ 2900 mg m⁻³
(정확한 변환은 온도에 의존, `environments/utils.py:336` `co2dens2ppm`).
`p[7] = etaMgPpm = 0.554` 라는 상수 근사도 코드에 있다.

### 3.2 제어 u (6개)

전부 **무차원 정규화 밸브 개도 [0, 1]** 이다 (`GreenLightEnv.yml`: `u_min` 전부 0, `u_max` 전부 1).
물리 단위로의 환산 계수는 파라미터 벡터에 들어 있다.

| j | 이름 | 물리적 의미 | 범위 [코드] | 물리 스케일 [코드] |
|---|------|-------------|------|-----------|
| 0 | `uBoil` | 보일러 난방수 밸브 개도 | 0~1 | `p[108] = pBoil = 130 × aFlr` W (기본 aFlr=144 m² → 18.7 kW) |
| 1 | `uCO2` | CO2 시비 밸브 개도 | 0~1 | `p[109] = phiExtCo2 = 5.0 × aFlr` mg s⁻¹ (기본 720 mg/s) |
| 2 | `uThScr` | 보온 스크린 전개율 (1 = 완전히 닫음) | 0~1 | — |
| 3 | `uVent` | 천창 환기창 개도 | 0~1 | `p[55] = aRoof` 최대 환기면적에 곱해짐 |
| 4 | `uLamp` | 보광등 출력 | 0~1 | `p[172] = thetaLampMax = 116` W m⁻² |
| 5 | `uBlScr` | 암막 스크린 전개율 | 0~1 | — |

에이전트 액션과 모델 입력 `u` 는 다르다 — `NamedControlActionScheme`
(`gl_gym/components/actions.py`)이 정규화 액션 [−1,1] 을 **변화율**로 해석해서
`u_{k+1} = clip(u_k + a·delta_u_max, 0, 1)`, `delta_u_max = 0.1` 로 적분한다.
**MPC 를 짤 땐 이 래퍼를 건너뛰고 `u ∈ [0,1]^6` 을 직접 결정변수로 두면 된다.**
레이트 제약을 그대로 살리고 싶으면 `|u_{k+1} − u_k| ≤ 0.1` 을 직접 넣으면 된다.

### 3.3 외란 d (10개)

`gl_gym/environments/utils.py:74` `load_weather_data()` 의 docstring 에 전부 명시돼 있다.
관측 범위는 동봉 데이터 `gl_gym/data/weather/Amsterdam/2010.csv`, 59일차부터 60일간
(5,808 스텝, 15분 간격) 기준.

| k | 이름 | 물리적 의미 | 단위 [코드] | 관측 min ~ max [관측] | 중앙값 |
|---|------|-------------|------|-----------|--------|
| 0 | `iGlob` | 전천 일사량 | W m⁻² | 0 ~ 864 | 18.8 |
| 1 | `tOut` | 외기 온도 | °C | −4.7 ~ 24.0 | 7.5 |
| 2 | `vpOut` | 외기 수증기압 | Pa | 320 ~ 1528 | 800 |
| 3 | `co2Out` | 외기 CO2 밀도 | mg m⁻³ | 722 ~ 799 | 764 |
| 4 | `wind` | 풍속 | m s⁻¹ | 0 ~ 12.9 | 4.7 |
| 5 | `tSky` | 천공 온도 (복사 냉각용) | °C | −33.4 ~ 17.3 | −1.6 |
| 6 | `tSoOut` | 외부 지중 온도 (깊이 1 m) | °C | 5.1 ~ 8.5 | 6.3 |
| 7 | `dli` | 일적산광량 | MJ m⁻² day⁻¹ | 2.0 ~ 23.8 | 11.9 |
| 8 | `isDay` | 주야 지시자 (선형 전이) | 0/1 | 0 ~ 1 | 1 |
| 9 | `isDaySmooth` | 주야 지시자 (시그모이드 전이) | 0~1 | 0 ~ 1 | 1 |

**중요:** `d[7]`, `d[8]`, `d[9]` (`dli`, `isDay`, `isDaySmooth`) 는 **ODE 안에서 전혀 안 쓰인다.**
`aux_states.py` 와 `ode.py` 를 통틀어 참조되는 건 `d[0]`~`d[6]` 뿐이다.
뒤 3개는 관측(`WeatherObservations`)과 룰베이스 컨트롤러 전용이다.
그래도 `F` 의 `p` 인자는 218차원 고정이니 **10개를 다 채워 넣어야 한다** (뒤 3개는 아무 값이나 무방).

`co2Out` 은 CSV 에 없다 — 400 ppm 상수로 가정하고 외기 온도로 밀도 환산한다
(`utils.py:89` `CO2_PPM = 400`). `tSoOut` 도 측정값이 아니라 네덜란드 초지 실측 논문 기반
사인함수 근사다 (`utils.py:258` `soilTempNl`).

### 3.4 파라미터 p (208개)

`gl_gym/configs/default_params.py` `init_default_params(208)` 에 208개 전부 이름·단위 주석과 함께
하드코딩돼 있다. MPC 에서는 상수로 두면 된다. 불확실성을 다루고 싶으면
`gl_gym/configs/greenlight_parameters.py` 가 튜닝 대상 5개를 인덱스·범위와 함께 정의해 둔 게 있다:

| 이름 | 인덱스 | 범위 | 단위 |
|------|--------|------|------|
| `floor_area` | `p[46]` | 0 ~ 2000 | m² |
| `max_heating_power` | `p[108]` | 0 ~ 1e6 | W |
| `max_co2_dosing` | `p[109]` | 0 ~ 1e5 | mg/s |
| `max_fruit_dw_growth_rate` | `p[154]` | 0.2 ~ 0.5 | mg/m²/s |
| `lamp_power` | `p[172]` | 50 ~ 400 | W/m² |

---

## 4. 자코비안 — 나온다

### 4a. `F.jacobian()` — 된다

```
생성 성공 (0.08 s)
  jac_xf_x0    (28, 28)     <- A
  jac_xf_u     (28, 6)      <- B
  jac_xf_p     (28, 218)    <- 외란/파라미터 민감도
```

나머지 출력은 대수변수 `z` 와 adjoint 라 전부 0×0 이다 (순수 ODE라 대수변수가 없음).
CasADi 가 CVODES 의 forward sensitivity 를 써서 자동으로 만들어 준다.

### 4b. 심볼릭 `ca.jacobian` — 된다 (MPC 에서 실제로 쓸 형태)

```python
xs = ca.MX.sym("x", 28); us = ca.MX.sym("u", 6); ps = ca.MX.sym("p", 218)
xfs = F(x0=xs, u=us, p=ps)["xf"]
JF = ca.Function("JF", [xs, us, ps],
                 [ca.jacobian(xfs, xs), ca.jacobian(xfs, us)], ["x","u","p"], ["A","B"])
```

```
A (28, 28), B (28, 6), 평가 176.9 ms
유한한가: A=True, B=True
A 대각 (1스텝 감쇠):  co2Air 0.545 | tAir 0.093 | tPipe 0.894 | vpAir 0.262 | cFruit 0.99992
B 열별 |합|:  uBoil 27.9 | uCO2 1170.2 | uThScr 276.5 | uVent 4601.4 | uLamp 448.8 | uBlScr 548.0
```

A 대각을 보면 물리적으로 말이 된다: `cFruit` 은 900초 만에 거의 안 변하고(0.99992),
공기 온도는 열용량이 작아 한 스텝이면 대부분 잊는다(0.093). MPC 튜닝의 좋은 출발점이다.

즉 `ca.nlpsol` / `ca.Opti` 에 그대로 넘겨도 IPOPT 가 미분을 받아갈 수 있다. **MPC 구성에 필요한
조건은 충족된다.**

### 다만 — 실제로 MPC 를 붙일 때 걸릴 것

자코비안 **1회 평가가 177 ms** 다. 한 스텝짜리인데도 그렇다. 예측 구간 N=24 짜리 다중슈팅이면
NLP 한 번 반복에 24번 = 4초 넘게 잡아먹고, IPOPT 가 수십 번 반복하면 감당이 안 된다.
가변스텝 적분기 안에서 sensitivity 방정식까지 푸느라 그렇다.

명시적 RK4 로 갈아타는 걸 검토해서 §5 로 측정해 봤는데 — **이 시스템은 강성(stiff)이다**:

| 서브스텝 | h [s] | CVODES 대비 max 오차 |
|---------|-------|---------------------|
| 1 | 900 | **NaN (발산)** |
| 15 | 60 | **NaN** |
| 60 | 15 | **NaN** |
| 150 | 6 | **NaN** |
| 300 | 3 | 1.17e−2 |
| 900 | 1 | 1.17e−2 |

h ≤ 3 s 라야 안정적이다. 900초 한 스텝에 서브스텝 300개, 즉 ODE 평가 1200회가 필요하다.
그래도 평가 자체는 9 ms 로 CVODES 자코비안(177 ms)보다 훨씬 싸긴 하지만, 심볼릭 그래프가
거대해져 IPOPT 코드생성 시간이 문제가 된다.

**MPC 를 짤 때 권할 방향** (아직 코드는 안 짰다, 결정은 다음 단계에서):

1. **직교 콜로케이션** (Radau IIA 3~4차) — 강성에 강하고, 심볼릭 그래프가 RK4-300 보다 훨씬
   작고, `ca.Opti` 다중슈팅에 그대로 얹힌다. 가장 유력하다.
2. **`ca.integrator` 를 `"idas"`/`"collocation"` 플러그인으로 교체** — `define_model` 을 그대로
   베끼고 `"cvodes"` 만 바꾸면 된다. 가장 손이 덜 간다.
3. 제어 구간을 900초로 두되 **적분 구간을 더 잘게** 쪼개기.

어느 쪽이든 `ODE(x, u, d, p)` 를 그대로 재사용하면 된다. 이 함수는 순수 CasADi SX 식이라
적분기 선택과 완전히 분리돼 있다.

---

## 부수적으로 발견한 것

`gl_gym/components/observations.py` 의 `StateObservations` 는 `space` 를 `shape=(27,)` 로
선언해 놓고 `compute_obs` 는 28차원 `ctx.x` 를 그대로 돌려준다. 업스트림 README 표에도
27로 적혀 있다. 기본 관측 모듈 목록에는 안 들어 있어서 평소엔 안 터지지만, 이 모듈을 켜면
관측공간과 실제 관측이 어긋난다. 우리 MPC 경로에는 영향 없다 (관측 모듈을 안 쓰므로).
