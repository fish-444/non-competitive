# non-competitive / alocasia-farm

## [alocasia-farm](alocasia-farm/) — 알로카시아 온실 스마트팜

사진 한 장으로 온실 전체를 재는 웹앱. 탑뷰 사진을 올리면 잎을 탐지해
포기별로 묶고, 잎 수·크기 등급·물 준 날을 기록하고, 3D 온실로 그려 준다.
빛이 덜 드는 자리를 찾아 화분 배치를 다시 짜 주기도 한다.
화분마다 **작물**(알로카시아·상추·바질·딸기 …)을 적으면 물주기 간격·크기 등급
기준·필요 광량이 그 작물 기준으로 계산된다. 쌓인 측정 이력의 **생장 추세**로
수확적기와 예상 생산량도 내다본다.

- 설치·사용법: [alocasia-farm/README.md](alocasia-farm/README.md)
- 파이썬(FastAPI) + 브라우저(three.js). 탐지는 로보플로우 워크플로.
- `python bench_real.py` 로 실제 사진 정확도를 잰다.

원래 `fish-444/first-contributions` 브랜치에서 개발하던 것을 이리로 옮겼다.
그쪽에도 사본이 남아 있다.
