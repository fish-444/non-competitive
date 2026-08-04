"""잎 → 식물 그룹화 스모크 테스트 (네트워크 불필요)

실행:  python3 test_grouping.py

탑뷰 사진 한 장에 여러 화분이 들어올 때, 어느 잎이 어느 식물인지 묶는 로직을 검증한다.
"""

import os
os.environ["FARM_DB"] = ""      # 테스트는 파일에 저장하지 않는다

from main import (analyze_metrics, analyze_top, group_by_pots_indexed, group_plants,
                  leaf_features, shape_similarity, _label_shape_groups)


def group_leaves(boxes, image=None, box_to_px=1.0, feats=None):
    """무리 목록만 꺼내는 테스트용 껍데기.

    앱은 group_plants 로 '무리 + 무리별 고정자리'를 함께 받는다. 여기 테스트는
    자리를 안 보므로 앞쪽만 쓴다.
    """
    return group_plants(boxes, image, box_to_px, feats)[0]


def group_by_pots_and_shape(leaves, pots, feats):
    """화분 번호를 뺀 무리 목록만. group_leaves 와 같은 이유의 껍데기."""
    return [g for _, g in group_by_pots_indexed(leaves, pots, feats)]


def leaves_only(boxes):
    """화분 박스를 빼고 잎만 — '화분이 없을 때'를 흉내 내 비교용으로 쓴다."""
    return [b for b in boxes if b["cls"] != "pot"]


def n_leaves(group):
    """무리의 잎 수. 캐노피 박스는 크기 등급용으로 같이 실려 오므로 뺀다."""
    from main import NON_LEAF
    return sum(1 for b in group if b["cls"].lower() not in NON_LEAF)


def leaf_sizes(groups):
    return sorted(n_leaves(g) for g in groups)


def box(cx, cy, w, h, cls="leaf"):
    return {"cls": cls, "conf": 0.9,
            "x1": cx - w / 2, "y1": cy - h / 2, "x2": cx + w / 2, "y2": cy + h / 2,
            "area": w * h}


def feat(aspect=1.0, size=100.0, h=60.0, s=180.0, v=120.0, color=True):
    return {"aspect": aspect, "size": size, "h": h, "s": s, "v": v, "has_color": color}


def test_two_separated_plants_split_by_distance():
    """멀리 떨어진 두 무리는 두 식물로 갈라져야 한다."""
    leaves = [box(100, 100, 60, 60), box(140, 130, 60, 60),      # 왼쪽 위
              box(900, 900, 60, 60), box(940, 930, 60, 60)]      # 오른쪽 아래
    groups = group_leaves(leaves)
    assert len(groups) == 2, [len(g) for g in groups]
    assert sorted(len(g) for g in groups) == [2, 2]


def test_touching_leaves_merge():
    """맞닿은 잎은 같은 식물로 묶인다."""
    leaves = [box(100, 100, 60, 60), box(130, 100, 60, 60), box(115, 130, 60, 60)]
    assert len(group_leaves(leaves)) == 1


def test_single_leaf_is_its_own_plant():
    assert len(group_leaves([box(50, 50, 30, 30)])) == 1


def test_no_leaves():
    assert group_leaves([]) == []


def test_pot_grouping_beats_distance_when_canopies_touch():
    """캐노피가 겹쳐도 화분이 있으면 정확히 갈린다 — 화분 방식을 쓰는 이유."""
    # 두 화분이 가깝고, 안쪽 잎끼리 실제로 겹쳐 있는 상황
    pots = [box(100, 100, 80, 80, cls="pot"), box(220, 100, 80, 80, cls="pot")]
    leaves = [box(100, 100, 70, 70), box(155, 100, 70, 70),     # 1번 화분 (오른쪽으로 뻗음)
              box(170, 100, 70, 70), box(220, 100, 70, 70)]     # 2번 화분 (왼쪽으로 뻗음)

    # 화분을 무시하고 잎만 보면 하나로 뭉친다
    assert len(group_leaves(leaves)) == 1

    # 화분을 쓰면 둘로 갈린다
    groups = group_leaves(pots + leaves)
    assert len(groups) == 2, [len(g) for g in groups]
    assert sorted(len(g) for g in groups) == [2, 2]


def test_group_leaves_prefers_pots_automatically():
    """group_leaves 는 화분이 잡히면 알아서 화분 기준으로 간다."""
    boxes = [box(100, 100, 80, 80, cls="pot"), box(220, 100, 80, 80, cls="pot"),
             box(90, 100, 70, 70), box(110, 110, 70, 70),
             box(215, 100, 70, 70), box(235, 110, 70, 70)]
    assert len(group_leaves(boxes)) == 2


def test_group_leaves_falls_back_to_distance_without_pots():
    boxes = [box(100, 100, 60, 60), box(900, 900, 60, 60)]
    assert len(group_leaves(boxes)) == 2


def test_pots_never_counted_as_leaves():
    """화분 박스가 잎 개수에 섞이면 안 된다."""
    boxes = [box(100, 100, 80, 80, cls="pot"), box(100, 100, 60, 60, cls="mature leaf")]
    groups = group_leaves(boxes)
    assert len(groups) == 1 and len(groups[0]) == 1
    assert analyze_metrics(groups[0], 10000)["leaf_count"] == 1


def test_leaf_outside_any_pot_joins_nearest():
    """화분 밖으로 뻗은 잎도 가장 가까운 화분에 붙는다 (알로카시아는 잎이 멀리 뻗는다)."""
    pots = [box(100, 100, 40, 40, cls="pot"), box(500, 100, 40, 40, cls="pot")]
    leaves = [box(160, 100, 60, 60)]        # 어느 화분 안에도 없음, 1번에 더 가까움
    groups = group_leaves(pots + leaves)
    assert len(groups) == 1 and len(groups[0]) == 1


