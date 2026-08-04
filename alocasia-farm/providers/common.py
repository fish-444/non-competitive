"""제공자들이 함께 쓰는 것들."""

import base64
import io
from typing import List

from PIL import Image


def jpeg_b64(image: Image.Image) -> str:
    buf = io.BytesIO(); image.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def boxes_from_predictions(preds: List[dict]) -> List[dict]:
    """로보플로우 predictions(중심 x,y + width,height) → 내부 박스(모서리 좌표).

    좌표 단위는 모두 **이미지 픽셀**이다.
    """
    boxes = []
    for p in preds:
        try:
            w_px, h_px = float(p["width"]), float(p["height"])
            cx_px, cy_px = float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError):
            continue
        boxes.append({"cls": p.get("class") or p.get("class_name") or "leaf",
                      "conf": float(p.get("confidence", 0) or 0),
                      "x1": cx_px - w_px / 2, "y1": cy_px - h_px / 2,
                      "x2": cx_px + w_px / 2, "y2": cy_px + h_px / 2,
                      "area": w_px * h_px})
    return boxes
