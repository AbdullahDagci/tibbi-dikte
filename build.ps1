# Tam derleme: model (yoksa) -> testler -> PyInstaller -> Inno Setup kurulum dosyası
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path "models\tibbi-tr-v2\model.json")) { & $py tools\setup_model.py }
if (-not (Test-Path "app\licensing\public_key.pem")) { throw "Önce: python tools\keygen.py init" }
& $py tools\make_notice.py | Out-Null
& $py -m pytest -q; if ($LASTEXITCODE) { throw "Testler başarısız" }
# Çalışan bir TibbiDikte.exe dist\ klasörünü kilitleyebilir: ayrı klasöre derle
$out = "dist-build"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
& .\.venv\Scripts\pyinstaller.exe TibbiDikte.spec --noconfirm --log-level WARN --distpath $out
# Inno Setup: makine geneli (Program Files) ya da kullanici kurulumu (winget varsayilani: LOCALAPPDATA)
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 bulunamadi: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DSrcDir=..\$out\TibbiDikte" installer\setup.iss
Get-ChildItem dist\installer