# ── canopy(잎 전체 뭉치) 앵커 ────────────────────────────────────────────
def test_canopy_box_anchors_leaves_like_a_pot_does():
    """canopy 는 화분보다 큰 앵커일 뿐, 역할은 같다 — 안에 든 잎을 확정으로 묶는다."""
    canopy = [box(150, 150, 300, 300, cls="canopy"), box(700, 150, 300, 300, cls="canopy")]
    leaves = [box(120, 120, 60, 60), box(180, 180, 60, 60),   # 왼쪽 캐노피 안
             box(680, 130, 60, 60)]                            # 오른쪽 캐노피 안
    groups = group_leaves(canopy + leaves)
    assert leaf_sizes(groups) == [1, 2], leaf_sizes(groups)


def test_canopy_is_never_counted_as_a_leaf():
    boxes = [box(150, 150, 300, 300, cls="canopy"), box(150, 150, 60, 60, cls="mature leaf")]
    groups = group_leaves(boxes)
    assert len(groups) == 1 and n_leaves(groups[0]) == 1
    assert analyze_metrics(groups[0], 10000)["leaf_count"] == 1


def test_a_leaf_deep_inside_the_overlap_of_two_canopies_lands_in_exactly_one():
    """캐노피끼리 겹쳐도(밀집된 트레이 흔한 상황) 잎이 양쪽에 중복으로 세이면 안 된다.

    잎을 못 받은 쪽도 화분으로는 남는다 — 캐노피가 있으면 포기도 있는 것이다.
    """
    canopy = [box(200, 200, 400, 400, cls="canopy"), box(500, 200, 400, 400, cls="canopy")]
    leaf = [box(340, 200, 40, 40)]          # 두 캐노피가 겹치는 구간, 왼쪽에 더 가까움
    groups = group_leaves(canopy + leaf)
    assert len(groups) == 2, [len(g) for g in groups]
    counted = [analyze_metrics(g, 10000)["leaf_count"] for g in groups]
    assert sorted(counted) == [0, 1], counted


def test_a_canopy_sitting_inside_another_keeps_its_own_leaves():
    """캐노피가 캐노피 안에 들어앉으면 안쪽이 임자다 — 바깥에서는 뺀다.

    포기가 다닥다닥 붙으면 작은 포기의 캐노피가 큰 포기 박스 안에 통째로
    들어간다. 그때 안쪽 포기의 잎까지 바깥 몫으로 세면 잎 수가 부푼다.
    집합으로 쓰면  own(바깥) = 바깥에 든 잎 − 안쪽에 든 잎.
    """
    outer = box(600, 500, 1000, 600, cls="canopy")      # 100~1100 × 200~800
    inner = box(800, 500, 200, 200, cls="canopy")       # 700~900 × 400~600
    outer_leaf = box(300, 400, 120, 120)                # 바깥에만
    inner_leaf = box(800, 500, 120, 120)                # 안쪽에 (바깥에도 들어감)

    groups = group_leaves([outer, inner, outer_leaf, inner_leaf])
    by_canopy = {id(next(b for b in g if b["cls"] == "canopy")): n_leaves(g)
                 for g in groups}
    assert by_canopy[id(outer)] == 1, by_canopy      # 안쪽 잎은 빠진다
    assert by_canopy[id(inner)] == 1, by_canopy

    import main
    assert main._nested_pairs([outer, inner]) == {0: [1]}


def test_side_by_side_canopies_split_by_how_fully_they_wrap_the_leaf():
    """나란히 걸친 캐노피 사이에서는 잎을 더 온전히 감싼 쪽이 임자다."""
    import main
    left = box(500, 550, 600, 300, cls="canopy")        # 200~800
    right = box(1000, 550, 600, 300, cls="canopy")      # 700~1300
    assert main._nested_pairs([left, right]) == {}, "나란히 걸친 것이어야 한다"

    leaf = box(700, 550, 300, 100)                      # 550~850, 중심은 양쪽 다 안
    groups = group_leaves([left, right, leaf])
    owner = next(g for g in groups if n_leaves(g) == 1)
    assert next(b for b in owner if b["cls"] == "canopy") is left
    assert main._covered_by(leaf, left) > main._covered_by(leaf, right)


def test_grouped_by_reports_canopy_distinctly_from_pot():
    import main
    assert main._grouped_by([box(0, 0, 10, 10, cls="canopy")], {}) == "canopy"
    assert main._grouped_by([box(0, 0, 10, 10, cls="pot")], {}) == "pot"
    assert main._grouped_by([box(0, 0, 10, 10, cls="leaf")], {}) == "distance"


# ── 화분당 잎 수 = 그 캐노피 박스 안의 잎 수 ──────────────────────────────
def test_leaf_count_per_pot_is_exactly_what_the_canopy_box_holds():
    """캐노피 안 잎만 그 화분 몫이다 — 밖의 잎이 얹혀 부풀면 안 된다."""
    canopy = [box(200, 200, 300, 300, cls="canopy")]       # x 50~350, y 50~350
    inside = [box(120, 120, 40, 40), box(200, 200, 40, 40), box(300, 300, 40, 40)]
    far = [box(900, 900, 40, 40)]                          # 캐노피 밖 (딴 포기)
    groups = group_leaves(canopy + inside + far)
    in_canopy = max(groups, key=n_leaves)
    assert n_leaves(in_canopy) == 3, leaf_sizes(groups)
    assert analyze_metrics(in_canopy, 10000)["leaf_count"] == 3


