"""기상청 단기예보 — 키를 넣으면 이쪽으로 바뀐다.

한국에서 키우는 온실이면 기상청 값이 동네에 더 잘 맞는다. 대신 공공데이터포털
키를 발급받아야 해서 기본은 아니다 — 키가 없으면 Open-Meteo 로 착지한다.

이 API 는 함정이 세 개 있고, 셋 다 조용히 빈 응답으로만 나타난다.

  1. **발표시각(base_time) 단위가 오퍼레이션마다 다르다.**
     초단기실황은 정시(HH00, 매시 40분 이후), 초단기예보는 HH30(45분 이후),
     단기예보는 하루 8회(0200·0500·…·2300, 각 10분 이후). 어긋나면 NODATA.
  2. **KST 기준이다.** 서버가 UTC 면 9시간 어긋나 매번 엉뚱한 발표를 조회한다.
     그래서 datetime.now() 를 안 쓰고 UTC+9 를 직접 만든다(zoneinfo 없이도 되게).
  3. **numOfRows 기본값이 10 이다.** 단기예보는 한 번에 700건이 넘어서, 기본값으로
     부르면 앞 10건만 오고 조용히 잘린다. 오류가 아니라 정상 200 이라 더 위험하다.

강수(POP/PCP/PTY)도 같이 받지만 **지붕 아래 화분에는 안 쓴다** — weather.py 가
노지일 때만 본다. 여기서는 받아 두기만 한다.
"""

import math
import os
from datetime import date, datetime, timedelta, timezone

URL = os.environ.get("KMA_URL",
                     "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0")
TIMEOUT = float(os.environ.get("WEATHER_TIMEOUT", "20"))
KST = timezone(timedelta(hours=9))

# 단기예보 발표시각 — 하루 8회. 각 시각 10분 이후에 나온다.
_FCST_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)


def now_kst() -> datetime:
    """KST 로 지금. 컨테이너가 UTC 여도 안 어긋나게 직접 만든다."""
    return datetime.now(timezone.utc).astimezone(KST)


# --------------------------------------------------------------------------- 격자
# 위경도 → 기상청 격자(nx, ny). Lambert Conformal Conic 이고, 활용가이드에 실린
# 상수 그대로다. 외부 의존성 없이 math 만으로 된다.
# 검증: 126.929810, 37.488201 → (59, 125) — 가이드의 공식 예시와 같다.
_RE, _GRID = 6371.00877, 5.0                 # 지구 반경(km), 격자 간격(km)
_SLAT1, _SLAT2 = 30.0, 60.0                  # 표준위도
_OLON, _OLAT = 126.0, 38.0                   # 기준점 경위도
_XO, _YO = 43, 136                           # 기준점 격자
_DEG = math.pi / 180.0


