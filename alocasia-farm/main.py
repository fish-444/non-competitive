"""
알로카시아 스마트팜 3D 온실 - FastAPI 백엔드
=================================================

핵심 파이프라인만:
  [웹 UI] 사진 + 식물 이름 + 자리(A1~E10) 선택
      │  POST /api/plants  (name, file, pos)
      ▼
  [FastAPI] YOLO 모델 2개로 분석 →
      · 모델1 맨 위 잎(광합성) → top_leaf_size  → 3D 화분/식물 크기
      · 모델2 잎 단계          → shoot/mature/old → 3D 잎 색 + 모달 수치
      · 겹침 밀도(overlap), 크기 분류(대/중/소품)
      → 선택한 자리에 식물로 등록/저장
      ▼
  [3D 온실] 화분으로 시각화, 클릭 시 이름+분석결과 모달

센서·RAG 없음. 오직 [사진+이름+자리 → YOLO → 3D 반영 + 이름/방향 커스텀].

좌표계가 네 가지라 변수 이름 뒤에 어느 것인지 붙인다:
  _px      이미지 픽셀        0~4032    탐지 박스, 화면 클릭
  _uv      선반 정규좌표      0~1       화분 자리 저장값 (카메라와 무관)
  _canvas  선반 가상 픽셀     0~1000    여러 장을 합칠 때 쓰는 공통 도화지
  _cm      실좌표 센티미터    -30~30    3D 배치, 조명 위치, 슬롯 중심

  px ──(원근 변환)──> canvas ──(/CANVAS)──> uv ──(x_W-W/2)──> cm

분석 엔진 자동 선택:
  1) 로보플로우(ROBOFLOW_API_KEY 있으면)  2) 로컬 ultralytics(.pt)  3) 데모(모델 없어도 동작)
실행법은 README.md 참고.
"""

import base64
import io
import math
import os
import re
import time
import uuid
from datetime import date
from typing import Dict, List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

import placement
import providers

# --------------------------------------------------------------------------- 설정
def _load_env_file() -> None:
    """farm_env.bat / farm_env.sh 를 앱이 직접 읽어 환경변수로 올린다.

    지금까지는 start.bat 이 call 로 불러 주는 것에 기대고 있었다. 그래서
    `uvicorn main:app` 을 직접 띄우면 설정이 통째로 무시돼 조용히 데모 모드로
    떨어졌다 — README 의 '명령어로 실행' 절이 바로 그 경로를 안내하고 있었다.
    실행 방법에 따라 결과가 달라지는 건 고쳐야 할 쪽이 앱이다.

    이미 환경에 있는 값은 덮지 않는다. 파워셸에서 직접 지정했거나 start.bat 이
    먼저 불러 준 값이 우선이어야 한다.
    """
    for name in ("farm_env.bat", "farm_env.sh"):
        path = os.path.join(os.getcwd(), name)
        if not os.path.exists(path):
            continue
        loaded = []
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(("rem ", "REM ", "::", "#", "@")):
                        continue
                    m = re.match(r"(?:set\s+|export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)", line)
                    if not m:
                        continue
                    key, val = m.group(1), m.group(2).strip()
                    if key in os.environ:          # 이미 지정된 값이 우선
                        continue
                    os.environ[key] = val
                    loaded.append(key)
        except OSError:
            return
        if loaded:
            print(f"[설정] {name} 에서 {len(loaded)}개 값을 읽었습니다: {', '.join(loaded)}")
        return


_load_env_file()


def _report_env_file() -> None:
    """키가 안 잡힐 때, 설정 파일 쪽인지 전달 쪽인지 갈라 준다.

    "[키] 없음" 만으로는 원인을 못 좁힌다. 파일이 없는 건지, 파일은 있는데 키
    줄이 빈 건지, 파일엔 키가 멀쩡히 있는데 앱까지 안 넘어온 건지가 전부 다른
    문제인데 증상이 같다. 마지막 경우가 특히 헷갈린다 — 파일을 고쳐 놓고
    저장을 안 했거나, 다른 폴더의 파일을 고쳤거나, start.bat 을 안 거치고
    uvicorn 을 직접 띄운 경우다.
    """
    here = os.getcwd()
    env_file = os.path.join(here, "farm_env.bat")
    has_env = bool(os.environ.get("ROBOFLOW_API_KEY", "").strip())

    if not os.path.exists(env_file):
        print(f"[설정] farm_env.bat 이 없습니다 — {here}")
        print("[설정]   farm_env.example.bat 을 farm_env.bat 으로 복사하고 키를 넣으세요.")
        print("[설정]   (메모장 '다른 이름으로 저장' 은 farm_env.bat.txt 를 만들기 쉽습니다. "
              "파일 형식을 '모든 파일' 로 두세요)")
        return

    in_file = ""
    try:
        with open(env_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"\s*set\s+ROBOFLOW_API_KEY\s*=(.*)", line, re.I)
                if m:
                    in_file = m.group(1).strip()
    except OSError as e:
        print(f"[설정] farm_env.bat 을 읽을 수 없습니다: {e}")
        return

    if has_env:
        return                                   # 정상 — [키] 줄이 이미 알려 준다
    if not in_file:
        print(f"[설정] farm_env.bat 에 키가 비어 있습니다 — {env_file}")
        print("[설정]   set ROBOFLOW_API_KEY=... 줄에 Private API Key 를 넣으세요.")
    else:
        # 여기가 핵심 — 파일엔 있는데 앱까지 안 왔다
        print(f"[설정] farm_env.bat 에는 키가 있는데({in_file[:4]}…) 앱까지 오지 않았습니다.")
        print(f"[설정]   파일: {env_file}")
        print("[설정]   ROBOFLOW_API_KEY 가 빈 값으로 환경에 이미 있으면 파일 값이 무시됩니다.")
        print("[설정]   그 창을 닫고 새로 여신 뒤 다시 켜 보세요.")


_report_env_file()

# 탐지기는 providers 패키지가 환경변수를 보고 골라 준다.
# 로보플로우를 걷어내고 로컬 모델로 갈아탈 때도 이 파일은 손대지 않는다.
DETECT_TOP, DETECT_STAGE = providers.select()
ENGINE_LABEL = DETECT_TOP.name          # 화면 왼쪽 위에 표시
print(f"[분석 엔진] {ENGINE_LABEL}")

CONFIDENCE = providers.CONFIDENCE

app = FastAPI(title="Alocasia Smart Farm")

# --------------------------------------------------------------------------- 상태
PLANTS: Dict[str, dict] = {}          # id -> 식물 상태
FEATS: Dict[str, dict] = {}           # id -> 생김새 특징(모양 그룹 계산용, 응답에는 안 나감)
# 미리 지정한 화분 자리 — 모델에 pot 클래스를 라벨링하는 대신 쓴다.
# 화분은 안 움직이니 한 번만 찍어 두면 계속 재사용되고, 자리(슬롯)가 고정돼
# 매번 스캔해도 "이 화분 = 항상 같은 식물"이 유지된다. 선반 정규좌표(0~1).
POTS: List[dict] = []
# 잎 낱개 기록. 개체 단위 집계만으론 '이 잎이 어느 화분 것'을 손으로 못 고친다.
LEAVES: Dict[str, dict] = {}          # leaf_id -> 잎 하나
# 사람이 옮긴 잎은 위치로 기억한다. 잎에는 고유번호가 없어서 다음 스캔의 잎과
# 짝지을 방법이 없다 — 대신 '그 자리에 난 잎은 이 화분 것'으로 기억해 두면
# 재스캔해도 보정이 살아남는다. 선반 정규좌표(uv).
LEAF_FIXES: List[dict] = []           # [{"u","v","pot_slot"}]
# 조명·팬 실측 위치(cm). 비어 있으면 placement 의 기본값을 쓴다.
ENVIRONMENT: dict = {}
# 번호 붙은 자리(슬롯): 온실 60x40cm 을 촘촘한 격자로 분할
# 기본 A1~E10 (5줄 x 10칸 = 50자리)
_ROWS = ["A", "B", "C", "D", "E"]
_COLS = 10
_W, _D = 60.0, 40.0
_CW, _CD = _W / _COLS, _D / len(_ROWS)      # 칸 크기 (6 x 8 cm)
SLOTS = [{"label": f"{r}{c + 1}",
          "x": round(-_W / 2 + _CW * (c + 0.5), 2),
          "z": round(-_D / 2 + _CD * (ri + 0.5), 2)}
         for ri, r in enumerate(_ROWS) for c in range(_COLS)]


# --------------------------------------------------------------------------- 저장
# 식물·화분 자리를 파일에 남긴다. 안 그러면 서버를 끌 때마다 손으로 고친 값과
# 새 잎 기록이 통째로 날아간다. FARM_DB="" 로 두면 저장하지 않는다(테스트용).
FARM_DB = os.environ.get("FARM_DB", "farm.db")


def _db():
    import sqlite3
    con = sqlite3.connect(FARM_DB)
    con.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT)")
    return con


def save_state() -> None:
    """지금 상태를 저장. 바뀔 때마다 부른다 (개체 수가 적어 통째로 써도 싸다)."""
    if not FARM_DB:
        return
    import json
    try:
        with _db() as con:
            for key, val in (("plants", PLANTS), ("feats", FEATS), ("pots", POTS),
                             ("leaves", LEAVES), ("leaf_fixes", LEAF_FIXES),
                             ("env", ENVIRONMENT)):
                con.execute(
                    "INSERT INTO state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(val, ensure_ascii=False)))
    except Exception as e:                      # 저장이 실패해도 서비스는 계속
        print(f"[경고] 저장 실패: {e}")


def load_state() -> None:
    """서버 시작 때 이전 상태를 되살린다."""
    if not FARM_DB or not os.path.exists(FARM_DB):
        return
    import json
    try:
        with _db() as con:
            rows = dict(con.execute("SELECT key, value FROM state").fetchall())
        PLANTS.update(json.loads(rows.get("plants", "{}")))
        FEATS.update(json.loads(rows.get("feats", "{}")))
        POTS.extend(json.loads(rows.get("pots", "[]")))
        LEAVES.update(json.loads(rows.get("leaves", "{}")))
        LEAF_FIXES.extend(json.loads(rows.get("leaf_fixes", "[]")))
        ENVIRONMENT.update(json.loads(rows.get("env", "{}")))
        if PLANTS or POTS:
            print(f"[저장소] 식물 {len(PLANTS)}개 · 화분자리 {len(POTS)}개 · "
                  f"잎 {len(LEAVES)}장 불러옴 ({FARM_DB})")
    except Exception as e:
        print(f"[경고] 불러오기 실패({e}) — 빈 상태로 시작합니다")


load_state()


def _slot_by_label(label: str):
    return next((s for s in SLOTS if s["label"] == label), None)


def _free_slot(prefer: str = None):
    used = {p.get("pos") for p in PLANTS.values()}
    if prefer:
        s = _slot_by_label(prefer)
        if s and s["label"] not in used:
            return s
    return next((s for s in SLOTS if s["label"] not in used), None)


# --------------------------------------------------------------------------- YOLO 탐지
# YOLO 가 잡아도 식물이 아닌 걸로 취급해 버리는 클래스 — 잡초/풀 뭉치 등.
# NON_LEAF 와는 역할이 다르다: NON_LEAF(예: pot)는 화분 자리를 찾는 '신호'로
# 계속 쓰이지만, 여긴 그 무엇으로도 안 쓰는 순수 잡음이라 탐지 직후 통째로
# 버린다 — 그룹화의 '화분 자리 후보'로도 안 들어가야 하기 때문이다(잡초 뭉치가
# 가짜 화분처럼 취급되면 근처 잎이 잡초 쪽으로 잘못 붙는다).
# Roboflow 쪽에 별도 클래스(예: weed)를 학습시켜 두면 여기서 자동으로 걸러진다.
NOISE_CLASSES = {c.strip().lower() for c in
                 os.environ.get("NOISE_CLASSES", "weed,weeds,grass").split(",") if c.strip()}


def detect_boxes(image: Image.Image, detector=None):
    """이미지 → (픽셀 좌표 박스 목록, 이미지 면적 px²).

    실제 탐지는 providers 가 맡는다. 이 함수는 앱 전체가 쓰는 하나의 출입구로,
    테스트에서 여기만 갈아 끼우면 어떤 제공자든 흉내 낼 수 있다.
    """
    boxes, area = (detector or DETECT_TOP).detect(image)
    boxes = [b for b in boxes if b["cls"].lower() not in NOISE_CLASSES]
    return boxes, area


def _iou(a, b):
    ix1, iy1 = max(a["x1"], b["x1"]), max(a["y1"], b["y1"])
    ix2, iy2 = min(a["x2"], b["x2"]), min(a["y2"], b["y2"])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1); inter = iw * ih
    if inter <= 0: return 0.0
    union = a["area"] + b["area"] - inter
    return inter / union if union > 0 else 0.0


# 잎이 아닌 클래스(화분·기준물 등)는 잎 계수에서 제외.
# canopy(그 식물 잎 전체를 감싸는 큰 박스)도 여기 들어간다 — group_plants() 는
# NON_LEAF 박스라면 뭐든 '앵커'로 취급해서, 그 안에 든 잎을 확정으로 묶는다.
# pot 은 화분(작음), canopy 는 그 화분의 잎 전체(큼)라 크기만 다를 뿐 같은 역할이다.
# 알로카시아는 잎이 화분 밖으로 멀리 뻗어 화분 앵커만으론 놓치는 잎이 많은데,
# canopy 는 그 잎 전체를 담고 있어서 거리·생김새 보정 없이도 대부분 확정된다.
NON_LEAF = {"object", "pot", "canopy", "background", "ruler", "marker", "tag"}

# 그중 '식물 한 개체의 잎 전체'를 뜻하는 클래스. 화분 앵커와 규칙이 달라서
# (group_by_canopies_indexed 참고) 따로 알아본다.
CANOPY_CLASSES = {"canopy"}


def _stage(cls: str) -> str:
    """클래스 이름을 잎 단계(shoot/mature/old)로 매핑. 이름 표기 흔들려도 인식."""
    c = cls.lower().replace(" ", "").replace("_", "").replace("-", "")
    if "shoot" in c or "newleaf" in c or c.startswith("new"):
        return "shoot"        # 새순
    if "old" in c or "senes" in c:
        return "old"          # 노엽(노화잎)
    return "mature"           # 성엽(성숙잎) — 'leaf','matureleaf','mature'