def test_leaf_just_outside_its_own_canopy_still_joins_it():
    """캐노피 박스는 잎 끝을 아슬아슬하게 자른다 — 중심이 살짝 나간 잎도 제 화분 것."""
    canopy = [box(200, 200, 200, 200, cls="canopy")]     # x 100~300
    leaves = [box(180, 200, 40, 40),                     # 안
              box(315, 200, 40, 40)]                     # 15px 밖 (제 크기보다 훨씬 가까움)
    groups = group_leaves(canopy + leaves)
    assert len(groups) == 1 and n_leaves(groups[0]) == 2, leaf_sizes(groups)


def test_canopy_hidden_under_a_big_leaf_is_still_a_pot():
    """이웃의 큰 잎에 가려 제 잎을 못 잡아도 포기는 거기 있다 — 화분이 사라지면 안 된다."""
    boxes = [box(200, 200, 200, 200, cls="canopy"),
             box(200, 200, 40, 40),
             box(900, 200, 200, 200, cls="canopy"),      # 제 잎은 하나도 안 잡힘
             box(250, 200, 1300, 60)]                    # 왼쪽 포기에서 뻗어 그 위를 덮은 큰 잎
    groups = group_leaves(boxes)
    assert len(groups) == 2, [n_leaves(g) for g in groups]
    empty = next(g for g in groups if n_leaves(g) == 0)
    m = analyze_metrics(empty, 10000)
    assert m["leaf_count"] == 0 and m["size_class"] == "미검출", m


def test_an_empty_canopy_in_bare_space_is_dropped():
    """빈 캐노피를 남기는 명분은 '가려졌다' 인데, 잎이 스치지도 않으면 가릴 것이 없다.

    실제 온실 사진에서 화분을 하나 더 세게 만든 오탐이 정확히 이 모양이었다 —
    허공에 뜬 작은 캐노피 상자 하나(bench_real.py 의 b2X4).
    """
    boxes = [box(200, 200, 200, 200, cls="canopy"),
             box(200, 200, 40, 40),
             box(900, 200, 200, 200, cls="canopy")]      # 잎이 근처에도 없다
    groups = group_leaves(boxes)
    assert len(groups) == 1, [n_leaves(g) for g in groups]


def test_a_faint_empty_canopy_is_not_promoted_to_a_pot():
    """빈 캐노피는 증거가 박스 하나뿐이라 오탐이기 쉽다 — 확신도가 낮으면 버린다."""
    boxes = [box(200, 200, 200, 200, cls="canopy"),
             box(200, 200, 40, 40),
             box(250, 200, 1300, 60)]                    # 가리는 잎은 있지만
    faint = box(900, 200, 200, 200, cls="canopy"); faint["conf"] = 0.3   # 확신도가 낮다
    groups = group_leaves(boxes + [faint])
    assert len(groups) == 1, [n_leaves(g) for g in groups]


# ── 개별 사진: 가운데 포기만 ──────────────────────────────────────────────
# 개체를 가까이 찍으면 프레임에 옆 포기 잎이 같이 들어온다. 그대로 세면 부풀어난다.
from main import focus_on_center_canopy

W = H = 1000


def test_only_the_center_plant_survives_in_a_closeup():
    """가운데 캐노피와 거기 딸린 잎만 남는다 — 옆 포기는 캐노피째 버린다."""
    boxes = [box(500, 500, 400, 400, cls="canopy"),          # 찍으려던 포기
             box(480, 480, 80, 80), box(560, 540, 80, 80),   # 그 안의 잎
             box(80, 80, 300, 300, cls="canopy"),            # 왼쪽 위 옆 포기
             box(80, 80, 90, 90), box(150, 120, 90, 90),     # 옆 포기의 잎
             box(950, 950, 60, 60)]                          # 멀리 떨어진 잎
    kept = focus_on_center_canopy(boxes, W, H)
    canopies = [b for b in kept if b["cls"] == "canopy"]
    assert len(canopies) == 1 and canopies[0]["x1"] == 300, canopies
    assert n_leaves(kept) == 2, [b["cls"] for b in kept]
    assert analyze_metrics(kept, W * H)["leaf_count"] == 2


def test_a_leaf_just_outside_the_center_canopy_still_counts():
    """캐노피 박스가 잎 끝을 자르므로, 붙어 있는 잎은 이 포기 것으로 본다."""
    boxes = [box(500, 500, 400, 400, cls="canopy"),   # x 300~700
             box(720, 500, 60, 60)]                   # 20px 밖 (제 크기의 절반보다 가깝다)
    assert n_leaves(focus_on_center_canopy(boxes, W, H)) == 1


def test_a_closeup_drops_leaves_of_a_canopy_nested_inside_the_center_one():
    """가운데 캐노피 안에 옆 포기 캐노피가 들어앉으면, 그 잎까지 세면 안 된다.

    탑뷰와 같은 규칙(_canopy_owner)을 쓴다. 개별 사진 경로가 가운데 캐노피
    하나만 보고 판정하던 시절에는 안쪽 포기의 잎을 통째로 흡수했다.
    """
    import main
    center = box(500, 500, 800, 800, cls="canopy")      # 100~900
    inner = box(750, 700, 200, 200, cls="canopy")       # 650~850 × 600~800
    mine = [box(300, 300, 100, 100), box(400, 550, 100, 100)]
    theirs = [box(750, 700, 80, 80)]                    # 안쪽 캐노피 것

    assert main._nested_pairs([center, inner]) == {0: [1]}
    kept = focus_on_center_canopy([center, inner] + mine + theirs, W, H)
    assert n_leaves(kept) == 2, [b["cls"] for b in kept]
    assert not any(b is theirs[0] for b in kept), "안쪽 포기 잎이 섞였다"


