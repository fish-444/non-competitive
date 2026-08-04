"""실제 사진 정확도 측정 (네트워크 불필요)

실행:  python3 bench_real.py

test_*.py 는 "규칙대로 도는가"를 본다. 이 파일은 다른 걸 본다 — **실제 사진에서
몇 개를 맞히는가**. 온실 탑뷰 사진 두 장을 로보플로우에 돌려 나온 박스와, 사람이
직접 센 정답(GT)을 그대로 박아 두었다. 그룹화 규칙을 건드릴 때마다 이걸 돌리면
"고쳤다"가 기분인지 사실인지 바로 갈린다.

박스는 v8(rfdetr-large, confidence 0.3) 출력이다. 지금 배포된 모델은 v10 이라
절대 수치는 조금 다를 수 있지만, **규칙을 바꿨을 때 좋아지는지 나빠지는지**를
재는 데는 같은 입력을 계속 쓰는 편이 오히려 정확하다.
"""

import glob
import json
import os
import sys

os.environ["FARM_DB"] = ""

from main import NON_LEAF, group_plants   # noqa: E402


# --------------------------------------------------------------------------- 자료
# (중심x, 중심y, 폭, 높이, 확신도, 클래스) — 로보플로우가 주는 형식 그대로
IMAGES = [
    ("b2X4", 10, 27, [
        (384.5, 1204.5, 767, 2409, .964, "canopy"), (300.5, 551.5, 601, 1103, .938, "leaf"),
        (1556.5, 3362.5, 1349, 897, .936, "leaf"), (1043.5, 923, 651, 992, .935, "leaf"),
        (1942.5, 1217.5, 459, 1131, .935, "leaf"), (1907.5, 2816, 1053, 1060, .921, "canopy"),
        (440, 1880, 692, 1142, .919, "leaf"), (1959.5, 2014.5, 467, 613, .917, "leaf"),
        (381.5, 3531.5, 763, 573, .917, "leaf"), (717, 2711, 384, 684, .913, "leaf"),
        (1128, 2394.5, 336, 459, .909, "leaf"), (397.5, 2296.5, 793, 419, .907, "leaf"),
        (1562, 2610, 376, 382, .907, "leaf"), (1961.5, 2567.5, 1001, 581, .898, "leaf"),
        (1487.5, 1886, 387, 688, .895, "leaf"), (1550, 1205.5, 452, 537, .880, "leaf"),
        (1544, 3375, 1342, 928, .880, "canopy"), (1912, 3075, 566, 584, .875, "leaf"),
        (892.5, 2385, 369, 258, .872, "leaf"), (1698, 1768.5, 474, 441, .871, "leaf"),
        (1253, 1301.5, 1078, 1731, .863, "canopy"), (963, 1989.5, 318, 585, .846, "old"),
        (1178, 3625, 484, 502, .835, "leaf"), (1202, 2034.5, 280, 189, .829, "leaf"),
        (1296.5, 2176, 793, 870, .825, "canopy"), (1163.5, 2804.5, 447, 337, .815, "leaf"),
        (888, 3343, 332, 454, .793, "canopy"), (840.5, 3449.5, 355, 247, .769, "leaf"),
        (1533.5, 2209, 301, 240, .768, "leaf"), (289.5, 2689.5, 245, 245, .741, "canopy"),
        (1787, 1485.5, 786, 1619, .738, "canopy"), (1674, 1389, 328, 308, .682, "leaf"),
        (382.5, 3511.5, 763, 615, .573, "canopy"), (528.5, 2557.5, 1045, 929, .567, "canopy"),
        (1158, 2801, 458, 364, .476, "canopy")]),

    ("SMYA", 9, 18, [
        (1494.5, 2012.5, 1285, 1187, .946, "canopy"), (2115.5, 2972.5, 1813, 1267, .942, "canopy"),
        (2379, 3759.5, 1290, 545, .938, "leaf"), (2531.5, 1744, 983, 656, .934, "leaf"),
        (1692.5, 2286.5, 671, 677, .919, "leaf"), (2723, 3195.5, 496, 741, .912, "leaf"),
        (1739, 3168.5, 1034, 895, .908, "leaf"), (2414, 2549.5, 844, 487, .903, "leaf"),
        (1377.5, 3041.5, 235, 181, .902, "leaf"), (1167.5, 1809, 649, 392, .901, "leaf"),
        (1178.5, 3724.5, 335, 615, .900, "leaf"), (1702.5, 1764.5, 895, 697, .900, "leaf"),
        (2549.5, 2833.5, 949, 455, .885, "leaf"), (1142, 2291, 470, 362, .879, "leaf"),
        (2096.5, 2111.5, 307, 313, .872, "leaf"), (1374.5, 3070.5, 339, 525, .864, "canopy"),
        (2376.5, 3759.5, 1295, 545, .849, "canopy"), (2899.5, 2733, 249, 342, .845, "leaf"),
        (1425.5, 3724, 811, 614, .843, "canopy"), (1601, 3679, 446, 334, .828, "leaf"),
        (1348, 3238, 132, 248, .827, "old"), (2017, 3620.5, 288, 301, .821, "canopy"),
        (1638, 2663, 578, 694, .817, "leaf"), (2251.5, 2152, 599, 410, .750, "canopy"),
        (2520.5, 1885.5, 1007, 921, .716, "canopy"), (2509, 2929, 1030, 1236, .677, "canopy"),
        (2366.5, 2118.5, 375, 383, .674, "shoot"), (2599, 3450, 210, 172, .414, "canopy")]),
]

