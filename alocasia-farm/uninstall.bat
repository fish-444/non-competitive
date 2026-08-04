@echo off
chcp 65001 >nul
title 알로카시아 스마트팜 - 자동 시작 해제
cd /d "%~dp0"

echo ==========================================================
echo    자동 시작 해제
echo ==========================================================
echo.
echo  지우는 것:  자동 시작 등록, 바탕화면 바로가기
echo  남기는 것:  farm.db(식물 정보), farm_env.bat(키), 프로그램 파일
echo.
echo  나중에 install.bat 을 다시 실행하면 그대로 되돌아옵니다.
echo.
pause
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "Remove-Item ([Environment]::GetFolderPath('Startup') + '\알로카시아 스마트팜.lnk') -ErrorAction SilentlyContinue;" ^
 "Remove-Item ([Environment]::GetFolderPath('Desktop') + '\알로카시아 온실.url') -ErrorAction SilentlyContinue;"

echo  자동 시작을 해제했습니다.
echo.
echo  지금 돌고 있는 서버는 그대로 켜져 있습니다.
echo  끄시려면 작업표시줄의 "알로카시아 스마트팜" 창에서 Ctrl+C 를 누르세요.
echo.
pause
