@echo off
chcp 65001 >nul
title 알로카시아 스마트팜
cd /d "%~dp0"

rem 로보플로우 키는 farm_env.bat 에 따로 둡니다 (깃에 안 올라감).
rem farm_env.example.bat 를 farm_env.bat 로 복사해 키를 채우세요.
if exist "farm_env.bat" (
    call "farm_env.bat"
) else (
    echo [알림] farm_env.bat 가 없어 데모 모드로 켭니다.
    echo        farm_env.example.bat 를 farm_env.bat 로 복사해 키를 넣으면
    echo        로보플로우로 실제 분석합니다.
    echo.
)

rem 자동 시작(윈도우 시작프로그램)으로 뜬 경우엔 브라우저를 열지 않습니다.
rem 부팅할 때마다 창이 뜨면 성가시니까요. 바탕화면 바로가기로 여시면 됩니다.
if /i "%~1"=="/nobrowser" set FARM_NOBROWSER=1

rem 포트: farm_env.bat 에서 FARM_PORT 를 정해 두면 늘 그 포트를 씁니다.
rem (바탕화면 바로가기 주소가 고정되려면 포트도 고정이어야 합니다)
rem 안 정했으면 8123 부터 비어 있는 번호를 찾습니다.
set PORT=8123
if defined FARM_PORT set PORT=%FARM_PORT%
if not defined FARM_PORT netstat -ano | findstr ":%PORT% " >nul && set PORT=8234
if not defined FARM_PORT netstat -ano | findstr ":%PORT% " >nul && set PORT=8345

echo 주소 - http://127.0.0.1:%PORT%
echo 끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.

rem 서버가 뜰 시간을 주고 브라우저를 띄웁니다
if not defined FARM_NOBROWSER start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%PORT%"

python -m uvicorn main:app --port %PORT%

echo.
echo 서버가 멈췄습니다. 저장된 식물 정보는 farm.db 에 남아 있습니다.
pause
