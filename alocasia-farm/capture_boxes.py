"""지금 배포된 모델로 사진을 돌려 정확도 측정용 자료를 만든다.

실행 (farm_env.bat 이 있는 폴더에서):

    python capture_boxes.py 사진.jpg --화분 10 --잎 27

--화분 / --잎 은 **사람이 직접 센 정답**이다. 사진을 열어 화분 몇 개, 잎 몇 장
인지 세어서 넣으면 된다. 이걸 넣어야 bench_real.py 가 맞았는지 틀렸는지 안다.

결과는 bench_data/사진이름.json 으로 저장된다. 그다음 bench_real.py 를 돌리면
저장해 둔 v8 자료와 나란히 성적이 나온다. 파일을 지우면 그 사진은 빠진다.

크레딧이 든다 — 사진 한 장에 추론 한 번. 데모 모드면 아무 의미 없는 결과가
나오므로 실행을 막는다.
"""

import argparse
import json
import os
import sys

import providers
from PIL import Image


def capture(path: str, gt_pots: int, gt_leaves: int, out_dir: str) -> str:
    detector, _ = providers.select()
    if detector.__class__.__name__.startswith("Demo"):
        sys.exit("[중단] 데모 모드입니다 — farm_env.bat 의 ROBOFLOW_API_KEY 를 먼저 넣으세요.\n"
                 "        데모는 사진과 무관한 가짜 박스를 냅니다.")

    image = Image.open(path).convert("RGB")
    boxes, area = detector.detect(image)
    if not boxes:
        sys.exit(f"[중단] {path} 에서 박스가 하나도 안 나왔습니다.")

    name = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"{name}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump({
            "name": name,
            "detector": getattr(detector, "name", detector.__class__.__name__),
            "gt_pots": gt_pots,
            "gt_leaves": gt_leaves,
            "image_area": area,
            # bench_real.py 가 읽는 형식 — 픽셀 좌표 박스 그대로
            "boxes": [{"cls": b["cls"], "conf": round(b["conf"], 4),
                       "x1": round(b["x1"], 1), "y1": round(b["y1"], 1),
                       "x2": round(b["x2"], 1), "y2": round(b["y2"], 1),
                       "area": round(b["area"], 1)} for b in boxes],
        }, f, ensure_ascii=False, indent=1)

    kinds = {}
    for b in boxes:
        kinds[b["cls"]] = kinds.get(b["cls"], 0) + 1
    print(f"  {dest}")
    print(f"    탐지: " + ", ".join(f"{k} {v}개" for k, v in sorted(kinds.items())))
    print(f"    정답: 화분 {gt_pots}개, 잎 {gt_leaves}장")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="배포된 모델로 정확도 측정 자료 만들기")
    ap.add_argument("images", nargs="+", help="사진 파일 경로")
    ap.add_argument("--화분", "--pots", dest="pots", type=int, required=True,
                    help="사람이 직접 센 화분(포기) 수")
    ap.add_argument("--잎", "--leaves", dest="leaves", type=int, required=True,
                    help="사람이 직접 센 잎 수")
    ap.add_argument("--out", default="bench_data", help="저장 폴더 (기본: bench_data)")
    a = ap.parse_args()

    if len(a.images) > 1:
        print("[알림] 정답 수는 사진마다 다릅니다. 여러 장이면 한 장씩 따로 돌리세요.")
        sys.exit(1)

    print()
    for p in a.images:
        capture(p, a.pots, a.leaves, a.out)
    print("\n이제  python bench_real.py  를 돌려 보세요.")
