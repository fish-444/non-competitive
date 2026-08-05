"""내려받은 관수 데이터셋 → water_profile.json

실행:
    python make_water_profile.py <데이터셋폴더> --inspect     # 구조부터 확인
    python make_water_profile.py <데이터셋폴더>               # 프로필 만들기

AI Hub '원예식물(화분류) 물주기(수분공급 주기) 생육 데이터' 를 염두에 두고 짰다.
그 데이터는 화분마다 토양수분을 계속 재 두었으므로, **물을 준 뒤 다음에 줄 때까지
며칠 걸렸는지**를 세면 관수 간격이 추측이 아니라 실측으로 나온다.

필드 이름을 박아 두지 않았다. 데이터셋 버전마다 키 이름이 달라지는 일이 잦아서,
JSON 을 훑어 '수분'·'관수'·'일시' 같은 뜻의 키를 찾아 쓴다. 못 찾으면 --inspect
로 실제 키를 보여 주고 멈춘다 — 엉뚱한 필드로 계산해서 그럴듯한 숫자를 내놓는
것보다 낫다.

기본 조건 (알로카시아에 맞춘 것):
  · 두는 곳    거실 (베란다는 바깥 기온·바람을 받아 훨씬 빨리 마른다)
  · 관수 환경  일반 (건조/과습은 일부러 치우치게 준 것이라 기준이 못 된다)
  · 품종       천남성과 습생 — 몬스테라·스파티필럼·디펜바키아
               (알로카시아는 이 데이터셋에 없다. 같은 과의 습생이 가장 가깝다)
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime

# 알로카시아와 같은 천남성과 습생. 이름 표기가 조금씩 달라도 잡히게 부분일치로 본다.
AROID_WET = ["몬스테라", "스파티필럼", "디펜바키아"]
PLACE_LIVING = ["거실", "실내", "L"]
REGIME_NORMAL = ["일반", "보통", "정상", "normal"]

# 키 이름을 찾을 때 쓰는 패턴 — 뜻이 같으면 이름이 달라도 잡는다.
PATTERNS = {
    "moisture": r"(토양)?.*(수분|moist|vwc)",
    "when": r"(일시|일자|날짜|시각|시간|date|time|measur)",
    "species": r"(작물|품종|식물|종명|plant|crop|species)",
    "place": r"(장소|공간|위치|place|room|location)",
    "regime": r"(관수|물주기|water)",
    "pot": r"(화분|개체|샘플|pot|sample|id)",
}


def walk(obj, prefix=""):
    """중첩 JSON → {점으로_이은_키: 값} 평탄화."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(walk(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:1]):        # 리스트는 첫 항목만 구조 파악용
            out.update(walk(v, f"{prefix}[]"))
    else:
        out[prefix] = obj
    return out


def find_key(flat, kind):
    """평탄화된 키 중 그 뜻에 맞는 것을 고른다. 없으면 None."""
    pat = re.compile(PATTERNS[kind], re.I)
    hits = [k for k in flat if pat.search(k)]
    if not hits:
        return None
    # 얕은 키를 먼저 — 깊은 곳의 비슷한 이름보다 대표 필드일 가능성이 높다
    return min(hits, key=lambda k: (k.count("."), len(k)))


def load_records(root):
    """폴더 아래 모든 JSON 을 읽어 평탄화한 dict 목록으로."""
    recs = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if not n.lower().endswith(".json"):
                continue
            path = os.path.join(dirpath, n)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            for item in (data if isinstance(data, list) else [data]):
                flat = walk(item)
                flat["__file"] = path
                recs.append(flat)
    return recs


def parse_when(v):
    s = str(v)[:19].replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def matches(value, wanted):
    s = str(value)
    return any(w.lower() in s.lower() for w in wanted)


def watering_events(series, jump=3.0):
    """(시각, 토양수분) 시계열 → 물 준 시각들.

    물을 주면 토양수분이 확 뛴다. 마르는 동안은 천천히 내려간다. 그래서 '직전보다
    jump 이상 뛴 지점' 을 관수 시점으로 본다. 센서 튐과 구분하려고, 뛰기 전보다
    확실히 높은 상태가 이어지는 것만 인정한다.
    """
    series = sorted(series)
    events = []
    for i in range(1, len(series)):
        prev, cur = series[i - 1][1], series[i][1]
        if cur - prev < jump:
            continue
        after = [v for _, v in series[i:i + 3]]
        if after and statistics.mean(after) > prev + jump / 2:
            events.append(series[i][0])
    return events


