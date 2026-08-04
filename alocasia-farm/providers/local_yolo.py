"""로컬 ultralytics(.pt) 탐지기 — 인터넷·크레딧 없이 돈다."""

from typing import List, Tuple

from PIL import Image

from . import CONFIDENCE


class LocalYoloDetector:
    def __init__(self, model_path: str):
        from ultralytics import YOLO
        print(f"[엔진=로컬] 모델 로딩: {model_path}")
        self.model = YOLO(model_path)
        self.name = "local"

    def detect(self, image: Image.Image) -> Tuple[List[dict], float]:
        r = self.model.predict(image, conf=CONFIDENCE / 100.0, verbose=False)[0]
        names = r.names
        boxes = []
        if r.boxes is not None:
            for b in r.boxes:
                x1_px, y1_px, x2_px, y2_px = [float(v) for v in b.xyxy[0]]
                boxes.append({"cls": names.get(int(b.cls[0]), "leaf"),
                              "conf": float(b.conf[0]),
                              "x1": x1_px, "y1": y1_px, "x2": x2_px, "y2": y2_px,
                              "area": (x2_px - x1_px) * (y2_px - y1_px)})
        return boxes, float(image.width * image.height)
