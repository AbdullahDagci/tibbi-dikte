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
if ($LASTEXITCODE) { throw "Kurulum dosyası derlenemedi" }
# Müşteriye giden paket (dist\demo): kurulum dosyası + OKUBENI.txt; eski sürümün kurulum dosyası kalmaz
$ver = (Select-String -Path installer\setup.iss -Pattern '#define AppVersion "(.+)"').Matches[0].Groups[1].Value
$demo = "dist\demo"
New-Item -ItemType Directory -Force $demo | Out-Null
Remove-Item "$demo\TibbiDikte-Demo-Kurulum-*.exe" -ErrorAction SilentlyContinue
Copy-Item "dist\installer\TibbiDikte-Kurulum-$ver.exe" "$demo\TibbiDikte-Demo-Kurulum-$ver.exe"
(Get-Content installer\OKUBENI.txt -Raw -Encoding UTF8).Replace("{SURUM}", $ver) | Set-Content "$demo\OKUBENI.txt" -Encoding UTF8
Get-ChildItem dist\installer, $demo
