; Inno Setup 6 — önce: pyinstaller TibbiDikte.spec --noconfirm
#define AppName "Tıbbi Dikte"
#define AppVersion "1.2.0"
#ifndef SrcDir
  #define SrcDir "..\dist\TibbiDikte"
#endif

[Setup]
AppId={{6C1C6C0E-3E2B-4D7A-9C55-7A1E2D0B9F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Tıbbi Dikte
DefaultDirName={autopf}\TibbiDikte
DefaultGroupName={#AppName}
OutputDir=..\dist\installer
OutputBaseFilename=TibbiDikte-Kurulum-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Kurulumda standart son kullanıcı sözleşmesi gösterilir; kişi adı ve bileşen listesi yok (10.11 kullanıcı kararı).
; Açık kaynak bildirimleri lisansları gereği NOTICE.txt olarak program klasörüne kurulur ([Files]).
LicenseFile=lisans_sozlesmesi.txt
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

[Code]
const
  UserDataDir = '{userappdata}\TibbiDikte';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    { Açık uygulama dosyalarını kilitler: kapatılmazsa program klasörü silinmez ve uygulama açık kalır (10.11) }
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM TibbiDikte.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
  end;
  { Lisans, ayarlar ve sözlük %APPDATA%'dadır; yeniden kurulumda kullanılsın diye varsayılan olarak kalır.
    Sessiz kaldırmada soru sorulmaz ve veriler kalır. }
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant(UserDataDir)) then
    if SuppressibleMsgBox('Lisans anahtarı, ayarlar ve sözlük de silinsin mi?' + #13#10#13#10 +
        'Evet: bu bilgisayardaki tüm Tıbbi Dikte verileri (veri toplama ses kayıtları dahil) silinir; yeniden ' +
        'kurulumda ürün anahtarı tekrar girilmelidir.' + #13#10#13#10 +
        'Hayır: yeniden kurulumda lisans, ayarlar ve sözlük olduğu gibi kullanılır.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(ExpandConstant(UserDataDir), True, True, True);
end;
