@echo off
chcp 65001 >nul
title 알로카시아 스마트팜 - 설치
cd /d "%~dp0"

echo ==========================================================
echo    알로카시아 스마트팜 설치
echo ==========================================================
echo.
echo  이 창이 하는 일:
echo    1) 파이썬이 있는지 확인
echo    2) 필요한 패키지 설치
echo    3) 키 파일(farm_env.bat) 준비
echo    4) 켤 때 자동 실행 등록 + 바탕화면 바로가기 만들기
echo.
echo  관리자 권한은 필요 없습니다.
echo.
pause
echo.

rem ---------------------------------------------------------- 1) 파이썬
python --version >nul 2>&1
if errorlevel 1 (
    echo [1/4] [오류] 파이썬을 찾을 수 없습니다.
    echo.
    echo        https://www.python.org/downloads/ 에서 설치하신 뒤
    echo        이 파일을 다시 실행하세요.
    echo        설치 화면 맨 아래 "Add Python to PATH" 를 꼭 체크하셔야 합니다.
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [1/4] %%v - 확인

rem ---------------------------------------------------------- 2) 패키지
echo [2/4] 필요한 패키지를 설치합니다. 1~2분 걸립니다...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo       [오류] 패키지 설치에 실패했습니다.
    echo              인터넷 연결을 확인하고 다시 실행해 주세요.
    echo.
    pause
    exit /b 1
)
echo       설치 완료.

rem ---------------------------------------------------------- 3) 키 파일
set NEEDKEY=
if exist "farm_env.bat" (
    echo [3/4] farm_env.bat 이미 있음 - 그대로 둡니다.
) else (
    copy /y "farm_env.example.bat" "farm_env.bat" >nul
    set NEEDKEY=1
    echo [3/4] farm_env.bat 를 만들었습니다.
)

rem ---------------------------------------------------------- 4) 자동 시작
echo [4/4] 자동 시작 등록 + 바탕화면 바로가기...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='Stop';" ^
 "$s = New-Object -ComObject WScript.Shell;" ^
 "$start = $s.CreateShortcut([Environment]::GetFolderPath('Startup') + '\알로카시아 스마트팜.lnk');" ^
 "$start.TargetPath = '%~dp0start.bat';" ^
 "$start.Arguments = '/nobrowser';" ^
 "$start.WorkingDirectory = '%~dp0';" ^
 "$start.WindowStyle = 7;" ^
 "$start.Description = '알로카시아 스마트팜 서버 (자동 시작)';" ^
 "$start.Save();" ^
 "$url = $s.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\알로카시아 온실.url');" ^
 "$url.TargetPath = 'http://localhost:8123';" ^
 "$url.Save();"
if errorlevel 1 (
    echo       [경고] 바로가기 만들기에 실패했습니다.
    echo              서버는 start.bat 을 더블클릭하면 그대로 켜집니다.
) else (
    echo       등록 완료.
)

rem 포트를 고정해 둡니다. 바탕화면 바로가기 주소가 항상 맞도록.
rem (예시 파일에 주석으로 들어 있는 rem set FARM_PORT 줄은 세지 않도록 줄 첫머리만 봅니다)
findstr /b /i /c:"set FARM_PORT" "farm_env.bat" >nul 2>&1
if errorlevel 1 (
    echo.>> "farm_env.bat"
    echo rem 자동 시작 바로가기와 주소를 맞추기 위해 포트를 고정합니다.>> "farm_env.bat"
    echo set FARM_PORT=8123>> "farm_env.bat"
)

echo.
echo ==========================================================
echo    설치가 끝났습니다.
echo ==========================================================
echo.
if defined NEEDKEY (
    echo  [!] 아직 할 일이 하나 있습니다 - 로보플로우 키 넣기.
    echo      안 넣으면 데모 모드로 돌아갑니다 ^(사진과 무관한 가짜 결과^).
    echo.
    echo      이어서 farm_env.bat 를 메모장으로 엽니다.
    echo        1^) "여기에_개인키" 를 지우고 Private API Key 를 붙여넣기
    echo        2^) 따옴표는 넣지 마세요 - 배치는 따옴표까지 키 값으로 씁니다
    echo        3^) 저장^(Ctrl+S^) 후 메모장 닫기
    echo.
    pause
    notepad "farm_env.bat"
    echo.
)
echo  다음부터는:
echo    - 컴퓨터를 켜면 서버가 알아서 뜹니다 (작업표시줄에 최소화된 창)
echo    - 바탕화면의 "알로카시아 온실" 을 더블클릭하면 열립니다
echo.
echo  지금 바로 켜시려면 아무 키나 누르세요. (그냥 닫으셔도 됩니다)
pause >nul
start "" "%~dp0start.bat"
