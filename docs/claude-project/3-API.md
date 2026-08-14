# 3. 엔드포인트

전부 `main.py` 에 있다. 인증은 없다 — `127.0.0.1` 에서만 쓰는 것을 전제로 한다.
(`--host 0.0.0.0` 으로 열면 `DELETE /api/plants/{id}` 까지 LAN 에 공개된다.)

## 식물

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/plants` | 전체 목록 (+ `engine`). 물주기·작물·수확 계산값이 얹혀 나온다 |
| POST | `/api/plants` | `name` + `file` + `pos` + `crop`(선택) → 분석 후 추가 |
| PATCH | `/api/plants/{id}` | `name` `rot` `note` `crop` `soil` `size_class` `shoot_count` `mature_count` `old_count` |
| PATCH | `/api/plants/{id}/move` | `pos` → 다른 자리로 (자리에 식물이 있으면 맞바꿈) |
| POST | `/api/plants/{id}/reanalyze` | `file` → 새 사진으로 갱신 |
| POST | `/api/plants/{id}/rescan` | 보관된 원본을 다시 분석 (모델이 좋아졌을 때) |
| DELETE | `/api/plants/{id}` | 제거 |

## 스캔 (온실 전체 사진)

| | 경로 | 무엇 |
|---|---|---|
| POST | `/api/scan` | `file`(탑뷰) + `mode`(keep/update/replace) |
| POST | `/api/scan-multi` | `files` + (`corners`+`regions` 또는 `pot_refs`) → 원근 보정 후 합쳐 등록 |
| GET | `/api/scans` | 온실 전체 사진 이력 |

`mode`: `keep`(잎 유지·새 잎만 기록, 권장) / `update`(탐지값으로 덮음) / `replace`(전부 새로).

## 자리 · 화분

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/slots` | 자리 50개 + 점유 여부 |
| GET·POST·DELETE | `/api/pots` | 미리 지정한 화분 자리 |
| GET·POST·DELETE | `/api/calibration` | 선반 네 모서리 — cm 배율의 기준 |

## 잎 낱개

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/leaves` | 잎 낱개 + 화분별 집계 (`?ambiguous=1`) |
| GET | `/api/plants/{id}/leaves` | 그 화분의 잎 나이·단계 |
| PATCH | `/api/leaves/{leaf_id}` | `pot_slot` → 잎 소속 화분 변경 |
| DELETE | `/api/leaves/fixes` | 손으로 옮긴 잎 기억 지우기 |

## 물주기

| | 경로 | 무엇 |
|---|---|---|
| POST·DELETE | `/api/plants/{id}/water` | `day`(YYYY-MM-DD, 없으면 오늘) 기록/취소 |
| POST·DELETE | `/api/water-all` | 전체에 한 번에 |
| GET | `/api/water-log` | `month=YYYY-MM` → 날짜별 준 화분 수 + 예정일 |

## 작물 · 수확

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/crops` | 심을 수 있는 작물 목록 (추가 폼·모달의 고르기) |
| GET | `/api/harvest` | 온실 전체 수확 계획 — `days`(기본 30) 안의 날짜별 예상 생산량 |
| GET | `/api/plants/{id}/forecast` | 그 화분의 수확적기·예상 생산량 |
| GET | `/api/plants/{id}/history` | 측정 이력 + `forecast`(같은 기록에서 나온 예측) |

## 기상

| | 경로 | 무엇 |
|---|---|---|
| GET·POST·DELETE | `/api/site` | 온실 위경도 + 재배 환경(`indoor`/`veranda`/`greenhouse`/`outdoor`) |
| GET | `/api/weather` | 지금 바깥 날씨 + 이 설정에서 물주기에 얼마나 반영되는지 (`?refresh=1`) |

## 배치

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/placement` | 배치 점수 + 자리별 빛·그늘·필요 광량 |
| POST | `/api/placement/optimize` | 최적 배치 제안 (제안만 — 기록은 안 바뀐다) |
| POST | `/api/placement/apply` | `moves` → 실제로 옮긴 뒤 기록 반영 |
| GET | `/api/placement/heatmap` | 선반 전체 빛 분포 |
| GET·POST | `/api/environment` | 조명 위치 — 좌·우 레일 3개, `z`(레일 방향)만 조절 |

## 저장 · 사진

| | 경로 | 무엇 |
|---|---|---|
| GET | `/api/backup` | 전체를 파일 하나로 |
| POST | `/api/restore` | 되돌리기 (직전 상태를 `farm-backup-이전.json` 으로 남김) |
| GET | `/api/photos/{rel}` | 보관된 원본 사진 |
| GET | `/api/plants/{id}/photos` | 그 화분의 사진들 |

## 분석 결과 필드

| 필드 | 출처 | 쓰이는 곳 |
|---|---|---|
| `top_leaf_size` `top_leaf_pct` | 모델1 | 3D 크기 · 모달 |
| `shoot_count` `mature_count` `old_count` | 모델2 | 3D 잎 색 · 모달 |
| `leaf_count` `overlap_count` `overlap_density` | 모델2 | 모달 |
| `canopy_cm` `leaf_max_cm` | 실측 | 모달 등급 칩 |
| `size_class` | 모델2 + 작물 기준치 | 리스트 · 모달 |
| `crop` `crop_name` | 사람이 고름 | 물주기 · 배치 · 수확 |
| `last_watered` `days_since_watered` `soil_dry` `next_water` `interval_days` `basis` | 물주기 | 3D 흙 색 · 모달 |
| `harvest_on` `harvest_days` `harvest_g` `harvest_ready` | 생장 추세 예측 | 리스트 딱지 · 수확 패널 |
| `manual` `empty` `note` | 사람 | 모달 |
| `pos` `x` `z` `rot` | 자리 | 3D 배치 |
