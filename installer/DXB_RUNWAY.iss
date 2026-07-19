#define MyAppName "DXB RUNWAY"
#define MyAppVersion "1.4.1"
#define MyAppPublisher "DXB RUNWAY"
#define MyAppExeName "DXB RUNWAY.exe"

[Setup]
AppId={{7F39501D-D1C5-4D9E-BEE6-C3CE16AE8DF1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DXB RUNWAY
DefaultGroupName=DXB RUNWAY
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DXB-RUNWAY-Setup
SetupIconFile=..\assets\dxb_runway.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\DXB RUNWAY"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\DXB RUNWAY"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch DXB RUNWAY"; Flags: nowait postinstall skipifsilent
