; Inno Setup 6 — önce: pyinstaller TibbiDikte.spec --noconfirm
#define AppName "Tıbbi Dikte"
#define AppVersion "1.1.0"
#ifndef SrcDir
  #define SrcDir "..\dist\TibbiDikte"
#endif

[Setup]
AppId={{6C1C6C0E-3E2B-4D7A-9C55-7A1E2D0B9F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Abdullah DAĞCI
DefaultDirName={autopf}\TibbiDikte
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=TibbiDikte-Kurulum-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\NOTICE.txt
SetupIconFile=..\app\icons\logo.ico
; Güncellemeden sonra Windows eski simgeyi önbellekten göstermesin
ChangesAssociations=yes
UninstallDisplayIcon={app}\TibbiDikte.exe

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "autostart"; Description: "Windows açılışında başlat"; GroupDescription: "Ek seçenekler:"
Name: "desktopicon"; Description: "Masaüstü kısayolu oluştur"; GroupDescription: "Ek seçenekler:"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; Kurulum yalnızca kendi eğittiğimiz modeli taşır (06.11 kullanıcı kararı; v2 artık paketlenmez)
Source: "..\models\tibbi-tr-v3-tam-w07\*"; DestDir: "{app}\models\tibbi-tr-v3-tam-w07"; Excludes: ".cache\*,config.json,LICENSE"; Flags: recursesubdirs ignoreversion
Source: "..\NOTICE.txt"; DestDir: "{app}"

[InstallDelete]
Type: files; Name: "{app}\_internal\app\medical\radiology_fuzzy_tr.txt"
; 1.1 öncesi model klasör adı (model listesinde çift görünmesin)
Type: filesandordirs; Name: "{app}\models\mihu-turkish-v2"
; 1.1 kurulumlarındaki v2 modeli (artık paketlenmiyor; seçili kalan kullanıcı varsayılana geçer)
Type: filesandordirs; Name: "{app}\models\tibbi-tr-v2"
; Önceki varsayılan model (06.11: yerini tibbi-tr-v3-tam-w07 aldı; seçili kalan kullanıcı varsayılana geçer)
Type: filesandordirs; Name: "{app}\models\tibbi-tr-v3-tam"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\TibbiDikte.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\TibbiDikte.exe"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\TibbiDikte.exe"; Tasks: autostart

[Run]
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden runasoriginaluser skipifdoesntexist
Filename: "{app}\TibbiDikte.exe"; Description: "{#AppName} uygulamasını başlat"; Flags: nowait postinstall skipifsilent
