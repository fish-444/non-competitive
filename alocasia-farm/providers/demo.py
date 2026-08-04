"""모델 없이도 앱을 굴려 보게 하는 가짜 탐지기."""

import random
from typing import List, Tuple

from PIL import Image


class DemoDetector:
    name = "demo"

    def detect(self, image: Image.Image) -> Tuple[List[dict], float]:
        w_px, h_px = image.width, image.height
        boxes = []
        for _ in range(random.randint(3, 11)):
            bw_px = random.uniform(0.12, 0.32) * w_px
            bh_px = random.uniform(0.12, 0.32) * h_px
            cx_px = random.uniform(bw_px / 2, w_px - bw_px / 2)
            cy_px = random.uniform(bh_px / 2, h_px - bh_px / 2)
            cls = random.choices(["shoot", "mature leaf", "old leaf"],
                                 weights=[0.22, 0.55, 0.23])[0]
            boxes.append({"cls": cls, "conf": random.uniform(0.4, 0.95),
                          "x1": cx_px - bw_px / 2, "y1": cy_px - bh_px / 2,
                          "x2": cx_px + bw_px / 2, "y2": cy_px + bh_px / 2,
                          "area": bw_px * bh_px})
        return boxes, float(w_px * h_px)
