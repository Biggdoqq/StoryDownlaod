; ====================================================================
; Inno Setup Script for Hongguo Downloader (红果短剧) VIP All-in-One
; Self-contained Installer with Python Engine + Java Unidbg Signer
; ====================================================================

#define MyAppName "Hongguo Downloader"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "Hongguo VIP Team"
#define MyAppURL "https://github.com/Biggdoqq/StoryDownlaod"
#define MyAppExeName "HongguoDownloader.exe"

[Setup]
AppId={{D97B8329-865A-4B69-A8F2-B3DF30A09172}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL="https://github.com/Biggdoqq/StoryDownlaod/issues"
AppUpdatesURL="https://github.com/Biggdoqq/StoryDownlaod/releases"
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=HongguoDownloader-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Hongguo Downloader Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
Name: "{app}"; Permissions: users-modify
Name: "{app}\engine"; Permissions: users-modify

[Files]
; Main PyInstaller GUI Application and runtime libraries
Source: "dist\HongguoDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Complete Offline Download Engine (Java Unidbg 9099 + Python Engine 8000)
Source: "engine\*"; DestDir: "{app}\engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
