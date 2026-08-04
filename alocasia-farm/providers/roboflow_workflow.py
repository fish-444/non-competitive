"""로보플로우 워크플로 탐지기.

모델 하나가 아니라 로보플로우에서 조립한 파이프라인을 통째로 호출한다.
워크플로마다 출력 블록 이름이 달라 응답 구조를 고정할 수 없으므로,
응답 트리를 훑어 박스처럼 생긴 predictions 를 전부 찾아 쓴다.
"""

import os
from typing import List, Tuple

from fastapi import HTTPException
from PIL import Image

from . import CONFIDENCE
from .common import boxes_from_predictions, jpeg_b64

API_URL = os.environ.get("ROBOFLOW_API_URL", "https://serverless.roboflow.com")
IMAGE_INPUT = os.environ.get("ROBOFLOW_WORKFLOW_IMAGE_INPUT", "image")


def workflow_urls(workspace: str, workflow_id: str, full_url: str = "") -> List[str]:
    """호출할 워크플로 URL 후보. 로보플로우가 쓰는 두 경로 형식을 모두 시도한다."""
    if full_url:
        return [full_url]
    return [f"{API_URL}/infer/workflows/{workspace}/{workflow_id}",
            f"{API_URL}/{workspace}/workflows/{workflow_id}"]


def _iter_prediction_lists(node):
    """워크플로 응답 어디에 박혀 있든 탐지 predictions 리스트를 전부 찾아낸다.

    출력 블록 이름(step 이름)이 워크플로마다 달라서 경로를 고정할 수 없다.
    그래서 응답 트리를 훑어 '박스처럼 생긴' predictions 리스트만 골라낸다.
    """
    if isinstance(node, dict):
        preds = node.get("predictions")
        if isinstance(preds, list) and any(
                isinstance(p, dict) and "x" in p and "width" in p for p in preds):
            yield preds
        for v in node.values():
            yield from _iter_prediction_lists(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_prediction_lists(v)


def _iter_image_dims(node):
    """응답에 실려 오는 이미지 크기({"image": {"width":…, "height":…}})를 찾는다."""
    if isinstance(node, dict):
        img = node.get("image")
        if isinstance(img, dict):
            w, h = img.get("width"), img.get("height")
            if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 and h > 0:
                yield float(w) * float(h)
        for v in node.values():
            yield from _iter_image_dims(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_image_dims(v)


def image_area_px(payload, fallback: float) -> float:
    """워크플로가 리사이즈를 포함하면 박스 좌표계가 업로드한 원본과 달라진다.
    응답이 알려 주는 이미지 크기를 우선 쓰고, 없으면 원본 크기로 되돌아간다."""
    return next(_iter_image_dims(payload), fallback)


def extract_boxes(payload) -> List[dict]:
    """워크플로 응답 → 박스 목록. 중복 박스는 한 번만 센다."""
    boxes, seen = [], set()
    for preds in _iter_prediction_lists(payload):
        for b in boxes_from_predictions(preds):
            key = (b["cls"], round(b["x1"], 1), round(b["y1"], 1),
                   round(b["x2"], 1), round(b["y2"], 1))
            if key in seen:
                continue
            seen.add(key)
            # 워크플로는 confidence 파라미터를 안 받는 경우가 있어 여기서 걸러 준다
            if b["conf"] and b["conf"] < CONFIDENCE / 100.0:
                continue
            boxes.append(b)
    return boxes


class WorkflowDetector:
    def __init__(self, api_key: str, workspace: str, workflow_id: str, full_url: str = ""):
        self.api_key = api_key
        self.workspace = workspace
        self.workflow_id = workflow_id
        self.full_url = full_url
        self.name = f"workflow · {workflow_id}" if workflow_id else "workflow"

    def urls(self) -> List[str]:
        return workflow_urls(self.workspace, self.workflow_id, self.full_url)

    def detect(self, image: Image.Image) -> Tuple[List[dict], float]:
        import requests
        payload = {"api_key": self.api_key,
                   "inputs": {IMAGE_INPUT: {"type": "base64", "value": jpeg_b64(image)}}}
        resp = None
        for url in self.urls():
            try:
                resp = requests.post(url, json=payload, timeout=90)
            except requests.RequestException:
                raise HTTPException(502, "로보플로우 서버 연결 실패 (인터넷 확인)")
            if resp.status_code != 404:
                break                  # 404 면 다른 경로 형식으로 한 번 더
        if resp.status_code in (401, 403):
            # 401 과 403 은 원인이 다르다. 뭉뚱그리면 멀쩡한 키를 새로 발급받게 된다.
            # 로보플로우가 보낸 본문에 진짜 이유가 들어 있으므로 그대로 보여 준다.
            detail = resp.text[:200].strip().replace("\n", " ")
            why = ("키가 다릅니다 — 오타·따옴표·줄 끝 공백을 확인하세요"
                   if resp.status_code == 401 else
                   "키는 맞지만 권한이 없습니다 — 크레딧 소진이거나 다른 워크스페이스의 키일 수 있어요")
            print(f"[로보플로우 거부] HTTP {resp.status_code} · {detail}")
            raise HTTPException(401, f"로보플로우가 거부했습니다 (HTTP {resp.status_code}). "
                                     f"{why}. 서버 창에 자세한 내용이 찍혔습니다.")
        if resp.status_code == 404:
            raise HTTPException(502, "워크플로를 찾을 수 없어요. "
                                     "ROBOFLOW_WORKSPACE / ROBOFLOW_WORKFLOW_ID 확인")
        if not resp.ok:
            raise HTTPException(502, f"워크플로 오류: {resp.text[:150]}")
        try:
            data = resp.json()
        except ValueError:
            raise HTTPException(502, "워크플로 응답을 해석할 수 없어요.")
        area_px = image_area_px(data, float(image.width * image.height))
        return extract_boxes(data), area_px


