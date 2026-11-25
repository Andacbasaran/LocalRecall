; LocalRecall v1.0.0 — Inno Setup 6 Windows x64 Installer & Clean-Uninstall Script
;
; Packages the PyInstaller --onedir bundle (dist\LocalRecall\*) into a modern,
; per-user Windows installer with bilingual TR/EN support and an optional clean
; uninstall prompt for the local SQLite vault & WebP screenshot archive.
;
; Build commands:
;   python scripts/build_exe.py --version 1.0.0
;   iscc /DMyAppVersion=1.0.0 packaging\inno\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#if Pos("-", MyAppVersion) > 0
  #define MyAppNumericVersion Copy(MyAppVersion, 1, Pos("-", MyAppVersion) - 1)
#else
  #define MyAppNumericVersion MyAppVersion
#endif

#define MyAppName "LocalRecall"
#define MyAppPublisher "Andac Basaran"
#define MyAppURL "https://localrecall.andacbasaran.com"
#define MyAppRepoURL "https://github.com/Andacbasaran/LocalRecall"
#define MyAppExeName "LocalRecall.exe"

[Setup]
AppId={{B4D8E219-4F3C-4A8E-9C12-7E5A1F63D804}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppRepoURL}/issues
AppUpdatesURL={#MyAppRepoURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=LocalRecall-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=yes
VersionInfoVersion={#MyAppNumericVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — 100% Offline Smart Screen Memory Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[CustomMessages]
english.AutoStartTask=Start LocalRecall minimized in the system tray at Windows login
turkish.AutoStartTask=Windows açılışında LocalRecall'ı sistem tepsisinde gizli başlat
english.UninstallVaultPrompt=Do you also want to permanently delete your local LocalRecall screen memory vault (SQLite database, WebP screenshots, and settings in %LOCALAPPDATA%\LocalRecall)?%n%n(Choose "No" to keep your searchable history if you plan to reinstall later.)
turkish.UninstallVaultPrompt=Yerel LocalRecall ekran hafızası kasanız (SQLite veritabanı, WebP ekran görüntüleri ve %LOCALAPPDATA%\LocalRecall içindeki ayarlar) da kalıcı olarak silinsin mi?%n%n(İpucu: İleride tekrar kurduğunuzda geçmişinizi korumak için "Hayır" seçebilirsiniz.)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStartTask}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\LocalRecall\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LocalRecall"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "LocalRecall"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LocalDataDir: String;
  PromptText: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    LocalDataDir := ExpandConstant('{localappdata}\LocalRecall');
    if (not UninstallSilent) and DirExists(LocalDataDir) then
    begin
      PromptText := ExpandConstant('{cm:UninstallVaultPrompt}');
      if MsgBox(PromptText, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(LocalDataDir, True, True, True);
      end;
    end;
  end;
end;
