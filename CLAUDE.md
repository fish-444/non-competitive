# 이 저장소에서 작업할 때

## 먼저 — 어느 브랜치에 있는지 본다

이 저장소에는 서로 무관한 작업물 둘이 브랜치를 나눠 들어 있다.

| 브랜치 | 작업물 | 규칙 |
| --- | --- | --- |
| `main` | `alocasia-farm/`, `light-sim/` | 아래 전부 |
| `field-track` | `field-track/` | **아래 규칙은 해당 없다.** `field-track/CLAUDE.md` 를 따른다 |

아래 내용은 전부 알로카시아 이야기다. `field-track` 브랜치에서 작업 중이면
여기 적힌 브랜치·테스트·커밋 금지 항목을 알로카시아 것으로 읽고 넘어가라.

원격에는 아직 병합 안 된 브랜치가 더 있다. **`main` 만 보고 "없다"고 하지 마라** —
이 저장소는 단일 브랜치로 클론돼 있어서 `git fetch` 만으로는 안 내려온다.

```bash
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
```

| 브랜치 | 들어 있는 것 |
| --- | --- |
| `claude/crop-greenhouse-implementation-rzsqhd` | `alocasia-farm/` 의 `crops.py`·`harvest.py`·`weather.py`·`providers/weather_kma.py`, `docs/claude-project/` |
| `claude/greenlight-casadi-dynamics-pa4ppq` | `greenlight/` — GreenLight-Gym 동역학을 MPC 에 쓸 수 있는지 조사한 결과 |

## 여기가 알로카시아 스마트팜의 본거지다

원래 `fish-444/first-contributions` 의 `claude/alocasia-canopy-deployment-check-0u21bk`
브랜치에서 개발하던 것을 2026-08-04 에 옮겨 왔다. **앞으로 작업은 여기서 한다.**
그쪽에도 사본이 남아 있지만 그건 그 시점의 스냅샷일 뿐이니, 고칠 때 그쪽을
건드리지 말 것 — 두 벌을 따라가면 반드시 갈라진다.

## 브랜치

**알로카시아는** `main` 에서 작업한다. `alocasia-farm/install.ps1` 이 `$Branch = 'main'` 을 보고
설치하기 때문에, 옆 브랜치에 올리면 사용자가 설치해도 그 변경이 안 따라온다.

이건 설치 스크립트 때문이지 저장소 전체 규칙이 아니다. `field-track` 은 설치되는 물건이
아니라서 자기 브랜치에 있어도 된다 — 오히려 `main` 에 섞으면 알로카시아 쪽 파일 목록만
지저분해진다.

## 고치고 나면 반드시 두 가지를 돌린다

```bash
cd alocasia-farm
for f in test_*.py; do python "$f"; done   # 243개, 전부 통과해야 한다
python bench_real.py                        # 실제 사진 정확도
```

`bench_real.py` 가 중요하다. `test_*.py` 는 "규칙대로 도는가"만 보는데, 그룹화
규칙은 규칙대로 돌면서도 실제 사진에서 틀릴 수 있다. 실제로 그런 일이 몇 번
있었다 — 그럴듯해 보이는 규칙(중복 캐노피 정리, 잎과 같은 박스인 캐노피 제거)을
넣었다가 벤치마크가 더 나빠져서 되돌렸다. **그룹화를 건드렸으면 재고 나서 말한다.**

현재 성적: 화분 오차 0, 잎 오차 3. 잎 3장은 모델이 아예 못 낸 것이라 코드로는
못 줄인다 — 후처리는 모델이 낸 박스를 하나도 안 흘린다.

## 절대 커밋하면 안 되는 것

- `farm_env.bat` / `farm_env.sh` — 로보플로우 API 키. 전에 실제로 공개 저장소에
  올라가 키를 폐기한 적이 있다. `farm_env.example.bat` 에도 키를 적지 말 것.
- `farm.db` — 사용자의 식물 기록.
- `bench_data/` — 각자 다른 사진으로 만든 측정 자료.

셋 다 `alocasia-farm/.gitignore` 가 막고 있다.