CONF = float(os.environ.get("BENCH_CONF", "0.4"))       # 앱 기본 문턱과 맞춘다

BENCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_data")


def to_box(x, y, w, h, conf, cls):
    return {"cls": cls, "conf": conf, "x1": x - w / 2, "y1": y - h / 2,
            "x2": x + w / 2, "y2": y + h / 2, "area": float(w * h)}


def cases():
    """(이름, 정답화분, 정답잎, 박스목록) 을 차례로 낸다.

    위에 박아 둔 v8 자료 + bench_data/*.json (capture_boxes.py 가 만든 것).
    지금 배포된 모델로 잰 자료를 넣으면 나란히 비교된다.
    """
    for name, gp, gl, raw in IMAGES:
        yield name, gp, gl, [to_box(*r) for r in raw if r[4] >= CONF], "v8"
    for path in sorted(glob.glob(os.path.join(BENCH_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        boxes = [dict(b) for b in d["boxes"] if b["conf"] >= CONF]
        yield d["name"], d["gt_pots"], d["gt_leaves"], boxes, d.get("detector", "?")[:10]


def n_leaves(group):
    return sum(1 for b in group if b["cls"].lower() not in NON_LEAF)


def run():
    rows, pot_err, leaf_err = [], 0, 0
    for name, gt_pots, gt_leaves, boxes, src in cases():
        groups, _ = group_plants(boxes)
        pots = len(groups)
        leaves = sum(n_leaves(g) for g in groups)
        dp, dl = pots - gt_pots, leaves - gt_leaves
        if src == "v8":                       # 기준선은 박아 둔 자료로만 잰다
            pot_err += abs(dp)
            leaf_err += abs(dl)
        rows.append((name, src, gt_pots, pots, dp, gt_leaves, leaves, dl,
                     sorted((n_leaves(g) for g in groups), reverse=True)))

    print(f"\n실제 사진 정확도 (confidence >= {CONF})")
    print("=" * 88)
    print(f"{'사진':14} {'모델':10} {'화분 GT':>7} {'측정':>5} {'차':>4}   "
          f"{'잎 GT':>6} {'측정':>5} {'차':>4}   포기별 잎")
    print("-" * 88)
    for name, src, gp, p, dp, gl, l, dl, dist in rows:
        print(f"{name:14} {src:10} {gp:7d} {p:5d} {dp:+4d}   "
              f"{gl:6d} {l:5d} {dl:+4d}   {dist}")
    print("-" * 88)
    print(f"{'기준선 오차':12} 화분 {pot_err}개    잎 {leaf_err}장   (v8 자료 기준)")
    if not os.path.isdir(BENCH_DIR) or not os.listdir(BENCH_DIR):
        print()
        print("  ※ 위 자료는 v8 로 받은 것입니다. 지금 배포된 모델로 재려면:")
        print("       python capture_boxes.py 사진.jpg --화분 10 --잎 27")
        print("     bench_data/ 에 저장되고 다음 실행부터 함께 나옵니다.")
    print()
    return pot_err, leaf_err


if __name__ == "__main__":
    pe, le = run()
    # 지금까지 확인된 최고 성적. 이보다 나빠지면 실패로 알린다.
    #   화분 0 — 그룹화가 화분 수를 정확히 맞춘다.
    #   잎  3 — b2X4 에서 모델이 잎 3장을 아예 못 냈다. 여기서 더 줄이려면
    #           규칙이 아니라 모델(학습 데이터)을 손대야 한다.
    # bench_data/ 로 넣은 사진은 기준에 안 넣는다 — 모델이 바뀌면 절대 수치도
    # 바뀌므로, 규칙이 나빠졌는지는 같은 입력(v8)으로만 판정해야 한다.
    budget_p = int(os.environ.get("BENCH_MAX_POT_ERR", "0"))
    budget_l = int(os.environ.get("BENCH_MAX_LEAF_ERR", "3"))
    if pe > budget_p or le > budget_l:
        print(f"  ✗ 기준(화분 {budget_p} / 잎 {budget_l})보다 나빠졌습니다.")
        sys.exit(1)
    print(f"  ✔ 기준(화분 {budget_p} / 잎 {budget_l}) 안에 들어옵니다.")
