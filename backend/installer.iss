; Inno Setup script for the TriFlow desktop app.
;
; Not run directly — use scripts/build_desktop.py, which builds the frontend,
; runs PyInstaller, then invokes this with /DMyAppVersion=<version.py's VERSION>
; so the installer filename/metadata always matches the app that was built.
; (PyInstaller doesn't stamp a Windows file-version resource, so that value
; can't be read back off TriFlow.exe — it has to be passed in.)
;
; AppId is a fixed GUID so future versions upgrade in place instead of
; installing side-by-side — do not change it once a release ships.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppName "TriFlow"
#define MyAppPublisher "TriFlow"

[Setup]
AppId={{6E7B7A0B-6E7B-4B4B-9D0F-8E7D8A1A9C11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=TriFlow-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install by default — no admin prompt, matches "just an app" feel.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TriFlow.exe
SetupIconFile=assets\triflow.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\TriFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\TriFlow.exe"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\TriFlow.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TriFlow.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

; App data (profile/plan/tokens under %APPDATA%\TriFlow) deliberately survives
; uninstall — re-installing or upgrading must not lose the athlete's plan.