def test_both_paths_share_the_same_ownership_rule():
    """탑뷰와 개별 사진이 같은 규칙으로 임자를 가려야 한다 — 갈리면 한쪽이 틀린다."""
    center = box(500, 500, 800, 800, cls="canopy")
    inner = box(750, 700, 200, 200, cls="canopy")
    mine = box(300, 300, 100, 100)
    theirs = box(750, 700, 80, 80)
    scene = [center, inner, mine, theirs]

    # 탑뷰 — 두 화분으로 갈리고 잎이 하나씩
    groups = group_leaves(scene)
    assert leaf_sizes(groups) == [1, 1], leaf_sizes(groups)

    # 개별 사진 — 가운데 포기 잎만
    kept = focus_on_center_canopy(scene, W, H)
    assert n_leaves(kept) == 1 and any(b is mine for b in kept), kept


def test_a_far_leaf_is_dropped_even_without_a_neighbour_canopy():
    boxes = [box(500, 500, 200, 200, cls="canopy"),   # x 400~600
             box(950, 950, 60, 60)]                   # 한참 떨어짐
    assert n_leaves(focus_on_center_canopy(boxes, W, H)) == 0


def test_the_canopy_holding_the_center_wins_over_a_closer_one():
    """가운데를 품은 캐노피가 있으면, 중심이 더 가까운 작은 옆 포기보다 우선한다."""
    big = box(500, 500, 900, 900, cls="canopy")       # 가운데를 품는다
    near = box(520, 520, 80, 80, cls="canopy")        # 중심은 더 가깝지만 가운데를 못 품음
    near["x1"], near["y1"], near["x2"], near["y2"] = 560, 560, 640, 640
    kept = focus_on_center_canopy([big, near], W, H)
    canopies = [b for b in kept if b["cls"] == "canopy"]
    assert len(canopies) == 1 and canopies[0] is big, canopies


# ── 근접 촬영에서 배경 화분 걸러내기 ──────────────────────────────────────
def _focus_scene(blur_background=True):
    """주인공 잎 4장(또렷) + 배경 잎 2장, 캐노피는 프레임을 거의 덮는다."""
    from PIL import Image, ImageDraw, ImageFilter

    def bx(x1, y1, x2, y2, cls="leaf"):
        return {"cls": cls, "conf": 0.9, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "area": float((x2 - x1) * (y2 - y1))}

    subject = [bx(300, 150, 520, 380), bx(120, 420, 420, 720),
               bx(560, 400, 880, 700), bx(430, 120, 620, 300)]
    bg = [bx(60, 60, 220, 200), bx(800, 60, 960, 220)]
    canopy = bx(50, 50, 970, 760, cls="canopy")

    img = Image.new("RGB", (1000, 1000), (30, 45, 35))
    d = ImageDraw.Draw(img)
    for b in subject + bg:
        d.rounded_rectangle([b["x1"], b["y1"], b["x2"], b["y2"]], radius=30, fill=(55, 130, 65))
        for i in range(int(b["x1"]), int(b["x2"]), 9):
            d.line([(i, b["y1"]), (i, b["y2"])], fill=(70, 150, 80), width=2)
        for j in range(int(b["y1"]), int(b["y2"]), 9):
            d.line([(b["x1"], j), (b["x2"], j)], fill=(40, 110, 55), width=2)
    if blur_background:
        mask = Image.new("L", (1000, 1000), 0)
        md = ImageDraw.Draw(mask)
        for b in bg:
            md.rounded_rectangle([b["x1"] - 12, b["y1"] - 12, b["x2"] + 12, b["y2"] + 12],
                                 radius=30, fill=255)
        img = Image.composite(img.filter(ImageFilter.GaussianBlur(9)), img, mask)
    return [canopy] + subject + bg, img


def test_blurred_background_plants_are_not_counted():
    """근접 촬영에서 뒤쪽 화분 잎이 캐노피 안에 걸쳐 들어와도 세면 안 된다.

    위치·크기로는 못 가른다 — 캐노피가 프레임을 거의 덮으니 배경 잎도 그 안이다.
    주인공은 초점이 맞고 배경은 날아간다는 차이로 가른다.
    """
    scene, img = _focus_scene(blur_background=True)
    kept = focus_on_center_canopy(scene, 1000, 1000, img, 1.0)
    assert n_leaves(kept) == 4, n_leaves(kept)


def test_an_all_sharp_photo_loses_nothing():
    """전부 초점이 맞은 사진에서는 아무것도 안 버린다 — 잘못 버리느니 다 센다."""
    scene, img = _focus_scene(blur_background=False)
    kept = focus_on_center_canopy(scene, 1000, 1000, img, 1.0)
    assert n_leaves(kept) == 6, n_leaves(kept)


def test_without_an_image_the_focus_check_is_skipped():
    """탑뷰 경로는 이미지를 안 넘긴다 — 그때는 이 판정이 아예 안 돈다."""
    scene, _ = _focus_scene(blur_background=True)
    assert n_leaves(focus_on_center_canopy(scene, 1000, 1000)) == 6


def test_without_a_canopy_nothing_is_dropped():
    """캐노피를 못 잡으면 고를 기준이 없다 — 잘못 버리느니 예전처럼 다 센다."""
    boxes = [box(100, 100, 60, 60), box(900, 900, 60, 60)]
    assert focus_on_center_canopy(boxes, W, H) == boxes


