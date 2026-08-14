"""Open-Meteo — 키 없이 바로 도는 기본 기상 제공자.

가입도 키도 없이 위경도만 있으면 된다. 그래서 이걸 기본으로 뒀다 — 사용자가
설정 파일을 건드리지 않아도 기상 기능이 그냥 돈다(탐지기에서 키가 없으면 데모로
착지하는 것과 같은 자리다. 다만 여긴 데모가 아니라 진짜 값이다).

두 곳을 부른다.

    forecast  api.open-meteo.com/v1/forecast   앞으로 며칠 + 지금
    archive   archive-api.open-meteo.com/...   지난 한 달 (평년 대비 편차를 보려면
                                               지나간 날이 필요하다)

두 응답을 한 벌의 일별 표로 합쳐 돌려준다. weather.py 는 이게 어디서 왔는지
모른 채 `daily[{on,t_max,t_min,et0,rain_mm}]` 만 본다.

토양수분·지온도 같이 받는다. **다만 이건 노지 격자의 육상모델 산출값이지 화분
상토가 아니다.** 화분은 부피가 작고 근권이 막혀 있어 마르는 속도가 아예 다르다.
그래서 화면에 '바깥 흙' 참고값으로만 띄우고, 물주기 계산에는 안 들어간다
(weather.py 가 그 결정을 갖고 있다).
"""

import os
from datetime import date, datetime, timedelta

FORECAST_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
ARCHIVE_URL = os.environ.get("OPEN_METEO_ARCHIVE_URL",
                             "https://archive-api.open-meteo.com/v1/archive")
TIMEOUT = float(os.environ.get("WEATHER_TIMEOUT", "20"))

# 평년 대비 편차를 보려면 지나간 날이 필요하다. weather.RECENT_DAYS(7)+30 을 덮는다.
PAST_DAYS = 35
AHEAD_DAYS = 14

_DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
_CURRENT = "temperature_2m,relative_humidity_2m,soil_moisture_0_to_1cm,soil_temperature_0cm"


class OpenMeteo:
    """위경도 → 기상 관측·예보. 키가 필요 없다."""

    name = "open-meteo"
    label = "Open-Meteo (키 불필요)"
    needs_key = False

    def __init__(self, timezone: str = "Asia/Seoul"):
        self.timezone = timezone

    def fetch(self, lat: float, lon: float, today: date = None) -> dict:
        import requests
        today = today or date.today()
        daily = {}

        # 1) 예보 — 지금 값 + 앞으로. archive 는 어제까지라 오늘·내일이 여기서 온다.
        fc = self._get(requests, FORECAST_URL, {
            "latitude": lat, "longitude": lon, "timezone": self.timezone,
            "daily": _DAILY, "current": _CURRENT,
            "past_days": 7, "forecast_days": AHEAD_DAYS,
        })
        self._merge_daily(daily, fc)

        # 2) 과거 — 편차의 기준이 되는 지난 한 달. 여기가 실패해도 예보만으로
        #    지금 날씨는 보여 줄 수 있으므로 통째로 죽이지 않는다.
        try:
            ar = self._get(requests, ARCHIVE_URL, {
                "latitude": lat, "longitude": lon, "timezone": self.timezone,
                "daily": _DAILY,
                "start_date": (today - timedelta(days=PAST_DAYS)).isoformat(),
                "end_date": (today - timedelta(days=1)).isoformat(),
            })
            self._merge_daily(daily, ar, keep_existing=False)
        except Exception as e:                    # noqa: BLE001 — 과거는 없어도 된다
            print(f"[기상] 과거 자료를 못 받았습니다({e}) — 예보만으로 진행합니다")

        cur = (fc.get("current") or {})
        return {
            "source": self.label,
            "provider": self.name,
            "place": f"{round(float(fc.get('latitude', lat)), 3)}, "
                     f"{round(float(fc.get('longitude', lon)), 3)}",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "current": {
                "at": cur.get("time"),
                "temp_c": cur.get("temperature_2m"),
                "humidity_pct": cur.get("relative_humidity_2m"),
                # 바깥 노지 흙이다 — 화분이 아니다. 이름에 그 뜻을 남긴다.
                "soil_moisture": cur.get("soil_moisture_0_to_1cm"),
                "soil_temp_c": cur.get("soil_temperature_0cm"),
            },
            "daily": [daily[k] for k in sorted(daily)],
        }

    def _get(self, requests, url: str, params: dict) -> dict:
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise RuntimeError(f"기상 서버에 연결하지 못했습니다: {e}")
        if not resp.ok:
            raise RuntimeError(f"기상 서버 오류 (HTTP {resp.status_code}) "
                               f"{resp.text[:150]}")
        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("기상 응답을 해석할 수 없습니다.")
        if data.get("error"):
            raise RuntimeError(f"기상 서버가 거부했습니다: {data.get('reason')}")
        return data

    @staticmethod
    def _merge_daily(into: dict, data: dict, keep_existing: bool = True) -> None:
        """일별 배열(time[] + 값[])을 날짜별 dict 로 접어 넣는다.

        예보와 과거가 며칠 겹친다. 겹치는 날은 **실측(과거)** 을 남기는 게 맞지만,
        오늘 이후는 과거에 없으므로 서로 빈자리를 메우는 모양이 된다.
        """
        d = data.get("daily") or {}
        days = d.get("time") or []
        cols = {"t_max": d.get("temperature_2m_max") or [],
                "t_min": d.get("temperature_2m_min") or [],
                "rain_mm": d.get("precipitation_sum") or [],
                "et0": d.get("et0_fao_evapotranspiration") or []}
        for i, on in enumerate(days):
            if not isinstance(on, str):
                continue
            row = into.setdefault(on, {"on": on})
            for key, arr in cols.items():
                if i >= len(arr) or arr[i] is None:
                    continue
                if keep_existing and row.get(key) is not None:
                    continue
                row[key] = arr[i]
