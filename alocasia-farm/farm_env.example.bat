@echo off
rem ════════════════════════════════════════════════════════════════
rem  ⚠️  이 파일(farm_env.example.bat)에는 키를 넣지 마세요! ⚠️
rem
rem  이 파일은 **깃에 올라갑니다**. 여기에 키를 적으면 깃허브에 그대로
rem  공개됩니다. .gitignore 가 막아 주는 건 farm_env.bat 하나뿐입니다.
rem
rem  올바른 순서:
rem    1) 이 파일을 복사해서 이름을 farm_env.bat 로 바꾼다
rem    2) 복사본(farm_env.bat)을 열어 키를 넣는다
rem  start.bat 이 읽는 것도 farm_env.bat 입니다 — 이 파일이 아닙니다.
rem ════════════════════════════════════════════════════════════════

rem 로보플로우 Private API Key (공개키는 막힙니다). 따옴표 없이 붙여넣으세요.
set ROBOFLOW_API_KEY=여기에_개인키

rem 워크플로 방식
set ROBOFLOW_WORKSPACE=s-workspace-br86f
set ROBOFLOW_WORKFLOW_ID=find-old-leaf-and-others

rem 모델 방식을 쓸 거면 위 두 줄을 지우고 아래를 쓰세요
rem set ROBOFLOW_MODEL_TOP=모델이름/1
rem set ROBOFLOW_MODEL_STAGE=모델이름/1

rem 탐지 민감도 (낮출수록 잎을 더 많이 잡음, 기본 25)
rem set CONFIDENCE=15

rem 저장 파일 위치 (기본: 이 폴더의 farm.db)
rem set FARM_DB=D:\백업\farm.db

rem 포트 고정 (install.bat 이 자동으로 넣어 줍니다).
rem 정해 두면 늘 이 포트를 쓰고, 안 정하면 8123 부터 빈 번호를 찾습니다.
rem set FARM_PORT=8123