def test_topview_keeps_every_canopy_while_a_closeup_keeps_one():
    """두 경로가 반대로 동작해야 한다 — 섞이면 한쪽이 통째로 틀린다.

    · 탑뷰 전체 사진: 캐노피 하나하나가 화분이다. 전부 센다.
    · 개별 사진: 찍으려던 포기 하나만. 프레임에 걸린 옆 포기는 버린다.
    """
    scene = [box(300, 300, 300, 300, cls="canopy"), box(300, 300, 60, 60),
             box(500, 500, 300, 300, cls="canopy"), box(500, 500, 60, 60),
             box(800, 800, 300, 300, cls="canopy"), box(800, 800, 60, 60)]

    # 탑뷰 — 캐노피 3개 = 화분 3개
    groups = group_leaves(scene)
    assert len(groups) == 3, leaf_sizes(groups)
    assert leaf_sizes(groups) == [1, 1, 1], leaf_sizes(groups)

    # 개별 사진 — 가운데(500,500) 포기 하나만
    kept = focus_on_center_canopy(scene, W, H)
    assert len([b for b in kept if b["cls"] == "canopy"]) == 1, kept
    assert n_leaves(kept) == 1, kept


def test_the_thumbnail_shows_what_was_counted():
    """개수가 이상할 때 무엇이 세어졌는지 볼 수 있어야 한다 — 숫자만으론 못 따진다."""
    import io, base64, main
    from PIL import Image

    scene = [box(450, 450, 400, 400, cls="canopy"),
             box(380, 380, 140, 140), box(520, 500, 140, 140),
             box(120, 120, 250, 250, cls="canopy"),   # 옆 포기 — 버려져야 한다
             box(110, 110, 110, 110)]
    orig = main.detect_boxes
    main.detect_boxes = lambda im, det=None: (list(scene), float(900 * 900))
    try:
        buf = io.BytesIO()
        Image.new("RGB", (900, 900), (18, 40, 26)).save(buf, format="JPEG")
        m, _ = main._analyze_file(buf.getvalue())
    finally:
        main.detect_boxes = orig

    assert m["leaf_count"] == 2, m                       # 가운데 포기 잎만
    assert m["thumb"].startswith("data:image/jpeg;base64,"), m["thumb"][:40]
    png = base64.b64decode(m["thumb"].split(",", 1)[1])
    im = Image.open(io.BytesIO(png))
    assert max(im.size) <= 520, im.size                  # 모달에 넣을 크기


# ── 크기 등급은 캐노피(포기 전체 폭)로 ────────────────────────────────────
def test_size_class_comes_from_the_canopy_not_the_biggest_leaf():
    """잎 한 장은 포기 크기를 대표하지 못한다 — 캐노피 폭으로 매긴다."""
    import main
    # 큰 잎 한 장만 달린 어린 포기 (캐노피가 작다)
    small = [box(200, 200, 100, 100, cls="canopy"), box(200, 200, 90, 90)]
    # 같은 크기 잎이 여러 장인 다 큰 포기 (캐노피가 크다)
    big = [box(1000, 200, 400, 400, cls="canopy"),
           box(880, 120, 90, 90), box(1050, 250, 90, 90), box(1100, 150, 90, 90)]
    groups = group_leaves(small + big)
    cm = 60.0 / 1200                              # 선반 60cm ↔ 박스 폭 1200
    graded = {}
    for g in groups:
        m = analyze_metrics(g, 1200 * 800, cm_per_unit=cm)
        graded[m["canopy_cm"]] = m["size_class"]
    assert graded == {5.0: "소품", 20.0: "중품"}, graded


def test_the_3d_size_follows_the_canopy_too():
    """3D 온실이 그리는 크기(top_leaf_size)가 소/중/대품 칩과 따로 놀면 안 된다.

    analyze_top 은 '사진에서 가장 위쪽 잎' 하나로 그 값을 정한다. 맨 위 잎이
    그 포기의 큰 잎이라는 보장이 없어서, 큰 포기인데 위쪽에 걸린 잎이 작으면
    3D 에서 작게 그려졌다 — "뒤에 있는 큰 식물이 작게 나온다" 가 이 경로다.
    """
    boxes = [box(600, 600, 1000, 1000, cls="canopy"),   # 포기 전체는 크다
             box(300, 150, 80, 80),                     # 맨 위 잎은 작다
             box(600, 800, 700, 700), box(800, 700, 600, 600)]
    g = group_leaves(boxes)[0]
    old_way = analyze_top(g, 1200 * 800, ref_area=1200 * 800 / 3)
    assert old_way["top_leaf_size"] == "소엽", old_way      # 예전 방식은 작다고 본다

    m = analyze_metrics(g, 1200 * 800, cm_per_unit=60.0 / 1200)
    assert m["size_class"] == "대품", m
    assert m["top_leaf_size"] == "대엽", m                  # 3D 도 같이 커진다


def test_canopy_cm_is_reported_so_thresholds_can_be_tuned():
    """모달에 실측 cm 이 떠야 기준치를 본인 농장에 맞출 수 있다."""
    boxes = [box(200, 200, 600, 300, cls="canopy"), box(200, 200, 60, 60)]
    g = group_leaves(boxes)[0]
    m = analyze_metrics(g, 1200 * 800, cm_per_unit=60.0 / 1200)
    assert m["canopy_cm"] == 30.0, m           # 긴 변 600px × 0.05cm/px
    assert m["size_class"] == "대품", m


def test_falls_back_to_leaf_size_when_no_canopy_was_detected():
    """캐노피를 못 잡은 사진(개체 근접 촬영 등)에서는 예전처럼 잎으로 잰다."""
    g = group_leaves([box(200, 200, 60, 60)])[0]
    m = analyze_metrics(g, 1200 * 800, cm_per_unit=60.0 / 1200)
    assert m["canopy_cm"] is None, m
    assert m["size_class"] == "소품", m        # 잎 긴 변 3cm


