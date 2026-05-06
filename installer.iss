; Inno Setup script for Whisperer Windows installer
; Build with:  iscc installer.iss

#define MyAppName "Whisperer"
#define MyAppVersion "6.0.2"
#define MyAppPublisher "Whisperer"
#define MyAppURL "https://github.com/whisperer/whisperer-windows"
#define MyAppExeName "Whisperer.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=Whisperer-Setup-{#MyAppVersion}
SetupIconFile=assets\whisperer.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "launchonlogin"; Description: "Start Whisperer when Windows starts"; GroupDescription: "Startup"; Flags: unchecked

[Files]
Source: "dist\Whisperer\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Whisperer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Launch on login
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "\"{app}\{#MyAppExeName}\""; Tasks: launchonlogin

; File associations for audio/video transcription
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueData: "\"{app}\{#MyAppExeName}\" \"--file=%1\""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""

; Open With menu entries
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\{#MyAppName}File\shell\open\command"; ValueType: string; ValueData: "\"{app}\{#MyAppExeName}\" \"--file=%1\""
Root: HKCU; Subkey: "Software\Classes\{#MyAppName}File"; ValueType: string; ValueName: ""; ValueData: "Audio/Video File"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