def to_grid(lat: float, lon: float) -> tuple:
    """위경도 → (nx, ny)."""
    re = _RE / _GRID
    sl1, sl2 = _SLAT1 * _DEG, _SLAT2 * _DEG
    olon, olat = _OLON * _DEG, _OLAT * _DEG
    sn = math.tan(math.pi * 0.25 + sl2 * 0.5) / math.tan(math.pi * 0.25 + sl1 * 0.5)
    sn = math.log(math.cos(sl1) / math.cos(sl2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + sl1 * 0.5)
    sf = (sf ** sn) * math.cos(sl1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)
    ra = math.tan(math.pi * 0.25 + lat * _DEG * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * _DEG - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return (int(ra * math.sin(theta) + _XO + 0.5),
            int(ro - ra * math.cos(theta) + _YO + 0.5))


def fcst_base(when: datetime) -> tuple:
    """단기예보의 (base_date, base_time). 아직 안 나온 발표는 고르지 않는다.

    00:00~02:09 에는 당일 0200 발표가 아직 없어서 **전날 2300** 으로 돌아가야 한다.
    이걸 빼먹으면 매일 새벽 두 시간 동안 빈 응답만 받는다.
    """
    ready = when - timedelta(minutes=15)          # 발표 10분 뒤 + 여유
    for hour in reversed(_FCST_HOURS):
        if ready.hour >= hour:
            return ready.strftime("%Y%m%d"), f"{hour:02d}00"
    prev = ready - timedelta(days=1)
    return prev.strftime("%Y%m%d"), "2300"


def ncst_base(when: datetime) -> tuple:
    """초단기실황의 (base_date, base_time). 정시 발표이고 40분 이후에 나온다."""
    ready = when - timedelta(minutes=45)
    return ready.strftime("%Y%m%d"), ready.strftime("%H00")


def _num(raw):
    """예보값을 숫자로. '강수없음' 같은 한글 범주가 섞여 들어온다.

    '1.0mm 미만' · '30.0~50.0mm' 처럼 숫자가 붙은 범주도 있어서, 앞의 숫자만
    떼어 쓴다. float() 로 바로 캐스팅하는 코드는 비 오는 날 터진다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in ("강수없음", "적설없음", "-"):
        return 0.0
    try:
        got = float(text)
    except ValueError:
        num = ""
        for ch in text.lstrip("-"):
            if ch.isdigit() or ch == ".":
                num += ch
            elif num:
                break
        try:
            got = float(num)
        except ValueError:
            return None
    # ±900 은 결측 마스킹이다 — 바다 격자를 찍었을 때 이런 값만 온다. 숫자로 바로
    # 읽히는 경로에도 걸어야 한다(-999 는 float() 를 그냥 통과한다).
    return None if abs(got) >= 900 else got


class KMA:
    """기상청 단기예보. 공공데이터포털 서비스키가 필요하다."""

    name = "kma"
    label = "기상청 단기예보"
    needs_key = True

    def __init__(self, service_key: str):
        self.service_key = service_key

    def fetch(self, lat: float, lon: float, today: date = None) -> dict:
        import requests
        nx, ny = to_grid(lat, lon)
        when = now_kst()

        cur = self._current(requests, nx, ny, when)
        daily = self._daily(requests, nx, ny, when)
        return {
            "source": self.label,
            "provider": self.name,
            "place": f"격자 {nx},{ny}",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "current": cur,
            "daily": [daily[k] for k in sorted(daily)],
            # 기상청은 지난 날을 안 준다. 평년 대비 편차는 예보 구간만으로 내야
            # 하므로, 그 한계를 밝혀 둔다 — main 이 이걸 보고 안내를 띄운다.
            "no_history": True,
        }

    def _call(self, requests, op: str, params: dict) -> list:
        params = {"serviceKey": self.service_key, "dataType": "JSON",
                  "pageNo": 1, "numOfRows": 1000, **params}
        try:
            resp = requests.get(f"{URL}/{op}", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise RuntimeError(f"기상청에 연결하지 못했습니다: {e}")
        try:
            data = resp.json()
        except ValueError:
            # 서비스키가 틀리면 dataType 과 무관하게 XML 이 오기도 한다.
            text = resp.text[:200].replace("\n", " ")
            raise RuntimeError(f"기상청 응답을 해석할 수 없습니다 (HTTP {resp.status_code}) {text}")
        if "OpenAPI_ServiceResponse" in data:
            head = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
            raise RuntimeError(f"기상청이 거부했습니다: {head.get('returnAuthMsg')} "
                               f"(코드 {head.get('returnReasonCode')}) — "
                               f"공공데이터포털의 **일반 인증키(Decoding)** 를 넣으셨는지 확인하세요.")
        body = (data.get("response") or {}).get("body") or {}
        header = (data.get("response") or {}).get("header") or {}
        if header.get("resultCode") not in (None, "00"):
            raise RuntimeError(f"기상청 오류: {header.get('resultMsg')} "
                               f"(코드 {header.get('resultCode')})")
        items = (body.get("items") or {}).get("item") or []
        return items if isinstance(items, list) else [items]

    def _current(self, requests, nx: int, ny: int, when: datetime) -> dict:
        """초단기실황 — 지금 기온·습도. 발표 직후엔 아직 없어 한 시간씩 물러난다."""
        for back in range(3):
            base_date, base_time = ncst_base(when - timedelta(hours=back))
            try:
                items = self._call(requests, "getUltraSrtNcst",
                                   {"base_date": base_date, "base_time": base_time,
                                    "nx": nx, "ny": ny})
            except RuntimeError:
                if back == 2:
                    raise
                continue
            if not items:
                continue
            got = {i.get("category"): _num(i.get("obsrValue")) for i in items}
            return {"at": f"{base_date} {base_time}", "temp_c": got.get("T1H"),
                    "humidity_pct": got.get("REH"),
                    # 기상청은 토양 값을 안 준다 — 없는 걸 있는 척하지 않는다.
                    "soil_moisture": None, "soil_temp_c": None}
        return {"at": None, "temp_c": None, "humidity_pct": None,
                "soil_moisture": None, "soil_temp_c": None}

    def _daily(self, requests, nx: int, ny: int, when: datetime) -> dict:
        """단기예보 → 날짜별 최고·최저기온과 강수합.

        TMX/TMN 은 하루에 한 번만 실리고 빠지는 날도 있어서, 없으면 시간별
        기온(TMP)에서 직접 뽑는다.
        """
        base_date, base_time = fcst_base(when)
        items = self._call(requests, "getVilageFcst",
                           {"base_date": base_date, "base_time": base_time,
                            "nx": nx, "ny": ny})
        daily, temps = {}, {}
        for it in items:
            on, cat = it.get("fcstDate"), it.get("category")
            val = _num(it.get("fcstValue"))
            if not isinstance(on, str) or len(on) != 8 or val is None:
                continue
            key = f"{on[:4]}-{on[4:6]}-{on[6:]}"
            row = daily.setdefault(key, {"on": key})
            if cat == "TMX":
                row["t_max"] = val
            elif cat == "TMN":
                row["t_min"] = val
            elif cat == "TMP":
                temps.setdefault(key, []).append(val)
            elif cat == "PCP":
                row["rain_mm"] = round(row.get("rain_mm", 0.0) + val, 1)
        for key, got in temps.items():
            row = daily.setdefault(key, {"on": key})
            row.setdefault("t_max", max(got))
            row.setdefault("t_min", min(got))
        # ET0 는 기상청이 안 준다. weather.water_adjust_days 는 ET0 가 없으면
        # '기록이 모자라다' 로 물러난다 — 없는 값을 기온으로 꾸며 내지 않는다.
        return daily