def test_leaf_outside_every_canopy_does_not_inflate_a_pots_count():
    """캐노피를 놓친 포기가 통째로 옆 화분 잎 수에 얹히면 안 된다."""
    canopy = [box(200, 200, 200, 200, cls="canopy")]       # x 100~300, y 100~300
    inside = [box(180, 180, 40, 40), box(230, 230, 40, 40)]
    missed = [box(500, 200, 40, 40), box(540, 220, 40, 40)]  # 캐노피가 안 잡힌 포기
    groups = group_leaves(canopy + inside + missed)
    assert leaf_sizes(groups) == [2, 2], leaf_sizes(groups)


def test_a_small_canopy_inside_a_big_one_stays_its_own_pot():
    """빽빽한 트레이에선 작은 포기가 큰 이웃 박스 안에 들어앉는 게 정상이다.
    '덮였으니 같은 포기'로 합치면 실제 화분이 통째로 사라진다."""
    canopy = [box(200, 200, 300, 300, cls="canopy"),
              box(120, 120, 80, 80, cls="canopy")]         # 큰 캐노피 안에 들어앉음
    leaves = [box(110, 110, 30, 30),                       # 작은 캐노피 몫
              box(300, 300, 30, 30), box(280, 260, 30, 30)]  # 큰 캐노피 몫
    groups = group_leaves(canopy + leaves)
    assert leaf_sizes(groups) == [1, 2], leaf_sizes(groups)


def test_canopy_wins_over_a_pot_box_on_the_same_plant():
    """한 포기에 화분 박스와 캐노피가 같이 잡혀도 화분 둘로 쪼개지지 않는다."""
    boxes = [box(200, 300, 400, 400, cls="canopy"),        # 잎 전체
             box(200, 400, 80, 80, cls="pot"),             # 같은 포기의 화분
             box(150, 200, 40, 40), box(250, 250, 40, 40), box(200, 400, 40, 40)]
    groups = group_leaves(boxes)
    assert len(groups) == 1 and n_leaves(groups[0]) == 3, leaf_sizes(groups)


def test_every_canopy_holding_a_leaf_becomes_its_own_pot():
    """캐노피가 겹쳐 잡혀도 잎을 담고 있으면 각각 화분이다 — 임의로 합치지 않는다."""
    canopy = [box(200, 200, 400, 400, cls="canopy"),
              box(320, 200, 400, 400, cls="canopy"),       # 크게 겹침
              box(700, 200, 200, 200, cls="canopy")]
    leaves = [box(60, 200, 30, 30), box(450, 200, 30, 30), box(700, 200, 30, 30)]
    groups = group_leaves(canopy + leaves)
    assert len(groups) == 3, [len(g) for g in groups]


def test_weed_class_is_dropped_at_the_detector_boundary():
    """풀(잡초) 뭉치를 새 클래스로 학습시켜 두면, detect_boxes 가 결과에서 통째로 뺀다.

    NON_LEAF(pot 등)와 다르다 — pot 은 그룹화의 화분 자리 신호로 계속 쓰이지만,
    잡초는 그 무엇으로도 안 쓰는 잡음이라 아예 안 보이게 지운다.
    """
    import main
    from PIL import Image

    class _Stub:
        def detect(self, image):
            return ([box(100, 100, 60, 60, cls="mature leaf"),
                    box(400, 100, 200, 200, cls="weed"),
                    box(600, 100, 150, 150, cls="Weeds")], 10000.0)

    boxes, area = main.detect_boxes(Image.new("RGB", (10, 10)), detector=_Stub())
    assert [b["cls"] for b in boxes] == ["mature leaf"], boxes
    assert area == 10000.0


def test_weed_boxes_are_not_used_as_fake_pot_anchors():
    """잡초 뭉치가 화분처럼 취급되면 근처 잎이 잘못 붙는다 — detect_boxes 를 거치면
    애초에 group_plants 가 보는 목록에 잡초가 없어야 한다."""
    import main
    from PIL import Image

    class _Stub:
        def detect(self, image):
            return ([box(100, 100, 40, 40, cls="pot"),
                    box(700, 100, 300, 300, cls="weed"),   # 화분처럼 취급되면 안 됨
                    box(120, 100, 60, 60, cls="mature leaf")], 10000.0)

    boxes, _ = main.detect_boxes(Image.new("RGB", (10, 10)), detector=_Stub())
    assert "weed" not in [b["cls"] for b in boxes]
    groups = group_leaves(boxes)
    assert len(groups) == 1 and len(groups[0]) == 1


def test_ref_area_keeps_leaf_size_meaningful_in_farm_photo():
    """농장 전체 사진에서도 대/중/소엽이 뭉개지면 안 된다."""
    farm_area = 4000 * 3000
    big_leaf = [box(500, 500, 700, 700)]     # 큰 잎이지만 전체 사진 대비로는 4%

    # 사진 전체를 기준으로 재면 무조건 소엽으로 뭉개진다
    assert analyze_top(big_leaf, farm_area)["top_leaf_size"] == "소엽"

    # 식물 1개 몫(10개체 가정)을 기준으로 재면 제대로 큰 잎으로 잡힌다
    per_plant = farm_area / 10
    assert analyze_top(big_leaf, farm_area, ref_area=per_plant)["top_leaf_size"] == "대엽"


def test_each_group_gets_its_own_stage_counts():
    """무리별로 단계 집계가 따로 나와야 3D 색이 개체별로 달라진다."""
    boxes = [box(100, 100, 60, 60, cls="old leaf"), box(140, 100, 60, 60, cls="old leaf"),
             box(900, 900, 60, 60, cls="shoot"), box(940, 900, 60, 60, cls="mature leaf")]
    groups = sorted(group_leaves(boxes), key=lambda g: g[0]["x1"])
    a = analyze_metrics(groups[0], 10 ** 6)
    b = analyze_metrics(groups[1], 10 ** 6)
    assert (a["old_count"], a["shoot_count"]) == (2, 0), a
    assert (b["shoot_count"], b["mature_count"]) == (1, 1), b