def build(root, species, place, regime, inspect=False):
    recs = load_records(root)
    if not recs:
        sys.exit(f"[중단] {root} 아래에서 JSON 을 못 찾았습니다.")
    sample = recs[0]
    keys = {k: find_key(sample, k) for k in PATTERNS}

    if inspect or not all(keys[k] for k in ("moisture", "when")):
        print(f"\nJSON {len(recs):,}건. 첫 건의 키를 보여 드립니다:\n")
        for k, v in list(sample.items())[:60]:
            if k != "__file":
                print(f"  {k} = {str(v)[:60]}")
        print("\n찾아낸 필드:")
        for k, v in keys.items():
            print(f"  {k:9} → {v or '못 찾음'}")
        if not inspect:
            print("\n[중단] 수분/시각 필드를 못 찾았습니다. 위 목록을 알려 주시면 맞춰 드립니다.")
            sys.exit(1)
        return None

    # 조건에 맞는 화분만 골라 화분별 시계열을 만든다
    by_pot = defaultdict(list)
    kept = 0
    for r in recs:
        if keys["species"] and species and not matches(r.get(keys["species"]), species):
            continue
        if keys["place"] and place and not matches(r.get(keys["place"]), place):
            continue
        if keys["regime"] and regime and not matches(r.get(keys["regime"]), regime):
            continue
        when = parse_when(r.get(keys["when"]))
        try:
            moist = float(r.get(keys["moisture"]))
        except (TypeError, ValueError):
            continue
        if when is None:
            continue
        pot = str(r.get(keys["pot"]) or r["__file"])
        by_pot[pot].append((when, moist))
        kept += 1

    print(f"  조건에 맞는 측정 {kept:,}건 · 화분 {len(by_pot)}개")
    if not by_pot:
        sys.exit("[중단] 조건에 맞는 자료가 없습니다. --species/--place/--regime 을 넓혀 보세요.")

    gaps_by_month = defaultdict(list)
    for series in by_pot.values():
        evs = watering_events(series)
        for a, b in zip(evs, evs[1:]):
            days = (b - a).total_seconds() / 86400
            if 0.5 <= days <= 30:
                gaps_by_month[b.month].append(days)

    if not gaps_by_month:
        sys.exit("[중단] 관수 시점을 못 찾았습니다. 수분이 뛰는 폭(jump)이 다를 수 있습니다.")

    by_month = {str(m): round(statistics.median(v), 1)
                for m, v in sorted(gaps_by_month.items()) if len(v) >= 3}
    allgaps = [g for v in gaps_by_month.values() for g in v]
    return {
        "source": f"AI Hub 원예식물(화분류) 물주기 생육 데이터 — {'·'.join(species)} / {place[0]} / {regime[0]}",
        "provisional": False,
        "group": "습생", "place": "거실",
        "base_interval_days": round(statistics.median(allgaps), 1),
        "by_month": by_month,
        "n_intervals": len(allgaps),
        "note": "수집 기간이 8~10월뿐이라 나머지 달은 by_month 에 없다 — "
                "그 달은 base_interval_days 로 계산된다.",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="관수 데이터셋 → water_profile.json")
    ap.add_argument("root", help="내려받아 압축을 푼 데이터셋 폴더")
    ap.add_argument("--inspect", action="store_true", help="계산 없이 JSON 구조만 보여준다")
    ap.add_argument("--species", nargs="*", default=AROID_WET)
    ap.add_argument("--place", nargs="*", default=PLACE_LIVING)
    ap.add_argument("--regime", nargs="*", default=REGIME_NORMAL)
    ap.add_argument("--out", default="water_profile.json")
    a = ap.parse_args()

    print(f"\n{a.root} 읽는 중...")
    prof = build(a.root, a.species, a.place, a.regime, a.inspect)
    if prof is None:
        sys.exit(0)

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=1)
    print(f"\n{a.out} 저장:")
    print(f"  기준 간격 {prof['base_interval_days']}일  (관수 간격 {prof['n_intervals']:,}건에서)")
    for m, v in prof["by_month"].items():
        print(f"    {m:>2}월 {v}일")
    print("\n서버를 껐다 켜면 이 값으로 달력 예정일이 계산됩니다.")