# --------------------------------------------------------------------------- 원근 보정
# 비스듬히 찍힌 사진의 네 모서리를 직사각형으로 펴서, 왜곡 없는 탑뷰 좌표를 얻는다.
# 사진을 '이어 붙이는' 게 아니라 탐지된 좌표만 선반 좌표계로 옮긴다.
# → 잎이 촬영 사이에 움직여도 상관없고, 특징점 매칭도 필요 없다.

def _solve_linear(A: List[List[float]], b: List[float]) -> List[float]:
    """가우스 소거법. 외부 라이브러리 없이 8x8 을 푼다."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            raise HTTPException(400, "모서리 네 점이 일직선이거나 겹칩니다. 다시 찍어 주세요.")
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col] / pv
            if f:
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    return [M[i][n] / M[i][i] for i in range(n)]


def homography(src: List[tuple], dst: List[tuple]) -> List[List[float]]:
    """네 점 대응 → 3x3 원근 변환 행렬. src/dst 는 [좌상, 우상, 우하, 좌하] 순서."""
    if len(src) != 4 or len(dst) != 4:
        raise HTTPException(400, "모서리는 정확히 4점이어야 해요.")
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = _solve_linear(A, b)
    return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]


def homography_lstsq(src: List[tuple], dst: List[tuple]) -> List[List[float]]:
    """대응점 4쌍 이상 → 최소제곱 원근 변환.

    모서리 대신 '이미 위치를 아는 화분'을 기준점으로 쓸 때 필요하다.
    점을 4개보다 많이 찍으면 클릭 오차가 평균돼 더 정확해진다.
    """
    if len(src) != len(dst) or len(src) < 4:
        raise HTTPException(400, "기준점이 4개 이상이어야 해요.")
    rows, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    # 정규방정식 AᵀA h = Aᵀb (8x8) 로 줄여서 푼다
    n = 8
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    atb = [sum(rows[k][i] * b[k] for k in range(len(rows))) for i in range(n)]
    h = _solve_linear(ata, atb)
    return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]]


def apply_h(H: List[List[float]], x: float, y: float) -> tuple:
    """점 하나를 원근 변환."""
    d = H[2][0] * x + H[2][1] * y + H[2][2]
    if abs(d) < 1e-12:
        d = 1e-12
    return ((H[0][0] * x + H[0][1] * y + H[0][2]) / d,
            (H[1][0] * x + H[1][1] * y + H[1][2]) / d)


def warp_box(H: List[List[float]], box: dict) -> dict:
    """박스의 네 꼭짓점을 변환한 뒤, 그걸 감싸는 축정렬 박스로 되돌린다."""
    pts = [apply_h(H, box["x1"], box["y1"]), apply_h(H, box["x2"], box["y1"]),
           apply_h(H, box["x2"], box["y2"]), apply_h(H, box["x1"], box["y2"])]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x1, x2 = min(xs), max(xs); y1, y2 = min(ys), max(ys)
    out = dict(box)
    out.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "area": max(0.0, (x2 - x1) * (y2 - y1))})
    return out


# --------------------------------------------------------------------------- 잎 → 식물 그룹화
# 탑뷰 사진 한 장에 여러 화분이 들어올 때, 어느 잎이 어느 식물인지 묶는다.
GROUP_GAP = float(os.environ.get("GROUP_GAP", "0.6"))   # 잎 크기 대비 '같은 무리' 인정 거리


def _center(b):
    return ((b["x1"] + b["x2"]) / 2, (b["y1"] + b["y2"]) / 2)


def _span(b):
    """잎 박스의 대표 크기(대각선 길이)."""
    return math.hypot(b["x2"] - b["x1"], b["y2"] - b["y1"])


def _contains(outer, x, y) -> bool:
    """박스 안에 점이 들어오는지. 좌표계는 호출부와 같은 것을 쓴다."""
    return outer["x1"] <= x <= outer["x2"] and outer["y1"] <= y <= outer["y2"]


# --- 잎 생김새(모양·색) 특징 ------------------------------------------------
# 품종마다 잎 모양·무늬·색이 뚜렷이 달라서, 같은 식물의 잎끼리는 서로 닮는다.
# 외부 API 없이 박스 비율 + 잘라낸 잎의 색으로 계산한다.
SHAPE_SIM = float(os.environ.get("SHAPE_SIM", "0.55"))   # 같은 모양으로 볼 최소 유사도(0~1)


def leaf_features(image: Image.Image, box: dict, box_to_px: float = 1.0) -> dict:
    """잎 하나의 생김새 특징. 이미지가 없으면 박스 비율만으로 만든다."""
    w, h = box["x2"] - box["x1"], box["y2"] - box["y1"]
    if w <= 0 or h <= 0:
        return {"aspect": 1.0, "size": 1.0, "h": 0.0, "s": 0.0, "v": 0.0, "has_color": False}
    # 잎이 어느 방향으로 눕든 같은 값이 나오도록 긴 변/짧은 변
    feat = {"aspect": max(w, h) / min(w, h), "size": math.sqrt(w * h),
            "h": 0.0, "s": 0.0, "v": 0.0, "has_color": False}
    if image is None:
        return feat
    # 박스 가운데 60%만 봐서 가장자리 배경이 섞이는 걸 줄인다
    cx, cy = _center(box)
    hw, hh = w * 0.3, h * 0.3
    crop_px = (max(0, int((cx - hw) * box_to_px)), max(0, int((cy - hh) * box_to_px)),
               min(image.width, int((cx + hw) * box_to_px)),
               min(image.height, int((cy + hh) * box_to_px)))
    if crop_px[2] <= crop_px[0] or crop_px[3] <= crop_px[1]:
        return feat
    pixels = list(image.crop(crop_px).resize((8, 8)).convert("HSV").getdata())
    if not pixels:
        return feat
    n = len(pixels)
    feat.update({"h": sum(p[0] for p in pixels) / n, "s": sum(p[1] for p in pixels) / n,
                 "v": sum(p[2] for p in pixels) / n, "has_color": True})
    return feat


def shape_similarity(a: dict, b: dict) -> float:
    """잎 두 장이 얼마나 닮았는지 0(전혀)~1(똑같이).

    모양(긴변/짧은변 비율)·크기·색을 함께 본다. 색 정보가 없으면 모양·크기만.
    """
    d = (abs(a["aspect"] - b["aspect"]) / 1.2) ** 2
    ratio = a["size"] / b["size"] if b["size"] else 1.0
    d += (math.log(max(ratio, 1e-6)) / 0.9) ** 2
    if a.get("has_color") and b.get("has_color"):
        dh = abs(a["h"] - b["h"]); dh = min(dh, 256 - dh)      # 색상은 원형이라 최단거리
        d += (dh / 26.0) ** 2 + (abs(a["s"] - b["s"]) / 70.0) ** 2 + (abs(a["v"] - b["v"]) / 70.0) ** 2
    return math.exp(-math.sqrt(d))


def _label_shape_groups(items: List[dict], feats: List[dict]) -> None:
    """식물들을 생김새로 묶어 '모양 그룹' 딱지(A, B, C…)를 붙인다.

    같은 품종이면 다른 화분에 있어도 같은 딱지가 붙는다.
    """
    n = len(items)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if shape_similarity(feats[i], feats[j]) >= SHAPE_SIM:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    # 큰 무리부터 A, B, C … 순서로
    buckets: Dict[int, List[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)
    order = sorted(buckets.values(), key=len, reverse=True)
    for gi, members in enumerate(order):
        tag = chr(ord("A") + gi) if gi < 26 else f"G{gi + 1}"
        for i in members:
            items[i]["shape_group"] = tag
            items[i]["shape_group_size"] = len(members)


def _mean_features(feats: List[dict]) -> dict:
    """잎 여러 장의 특징 평균 = 그 식물의 생김새."""
    if not feats:
        return {"aspect": 1.0, "size": 1.0, "h": 0.0, "s": 0.0, "v": 0.0, "has_color": False}
    n = len(feats)
    colored = [f for f in feats if f.get("has_color")]
    out = {k: sum(f[k] for f in feats) / n for k in ("aspect", "size")}
    if colored:
        m = len(colored)
        out.update({k: sum(f[k] for f in colored) / m for k in ("h", "s", "v")})
        out["has_color"] = True
    else:
        out.update({"h": 0.0, "s": 0.0, "v": 0.0, "has_color": False})
    return out


def synthetic_pots(space_w: float, space_h: float) -> List[dict]:
    """미리 지정한 화분 자리 → 화분 박스. 모델이 화분을 못 잡아도 그룹화가 된다.

    화분 크기는 이웃 화분과의 간격에서 추정한다(빽빽한 트레이에서 잘 맞는다).
    """
    if not POTS:
        return []
    pts = [(p["u"] * space_w, p["v"] * space_h) for p in POTS]   # uv → 박스 좌표계
    if len(pts) > 1:
        nn = [min(math.dist(a, b) for j, b in enumerate(pts) if j != i) for i, a in enumerate(pts)]
        r = sorted(nn)[len(nn) // 2] * 0.45
    else:
        r = min(space_w, space_h) * 0.1
    return [{"cls": "pot", "conf": 1.0, "x1": x - r, "y1": y - r,
             "x2": x + r, "y2": y + r, "area": 4 * r * r} for x, y in pts]


def group_by_pots_indexed(leaves: List[dict], pots: List[dict],
                          feats: List[dict]) -> List[tuple]:
    """group_by_pots_and_shape 와 같되, 각 무리가 몇 번 화분에서 나왔는지도 알려 준다."""
    groups: List[List[dict]] = [[] for _ in pots]
    seed_feats: List[List[dict]] = [[] for _ in pots]
    strays = []
    for idx, lf in enumerate(leaves):
        lx, ly = _center(lf)
        inside = [i for i, p in enumerate(pots) if _contains(p, lx, ly)]
        if inside:
            best = min(inside, key=lambda i: math.dist(_center(pots[i]), (lx, ly)))
            groups[best].append(lf)
            seed_feats[best].append(feats[idx])
        else:
            strays.append(idx)

    ref = sum(_span(p) for p in pots) / len(pots)
    for idx in strays:
        lx_ly = _center(leaves[idx])

        def score(i):
            dist = math.dist(_center(pots[i]), lx_ly)
            near = ref / (ref + dist)
            sim = shape_similarity(feats[idx], _mean_features(seed_feats[i])) if seed_feats[i] else 0.5
            # 곱으로 본다 — 더하면 '아주 가깝다'가 '전혀 안 닮았다'를 덮어써서
            # 멀리 뻗은 잎이 옆 화분에 붙어 버린다. 곱이면 둘 다 맞아야 이긴다.
            return near * sim

        groups[max(range(len(pots)), key=score)].append(leaves[idx])
    return [(i, g) for i, g in enumerate(groups) if g]


# --- 캐노피 앵커 -----------------------------------------------------------
# 캐노피 하나 = 화분 하나, 그 안에 든 잎 수 = 그 화분의 잎 수.
#
# 겹쳐 잡힌 캐노피를 '같은 포기를 두 번 잡은 것'으로 보고 합쳐 봤지만, 실제
# 추론 결과로 재 보니 손해였다. 빽빽한 트레이를 위에서 찍으면 작은 포기의
# 캐노피가 큰 이웃 포기의 박스 안에 통째로 들어앉는 게 정상이라, '덮였다'로는
# 중복 박스와 이웃 포기를 구분할 수 없다. 한 사진에서 캐노피 10개 중 5개가
# 이웃에 흡수돼 화분 9개가 5개로 줄었다. 그래서 겹침 정리는 하지 않는다 —
# 같은 박스를 두 번 잡는 진짜 중복은 모델 쪽 NMS 가 이미 걸러 준다.
# 박스 경계에서 이만큼(잎 크기 배수) 안쪽이면 그 캐노피 것으로 본다.
# 캐노피 박스는 잎 끝을 아슬아슬하게 자르는 일이 잦아서, 자기 잎인데 중심이
# 몇 픽셀 밖으로 나가는 경우가 실제로 많다. 그런 잎까지 남남으로 두면
# 캐노피가 통째로 빈 채로 남아 화분이 안 만들어진다.
CANOPY_MARGIN = float(os.environ.get("CANOPY_MARGIN", "0.5"))

# 잎이 하나도 안 든 캐노피를 화분으로 인정할 최소 확신도.
# 잎이 든 캐노피는 잎 자체가 '거기 포기가 있다'는 증거지만, 빈 캐노피는 증거가
# 박스 하나뿐이라 오탐일 확률이 높다. 그래서 문턱을 따로 높게 잡는다.
CANOPY_EMPTY_CONF = float(os.environ.get("CANOPY_EMPTY_CONF", "0.6"))

# 빈 캐노피를 인정하려면 잎이 최소한 이만큼은 걸쳐 있어야 한다.
# 빈 캐노피를 남겨 두는 명분은 "큰 잎에 가려 잎을 못 잡았을 뿐 포기는 있다"였다.
# 그 말이 성립하려면 가리는 잎이 실제로 그 자리에 걸쳐 있어야 한다. 잎 박스가
# 스치지도 않는 빈 캐노피는 가려진 포기가 아니라 허공에 그려진 상자다.
# 실제 사진에서 이 둘이 깨끗하게 갈린다(bench_real.py 참고).
CANOPY_TOUCH = float(os.environ.get("CANOPY_TOUCH", "0.05"))


def _dist_to_box(box: dict, x: float, y: float) -> float:
    """점에서 박스까지의 거리. 안에 있으면 0."""
    dx = max(box["x1"] - x, 0.0, x - box["x2"])
    dy = max(box["y1"] - y, 0.0, y - box["y2"])
    return math.hypot(dx, dy)


def _covered_by(leaf: dict, canopy: dict) -> float:
    """잎 박스가 캐노피에 얼마나 덮이는지 (0~1).

    겹친 캐노피 중에서 임자를 고를 때 쓴다. 중심점 하나만 보면, 잎을 절반밖에
    안 감싸는 캐노피가 중심이 가깝다는 이유로 이기는 일이 생긴다. 캐노피는
    '그 포기의 잎을 감싸는 박스' 이므로, 잎을 더 온전히 담은 쪽이 임자다.
    """
    ix1, iy1 = max(leaf["x1"], canopy["x1"]), max(leaf["y1"], canopy["y1"])
    ix2, iy2 = min(leaf["x2"], canopy["x2"]), min(leaf["y2"], canopy["y2"])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    return (iw * ih) / leaf["area"] if leaf["area"] > 0 else 0.0


# 캐노피가 다른 캐노피에 이만큼 덮이면 '안에 들어앉았다' 로 본다.
CANOPY_NESTED_IN = float(os.environ.get("CANOPY_NESTED_IN", "0.8"))


def _nested_pairs(canopies: List[dict]) -> Dict[int, List[int]]:
    """{바깥 캐노피 index: [그 안에 들어앉은 캐노피 index들]}.

    포기가 다닥다닥 붙으면 작은 포기의 캐노피가 큰 포기의 박스 안에 통째로
    들어간다. 이때 안쪽 포기의 잎까지 바깥 몫으로 세면 잎 수가 부푼다.
    """
    nested: Dict[int, List[int]] = {}
    for i, outer in enumerate(canopies):
        for j, inner in enumerate(canopies):
            if i == j or inner["area"] >= outer["area"]:
                continue
            if _covered_by(inner, outer) >= CANOPY_NESTED_IN:
                nested.setdefault(i, []).append(j)
    return nested


def _canopy_owner(leaf: dict, canopies: List[dict], inside: List[int],
                  nested: Dict[int, List[int]]) -> int:
    """이 잎이 어느 캐노피 몫인지. inside 는 잎 중심을 품은 캐노피 index 목록.

    두 경우를 나눈다:

    · **캐노피가 캐노피 안에 들어앉음** — 안쪽이 임자다. 바깥에서는 뺀다.
      집합으로 쓰면 own(바깥) = 안에 든 잎 − 안쪽 캐노피에 든 잎.
      옆 포기가 큰 포기 박스에 잡아먹히는 걸 막는 게 목적이라, 여기서는
      '누가 더 감쌌나' 를 따지지 않는다 — 안쪽에 들었으면 안쪽 것이다.

    · **나란히 걸침** (어느 쪽도 상대를 품지 않음) — 잎을 더 온전히 감싼 쪽.
      캐노피가 포기 일부만 잡히는 일이 잦아, 중심 거리로는 잘못 고른다.
    """
    lx, ly = _center(leaf)
    # 후보 중 '다른 후보를 품고 있지 않은' 가장 안쪽 캐노피들만 남긴다
    innermost = [i for i in inside
                 if not any(j in inside for j in nested.get(i, ()))]
    pool = innermost or inside
    return max(pool, key=lambda i: (_covered_by(leaf, canopies[i]),
                                    -math.dist(_center(canopies[i]), (lx, ly))))


def group_by_canopies_indexed(leaves: List[dict], canopies: List[dict],
                              feats: List[dict]) -> List[List[dict]]:
    """캐노피 앵커 전용 그룹화 — 캐노피 하나가 화분 하나, 그 안의 잎이 그 화분 몫.

    화분(pot) 앵커와 규칙이 다르다. 화분은 작아서 잎이 밖으로 뻗는 게 정상이라
    바깥 잎도 무조건 가장 가까운 화분에 붙여 준다(group_by_pots_indexed).
    캐노피는 그 식물의 잎 전체를 감싸는 박스라 멀리 떨어진 잎까지 끌어오면
    잎 수가 부풀어, 캐노피로 세는 의미가 없어진다.

    그래서 세 단계로 나눈다:
      1. 캐노피 안에 중심이 든 잎 → 그 화분 확정.
         겹쳐서 후보가 여럿이면 **잎을 더 온전히 감싼 캐노피**가 임자다 —
         중심 거리만 보면 잎을 절반만 덮는 캐노피가 이기는 일이 생긴다
      2. 살짝 밖으로 나간 잎(제 크기의 CANOPY_MARGIN 배 이내) → 가장 가까운 캐노피
         캐노피 박스가 잎 끝을 아슬아슬하게 자르는 일이 잦아서 필요하다
      3. 어느 캐노피와도 먼 잎 → 자기들끼리 거리+생김새로 묶어 별도 포기로

    잎이 하나도 안 든 캐노피도, **잎이 걸쳐 있기만 하면** 화분으로 남긴다. 큰 잎에
    가려 잎을 못 잡았을 뿐 포기는 거기 있기 때문이다 — 지정해 둔 화분을 '미검출'로
    남기는 것과 같은 이유다(_ensure_pot_slots). 반대로 잎 박스가 스치지도 않는
    빈 캐노피는 가려진 포기가 아니라 오탐이라 버린다. 이때 무리에는 캐노피 박스만
    들어가는데, 잎 계수·크기 판정은 전부 NON_LEAF 를 걸러 내므로 잎 0장으로 잡힌다.
    """
    groups: List[List[dict]] = [[] for _ in canopies]
    nested = _nested_pairs(canopies)
    strays, stray_feats = [], []
    for lf, ft in zip(leaves, feats):
        lx, ly = _center(lf)
        inside = [i for i, c in enumerate(canopies) if _contains(c, lx, ly)]
        if inside:
            groups[_canopy_owner(lf, canopies, inside, nested)].append(lf)
        else:
            strays.append(lf)
            stray_feats.append(ft)

    # 2단계 — 경계 바로 밖의 잎 되찾기
    far, far_feats = [], []
    for lf, ft in zip(strays, stray_feats):
        lx, ly = _center(lf)
        reach = _span(lf) * CANOPY_MARGIN
        near = [i for i, c in enumerate(canopies) if _dist_to_box(c, lx, ly) <= reach]
        if near:
            groups[min(near, key=lambda i: _dist_to_box(canopies[i], lx, ly))].append(lf)
        else:
            far.append(lf)
            far_feats.append(ft)

    # 캐노피 박스를 무리에 같이 넣어 보낸다. 크기 등급(소/중/대품)을 잎 한 장이
    # 아니라 포기 전체 폭으로 매기려면 아래쪽에서 그 박스가 필요하다. 잎 계수·
    # 생김새·자리 계산은 전부 NON_LEAF 를 걸러 내므로 섞여 들어갈 일은 없다.
    out = []
    for i, g in enumerate(groups):
        if g:
            out.append(g + [canopies[i]])
        elif ((canopies[i].get("conf") or 0) >= CANOPY_EMPTY_CONF
                and any(_covered_by(lf, canopies[i]) > CANOPY_TOUCH for lf in leaves)):
            out.append([canopies[i]])          # 잎에 가려졌을 뿐 포기는 있다
    if far:
        out.extend(group_by_distance_and_shape(far, far_feats))
    return out


# 근접 촬영에서 '배경 화분' 을 걸러 낼 초점 기준.
# 주인공보다 이 배수만큼 덜 또렷하면 배경으로 본다. 0 이면 이 판정을 끈다.
LEAF_FOCUS_MIN = float(os.environ.get("LEAF_FOCUS_MIN", "0.35"))


def _sharpness(image: Image.Image, box: dict, box_to_px: float) -> float:
    """잎 박스 안이 얼마나 또렷한지. 가장자리 세기의 표준편차로 잰다.

    근접 촬영에서는 주인공 포기에 초점이 맞고 뒤쪽 화분은 흐리게 날아간다.
    캐노피 박스가 프레임을 거의 덮을 만큼 크면 배경 잎도 그 안에 들어와
    같이 세어지는데, 위치·크기로는 갈라낼 수 없고 또렷함으로는 갈린다.
    """
    from PIL import ImageFilter, ImageStat

    x1, y1 = max(0, box["x1"] * box_to_px), max(0, box["y1"] * box_to_px)
    x2, y2 = min(image.width, box["x2"] * box_to_px), min(image.height, box["y2"] * box_to_px)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return 0.0
    crop = image.crop((int(x1), int(y1), int(x2), int(y2))).convert("L")
    crop.thumbnail((160, 160))                     # 큰 잎도 같은 잣대로 재려고 줄인다
    return ImageStat.Stat(crop.filter(ImageFilter.FIND_EDGES)).stddev[0]


def _drop_out_of_focus(leaves: List[dict], image: Image.Image,
                       box_to_px: float) -> List[dict]:
    """또렷한 잎만 남긴다. 다 비슷하게 또렷하면 아무것도 안 버린다.

    배경이 흐리지 않은 사진(전부 초점이 맞은 경우)에서는 최대·최소 차이가
    작아 자동으로 통과된다 — 잘못 버리는 것보다 다 세는 편이 낫다.
    """
    if LEAF_FOCUS_MIN <= 0 or image is None or len(leaves) < 2:
        return leaves
    sharp = [(_sharpness(image, b, box_to_px), b) for b in leaves]
    top = max(v for v, _ in sharp)
    if top <= 0:
        return leaves
    return [b for v, b in sharp if v >= top * LEAF_FOCUS_MIN]


def focus_on_center_canopy(boxes: List[dict], det_w: float, det_h: float,
                           image: Image.Image = None,
                           box_to_px: float = 1.0) -> List[dict]:
    """개별 사진용 — 사진 가운데 포기 하나만 남긴다.

    개체를 가까이 찍으면 프레임 안에 옆 포기 잎이 같이 들어온다. 그대로 세면
    이 포기 잎이 아닌 것까지 얹혀 잎 수가 부풀고, 크기도 남의 캐노피로 매겨진다.
    가운데 있는 포기가 찍으려던 포기라고 보고, 그 캐노피와 거기 딸린 잎만 남긴다.

    딸린 잎의 기준은 탑뷰 그룹화와 같다 — 박스 안에 들었거나, 제 크기의
    CANOPY_MARGIN 배 이내로 붙어 있으면 그 포기 것이다(캐노피 박스는 잎 끝을
    아슬아슬하게 자른다).

    캐노피를 못 잡았으면 고를 기준이 없으므로 그대로 둔다 — 잘못 골라 버리느니
    예전처럼 다 세는 편이 낫다.
    """
    canopies = [b for b in boxes if b["cls"].lower() in CANOPY_CLASSES]
    if not canopies:
        return boxes

    cx, cy = det_w / 2, det_h / 2
    # 가운데를 품은 캐노피가 있으면 그중에서, 없으면 전체에서 가장 가까운 것
    holding = [c for c in canopies if _contains(c, cx, cy)]
    main = min(holding or canopies, key=lambda c: math.dist(_center(c), (cx, cy)))
    nested = _nested_pairs(canopies)

    kept = [main]
    for b in boxes:
        if b["cls"].lower() in NON_LEAF:
            continue                       # 다른 캐노피·화분 박스는 버린다
        lx, ly = _center(b)
        inside = [i for i, c in enumerate(canopies) if _contains(c, lx, ly)]
        if inside:
            # 가운데 캐노피 안에 있다고 다 이 포기 것은 아니다. 옆 포기의 캐노피가
            # 이 안에 들어앉아 있으면 그 포기 잎까지 흡수해 잎 수가 부푼다.
            # 임자는 탑뷰와 같은 규칙으로 가른다 (_canopy_owner).
            if canopies[_canopy_owner(b, canopies, inside, nested)] is main:
                kept.append(b)
            continue
        # 어느 캐노피에도 안 들었으면, 가운데 캐노피에 붙어 있을 때만 받는다
        if (_dist_to_box(main, lx, ly) <= _span(b) * CANOPY_MARGIN
                and min(canopies, key=lambda c: _dist_to_box(c, lx, ly)) is main):
            kept.append(b)

    # 뒤쪽 화분이 캐노피 안에 걸쳐 들어오는 건 위치로는 못 거른다. 초점으로 거른다.
    leaves = [b for b in kept if b["cls"].lower() not in NON_LEAF]
    focused = _drop_out_of_focus(leaves, image, box_to_px)
    return [main] + focused


def group_by_distance_and_shape(leaves: List[dict], feats: List[dict],
                                gap: float = None) -> List[List[dict]]:
    """화분이 없을 때: 거리 + 생김새를 함께 본다.

    거리만 쓰면 뻗은 잎이 끊겨 과분할되는데, '닮았으면 조금 멀어도 같은 식물'로
    이어 줘서 이를 줄인다. 대신 안 닮은 잎끼리는 가까워도 잇지 않는다.
    """
    gap = GROUP_GAP if gap is None else gap
    n = len(leaves)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            base = (_span(leaves[i]) + _span(leaves[j])) / 2 * gap
            dist = math.dist(_center(leaves[i]), _center(leaves[j]))
            sim = shape_similarity(feats[i], feats[j])
            close = dist <= base or _iou(leaves[i], leaves[j]) > 0.05
            # 가깝다는 것만으로는 부족하다 — 겹친 잎이 옆 식물 것일 수 있어서
            # 최소한의 생김새 일치를 요구하고, 확실히 닮았으면 더 멀리까지 이어 준다.
            link = (close and sim >= SHAPE_SIM * 0.6) or (sim >= SHAPE_SIM and dist <= base * 4)
            if link:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    buckets: Dict[int, List[dict]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(leaves[i])
    return list(buckets.values())


def group_plants(boxes: List[dict], image: Image.Image = None, box_to_px: float = 1.0,
                 feats: List[dict] = None, canvas: tuple = None) -> tuple:
    """탐지 박스 전체 → (식물별 잎 묶음, 무리→고정자리).

    캐노피가 잡히면 캐노피, 아니면 화분+생김새, 그것도 없으면 거리+생김새로 묶는다.
    image 를 주면 잎을 잘라 색까지 보고, 없으면 박스 비율·크기만으로 판단한다.
    feats 를 주면 그걸 쓴다 — 사진이 여러 장이라 박스마다 원본이 다를 때 필요.

    canvas(=(폭, 높이)) 를 주고 화분 자리를 미리 지정해 뒀으면, 모델이 화분을
    못 잡아도 그 자리를 화분으로 삼는다. 이때 무리마다 자리가 고정된다.
    """
    leaves = [b for b in boxes if b["cls"].lower() not in NON_LEAF]
    pots = [b for b in boxes if b["cls"].lower() in NON_LEAF]
    if not leaves:
        return [], {}
    if feats is not None:
        by_id = {id(b): f for b, f in zip(boxes, feats)}
        lfeats = [by_id[id(b)] for b in leaves]
    else:
        lfeats = [leaf_features(image, b, box_to_px) for b in leaves]

    # 캐노피가 잡혔으면 캐노피만 앵커로 쓴다. 화분 박스와 섞으면 같은 포기에
    # 앵커가 둘 붙어 한 식물이 두 화분으로 쪼개진다 — 캐노피 쪽이 잎 전체를
    # 담고 있어 더 믿을 만하므로 캐노피에 몰아 준다.
    canopies = [b for b in pots if b["cls"].lower() in CANOPY_CLASSES]
    if canopies:
        return group_by_canopies_indexed(leaves, canopies, lfeats), {}

    predefined = False
    if not pots and POTS and canvas:
        pots = synthetic_pots(*canvas)
        predefined = True

    if pots:
        indexed = group_by_pots_indexed(leaves, pots, lfeats)
        groups = [g for _, g in indexed]
        slots = {id(g): POTS[i]["slot"] for i, g in indexed} if predefined else {}
        return groups, slots
    return group_by_distance_and_shape(leaves, lfeats), {}


# --------------------------------------------------------------------------- 잎 낱개
# 여기까지는 '잎 무리 = 식물' 단위로만 다뤘다. 잎 하나하나에 이름을 붙여 두면
# 어느 잎이 어느 화분 것인지 사람이 손으로 옮길 수 있고, 애매한 잎만 골라
# 보여 줄 수 있다. 아래가 그 낱개 기록이다.
# 1·2순위 화분 거리의 격차. 절대 거리로 자르면 화분 간격이 불규칙해서
# 어떤 곳은 헐겁고 어떤 곳은 빡빡하다. 격차 비율은 간격에 알아서 맞춰진다.
AMBIGUOUS_MARGIN = float(os.environ.get("AMBIGUOUS_MARGIN", "0.15"))
LEAF_FIX_RADIUS_UV = float(os.environ.get("LEAF_FIX_RADIUS_UV", "0.03"))


def assign_leaf_to_pot(centroid_uv: tuple, pots: List[dict] = None) -> dict:
    """잎 무게중심 → 소속 화분. 가장 가까운 화분으로 반올림한다.

    격자 칸(A1~E10)으로 매핑하지 않는 이유: 칸은 6x8cm 인데 실제로 가장 가까운
    두 화분은 5.6cm 떨어져 있어 한 칸에 두 화분이 들어간다. 칸으로 자르면 서로
    다른 화분이 같은 칸으로 가고 빈 칸도 잎을 받는다. 격자는 이름표로만 쓴다.

    거리는 cm 로 잰다. uv 는 가로 60cm·세로 40cm 를 똑같이 0~1 로 눌러 놓은
    좌표라 그대로 재면 세로 거리가 1.5배 부풀려진다.
    """
    pots = POTS if pots is None else pots
    if not pots:
        return {"pot_slot": None, "nearest": None, "second": None,
                "margin": 0.0, "ambiguous": True}
    u_uv, v_uv = centroid_uv
    here_cm = ((u_uv - 0.5) * _W, (v_uv - 0.5) * _D)
    ranked = sorted((math.dist(((p["u"] - 0.5) * _W, (p["v"] - 0.5) * _D), here_cm), p["slot"])
                    for p in pots)
    d1_cm, first = ranked[0]
    d2_cm, second = ranked[1] if len(ranked) > 1 else (d1_cm, None)
    margin = (d2_cm - d1_cm) / (d2_cm + d1_cm) if (d1_cm + d2_cm) else 1.0
    return {"pot_slot": first, "nearest": first, "second": second,
            "margin": round(margin, 3),
            "ambiguous": second is not None and margin < AMBIGUOUS_MARGIN}


def _leaf_fix_for(u_uv: float, v_uv: float):
    """그 자리에 사람이 옮겨 둔 잎이 있으면 그 화분 이름."""
    best, best_d = None, LEAF_FIX_RADIUS_UV
    for fix in LEAF_FIXES:
        d = math.dist((fix["u"], fix["v"]), (u_uv, v_uv))
        if d <= best_d:
            best, best_d = fix, d
    return best["pot_slot"] if best else None


def _leaves_of(group: List[dict]) -> List[dict]:
    """무리에서 잎만. 캐노피 박스가 크기 등급용으로 같이 실려 오기 때문에,
    자리·낱개 기록처럼 '잎마다 하나씩' 도는 곳에서는 이걸로 걸러야 한다."""
    return [b for b in group if b["cls"].lower() not in NON_LEAF]


def assign_leaves(groups: List[List[dict]], slots: dict,
                  space_w: float, space_h: float) -> tuple:
    """(무리, 무리→자리) → 잎 낱개까지 소속을 정한 (무리, 무리→자리, 박스별 판정).

    묶기 자체는 건드리지 않는다 — 화분+생김새 교정은 이미 검증된 동작이다.
    여기서 하는 일은 두 가지뿐:
      · 잎마다 최근접 화분과 1·2순위 격차를 재서 '애매함' 딱지를 붙인다
      · 사람이 옮겨 둔 잎은 그 화분으로 되돌리고, 무리를 다시 짠다

    화분 자리를 지정하지 않았으면 기준이 없으므로 그대로 통과시킨다.
    """
    if not POTS or not slots:
        return groups, slots, {}

    verdicts, by_slot = {}, {}
    for g in groups:
        group_slot = slots.get(id(g))
        for b in _leaves_of(g):
            cx_space, cy_space = _center(b)
            u_uv = min(max(cx_space / space_w, 0.0), 1.0) if space_w else 0.5
            v_uv = min(max(cy_space / space_h, 0.0), 1.0) if space_h else 0.5
            verdict = assign_leaf_to_pot((u_uv, v_uv))
            fixed = _leaf_fix_for(u_uv, v_uv)
            slot = fixed or group_slot or verdict["nearest"]
            # 생김새 교정이 최근접을 뒤집은 잎은 사람이 한 번 봐 줄 만하다
            if not fixed and verdict["nearest"] != slot:
                verdict["ambiguous"] = True
            verdict.update({"pot_slot": slot, "manual": bool(fixed),
                            "centroid_uv": [round(u_uv, 4), round(v_uv, 4)]})
            verdicts[id(b)] = verdict
            by_slot.setdefault(slot, []).append(b)

    new_groups = list(by_slot.values())
    new_slots = {id(g): s for s, g in zip(by_slot.keys(), new_groups)}
    return new_groups, new_slots, verdicts


def _record_leaves(plant: dict, group: List[dict], verdicts: dict, scan_id: str,
                   cm_per_unit: float = None, extra_of=None) -> None:
    """이 개체의 잎 낱개 기록을 새로 쓴다 (다른 개체 기록은 안 건드린다)."""
    pid = plant["id"]
    for lid in [k for k, v in LEAVES.items() if v.get("plant_id") == pid]:
        del LEAVES[lid]
    ids = []
    for i, b in enumerate(_leaves_of(group)):
        verdict = verdicts.get(id(b))
        if verdict is None:
            continue
        lid = "lf_" + uuid.uuid4().hex[:8]
        rec = {"leaf_id": lid, "scan_id": scan_id, "mask_id": b.get("mask_id", i),
               "plant_id": pid, "pot_slot": verdict["pot_slot"],
               "stage": _stage(b["cls"]), "centroid_uv": verdict["centroid_uv"],
               "long_side_cm": (round(_leaf_long_side(b) * cm_per_unit, 1)
                                if cm_per_unit else None),
               "conf": round(float(b.get("conf", 0) or 0), 3),
               "ambiguous": verdict["ambiguous"], "manual": verdict["manual"],
               "assign": {"nearest": verdict["nearest"], "second": verdict["second"],
                          "margin": verdict["margin"]}}
        if extra_of:
            rec.update(extra_of(b) or {})
        LEAVES[lid] = rec
        ids.append(lid)
    plant["leaf_ids"] = ids
    plant["ambiguous_ids"] = [i for i in ids if LEAVES[i]["ambiguous"]]


def _forget_leaves(pid: str) -> None:
    for lid in [k for k, v in LEAVES.items() if v.get("plant_id") == pid]:
        del LEAVES[lid]


def leaf_report(scan_id: str = None) -> dict:
    """화분별 잎 산출 구조체 — 어느 화분에 어떤 잎이 몇 장인지."""
    pots = []
    for plant in sorted(PLANTS.values(), key=lambda p: p.get("pos") or ""):
        ids = plant.get("leaf_ids") or []
        pots.append({"slot": plant.get("pos"), "plant_id": plant["id"],
                     "shoot": plant.get("shoot_count", 0),
                     "mature": plant.get("mature_count", 0),
                     "old": plant.get("old_count", 0),
                     "leaf_ids": ids,
                     "ambiguous_ids": plant.get("ambiguous_ids") or []})
    assigned = {lid for p in pots for lid in p["leaf_ids"]}
    return {"scan_id": scan_id, "pots": pots,
            "unassigned": [l["leaf_id"] for l in LEAVES.values()
                           if l["leaf_id"] not in assigned],
            "ambiguous_total": sum(len(p["ambiguous_ids"]) for p in pots)}


def analyze_top(boxes: List[dict], img_area: float, ref_area: float = None) -> dict:
    """모델1: 식물의 '맨 위 잎'(광합성 주력) 크기 → 3D 온실 반영용.

    ref_area: 잎 크기를 재는 기준 면적. 기본은 사진 전체(=식물 1개를 찍은 사진).
    농장 전체를 한 장에 담은 경우엔 식물 1개 몫의 면적을 넘겨야 대/중/소엽이 맞는다.
    """
    leaves = [b for b in boxes if b["cls"].lower() not in NON_LEAF]
    if not leaves:
        return {"top_leaf_size": "없음", "top_leaf_pct": 0.0}
    ref = ref_area or img_area
    top = min(leaves, key=lambda b: b["y1"])          # 사진에서 가장 위쪽 잎
    # 좌표계가 어긋나도 100%를 넘지 않게 (워크플로 리사이즈 등)
    pct = min(round(top["area"] / ref * 100, 1), 100.0) if ref else 0.0
    size = "대엽" if pct > 18 else ("중엽" if pct > 8 else "소엽")
    return {"top_leaf_size": size, "top_leaf_pct": pct}


def analyze_metrics(boxes: List[dict], img_area: float, cm_per_unit: float = None) -> dict:
    """개체 지표. cm_per_unit 을 주면 잎을 실제 길이로 재서 등급을 매긴다.

    cm_per_unit = 선반 폭(cm) / 박스 좌표계 폭. 한 장 스캔이면 사진 폭 기준,
    여러 장 스캔이면 선반 캔버스 기준이라 어느 쪽이든 같은 식으로 구해진다.
    """
    leaves = [b for b in boxes if b["cls"].lower() not in NON_LEAF]
    leaf_count = len(leaves)
    if not leaf_count:
        # 캐노피만 잡히고 잎은 못 잡은 화분. '소품'으로 적으면 진짜 소품과
        # 구분이 안 되므로 '미검출'로 둔다 (_ensure_pot_slots 와 같은 이유).
        return {"size_class": "미검출", "leaf_max_cm": None, "leaf_count": 0,
                "shoot_count": 0, "mature_count": 0, "old_count": 0,
                "overlap_count": 0, "overlap_density": 0, "empty": True}

    # 단계별 개수 (Shoot / Mature / Old)
    counts = {"shoot": 0, "mature": 0, "old": 0}
    for b in leaves:
        counts[_stage(b["cls"])] += 1

    # 겹침
    OVERLAP_IOU = 0.12
    overlapping = set()
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            if _iou(leaves[i], leaves[j]) > OVERLAP_IOU:
                overlapping.add(i); overlapping.add(j)
    overlap_count = len(overlapping)
    overlap_density = round(overlap_count / leaf_count * 100) if leaf_count else 0

    # 크기 등급 — 가장 큰 잎의 긴 변 길이
    biggest = max(leaves, key=_leaf_long_side) if leaves else None
    leaf_max_cm = None
    if biggest is not None and cm_per_unit:
        leaf_max_cm = round(_leaf_long_side(biggest) * cm_per_unit, 1)

    # 크기 등급 — 캐노피가 있으면 그걸로 잰다.
    # 잎 한 장은 그 포기의 크기를 대표하지 못한다. 큰 잎 한 장만 달린 어린 포기와
    # 같은 크기 잎이 여덟 장 달린 다 큰 포기가 같은 등급이 돼 버린다. 캐노피는
    # 잎 전체 퍼짐을 담고 있어서 '포기가 얼마나 큰가'에 훨씬 가깝다.
    canopy = max((b for b in boxes if b["cls"].lower() in CANOPY_CLASSES),
                 key=_leaf_long_side, default=None)
    canopy_cm = (round(_leaf_long_side(canopy) * cm_per_unit, 1)
                 if (canopy is not None and cm_per_unit) else None)

    if canopy_cm is not None:
        size_class = grade_by_canopy_cm(canopy_cm)
    elif leaf_max_cm is not None:
        size_class = grade_by_leaf_cm(leaf_max_cm)          # 캐노피를 못 잡은 경우
    else:
        # 실측 배율을 모르는 경우(개체 사진 1장 등)엔 화면 대비 비율로 대신한다
        ref = canopy or biggest
        pct = (ref["area"] / img_area * 100) if (ref and img_area) else 0
        if canopy is not None:
            size_class = "대품" if pct > 30 else ("중품" if pct > 12 else "소품")
        else:
            size_class = "대품" if pct > 18 else ("중품" if pct > 8 else "소품")

    out = {"size_class": size_class, "leaf_max_cm": leaf_max_cm,
           "canopy_cm": canopy_cm,
           "leaf_count": leaf_count,
           "shoot_count": counts["shoot"], "mature_count": counts["mature"],
           "old_count": counts["old"], "overlap_count": overlap_count,
           "overlap_density": overlap_density}

    # 3D 온실이 그리는 크기는 top_leaf_size 를 본다 — size_class 와는 다른 필드다.
    # analyze_top 이 '사진에서 가장 위쪽 잎' 하나의 면적으로 그 값을 정하는데,
    # 맨 위 잎이 그 포기의 큰 잎이라는 보장이 없다. 큰 포기인데 위쪽에 걸린 잎이
    # 작으면 3D 에서 작게 그려진다 — "뒤에 있는 큰 식물이 작게 나온다" 가 이거다.
    # 캐노피를 쟀으면 그 등급을 3D 에도 그대로 물려, 화면과 칩이 따로 놀지 않게 한다.
    if canopy is not None:
        out["top_leaf_size"] = SIZE_TO_TOP_LEAF.get(size_class, "중엽")
    return out


def _recompute_shape_groups() -> None:
    """등록된 식물 전체를 생김새로 다시 묶어 '모양 그룹' 딱지를 갱신한다."""
    ids = [pid for pid in PLANTS if pid in FEATS]
    if ids:
        _label_shape_groups([PLANTS[pid] for pid in ids], [FEATS[pid] for pid in ids])


# 클래스별 색 — 모달 사진 위에 그리는 박스.
BOX_COLORS = {"canopy": (255, 150, 40), "shoot": (90, 220, 255),
              "old": (240, 210, 60), "mature": (90, 230, 120)}


def _draw_boxes(image: Image.Image, kept: List[dict], dropped: List[dict],
                img_area: float, size: int = 520) -> Image.Image:
    """센 박스를 사진 위에 그린다. 버린 박스는 흐린 회색으로 같이 보여 준다.

    개수가 이상할 때 '무엇이 세어졌는지' 를 볼 수 있어야 한다. 숫자만 있으면
    모델이 못 잡은 건지, 옆 포기가 섞인 건지, 앱이 버린 건지 구분이 안 된다.
    """
    from PIL import ImageDraw

    out = image.copy()
    out.thumbnail((size, size))
    # 박스는 탐지 좌표계에 있다. 줄어든 썸네일 좌표로 옮긴다.
    det_w = math.sqrt(img_area * (image.width / image.height)) if img_area else image.width
    scale = (out.width / det_w) if det_w else 1.0
    d = ImageDraw.Draw(out, "RGBA")

    for b in dropped:                       # 버린 것 먼저 (아래 깔리게)
        d.rectangle([b["x1"] * scale, b["y1"] * scale, b["x2"] * scale, b["y2"] * scale],
                    outline=(150, 150, 150, 110), width=1)
    for b in kept:
        cls = b["cls"].lower()
        color = BOX_COLORS.get("canopy" if cls in CANOPY_CLASSES else _stage(cls),
                               (90, 230, 120))
        wide = 3 if cls in CANOPY_CLASSES else 2
        d.rectangle([b["x1"] * scale, b["y1"] * scale, b["x2"] * scale, b["y2"] * scale],
                    outline=color + (255,), width=wide)
    return out


def _analyze_file(raw: bytes) -> dict:
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(400, "이미지를 읽을 수 없어요.")

    # 모델1(맨 위 잎) 실행
    boxes_top, img_area = detect_boxes(image)
    # 모델2(단계) — 제공자가 다를 때만 따로 호출한다. 같은 객체면 재사용해 크레딧 절약.
    if DETECT_STAGE is not DETECT_TOP:
        boxes_stage, _ = detect_boxes(image, DETECT_STAGE)
    else:
        boxes_stage = boxes_top

    # 개별 사진은 '이 포기 하나' 를 찍은 것이다. 프레임에 걸린 옆 포기 잎까지
    # 세면 잎 수가 부풀므로, 가운데 캐노피와 거기 딸린 잎만 남긴다.
    # 박스 좌표계는 사진 픽셀과 다를 수 있어(워크플로 리사이즈) 면적에서 되돌린다.
    det_w = math.sqrt(img_area * (image.width / image.height)) if img_area else image.width
    det_h = (img_area / det_w) if det_w else image.height
    same_detector = boxes_stage is boxes_top
    box_to_px = (image.width / det_w) if det_w else 1.0
    kept_top = focus_on_center_canopy(boxes_top, det_w, det_h, image, box_to_px)
    dropped = [b for b in boxes_top if not any(b is k for k in kept_top)]
    boxes_stage = (kept_top if same_detector
                   else focus_on_center_canopy(boxes_stage, det_w, det_h, image, box_to_px))
    boxes_top = kept_top

    metrics = {}
    metrics.update(analyze_top(boxes_top, img_area))        # 모델1 → 3D
    metrics.update(analyze_metrics(boxes_stage, img_area))  # 모델2 → 모달

    # 무엇이 세어졌는지 사진 위에 그려 준다. 숫자만 보여 주면 개수가 이상해도
    # 어디서 틀렸는지 확인할 방법이 없어서, 매번 코드를 뒤져야 했다.
    thumb = _draw_boxes(image, boxes_top, dropped, img_area)
    tb = io.BytesIO(); thumb.save(tb, format="JPEG", quality=80)
    metrics["thumb"] = "data:image/jpeg;base64," + base64.b64encode(tb.getvalue()).decode()

    # 이 식물의 생김새 = 잎들의 특징 평균 (모양 그룹 딱지 계산에 쓰임)
    leaves = [b for b in boxes_top if b["cls"].lower() not in NON_LEAF]
    box_to_px = (image.width / math.sqrt(img_area * (image.width / image.height))
                 if img_area else 1.0)
    feat = _mean_features([leaf_features(image, b, box_to_px) for b in leaves])
    return metrics, feat


# --------------------------------------------------------------------------- 엔드포인트
@app.get("/")
def index():
    return FileResponse(os.path.join("static", "index.html"))


@app.get("/api/plants")
def list_plants():
    for p in PLANTS.values():
        _augment_water(p)
    return {"engine": ENGINE_LABEL, "plants": list(PLANTS.values())}


@app.get("/api/slots")
def get_slots():
    """온실 자리(슬롯) 목록 + 점유 여부. 자리 지도·자리 선택에 사용."""
    used = {p.get("pos"): p["id"] for p in PLANTS.values()}
    return [{"label": s["label"], "x": s["x"], "z": s["z"],
             "occupied": s["label"] in used, "plant_id": used.get(s["label"])} for s in SLOTS]


@app.get("/api/pots")
def get_pots():
    """미리 지정해 둔 화분 자리."""
    return {"count": len(POTS), "pots": POTS}


@app.post("/api/pots")
async def set_pots(points: str = Form(None), points_px: str = Form(None),
                   corners: str = Form(None)):
    """화분 중심을 저장. 모델에 pot 클래스를 라벨링하는 대신 쓴다.

    화분은 안 움직이니 한 번만 지정하면 이후 스캔에서 계속 재사용되고,
    화분마다 자리(슬롯)가 고정돼 개체가 안 섞인다.

    · `points`    선반 정규좌표 `[[u,v], …]` (0~1)
    · `points_px` 사진 픽셀 좌표 + `corners`(네 모서리) → 서버가 원근 보정해서 변환
    """
    import json
    if points_px and corners:
        try:
            px, quad = json.loads(points_px), json.loads(corners)
        except ValueError:
            raise HTTPException(400, "좌표를 읽을 수 없어요 (JSON 형식).")
        H = homography([tuple(p) for p in quad], [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        pts = [apply_h(H, float(p[0]), float(p[1])) for p in px]
    elif points:
        try:
            pts = json.loads(points)
        except ValueError:
            raise HTTPException(400, "points 를 읽을 수 없어요 (JSON 형식).")
    else:
        raise HTTPException(400, "points 또는 points_px+corners 가 필요해요.")
    if not isinstance(pts, list) or not pts:
        raise HTTPException(400, "화분을 하나 이상 찍어 주세요.")

    POTS.clear()
    taken = set()
    for i, p in enumerate(pts):
        try:
            u, v = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise HTTPException(400, f"{i + 1}번째 화분 좌표가 이상해요.")
        u_uv, v_uv = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
        slot = _nearest_slot((u_uv - 0.5) * _W, (v_uv - 0.5) * _D, taken)
        if slot is None:
            raise HTTPException(400, "자리가 모자라요. 화분 수를 줄여 주세요.")
        taken.add(slot["label"])
        POTS.append({"i": i, "u": round(u_uv, 4), "v": round(v_uv, 4), "slot": slot["label"]})
    removed = _drop_orphans()      # 예전 자리에 남은 식물은 유령이 된다
    save_state()
    return {"count": len(POTS), "removed": removed, "pots": POTS}


@app.delete("/api/pots")
def clear_pots():
    POTS.clear()
    save_state()
    return {"ok": True}


@app.post("/api/plants")
async def add_plant(name: str = Form(...), file: UploadFile = File(...), pos: str = Form(None)):
    """사진 + 이름 + 자리로 식물을 3D 온실에 추가(분석 포함)."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "이미지 파일만 업로드할 수 있어요.")
    name = name.strip() or "이름없는 알로카시아"

    slot = _free_slot(pos)
    if slot is None:
        raise HTTPException(400, "빈 자리가 없어요. 식물을 제거해 자리를 비워 주세요.")

    raw = await file.read()
    metrics, feat = _analyze_file(raw)

    pid = uuid.uuid4().hex[:8]
    plant = {"id": pid, "name": name, "pos": slot["label"], "x": slot["x"], "z": slot["z"], "rot": 0,
             "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **metrics}
    PLANTS[pid] = plant
    FEATS[pid] = feat
    _recompute_shape_groups()
    save_state()
    return plant


def _nearest_slot(x_cm: float, z_cm: float, blocked: set):
    """3D 좌표에 가장 가까운, 아직 안 쓴 자리."""
    free = [s for s in SLOTS if s["label"] not in blocked]
    if not free:
        return None
    return min(free, key=lambda s: math.dist((s["x"], s["z"]), (x_cm, z_cm)))


def _nearest_pot_or_slot(x_cm: float, z_cm: float, blocked: set):
    """빈 자리 중 가장 가까운 곳 — 화분을 마크해 뒀으면 그 화분들 중에서만 고른다.

    canopy(잎 전체 뭉치) 처럼 화분 자리가 아닌 앵커로 묶었을 때 특히 중요하다.
    50칸 격자 전체에서 그냥 최근접을 고르면, 마크 안 한 빈 칸이 실제 화분보다
    가까이 걸려서 있지도 않은 자리에 식물이 등록될 수 있다. 화분을 마크해 뒀다면
    "농장 = 지정한 화분들"이므로 그 화분들 중에서만 찾는다.
    """
    if POTS:
        candidates = [p for p in POTS if p["slot"] not in blocked]
        if not candidates:
            return None
        best = min(candidates, key=lambda p: math.dist(
            ((p["u"] - 0.5) * _W, (p["v"] - 0.5) * _D), (x_cm, z_cm)))
        return _slot_by_label(best["slot"])
    return _nearest_slot(x_cm, z_cm, blocked)


@app.post("/api/scan")
async def scan_farm(file: UploadFile = File(...), replace: str = Form(None),
                    mode: str = Form(None)):
    """농장 전체를 찍은 탑뷰 사진 1장 → 잎을 식물별로 묶어 여러 개체를 한 번에 등록.

    사진 속 위치가 그대로 3D 온실 자리로 이어진다(사진 위쪽 = 온실 안쪽 A줄).
    같은 자리에 이미 식물이 있으면 이름·방향을 유지한 채 상태만 갱신한다.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "이미지 파일만 업로드할 수 있어요.")
    raw = await file.read()
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(400, "이미지를 읽을 수 없어요.")

    boxes, img_area = detect_boxes(image)

    # 박스가 놓인 좌표계의 폭·높이 (워크플로가 리사이즈했어도 비율은 유지된다고 본다)
    aspect = image.width / image.height
    space_w = math.sqrt(img_area * aspect)
    space_h = math.sqrt(img_area / aspect) if aspect else float(image.height)
    box_to_px = image.width / space_w if space_w else 1.0

    groups, slots = group_plants(boxes, image, box_to_px, canvas=(space_w, space_h))
    if not groups:
        raise HTTPException(400, "사진에서 잎을 찾지 못했어요. 조명·각도를 바꿔 다시 찍어 주세요.")

    groups, slots, verdicts = assign_leaves(groups, slots, space_w, space_h)

    scan_mode = _scan_mode(mode, replace)
    if scan_mode == "replace":
        PLANTS.clear()
        FEATS.clear()
        LEAVES.clear()
    removed = _drop_orphans()      # 예전 화분 좌표로 만들어진 유령 정리

    scan_id = "sc_" + uuid.uuid4().hex[:8]
    result = _register_groups(
        groups, space_w, space_h,
        feat_of=lambda g: _mean_features([leaf_features(image, b, box_to_px) for b in g
                                          if b["cls"].lower() not in NON_LEAF]),
        per_plant_area=img_area / len(groups),      # 식물 1개 몫 — 대/중/소엽 기준
        img_area=img_area,
        slot_of=(lambda g: slots.get(id(g))) if slots else None,
        mode=scan_mode,
        cm_per_unit=(_W / space_w) if space_w else None,
        verdicts=verdicts, scan_id=scan_id,
        leaf_extra_of=lambda b: {"bbox_px": [round(b["x1"] * box_to_px, 1),
                                             round(b["y1"] * box_to_px, 1),
                                             round(b["x2"] * box_to_px, 1),
                                             round(b["y2"] * box_to_px, 1)]})

    shapes = {p.get("shape_group") for p in result if p.get("shape_group")}
    return {"count": len(result), "grouped_by": _grouped_by(boxes, slots),
            "shape_groups": len(shapes), "mode": scan_mode, "removed": removed,
            "new_leaves": sum(p.get("new_leaves", 0) for p in result),
            "leaves": leaf_report(scan_id), "plants": result}


SCAN_MODES = ("replace", "update", "keep")


def _scan_mode(mode: str, replace: str) -> str:
    """스캔 모드 정리. replace 는 예전 방식이라 mode 로 접어 준다."""
    if replace and not mode:
        return "replace"
    mode = (mode or "update").strip()
    if mode not in SCAN_MODES:
        raise HTTPException(400, f"스캔 모드는 {' / '.join(SCAN_MODES)} 중 하나여야 해요.")
    return mode


def _merge_keep(old: dict, new: dict) -> tuple:
    """'잎은 유지, 새 잎만 기록' 병합.

    사진마다 잎이 가려져 탐지가 들쭉날쭉한데, 그걸 그대로 반영하면 어제 8장이던
    식물이 오늘 5장이 된다. 그래서 잎 수가 줄어드는 건 '가려진 것'으로 보고 무시하고,
    늘어난 만큼만 새 잎으로 기록한다.

    단계 분포(새순/성엽/노엽)는 탐지가 기존만큼 잡았을 때만 갱신한다.
    그래야 새순이 성엽이 되는 변화는 따라가면서, 덜 잡힌 사진에 값이 깎이지 않는다.
    """
    o_tot = old.get("leaf_count", 0) or 0
    n_tot = new.get("leaf_count", 0) or 0
    added = max(0, n_tot - o_tot)
    out = dict(new)
    if n_tot < o_tot:                       # 덜 잡혔다 → 잎 수치는 기존 값을 지킨다
        for k in ("shoot_count", "mature_count", "old_count", "leaf_count", "size_class"):
            if k in old:
                out[k] = old[k]
        # 이번엔 잎을 못 잡았어도 기존 잎 수를 지켰으면 '빈 화분'이 아니다.
        # 안 그러면 잎 5장을 그대로 들고 있으면서 미검출로 표시된다.
        out.pop("empty", None)
    return out, added


def _pot_xz_cm(slot_label: str):
    """지정한 화분의 실제 위치(cm). 격자 칸 중앙이 아니라 찍은 그 자리."""
    pot = next((p for p in POTS if p["slot"] == slot_label), None)
    if pot is None:
        return None
    return (pot["u"] - 0.5) * _W, (pot["v"] - 0.5) * _D


def _drop_orphans() -> int:
    """지정한 화분에 없는 식물을 정리한다.

    화분 자리를 다시 찍으면 자리 이름이 바뀌는데, 예전 자리에 있던 식물이 그대로
    남아 유령이 된다. 화분 14개를 지정했는데 개체가 24개로 불어난 게 그 경우다.
    화분 자리를 정해 뒀다면 '농장 = 지정한 화분들' 이므로 나머지는 지운다.
    """
    if not POTS:
        return 0
    keep = {p["slot"] for p in POTS}
    gone = [pid for pid, p in PLANTS.items() if p.get("pos") not in keep]
    for pid in gone:
        PLANTS.pop(pid, None)
        FEATS.pop(pid, None)
        _forget_leaves(pid)
    return len(gone)


def _ensure_pot_slots(result: List[dict]) -> None:
    """지정해 둔 화분은 잎이 안 잡혀도 자리를 지킨다.

    잎이 하나도 탐지되지 않은 화분은 그룹이 안 만들어져 사라졌고, 그래서 등록된
    개체 수가 실제 화분 수보다 적게 나왔다. 빈 화분(흙만)이거나 큰 잎에 완전히
    가린 화분이 그런 경우다. 자리는 남겨 두고 '잎 0장'으로 표시한다.
    """
    if not POTS:
        return
    by_slot = {p["pos"] for p in PLANTS.values()}
    for pot in POTS:
        if pot["slot"] in by_slot:
            continue
        slot = _slot_by_label(pot["slot"])
        if slot is None:
            continue
        xz_cm = _pot_xz_cm(slot["label"]) or (slot["x"], slot["z"])
        pid = uuid.uuid4().hex[:8]
        plant = {"id": pid, "name": f"식물 {slot['label']}", "pos": slot["label"],
                 "x": xz_cm[0], "z": xz_cm[1], "rot": 0,
                 # 잎을 못 찾은 것뿐이지 '작은 식물'이라는 뜻이 아니다.
                 # 소품으로 적어 두면 실제 소품과 구분이 안 된다.
                 "size_class": "미검출", "leaf_max_cm": None,
                 "leaf_count": 0, "shoot_count": 0,
                 "mature_count": 0, "old_count": 0,
                 "top_leaf_size": "없음", "top_leaf_pct": 0.0,
                 "overlap_count": 0, "overlap_density": 0, "empty": True,
                 "leaf_ids": [], "ambiguous_ids": [],
                 "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        PLANTS[pid] = plant
        result.append(plant)


def _grouped_by(boxes: List[dict], slots: dict) -> str:
    """어떤 신호로 묶었는지 — UI 에 그대로 보여 준다."""
    if slots:
        return "pot_preset"                                    # 미리 지정한 화분 자리
    if any(b["cls"].lower() == "canopy" for b in boxes):
        return "canopy"                                        # 모델이 잡은 잎 전체 뭉치
    if any(b["cls"].lower() in NON_LEAF for b in boxes):
        return "pot"                                           # 모델이 잡은 화분
    return "distance"


def _register_groups(groups: List[List[dict]], space_w: float, space_h: float,
                     feat_of, per_plant_area: float, img_area: float,
                     slot_of=None, mode: str = "update",
                     cm_per_unit: float = None, verdicts: dict = None,
                     scan_id: str = None, leaf_extra_of=None) -> List[dict]:
    """무리 목록 → 자리 배정 후 등록/갱신. 스캔 엔드포인트들이 함께 쓴다.

    space_w/space_h 는 **박스가 놓인 좌표계의 크기**다. 한 장 스캔이면 사진 박스
    공간, 여러 장 스캔이면 선반 캔버스라 값의 단위가 다르다. 여기서는 정규화
    (0~1)에만 쓰므로 어느 쪽이든 상관없지만, 이름을 canvas 로 두면 늘 선반
    캔버스인 것처럼 읽혀서 space 로 바꿨다.

    slot_of 를 주면(화분 자리를 미리 지정한 경우) 그 자리에 고정 배정한다.
    그러면 매번 스캔해도 같은 화분이 같은 자리로 가서 개체가 안 섞인다.

    썸네일은 여기서 안 건드린다. 농장 전체 탑뷰에서 잘라 낸 조각은 멀리서 찍은
    사진의 일부라 흐릿하고 작아서 모달에 보여줄 만하지 않다 — 개체 사진(POST
    /api/plants)이나 '새 사진으로 갱신'으로 직접 올린 사진만 썸네일로 쓴다.
    """
    # 자리는 잎 무리의 무게중심으로 정한다. 캐노피 박스까지 넣으면 중심이
    # 밀리므로 뺀다 — 잎이 하나도 없는 빈 화분일 때만 캐노피 중심을 쓴다.
    def _anchor(g):
        return _leaves_of(g) or g

    groups.sort(key=lambda g: sum(_center(b)[1] for b in _anchor(g)) / len(_anchor(g)))
    occupied = {p["pos"] for p in PLANTS.values()}
    claimed = set()
    by_slot = {p["pos"]: p for p in PLANTS.values()}
    result = []
    for g in groups:
        pts = _anchor(g)
        cx_space = sum(_center(b)[0] for b in pts) / len(pts)
        cy_space = sum(_center(b)[1] for b in pts) / len(pts)
        u_uv = min(max(cx_space / space_w, 0.0), 1.0) if space_w else 0.5
        v_uv = min(max(cy_space / space_h, 0.0), 1.0) if space_h else 0.5
        x_cm, z_cm = (u_uv - 0.5) * _W, (v_uv - 0.5) * _D

        forced = slot_of(g) if slot_of else None
        if forced:
            slot = _slot_by_label(forced)
            existing = by_slot.get(forced)
        else:
            existing = None
            cand = min((p for p in by_slot.values() if p["pos"] not in claimed),
                       key=lambda p: math.dist((p["x"], p["z"]), (x_cm, z_cm)), default=None)
            if cand is not None and math.dist((cand["x"], cand["z"]), (x_cm, z_cm)) <= max(_CW, _CD):
                existing = cand
            slot = (_slot_by_label(existing["pos"]) if existing
                    else _nearest_pot_or_slot(x_cm, z_cm, occupied | claimed))
        if slot is None or slot["label"] in claimed:
            continue
        claimed.add(slot["label"])
        # 격자 칸 중앙으로 스냅하면 가까운 화분끼리 같은 줄로 뭉친다.
        # 지정한 화분이면 그 화분의 실제 자리를, 아니면 잎 무리의 무게중심을 쓴다.
        px_cm, pz_cm = _pot_xz_cm(slot["label"]) or (x_cm, z_cm)

        metrics = {}
        metrics.update(analyze_top(g, img_area, ref_area=per_plant_area))
        metrics.update(analyze_metrics(g, img_area, cm_per_unit))
        feat = feat_of(g)

        if existing:
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            if mode == "keep":
                metrics, added = _merge_keep(existing, metrics)
                if added:
                    log = existing.setdefault("leaf_log", [])
                    log.append({"at": now, "added": added,
                                "total": metrics.get("leaf_count", 0)})
                    del log[:-30]                      # 최근 30건만
                    existing["new_leaves"] = added
                else:
                    existing["new_leaves"] = 0
            else:
                existing.pop("manual", None)           # 새 탐지값으로 덮어씀
            existing.pop("empty", None)                # 잎이 잡혔으니 빈 화분 아님
            existing["x"], existing["z"] = round(px_cm, 2), round(pz_cm, 2)
            existing.update(metrics)
            existing["updated"] = now
            FEATS[existing["id"]] = feat
            if verdicts:
                _record_leaves(existing, g, verdicts, scan_id, cm_per_unit, leaf_extra_of)
            result.append(existing)
        else:
            pid = uuid.uuid4().hex[:8]
            plant = {"id": pid, "name": f"식물 {slot['label']}", "pos": slot["label"],
                     "x": round(px_cm, 2), "z": round(pz_cm, 2), "rot": 0,
                     "updated": time.strftime("%Y-%m-%d %H:%M:%S"), **metrics}
            PLANTS[pid] = plant
            FEATS[pid] = feat
            by_slot[slot["label"]] = plant
            if verdicts:
                _record_leaves(plant, g, verdicts, scan_id, cm_per_unit, leaf_extra_of)
            result.append(plant)
    _ensure_pot_slots(result)
    _recompute_shape_groups()
    save_state()
    return result


@app.post("/api/scan-multi")
async def scan_multi(files: List[UploadFile] = File(...), corners: str = Form(None),
                     regions: str = Form(None), replace: str = Form(None),
                     pot_refs: str = Form(None), mode: str = Form(None)):
    """여러 장을 원근 보정해 하나의 선반 좌표계로 합친 뒤 식물을 등록.

    사진을 이어 붙이지 않는다. 사진마다 네 모서리로 원근 변환을 구해
    '탐지 결과'만 선반 좌표로 옮기고, 겹치는 구역의 중복 탐지를 지운다.
    잎이 촬영 사이에 움직여도 안전하고 특징점 매칭이 필요 없다.

    기준점은 둘 중 하나로 준다:
    · corners  사진별 [좌상, 우상, 우하, 좌하] 픽셀 좌표 + regions(그 사진이 덮는 구역)
    · pot_refs 사진별 [[화분번호, x, y], …] — 이미 위치를 아는 화분 4개 이상을 찍는다.
               케이지가 좁아 트레이 모서리가 프레임에 안 들어올 때 쓴다. 화분은 항상
               잘 보이고 안 움직이며, 프레임 안쪽에 퍼져 있어 외삽이 아니라 내삽이 된다.
    """
    import json
    refs = None
    if pot_refs:
        if not POTS:
            raise HTTPException(400, "화분 자리를 먼저 지정해 주세요 (🪴 화분 자리 지정).")
        try:
            refs = json.loads(pot_refs)
        except ValueError:
            raise HTTPException(400, "pot_refs 를 읽을 수 없어요 (JSON 형식).")
        if len(refs) != len(files):
            raise HTTPException(400, f"사진 {len(files)}장인데 기준점은 {len(refs)}장분이에요.")
    if corners:
        try:
            quads = json.loads(corners)
        except ValueError:
            raise HTTPException(400, "corners 를 읽을 수 없어요 (JSON 형식).")
        if len(quads) != len(files):
            raise HTTPException(400, f"사진 {len(files)}장인데 모서리는 {len(quads)}장분이에요.")
    elif refs:
        quads = [None] * len(files)
    else:
        raise HTTPException(400, "corners 또는 pot_refs 가 필요해요.")
    if regions:
        try:
            rects = json.loads(regions)
        except ValueError:
            raise HTTPException(400, "regions 를 읽을 수 없어요 (JSON 형식).")
        if len(rects) != len(files):
            raise HTTPException(400, "regions 개수가 사진 수와 달라요.")
    else:
        rects = [[0, 0, 1, 1]] * len(files)

    CANVAS = 1000.0                       # 선반 캔버스 폭(가상 픽셀). 높이는 선반 비율대로
    canvas_h = CANVAS * (_D / _W)

    merged, feats, sources = [], [], []
    for i, f in enumerate(files):
        if not f.content_type or not f.content_type.startswith("image/"):
            raise HTTPException(400, "이미지 파일만 올릴 수 있어요.")
        try:
            image = Image.open(io.BytesIO(await f.read())).convert("RGB")
        except Exception:
            raise HTTPException(400, f"{i + 1}번째 이미지를 읽을 수 없어요.")

        boxes, img_area = detect_boxes(image)
        aspect = image.width / image.height
        space_w = math.sqrt(img_area * aspect)
        box_to_px = image.width / space_w if space_w else 1.0

        if refs and refs[i]:
            # 이미 위치를 아는 화분들을 기준점으로 (모서리가 안 보일 때)
            src, dst = [], []
            for ref in refs[i]:
                try:
                    pi, px, py = int(ref[0]), float(ref[1]), float(ref[2])
                except (TypeError, ValueError, IndexError):
                    raise HTTPException(400, f"{i + 1}번째 사진의 기준점 형식이 이상해요.")
                if not 0 <= pi < len(POTS):
                    raise HTTPException(400, f"{pi}번 화분이 없어요.")
                src.append((px / box_to_px, py / box_to_px))
                dst.append((POTS[pi]["u"] * CANVAS, POTS[pi]["v"] * canvas_h))
            H = homography_lstsq(src, dst)
        else:
            u0, v0, u1, v1 = rects[i]
            dst = [(u0 * CANVAS, v0 * canvas_h), (u1 * CANVAS, v0 * canvas_h),
                   (u1 * CANVAS, v1 * canvas_h), (u0 * CANVAS, v1 * canvas_h)]
            src = [(p[0] / box_to_px, p[1] / box_to_px) for p in quads[i]]   # 클릭은 원본 픽셀 기준
            H = homography(src, dst)

        for b in boxes:
            merged.append(warp_box(H, b))
            feats.append(leaf_features(image, b, box_to_px))
            sources.append((i, b))

    # 겹치는 구역에서 같은 잎이 두 번 잡힌 것 제거 (사진이 다르고 위치가 거의 같으면 중복)
    keep = []
    for idx, b in enumerate(merged):
        dup = None
        for kidx in keep:
            if sources[kidx][0] != sources[idx][0] and _iou(merged[kidx], b) > 0.5:
                dup = kidx
                break
        if dup is None:
            keep.append(idx)
        elif b["conf"] > merged[dup]["conf"]:
            keep[keep.index(dup)] = idx                 # 더 확신하는 쪽을 남긴다
    dropped = len(merged) - len(keep)

    boxes_m = [merged[i] for i in keep]
    feats_m = [feats[i] for i in keep]
    groups, slots = group_plants(boxes_m, feats=feats_m, canvas=(CANVAS, canvas_h))
    if not groups:
        raise HTTPException(400, "사진에서 잎을 찾지 못했어요. 조명·각도를 바꿔 다시 찍어 주세요.")

    groups, slots, verdicts = assign_leaves(groups, slots, CANVAS, canvas_h)

    scan_mode = _scan_mode(mode, replace)
    if scan_mode == "replace":
        PLANTS.clear(); FEATS.clear(); LEAVES.clear()
    removed = _drop_orphans()      # 예전 화분 좌표로 만들어진 유령 정리

    src_of = {id(merged[i]): sources[i] for i in keep}
    feat_of_box = {id(merged[i]): feats[i] for i in keep}

    def feat_of(group):
        return _mean_features([feat_of_box[id(b)] for b in group
                               if b["cls"].lower() not in NON_LEAF])

    def leaf_extra_of(b):
        """합친 좌표 말고 원본 사진 어디서 온 잎인지도 남긴다."""
        img_i, orig = src_of[id(b)]
        return {"photo": img_i,
                "bbox_px": [round(orig["x1"], 1), round(orig["y1"], 1),
                            round(orig["x2"], 1), round(orig["y2"], 1)]}

    canvas_area = CANVAS * canvas_h
    scan_id = "sc_" + uuid.uuid4().hex[:8]
    result = _register_groups(groups, CANVAS, canvas_h, feat_of,
                              canvas_area / len(groups), canvas_area,
                              slot_of=(lambda g: slots.get(id(g))) if slots else None,
                              mode=scan_mode, cm_per_unit=_W / CANVAS,
                              verdicts=verdicts, scan_id=scan_id,
                              leaf_extra_of=leaf_extra_of)
    shapes = {p.get("shape_group") for p in result if p.get("shape_group")}
    return {"count": len(result), "photos": len(files), "merged_boxes": len(boxes_m),
            "deduped": dropped, "shape_groups": len(shapes), "mode": scan_mode,
            "removed": removed,
            "new_leaves": sum(p.get("new_leaves", 0) for p in result),
            "leaves": leaf_report(scan_id),
            "grouped_by": _grouped_by(boxes_m, slots), "plants": result}


@app.post("/api/plants/{pid}/reanalyze")
async def reanalyze(pid: str, file: UploadFile = File(...)):
    """기존 식물에 새 사진으로 상태 갱신."""
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    raw = await file.read()
    metrics, feat = _analyze_file(raw)
    PLANTS[pid].update(metrics)
    PLANTS[pid]["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    FEATS[pid] = feat
    _recompute_shape_groups()
    save_state()
    return PLANTS[pid]


SIZE_CLASSES = ("소품", "중품", "대품")
# 3D 화분·잎 크기는 top_leaf_size(모델1) 를 본다 — size_class(모델2, 소중대품)와는
# 다른 필드다. 손으로 소/중/대품을 바꿔도 top_leaf_size 를 같이 안 바꾸면 모달
# 표시만 바뀌고 3D 는 그대로라 "고쳤는데 반영이 안 된다"로 보인다.
SIZE_TO_TOP_LEAF = {"소품": "소엽", "중품": "중엽", "대품": "대엽"}


# --------------------------------------------------------------------------- 물주기
# 센서가 없으니 실제 흙 수분은 모른다. 대신 "언제 물을 줬는지"만 사람이 기록하고,
# 며칠 지났는지로 마름 위험을 보여준다. 날씨 API는 안 쓴다 — 온실 안은 냉난방으로
# 외부 기온 영향이 작아서 굳이 외부 의존성을 늘일 이유가 없고, 여름 기준 일수만
# 맞으면 충분하다는 판단(사람이 확인).
WATER_DRY_DAYS = int(os.environ.get("WATER_DRY_DAYS", "3"))    # 이 일수를 넘기면 마름 위험


WATER_LOG_DAYS = int(os.environ.get("WATER_LOG_DAYS", "400"))  # 달력 1년치 남짓


def _augment_water(p: dict) -> None:
    """물 준 지 며칠째인지 + 마름 위험 여부를 얹는다. last_watered 가 없으면 '기록 없음'."""
    last = p.get("last_watered")
    days = None
    if last:
        try:
            days = (date.today() - date.fromisoformat(last)).days
        except ValueError:
            days = None
    p["days_since_watered"] = days
    p["soil_dry"] = bool(days is not None and days > WATER_DRY_DAYS)


def _water_date(raw: str = None) -> str:
    """물 준 날짜를 정리한다. 안 주면 오늘.

    달력에서 지난 날짜를 골라 뒤늦게 적을 수 있어야 한다 — 물은 줬는데 앱을
    안 켠 날이 생기기 때문이다. 대신 미래 날짜는 막는다. 아직 안 준 물을
    적어 두면 마름 경고가 그만큼 늦게 떠서, 정작 필요한 날 알림이 안 온다.
    """
    # 파이썬에서 이 함수를 직접 부르면 FastAPI 의 Form(None) 기본값이 그대로
    # 넘어온다(None 이 아니다). 문자열이 아니면 '안 준 것'으로 본다.
    if not raw or not isinstance(raw, str) or not raw.strip():
        return date.today().isoformat()
    try:
        d = date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        raise HTTPException(400, "날짜는 YYYY-MM-DD 형식이어야 해요.")
    if d > date.today():
        raise HTTPException(400, "아직 오지 않은 날짜에는 물 준 기록을 남길 수 없어요.")
    return d.isoformat()


def _log_watered(p: dict, day: str) -> None:
    """그날 물 줬다고 기록 — 같은 날을 여러 번 눌러도 하루는 한 번만 남는다.

    지난 날짜를 뒤늦게 넣을 수 있으므로 끝에 붙이지 않고 날짜순을 유지한다.
    last_watered 는 기록 중 가장 최근 날짜다 — 방금 넣은 날짜가 아니다.
    5일 전을 뒤늦게 적었다고 어제 준 기록이 밀려나면 안 된다.
    """
    log = p.setdefault("water_log", [])
    if day not in log:
        log.append(day)
        log.sort()
        del log[:-WATER_LOG_DAYS]
    p["last_watered"] = log[-1] if log else day


def _unlog_watered(p: dict, day: str) -> bool:
    """그날 물 준 기록을 지운다. 잘못 누른 날을 되돌리는 자리."""
    log = p.get("water_log") or []
    if day not in log:
        return False
    log.remove(day)
    p["last_watered"] = log[-1] if log else None
    return True


@app.post("/api/plants/{pid}/water")
def water_plant(pid: str, day: str = Form(None)):
    """물을 줬다고 기록한다. day(YYYY-MM-DD)를 주면 그날, 안 주면 오늘.

    흙 마름 표시는 기록 중 가장 최근 날짜부터 다시 센다.
    """
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    p = PLANTS[pid]
    _log_watered(p, _water_date(day))
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _augment_water(p)
    save_state()
    return p


@app.delete("/api/plants/{pid}/water")
def unwater_plant(pid: str, day: str):
    """잘못 남긴 물주기 기록을 지운다 (날짜 필수)."""
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    p = PLANTS[pid]
    if not _unlog_watered(p, _water_date(day)):
        raise HTTPException(404, "그날 물 준 기록이 없어요.")
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _augment_water(p)
    save_state()
    return p


@app.post("/api/water-all")
def water_all_plants(day: str = Form(None)):
    """화분 전체 구역에 한 번에 물을 줬다고 기록한다.

    한 포기씩 모달을 열어 누르는 대신, 트레이를 통째로 준 실제 물주기를 한 번에
    반영하는 자리다. '미검출'(잎이 안 잡힌) 화분도 물리적으로는 물을 받으므로
    똑같이 기록한다.

    day(YYYY-MM-DD)를 주면 그날로 남긴다 — 달력에서 지난 날짜를 골라 뒤늦게
    적는 경우다. 안 주면 오늘.
    """
    when = _water_date(day)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for p in PLANTS.values():
        _log_watered(p, when)
        p["updated"] = now
        _augment_water(p)
    save_state()
    return {"ok": True, "watered": len(PLANTS), "date": when}


@app.delete("/api/water-all")
def unwater_all_plants(day: str):
    """그날 남긴 전체 물주기 기록을 되돌린다 (날짜 필수)."""
    when = _water_date(day)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    undone = 0
    for p in PLANTS.values():
        if _unlog_watered(p, when):
            undone += 1
            p["updated"] = now
        _augment_water(p)
    save_state()
    return {"ok": True, "undone": undone, "date": when}


@app.get("/api/water-log")
def water_log(month: str = None):
    """날짜별로 몇 개 화분에 물을 줬는지 — 달력에 점으로 찍는 데 쓴다.

    month(`YYYY-MM`)를 주면 그 달만, 안 주면 전체 기록을 돌려준다.
    """
    counts: Dict[str, int] = {}
    for p in PLANTS.values():
        for d in (p.get("water_log") or []):
            if month and not d.startswith(month):
                continue
            counts[d] = counts.get(d, 0) + 1
    return {"days": [{"date": d, "count": c} for d, c in sorted(counts.items())]}

# 품 등급은 '가장 큰 잎의 긴 변 길이(cm)'로 가른다.
# 사진 전체 면적 대비 비율로 재던 예전 방식은 구도에 휘둘렸다 — 같은 식물도
# 가까이 찍으면 대품, 멀리서 찍으면 소품이 됐고, 농장 전체 사진에서는 한 개체가
# 화면의 3~5% 뿐이라 비율 조건이 아예 발동하지 않아 사실상 잎 개수로만 갈렸다.
LEAF_SMALL_CM = float(os.environ.get("LEAF_SMALL_CM", "8"))    # 이하 → 소품
LEAF_LARGE_CM = float(os.environ.get("LEAF_LARGE_CM", "16"))   # 초과 → 대품


def _leaf_long_side(box: dict) -> float:
    """잎 박스의 긴 변. 잎이 어느 방향으로 눕든 같은 값이 나오게."""
    return max(box["x2"] - box["x1"], box["y2"] - box["y1"])


def grade_by_leaf_cm(leaf_cm: float) -> str:
    if leaf_cm <= LEAF_SMALL_CM:
        return "소품"
    return "중품" if leaf_cm <= LEAF_LARGE_CM else "대품"


# 캐노피(포기 전체 폭) 기준 등급. 잎 한 장보다 훨씬 크므로 기준치도 따로 둔다.
# 모달에 실측 cm 이 함께 뜨니, 그 값을 보고 본인 기준에 맞춰 조정하시면 된다.
CANOPY_SMALL_CM = float(os.environ.get("CANOPY_SMALL_CM", "12"))   # 이하 → 소품
CANOPY_LARGE_CM = float(os.environ.get("CANOPY_LARGE_CM", "22"))   # 초과 → 대품


def grade_by_canopy_cm(canopy_cm: float) -> str:
    if canopy_cm <= CANOPY_SMALL_CM:
        return "소품"
    return "중품" if canopy_cm <= CANOPY_LARGE_CM else "대품"


@app.patch("/api/plants/{pid}")
async def update_plant(pid: str, name: str = Form(None), rot: float = Form(None),
                       note: str = Form(None), size_class: str = Form(None),
                       shoot_count: int = Form(None), mature_count: int = Form(None),
                       old_count: int = Form(None)):
    """이름 · 화분 방향 · 메모 · 그리고 사람이 직접 고치는 값들.

    사진이 뭉개지거나 잎이 가려지면 탐지가 틀립니다. 그럴 때 손으로 바로잡으라고
    크기 등급과 단계별 잎 수를 열어 뒀어요. 단계 이동(성엽→노엽)은 한쪽을 줄이고
    다른 쪽을 늘리면 됩니다. 직접 고친 식물은 manual 로 표시됩니다.

    메모는 탐지값을 고치는 게 아니라 그냥 적어 두는 글이라 manual 표시와는 무관합니다
    (이름과 같은 취급). 빈 문자열을 보내면 메모를 지웁니다.
    """
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    p = PLANTS[pid]
    if name is not None and name.strip():
        p["name"] = name.strip()
    if rot is not None:
        p["rot"] = float(rot) % 360
    if note is not None:
        p["note"] = note.strip()

    touched = False
    if size_class is not None:
        if size_class not in SIZE_CLASSES:
            raise HTTPException(400, f"크기 등급은 {' / '.join(SIZE_CLASSES)} 중 하나여야 해요.")
        p["size_class"] = size_class
        p["top_leaf_size"] = SIZE_TO_TOP_LEAF[size_class]   # 3D 크기도 같이 반영
        p["top_leaf_pct"] = None                            # 더는 실측 비율과 안 맞으니 표시 안 함
        touched = True
    for key, val in (("shoot_count", shoot_count), ("mature_count", mature_count),
                     ("old_count", old_count)):
        if val is not None:
            if val < 0:
                raise HTTPException(400, "잎 개수는 0보다 작을 수 없어요.")
            p[key] = int(val)
            touched = True
    if touched:
        p["leaf_count"] = sum(p.get(k, 0) or 0 for k in
                              ("shoot_count", "mature_count", "old_count"))
        if p["leaf_count"] > 0:
            # 빈 화분(잎을 못 잡은 자리)은 3D 가 흙만 그리고 잎을 아예 안 그린다.
            # 손으로 잎 수를 넣었는데 empty 를 안 지우면, 수치는 바뀌어도
            # 화면엔 여전히 빈 화분으로 남아 "반영이 안 된다"로 보인다.
            p.pop("empty", None)
            if p.get("size_class") not in SIZE_CLASSES:
                p["size_class"] = "소품"      # '미검출'로는 등급 배지·3D 크기를 못 정한다
        p["manual"] = True
        p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state()
    return p


def _place_plant(plant: dict, label: str, now: str) -> None:
    """식물을 그 자리(label)로 옮긴다 — 좌표·잎 소속을 자리에 맞춘다."""
    slot = _slot_by_label(label)
    xz_cm = _pot_xz_cm(label) or (slot["x"], slot["z"])
    plant["pos"] = label
    plant["x"], plant["z"] = round(xz_cm[0], 2), round(xz_cm[1], 2)
    plant["manual"] = True
    plant["updated"] = now
    for leaf in LEAVES.values():
        if leaf["plant_id"] == plant["id"]:
            leaf["pot_slot"] = label


@app.patch("/api/plants/{pid}/move")
async def move_plant(pid: str, pos: str = Form(...)):
    """식물을 다른 자리로 옮긴다. 자동 배치(스캔·화분 최근접)가 틀렸을 때,
    혹은 실제로 화분을 옮긴 뒤 기록만 맞출 때 손으로 바로잡는 자리다.

    화분 자리를 지정해 뒀으면 빈 화분에도 '미검출' 자리표시 식물이 항상 있으므로
    (`_ensure_pot_slots`), 목적지에 다른 식물이 있으면 **서로 자리를 맞바꾼다** —
    자리 하나에 둘이 앉는 일이 없게. 이름·잎 기록은 식물을 따라가고, 좌표는
    자리를 따라간다.
    """
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    label = (pos or "").strip()
    slot = _slot_by_label(label)
    if slot is None:
        raise HTTPException(400, "없는 자리예요.")
    plant = PLANTS[pid]
    old_pos = plant["pos"]
    if old_pos == label:
        return {"ok": True, "moved": False, "plant": plant, "swapped_with": None}

    other = next((p for p in PLANTS.values() if p["id"] != pid and p.get("pos") == label), None)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    _place_plant(plant, label, now)
    if other:
        _place_plant(other, old_pos, now)
    LEAF_FIXES.clear()     # 손으로 옮긴 잎 기억은 좌표에 묶여 있다 — 화분 배치가 바뀌었으니 무효
    save_state()
    return {"ok": True, "moved": True, "plant": plant, "swapped_with": other}


# --------------------------------------------------------------------------- 배치
# 조명은 실제로 좌측·우측 레일에 3개(2+1) 달려 있다. 레일에 고정돼 있으니
# 좌우(x)는 못 옮기고 레일을 따라(z)만 조절한다 — 기본값(화분 자리를 처음
# 표시할 때 쓴 세 지점)을 쓰다가 실제 위치를 사람이 넣으면 그 값으로 계산한다.
# 저장되므로 한 번만 넣으면 된다. 팬은 없다 — 빛만 본다.
def _normalize_lights(raw: list) -> list:
    """예전 자유배치 저장값(side 없음)을 레일 형식으로 옮긴다.

    레일 도입 전에 저장된 farm.db 는 조명이 `{x,y,z,power,angle}` 뿐이라 side 가
    없다. 그대로 쓰면 프런트가 전부 우측 레일로 몰아 버리고, 다음 저장은
    side 누락으로 거부된다 — 조절해도 반영이 안 되는 것처럼 보인다. x 부호로
    좌/우를 되살리고, 개수가 안 맞으면(레일 도입 전 자유 추가로 늘었을 수 있음)
    기본값으로 되돌린다.
    """
    out = []
    for item in raw:
        if not isinstance(item, dict):
            return [dict(l) for l in placement.DEFAULT_LIGHTS]
        side = item.get("side")
        if side not in ("left", "right"):
            x = item.get("x")
            side = "right" if (isinstance(x, (int, float)) and x > 0) else "left"
        try:
            z_cm = min(max(float(item.get("z", 0.0)), -_D / 2), _D / 2)
            y_cm = float(item.get("y", 47.0))
            power = max(0.1, min(3.0, float(item.get("power", 1.0))))
            angle = max(5.0, min(80.0, float(item.get("angle", placement.DEFAULT_ANGLE))))
        except (TypeError, ValueError):
            return [dict(l) for l in placement.DEFAULT_LIGHTS]
        out.append({"side": side, "x": placement.rail_x(side, _W),
                    "y": round(y_cm, 1), "z": round(z_cm, 1),
                    "power": round(power, 2), "angle": round(angle, 1)})
    if len(out) != placement.LIGHT_COUNT:
        return [dict(l) for l in placement.DEFAULT_LIGHTS]
    return out


def _env():
    raw = ENVIRONMENT.get("lights")
    if not raw:
        return placement.DEFAULT_LIGHTS
    if (not isinstance(raw, list) or len(raw) != placement.LIGHT_COUNT
            or any(not isinstance(l, dict) or l.get("side") not in ("left", "right") for l in raw)):
        norm = _normalize_lights(raw)
        ENVIRONMENT["lights"] = norm
        save_state()
        return norm
    return raw


def _spots():
    return placement.build_spots(list(PLANTS.values()), _pot_xz_cm)


@app.get("/api/environment")
def get_environment():
    """조명 위치(cm). 안 넣었으면 기본값을 그대로 돌려준다."""
    return {"lights": _env(), "shelf": {"w": _W, "d": _D},
            "rail_margin": placement.RAIL_MARGIN_CM, "custom": bool(ENVIRONMENT)}


@app.post("/api/environment")
async def set_environment(lights: str = Form(...)):
    """조명 `[{side,z,y,power,angle}]` 을 실좌표 cm 로.

    `side` 는 `left`/`right` — 레일에 고정된 x 는 여기서 정해진다(사람이 못 정함).
    `angle` 은 빔 반각(도), 기본 30. 레일에 조명이 3개(고정) 달려 있다.
    """
    import json
    try:
        val = json.loads(lights)
    except ValueError:
        raise HTTPException(400, "lights 를 읽을 수 없어요 (JSON 형식).")
    if not isinstance(val, list) or len(val) != placement.LIGHT_COUNT:
        raise HTTPException(400, f"조명은 {placement.LIGHT_COUNT}개여야 해요 (레일에 고정된 개수).")
    norm = []
    for i, item in enumerate(val):
        if not isinstance(item, dict) or item.get("side") not in ("left", "right"):
            raise HTTPException(400, f"{i + 1}번째 조명의 side 는 left/right 여야 해요.")
        try:
            z_cm = min(max(float(item.get("z", 0.0)), -_D / 2), _D / 2)
            y_cm = float(item.get("y", 47.0))
            power = max(0.1, min(3.0, float(item.get("power", 1.0))))
            angle = max(5.0, min(80.0, float(item.get("angle", placement.DEFAULT_ANGLE))))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{i + 1}번째 조명 값이 이상해요.")
        norm.append({"side": item["side"], "x": placement.rail_x(item["side"], _W),
                    "y": round(y_cm, 1), "z": round(z_cm, 1),
                    "power": round(power, 2), "angle": round(angle, 1)})
    ENVIRONMENT["lights"] = norm
    save_state()
    return get_environment()


@app.get("/api/placement")
def get_placement():
    """지금 배치의 점수. 자리마다 빛·그늘과 그 식물에게 필요한 양."""
    graded = placement.score_layout(_spots(), _env())
    worst = sorted(graded["spots"], key=lambda s: s["score"])[:3]
    return {**graded, "worst": worst, "custom_env": bool(ENVIRONMENT)}


@app.get("/api/placement/heatmap")
def get_heatmap(cols: int = 20, rows: int = 14):
    """선반 전체의 빛 분포. 3D 바닥에 깔아 보여 준다."""
    cols = max(4, min(60, cols)); rows = max(4, min(40, rows))
    return placement.heatmap(_W, _D, cols, rows, _env())


@app.post("/api/placement/optimize")
def optimize_placement():
    """자리를 바꾸면 얼마나 좋아지는지 — '무엇을 어디로 옮기라' 목록.

    화분은 사람이 직접 옮긴다. 서버가 기록을 먼저 바꿔 버리면 실제 온실과
    어긋나므로, 여기서는 제안만 하고 적용은 따로 부른다.
    """
    return placement.optimize(_spots(), _env())


@app.post("/api/placement/apply")
async def apply_placement(moves: str = Form(...)):
    """실제로 화분을 옮긴 뒤 부른다 — 기록의 자리를 새 배치로 맞춘다.

    `moves` 는 최적화가 준 `[{plant_id, from, to}, …]` 그대로. 둘씩 맞바꾸는
    걸로 안 끝나는 고리(A→B→C→A)가 있어서 '쌍'이 아니라 '식물마다 갈 자리'로 받는다.
    이름·잎 기록은 식물을 따라가고, 좌표는 자리를 따라간다.
    """
    import json
    try:
        plan = json.loads(moves)
    except ValueError:
        raise HTTPException(400, "moves 를 읽을 수 없어요 (JSON 형식).")
    if not isinstance(plan, list):
        raise HTTPException(400, "moves 는 목록이어야 해요.")

    by_slot = {p["pos"]: p for p in PLANTS.values()}
    todo = []
    for mv in plan:
        plant = PLANTS.get(mv.get("plant_id")) or by_slot.get(mv.get("from"))
        slot = mv.get("to")
        if plant is None or not _slot_by_label(slot or ""):
            continue
        todo.append((plant, slot))
    if len({id(p) for p, _ in todo}) != len(todo) or len({s for _, s in todo}) != len(todo):
        raise HTTPException(400, "한 식물이나 한 자리가 두 번 나와요.")
    # 옮겨 갈 자리가 계획에 없는 식물의 자리라면 그 식물도 움직여야 한다
    staying = {p["pos"] for p in PLANTS.values() if all(p is not q for q, _ in todo)}
    if staying & {s for _, s in todo}:
        raise HTTPException(400, "안 움직이는 식물의 자리로는 못 옮겨요.")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for plant, slot in todo:
        _place_plant(plant, slot, now)
    # 잎을 손으로 옮긴 기억은 좌표에 묶여 있다. 식물이 자리를 옮겼으니 무효다.
    if todo:
        LEAF_FIXES.clear()
    save_state()
    return {"ok": True, "applied": len(todo), **get_placement()}


@app.get("/api/leaves")
def list_leaves(ambiguous: str = None):
    """잎 낱개 + 화분별 집계. ambiguous=1 이면 애매한 잎만."""
    report = leaf_report()
    leaves = list(LEAVES.values())
    if ambiguous:
        leaves = [l for l in leaves if l["ambiguous"]]
    return {"count": len(leaves), "leaves": leaves, "fixes": len(LEAF_FIXES), **report}


def _shift_leaf_count(pid: str, stage: str, leaf_id: str, delta: int) -> None:
    """잎 한 장이 오간 만큼만(+1/-1) 반영한다 — 전체를 다시 세지 않는다.

    한때 여기서 LEAVES 를 통째로 다시 세서 넣었는데, 그러면 사람이 ± 버튼으로
    얹어 둔 보정치(감지 안 된 잎을 메꾸려고 손으로 올린 값)가 사라진다.
    잎이 3장인데 카메라가 2장만 잡아서 mature_count 를 손으로 3으로 올려
    놨다고 하자 — 그중 잡힌 잎 하나를 다른 화분으로 옮기면, 통째로 다시 셀 땐
    "화분에 실제로 LEAVES 가 1장 남았다"는 이유로 카운트가 1로 뚝 떨어졌다.
    사람이 애써 고친 값이 잎 이동 한 번에 지워진 것 — 옮긴 만큼만 가감하면
    이 보정치가 살아남는다.
    """
    plant = PLANTS.get(pid)
    if plant is None:
        return
    key = f"{stage}_count"
    plant[key] = max(0, (plant.get(key) or 0) + delta)
    plant["leaf_count"] = sum(plant.get(k, 0) or 0 for k in
                              ("shoot_count", "mature_count", "old_count"))
    ids = list(plant.get("leaf_ids") or [])
    if delta > 0 and leaf_id not in ids:
        ids.append(leaf_id)
    elif delta < 0 and leaf_id in ids:
        ids.remove(leaf_id)
    plant["leaf_ids"] = ids
    plant["ambiguous_ids"] = [i for i in ids if LEAVES.get(i, {}).get("ambiguous")]
    if delta > 0:
        plant.pop("empty", None)       # 잎이 들어왔으니 빈 화분이 아니다
    plant["manual"] = True             # 사람이 옮긴 결과다 — 재스캔이 덮지 않게
    plant["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")


@app.patch("/api/leaves/{leaf_id}")
async def move_leaf(leaf_id: str, pot_slot: str = Form(...)):
    """잎 하나를 다른 화분 소속으로 옮긴다 (지도 위로 드래그).

    자동 판정이 애매한 잎 — 화분 두 개 사이에 걸친 잎 — 을 사람이 바로잡는 자리다.
    옮긴 자리는 좌표로 기억해 두므로 다음 스캔에서도 같은 자리의 잎은 이 화분으로
    간다. 개체 단위 ± 버튼은 그대로 남아 있고, 잎 기록이 없는 화분에선 그쪽이
    여전히 유일한 수정 수단이다.
    """
    leaf = LEAVES.get(leaf_id)
    if leaf is None:
        raise HTTPException(404, "없는 잎")
    slot = (pot_slot or "").strip()
    target = next((p for p in PLANTS.values() if p.get("pos") == slot), None)
    if target is None:
        raise HTTPException(400, f"{slot} 자리에 식물이 없어요.")
    if leaf["pot_slot"] == slot:
        return {"ok": True, "leaf": leaf, "moved": False}

    was, stage = leaf["plant_id"], leaf["stage"]
    leaf.update({"pot_slot": slot, "plant_id": target["id"],
                 "manual": True, "ambiguous": False})

    u_uv, v_uv = leaf["centroid_uv"]
    LEAF_FIXES[:] = [f for f in LEAF_FIXES
                     if math.dist((f["u"], f["v"]), (u_uv, v_uv)) > LEAF_FIX_RADIUS_UV]
    LEAF_FIXES.append({"u": u_uv, "v": v_uv, "pot_slot": slot})

    _shift_leaf_count(was, stage, leaf_id, -1)
    _shift_leaf_count(target["id"], stage, leaf_id, 1)
    save_state()
    return {"ok": True, "moved": True, "leaf": leaf,
            "from": PLANTS.get(was), "to": target}


@app.delete("/api/leaves/fixes")
def clear_leaf_fixes():
    """손으로 옮긴 잎 기억을 지운다. 자동 판정만으로 다시 보고 싶을 때."""
    n = len(LEAF_FIXES)
    LEAF_FIXES.clear()
    save_state()
    return {"ok": True, "cleared": n}


@app.delete("/api/plants/{pid}")
def remove_plant(pid: str):
    """식물 제거."""
    if pid not in PLANTS:
        raise HTTPException(404, "없는 식물")
    del PLANTS[pid]
    FEATS.pop(pid, None)
    _forget_leaves(pid)
    _recompute_shape_groups()
    save_state()
    return {"ok": True, "id": pid}


app.mount("/static", StaticFiles(directory="static"), name="static")
