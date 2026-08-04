"""탐지 제공자(provider) — 잎을 찾아 주는 쪽을 갈아 끼울 수 있게 분리한 층.

앱의 나머지 코드는 "누가 탐지하는지" 몰라도 되고, 아래 한 가지만 알면 된다:

    detector.detect(image) -> (boxes_px, img_area_px)

`boxes_px` 는 **이미지 픽셀 좌표**의 박스 목록:
    {"cls": 클래스명, "conf": 0~1, "x1","y1","x2","y2": px, "area": px²}

로보플로우를 걷어내고 로컬 모델(HuggingFace·SAM 등)로 바꿀 때도
이 파일에 제공자 하나를 더 붙이면 되고, 위쪽 코드는 건드릴 필요가 없다.
"""

import os
from typing import List, Protocol, Tuple

from PIL import Image

CONFIDENCE = float(os.environ.get("CONFIDENCE", "25"))        # 0~100


def clean_api_key(raw: str) -> Tuple[str, List[str]]:
    """환경변수로 들어온 키를 다듬고, 사람이 읽을 경고를 함께 돌려준다.

    윈도우 배치 파일에서 키를 넣다가 걸리는 함정이 늘 같다. 파워셸 습관대로
    `set ROBOFLOW_API_KEY="abcd..."` 라고 쓰면 **따옴표까지 키 값이 된다**.
    복사·붙여넣기하면 줄 끝 공백도 자주 딸려온다. 둘 다 401 로만 돌아와서
    키가 죽은 줄 알고 새로 발급받게 되는데, 실제로는 글자 두 개 문제다.
    그래서 조용히 걷어내고, 대신 무엇을 걷어냈는지 알려 준다.
    """
    warnings: List[str] = []
    key = (raw or "").strip()
    if key != (raw or ""):
        warnings.append("키 앞뒤의 공백을 떼고 씁니다. farm_env.bat 에서도 지워 주세요.")
    for q in ('"', "'"):
        if len(key) >= 2 and key.startswith(q) and key.endswith(q):
            key = key[1:-1].strip()
            warnings.append(f"키를 감싼 {q} 를 떼고 씁니다 — 배치 파일에서는 "
                            f"따옴표까지 키 값이 됩니다. farm_env.bat 에서도 지워 주세요.")
    if key.startswith("rf_"):
        warnings.append("rf_ 로 시작하는 키는 공개(publishable) 키라 막힙니다. "
                        "Private API Key 를 넣으세요.")
    if any(c.isspace() for c in key):
        warnings.append("키 중간에 공백이 있습니다 — 붙여넣다 잘린 것 같습니다.")
    return key, warnings


class Detector(Protocol):
    """탐지 제공자가 지켜야 할 최소 약속."""

    name: str

    def detect(self, image: Image.Image) -> Tuple[List[dict], float]:
        """이미지 → (픽셀 좌표 박스 목록, 이미지 면적 px²)"""
        ...


def select() -> Tuple[Detector, Detector]:
    """환경변수를 보고 제공자를 고른다. → (모델1용, 모델2용)

    둘이 같은 객체면 위쪽 코드가 추론을 한 번만 돌려 크레딧을 아낀다.
    우선순위: 로보플로우 워크플로 → 로보플로우 모델 → 로컬 .pt → 데모
    """
    api_key, key_warnings = clean_api_key(os.environ.get("ROBOFLOW_API_KEY", ""))
    for w in key_warnings:
        print(f"[키 경고] {w}")
    workspace = os.environ.get("ROBOFLOW_WORKSPACE", "")
    workflow_id = os.environ.get("ROBOFLOW_WORKFLOW_ID", "")
    workflow_url = os.environ.get("ROBOFLOW_WORKFLOW_URL", "")
    model_path = os.environ.get("MODEL_PATH", "yolov8n.pt")

    # 앱이 실제로 어떤 키를 들고 있는지 앞 4자리만 찍는다. 키를 고쳤는데도 401 이
    # 계속 날 때, 파일을 고쳤지만 앱이 못 읽고 있는 건지(예: 예제 파일을 고쳤거나
    # 서버를 안 껐다 켬) 아니면 키 자체가 틀린 건지 이 한 줄로 갈린다.
    # 로보플로우 대시보드도 키를 같은 방식(앞 4자리)으로 표시한다.
    if api_key:
        print(f"[키] {api_key[:4]}… ({len(api_key)}자)  ← 로보플로우 대시보드의 "
              f"키 앞자리와 같은지 확인하세요")
    else:
        print("[키] 없음 — farm_env.bat 의 ROBOFLOW_API_KEY 가 비어 있습니다 "
              "(farm_env.example.bat 이 아니라 farm_env.bat 입니다)")

    if api_key and (workflow_url or (workspace and workflow_id)):
        from .roboflow_workflow import WorkflowDetector
        one = WorkflowDetector(api_key, workspace, workflow_id, workflow_url)
        return one, one                      # 워크플로는 한 번에 다 내주므로 재사용

    if api_key:
        from .roboflow_model import ModelDetector
        default_id = os.environ.get("ROBOFLOW_MODEL_ID", "find-leaf-and-object/1")
        top_id = os.environ.get("ROBOFLOW_MODEL_TOP", default_id)
        stage_id = os.environ.get("ROBOFLOW_MODEL_STAGE", default_id)
        top = ModelDetector(api_key, top_id)
        # 모델 이름이 같으면 같은 객체를 돌려줘서 호출을 한 번만 하게 한다
        return top, (top if stage_id == top_id else ModelDetector(api_key, stage_id))

    if os.path.exists(model_path) or os.environ.get("USE_LOCAL"):
        from .local_yolo import LocalYoloDetector
        try:
            one = LocalYoloDetector(model_path)
            return one, one
        except Exception as e:
            print(f"[경고] 로컬 모델 로딩 실패({e}) → 데모 모드")

    from .demo import DemoDetector
    one = DemoDetector()
    return one, one
