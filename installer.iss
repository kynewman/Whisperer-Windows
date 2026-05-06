; Inno Setup script for Whisperer Windows installer
; Build with:  iscc installer.iss

#define MyAppName "Whisperer"
#define MyAppVersion "6.0.8"
#define MyAppPublisher "Whisperer"
#define MyAppURL "https://github.com/kynewman/Whisperer-Windows"
#define MyAppExeName "Whisperer.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no
AppMutex=Local\WhispererWindowsUI,Local\WhispererWindowsEngine
SetupMutex=WhispererWindowsInstaller
OutputDir=dist
OutputBaseFilename=Whisperer-Setup-{#MyAppVersion}
SetupIconFile=assets\whisperer.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
ChangesAssociations=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "launchonlogin"; Description: "Start Whisperer when Windows starts"; GroupDescription: "Startup"; Flags: unchecked

[Files]
Source: "dist\Whisperer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "scripts\Launch Whisperer Diagnostic Mode.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "scripts\Collect Whisperer Diagnostics.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\Whisperer\logs"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName} Diagnostic Mode"; Filename: "{app}\Launch Whisperer Diagnostic Mode.cmd"; WorkingDir: "{app}"
Name: "{autoprograms}\Collect {#MyAppName} Diagnostics"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Collect Whisperer Diagnostics.ps1"""; WorkingDir: "{app}"
Name: "{autoprograms}\{#MyAppName} Logs"; Filename: "{localappdata}\Whisperer\logs"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Launch on login
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: launchonlogin; Flags: uninsdeletevalue

; File associations for audio/video transcription
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""--file=%1"""
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
Root: HKCU; Subkey: "Software\Classes\.mov\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\.webm\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppName}File"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\{#MyAppName}File\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""--file=%1"""
Root: HKCU; Subkey: "Software\Classes\{#MyAppName}File"; ValueType: string; ValueName: ""; ValueData: "Audio/Video File"

[InstallDelete]
; Clean up files removed from newer lightweight bundles so upgrades do not
; leave stale payloads or old hashed frontend assets behind.
Type: files; Name: "{app}\_internal\PyQt6\Qt6\resources\*.debug.pak"
Type: files; Name: "{app}\_internal\PyQt6\Qt6\resources\*.debug.bin"
Type: files; Name: "{app}\_internal\PyQt6\Qt6\resources\qtwebengine_devtools_resources*.pak"
Type: filesandordirs; Name: "{app}\_internal\PyQt6\Qt6\qml"
Type: files; Name: "{app}\_internal\whisperer-app\dist\assets\*.js"
Type: files; Name: "{app}\_internal\whisperer-app\dist\assets\*.css"
Type: filesandordirs; Name: "{app}\_internal\torch"
Type: filesandordirs; Name: "{app}\_internal\torchaudio"
Type: filesandordirs; Name: "{app}\_internal\torchvision"
Type: filesandordirs; Name: "{app}\_internal\transformers"
Type: filesandordirs; Name: "{app}\_internal\nemo"
Type: filesandordirs; Name: "{app}\_internal\nemo_toolkit"
Type: filesandordirs; Name: "{app}\_internal\faster_whisper"
Type: filesandordirs; Name: "{app}\_internal\ctranslate2"
Type: filesandordirs; Name: "{app}\_internal\huggingface_hub"
Type: filesandordirs; Name: "{app}\_internal\safetensors"
Type: filesandordirs; Name: "{app}\_internal\tokenizers"

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
procedure CopyInstallerLog();
var
  LogSource: string;
  LogTarget: string;
begin
  LogSource := ExpandConstant('{log}');
  if LogSource = '' then
    exit;

  LogTarget := ExpandConstant('{localappdata}\Whisperer\logs\installer-{#MyAppVersion}.log');
  ForceDirectories(ExtractFileDir(LogTarget));
  CopyFile(LogSource, LogTarget, False);
  CopyFile(LogSource, ExpandConstant('{localappdata}\Whisperer\logs\installer-latest.log'), False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    CopyInstallerLog();
end;

procedure DeinitializeSetup();
begin
  CopyInstallerLog();
end;
