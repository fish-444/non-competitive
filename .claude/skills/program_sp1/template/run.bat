@echo off
rem 개발용 실행. 워커는 하나만 - 상태를 메모리에 들고 있어서 여럿이면 서로 덮어쓴다.
cd /d "%~dp0"
if "%{{ENV}}_PORT%"=="" set {{ENV}}_PORT=8000
python -m uvicorn backend.app:app --reload --port %{{ENV}}_PORT%
