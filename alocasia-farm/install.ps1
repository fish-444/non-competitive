# 알로카시아 스마트팜 — 파워셸 한 줄 설치
#
#   irm https://raw.githubusercontent.com/fish-444/non-competitive/refs/heads/main/alocasia-farm/install.ps1 | iex
#
# 저장소를 내려받고, 패키지를 깔고, 키 파일을 만들고, 자동 시작까지 등록한다.
# irm | iex 로 실행되면 $PSScriptRoot 가 없으므로 아무것도 가정하지 않는다.
# 이미 깔려 있으면 최신 코드만 받아 갱신한다(설정과 farm.db 는 안 건드림).

$ErrorActionPreference = 'Stop'

$Repo   = 'fish-444/non-competitive'
$Branch = 'main'
$SubDir = 'alocasia-farm'

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Step($n, $t) { Write-Host ''; Say "[$n] $t" Cyan }

Write-Host ''
Say '==========================================================' Cyan
Say '   알로카시아 스마트팜 설치' Cyan
Say '==========================================================' Cyan
Say '   관리자 권한은 필요 없습니다.' DarkGray

# ---------------------------------------------------------------- 파이썬
Step '1/5' '파이썬 확인'
$py = $null
foreach ($c in @('python', 'py')) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) {
        # 윈도우 스토어의 가짜 python.exe 는 --version 에 아무것도 안 뱉는다
        $v = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3') { $py = $c; break }
    }
}
if (-not $py) {
    Say '  [중단] 파이썬 3 을 찾을 수 없습니다.' Red
    Say '         https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요.' Red
    Say '         설치 화면 맨 아래 "Add Python to PATH" 를 꼭 체크하셔야 합니다.' Yellow
    return
}
Say "      $(& $py --version) 확인" Green

# ---------------------------------------------------------------- 받을 위치
Step '2/5' '설치 위치'
$defaultRoot = Join-Path $HOME 'non-competitive'
$answer = Read-Host "      설치 폴더 [$defaultRoot]"
$root = if ([string]::IsNullOrWhiteSpace($answer)) { $defaultRoot } else { $answer.Trim().Trim('"') }
$app = Join-Path $root $SubDir

# ---------------------------------------------------------------- 내려받기
Step '3/5' '코드 내려받기'
$git = Get-Command git -ErrorAction SilentlyContinue

if ($git -and (Test-Path (Join-Path $root '.git'))) {
    Say '      이미 있는 저장소를 갱신합니다...'
    git -C $root fetch origin $Branch --quiet
    git -C $root checkout $Branch --quiet
    git -C $root pull origin $Branch --quiet
} elseif ($git -and -not (Test-Path -LiteralPath $root)) {
    Say '      git clone 으로 받습니다...'
    git clone --branch $Branch --single-branch "https://github.com/$Repo.git" $root --quiet
} elseif ($git -and -not (Get-ChildItem -LiteralPath $root -Force | Select-Object -First 1)) {
    Say '      git clone 으로 받습니다...'
    git clone --branch $Branch --single-branch "https://github.com/$Repo.git" $root --quiet
} else {
    # git 이 없으면 ZIP 으로 받는다. 갱신은 못 하고 통째로 다시 받는 방식이다.
    Say '      git 이 없어 ZIP 으로 받습니다 (나중에 갱신하려면 git 설치를 권합니다).' Yellow
    $zip  = Join-Path $env:TEMP 'alocasia-farm.zip'
    $tmp  = Join-Path $env:TEMP ('alocasia-extract-' + [guid]::NewGuid().ToString('N'))
    Invoke-WebRequest -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    Copy-Item -Path (Join-Path $inner.FullName '*') -Destination $root -Recurse -Force
    Remove-Item -LiteralPath $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $app)) {
    Say "  [중단] $app 이 없습니다. 내려받기가 덜 된 것 같습니다." Red
    return
}
Say "      $app" Green

