# non-competitive

경진대회에 내지 않는 작업물을 둔다. 지금 셋이고, **브랜치가 갈린다** —
`alocasia-farm` 과 `light-sim` 은 `main`, `field-track` 은 `field-track` 브랜치다.

## [alocasia-farm](alocasia-farm/) — 알로카시아 온실 스마트팜

사진 한 장으로 온실 전체를 재는 웹앱. 탑뷰 사진을 올리면 잎을 탐지해
포기별로 묶고, 잎 수·크기 등급·물 준 날을 기록하고, 3D 온실로 그려 준다.
빛이 덜 드는 자리를 찾아 화분 배치를 다시 짜 주기도 한다.

- 설치·사용법: [alocasia-farm/README.md](alocasia-farm/README.md)
- 파이썬(FastAPI) + 브라우저(three.js). 탐지는 로보플로우 워크플로.
- `python bench_real.py` 로 실제 사진 정확도를 잰다.

원래 `fish-444/first-contributions` 브랜치에서 개발하던 것을 이리로 옮겼다.
그쪽에도 사본이 남아 있다.

## [light-sim](light-sim/) — 실내 재배 공간 광 분포·배치 최적화

선반과 조명의 배치에서 빛이 어떻게 떨어지는지 계산하고, 고르게 나뉘도록 배치를 다시 짠다.
`alocasia-farm` 이 잰 값을 `farm_bridge.py` 로 받아 쓴다.

## [field-track](field-track/) — 노지 생장·수확 예측 (`field-track` 브랜치)

노지 상추·방울토마토의 **수확 시기와 출하 분포**를 예측한다.
생장곡선으로 시작해 방울토마토에서 DSSAT 대리모형까지 간다.

`main` 에는 없다. `git switch field-track` 으로 옮겨야 보인다.
알로카시아와 코드를 공유하지 않으므로 서로 건드릴 일이 없다.

**아직 모델 코드가 없다.** 데이터 실사(Phase 0) 결과가 `시험포 설계로 전환` 이라
상추·방울토마토 실측이 0건인 상태다. 없는 데이터를 가정한 코드를 먼저 쓰면
시험포 결과가 나왔을 때 전부 버리게 된다.

- 무엇이 막고 있는지: [field-track/docs/결정대기.md](field-track/docs/결정대기.md)
- 왜 그렇게 판정했는지: [field-track/analysis/노지_데이터실사.md](field-track/analysis/노지_데이터실사.md)