def test_shape_similarity_basics():
    """같은 잎끼리는 1에 가깝고, 모양·색이 다르면 뚝 떨어진다."""
    a = feat(aspect=1.2, size=100, h=60, s=180, v=120)
    assert shape_similarity(a, a) > 0.99

    long_narrow = feat(aspect=3.0, size=100, h=60, s=180, v=120)
    assert shape_similarity(a, long_narrow) < 0.4, shape_similarity(a, long_narrow)

    much_bigger = feat(aspect=1.2, size=400, h=60, s=180, v=120)
    assert shape_similarity(a, much_bigger) < 0.4

    different_colour = feat(aspect=1.2, size=100, h=110, s=180, v=120)
    assert shape_similarity(a, different_colour) < 0.4


def test_shape_similarity_ignores_missing_colour():
    """색 정보가 없으면 모양·크기만으로 판단하고, 그래도 동작해야 한다."""
    a = feat(aspect=1.2, size=100, color=False)
    b = feat(aspect=1.25, size=105, color=False)
    assert shape_similarity(a, b) > 0.9


def test_leaf_features_survive_degenerate_boxes():
    """폭이 0인 박스 같은 쓰레기 입력에도 죽지 않는다."""
    bad = {"cls": "leaf", "x1": 10, "y1": 10, "x2": 10, "y2": 50, "area": 0}
    f = leaf_features(None, bad)
    assert f["aspect"] == 1.0 and f["has_color"] is False


def test_shape_groups_label_varieties():
    """생김새가 닮은 개체끼리 같은 딱지를, 다른 개체는 다른 딱지를 받는다."""
    items = [{"name": "둥근잎1"}, {"name": "둥근잎2"}, {"name": "길쭉잎"}]
    feats = [feat(aspect=1.2, size=100), feat(aspect=1.25, size=104),
             feat(aspect=3.2, size=100)]
    _label_shape_groups(items, feats)
    assert items[0]["shape_group"] == items[1]["shape_group"]
    assert items[2]["shape_group"] != items[0]["shape_group"]
    # 큰 무리가 A 를 받는다
    assert items[0]["shape_group"] == "A" and items[0]["shape_group_size"] == 2


def test_shape_helps_a_stray_leaf_find_its_own_pot():
    """화분 밖으로 뻗은 잎: 거리만 보면 옆 화분, 생김새를 보면 제 화분.

    A(화분) + B(거리) 를 합치고 생김새로 교정하는 부분의 핵심.
    """
    # 화분 박스는 x 70~130 과 370~430
    pots = [box(100, 100, 60, 60, "pot"), box(400, 100, 60, 60, "pot")]
    leaves = [box(100, 100, 40, 120),      # 1번 화분: 길쭉한 잎
              box(400, 100, 90, 90)]       # 2번 화분: 둥근 잎
    feats = [feat(aspect=3.0), feat(aspect=1.0)]

    # 어느 화분 박스에도 안 걸치는 떠돌이 잎. 2번이 4배 가깝지만(60 vs 240) 생김새는 길쭉 = 1번 쪽
    stray = box(340, 100, 40, 120)
    groups = group_by_pots_and_shape(leaves + [stray], pots, feats + [feat(aspect=3.0)])
    assert len(groups) == 2, [len(g) for g in groups]

    owner = next(g for g in groups if any(b is stray for b in g))
    assert any(b is leaves[0] for b in owner), "생김새가 같은 1번 화분에 붙어야 한다"
    assert not any(b is leaves[1] for b in owner), "가깝다는 이유로 2번에 붙으면 안 된다"


def test_shape_gate_stops_unlike_leaves_merging():
    """가까워도 생김새가 전혀 다르면 (화분 없을 때) 같은 식물로 묶지 않는다."""
    round_leaf = box(100, 100, 90, 90)
    long_leaf = box(150, 100, 30, 150)
    groups = group_leaves([round_leaf, long_leaf])
    assert len(groups) == 2, [len(g) for g in groups]


def _farm_boxes():
    """실제 농장 탑뷰와 비슷한 배치: 화분 3개가 한 줄, 잎은 사방으로 뻗어 이웃과 겹침."""
    boxes = []
    for px in (400, 1000, 1600):
        boxes.append(box(px, 900, 260, 260, "pot"))
        for dx, dy, cls in [(-260, -120, "leaf"), (250, -100, "leaf"), (0, -300, "shoot"),
                            (-150, 180, "old leaf"), (170, 200, "leaf")]:
            boxes.append(box(px + dx, 900 + dy, 300, 300, cls))
    return boxes


def test_radiating_canopy_defeats_distance_grouping():
    """알로카시아 탑뷰의 핵심 성질: '이웃 식물의 잎'이 '같은 식물의 잎'보다 가깝다.

    잎이 잎자루로 사방으로 뻗기 때문에, 거리 임계값을 어떻게 잡아도
    같은 식물끼리 묶으면 이웃까지 딸려 오고, 이웃을 떼면 자기 잎도 떨어져 나간다.
    → 화분 클래스가 '있으면 좋은 것'이 아니라 '필요한 것'인 이유.
    """
    import math
    same_plant = math.dist((400 - 260, 900 - 120), (400 + 250, 900 - 100))
    neighbours = math.dist((400 + 250, 900 - 100), (1000 - 260, 900 - 120))
    assert neighbours < same_plant / 3, (neighbours, same_plant)

    boxes = _farm_boxes()
    leaves = leaves_only(boxes)
    assert len(group_leaves(leaves)) != 3            # 잎만으로는 3개가 안 나온다
    assert len(group_leaves(boxes)) == 3             # 화분을 쓰면 정확히 3개