# ---------------------------------------------------------------- 패키지
Step '4/5' '필요한 패키지 설치 (1~2분)'
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $app 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Say '  [중단] 패키지 설치에 실패했습니다. 인터넷 연결을 확인하세요.' Red
    return
}
Say '      설치 완료' Green

# ---------------------------------------------------------------- 설정·바로가기
Step '5/5' '설정 파일 + 자동 시작'
$envFile = Join-Path $app 'farm_env.bat'
$example = Join-Path $app 'farm_env.example.bat'
$needKey = $false
if (Test-Path -LiteralPath $envFile) {
    Say '      farm_env.bat 이미 있음 - 그대로 둡니다 (키가 지워지지 않습니다).'
} else {
    Copy-Item -LiteralPath $example -Destination $envFile
    $needKey = $true
    Say '      farm_env.bat 을 만들었습니다.'
}

# 포트를 고정해 둔다. 바탕화면 바로가기 주소가 항상 맞도록.
if (-not (Select-String -LiteralPath $envFile -Pattern '^\s*set\s+FARM_PORT' -Quiet)) {
    Add-Content -LiteralPath $envFile -Value ''
    Add-Content -LiteralPath $envFile -Value 'rem 자동 시작 바로가기와 주소를 맞추기 위해 포트를 고정합니다.'
    Add-Content -LiteralPath $envFile -Value 'set FARM_PORT=8123'
}

try {
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) '알로카시아 스마트팜.lnk'))
    $lnk.TargetPath       = Join-Path $app 'start.bat'
    $lnk.Arguments        = '/nobrowser'
    $lnk.WorkingDirectory = $app
    $lnk.WindowStyle      = 7           # 최소화
    $lnk.Description      = '알로카시아 스마트팜 서버 (자동 시작)'
    $lnk.Save()

    $url = $sh.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '알로카시아 온실.url'))
    $url.TargetPath = 'http://localhost:8123'
    $url.Save()
    Say '      자동 시작 등록 + 바탕화면 바로가기 생성 완료' Green
} catch {
    Say "      [경고] 바로가기를 만들지 못했습니다: $($_.Exception.Message)" Yellow
    Say '             start.bat 을 더블클릭하면 서버는 그대로 켜집니다.' Yellow
}

# ---------------------------------------------------------------- 마무리
Write-Host ''
Say '==========================================================' Cyan
Say '   설치가 끝났습니다.' Cyan
Say '==========================================================' Cyan
Write-Host ''

if ($needKey) {
    Say '  [!] 아직 할 일이 하나 있습니다 - 로보플로우 키 넣기.' Yellow
    Say '      안 넣으면 데모 모드로 돕니다 (사진과 무관한 가짜 결과).' Yellow
    Write-Host ''
    Write-Host '      메모장이 열리면:'
    Write-Host '        1) "여기에_개인키" 를 지우고 Private API Key 를 붙여넣기'
    Write-Host '        2) 따옴표는 넣지 마세요 - 배치는 따옴표까지 키 값으로 씁니다'
    Write-Host '        3) 저장(Ctrl+S) 후 닫기'
    Write-Host ''
    Read-Host '      엔터를 누르면 메모장을 엽니다'
    Start-Process notepad $envFile -Wait
    Write-Host ''
}

Write-Host '  다음부터는:'
Write-Host '    - 컴퓨터를 켜면 서버가 알아서 뜹니다 (작업표시줄에 최소화된 창)'
Write-Host '    - 바탕화면의 "알로카시아 온실" 을 더블클릭하면 열립니다'
Write-Host ''
Write-Host '  서버 창 맨 위 두 줄로 키가 제대로 들어갔는지 확인하세요:'
Say '    [키] abcd... (20자)   <- 대시보드의 키 앞자리와 같아야 합니다' DarkGray
Say '    [분석 엔진] workflow · find-old-leaf-and-others' DarkGray
Write-Host ''

if ((Read-Host '  지금 서버를 켤까요? (Y/n)') -notmatch '^[nN]') {
    Start-Process (Join-Path $app 'start.bat') -WorkingDirectory $app
}