def test_scan_endpoint_registers_one_plant_per_pot():
    """농장 사진 1장 → 화분 수만큼 개체가 자리와 함께 등록된다."""
    import asyncio, io
    from PIL import Image
    import main

    class _Upload:                                   # UploadFile 흉내 (content_type + read)
        content_type = "image/jpeg"

        def __init__(self, raw):
            self._raw = raw

        async def read(self):
            return self._raw

    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), (20, 80, 30)).save(buf, format="JPEG")

    boxes = _farm_boxes()
    orig_detect, orig_plants = main.detect_boxes, dict(main.PLANTS)
    main.detect_boxes = lambda image, det=None: (boxes, float(2000 * 1500))
    main.PLANTS.clear()
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(buf.getvalue()), replace=None, mode=None))
        assert res["count"] == 3, res
        assert res["grouped_by"] == "pot", res

        positions = [p["pos"] for p in res["plants"]]
        assert len(set(positions)) == 3, positions          # 자리가 겹치면 안 된다
        for p in res["plants"]:
            assert p["leaf_count"] == 5, p
            # 농장 전체 탑뷰에서 잘라 낸 조각은 흐릿해서 모달 사진으로 안 쓴다 —
            # 개체 사진을 따로 올리기 전까진 썸네일이 없다.
            assert "thumb" not in p, p

        # 같은 사진을 다시 스캔해도 개체가 늘어나지 않는다 (이름·방향 유지하며 갱신)
        main.PLANTS[list(main.PLANTS)[0]]["name"] = "내가 지은 이름"
        again = asyncio.run(main.scan_farm(file=_Upload(buf.getvalue()), replace=None, mode=None))
        assert again["count"] == 3 and len(main.PLANTS) == 3, (again["count"], len(main.PLANTS))
        assert "내가 지은 이름" in [p["name"] for p in main.PLANTS.values()]
    finally:
        main.detect_boxes = orig_detect
        main.PLANTS.clear()
        main.PLANTS.update(orig_plants)


def test_farm_scan_does_not_clobber_a_dedicated_photo_thumbnail():
    """개체 사진으로 따로 올려 둔 썸네일은 탑뷰 스캔이 지나가도 안 지워진다."""
    import asyncio, io
    from PIL import Image
    import main

    class _Upload:
        content_type = "image/jpeg"

        def __init__(self, raw):
            self._raw = raw

        async def read(self):
            return self._raw

    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), (20, 80, 30)).save(buf, format="JPEG")

    boxes = _farm_boxes()
    orig_detect, orig_plants = main.detect_boxes, dict(main.PLANTS)
    main.detect_boxes = lambda image, det=None: (boxes, float(2000 * 1500))
    main.PLANTS.clear()
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(buf.getvalue()), replace=None, mode=None))
        pid = res["plants"][0]["id"]
        main.PLANTS[pid]["thumb"] = "data:image/jpeg;base64,already-here"

        again = asyncio.run(main.scan_farm(file=_Upload(buf.getvalue()), replace=None, mode=None))
        assert main.PLANTS[pid]["thumb"] == "data:image/jpeg;base64,already-here"
        assert pid in [p["id"] for p in again["plants"]]
    finally:
        main.detect_boxes = orig_detect
        main.PLANTS.clear()
        main.PLANTS.update(orig_plants)


def test_scan_labels_varieties_across_pots():
    """서로 떨어진 화분이라도 생김새가 같으면 같은 모양 그룹을 받는다."""
    import asyncio, io
    from PIL import Image
    import main

    class _Upload:
        content_type = "image/jpeg"

        def __init__(self, raw):
            self._raw = raw

        async def read(self):
            return self._raw

    # 대각선으로 마주 보는 화분끼리 같은 품종 (위치가 아니라 생김새로 묶이는지 확인)
    plan = [(300, 400, "long"), (900, 400, "round"),
            (300, 1000, "round"), (900, 1000, "long")]
    boxes = []
    for px, py, kind in plan:
        boxes.append(box(px, py, 200, 200, "pot"))
        for dx, dy in [(-180, -90), (180, -90), (0, -200)]:
            w, h = (80, 240) if kind == "long" else (190, 190)
            boxes.append(box(px + dx, py + dy, w, h))

    buf = io.BytesIO()
    Image.new("RGB", (1200, 1400), (20, 80, 30)).save(buf, format="JPEG")

    orig_detect, orig_plants, orig_feats = main.detect_boxes, dict(main.PLANTS), dict(main.FEATS)
    main.detect_boxes = lambda image, det=None: (boxes, float(1200 * 1400))
    main.PLANTS.clear(); main.FEATS.clear()
    try:
        res = asyncio.run(main.scan_farm(file=_Upload(buf.getvalue()), replace=None, mode=None))
        assert res["count"] == 4, res["count"]
        assert res["shape_groups"] == 2, res["shape_groups"]

        # 같은 품종끼리는 같은 딱지, 다른 품종끼리는 다른 딱지 → 2개씩 두 무리
        groups = {}
        for p in res["plants"]:
            groups.setdefault(p["shape_group"], []).append(p["pos"])
        assert sorted(len(v) for v in groups.values()) == [2, 2], groups
        for p in res["plants"]:
            assert p["shape_group_size"] == 2, p
    finally:
        main.detect_boxes = orig_detect
        main.PLANTS.clear(); main.PLANTS.update(orig_plants)
        main.FEATS.clear(); main.FEATS.update(orig_feats)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ✔ {t.__name__}")
    print(f"\n{len(tests)}개 통과")
