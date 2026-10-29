; Windows installer, built by the Release workflow after PyInstaller:
;   iscc /DAppVersion=0.2.0 packaging\windows\jobportal.iss
; One click: no questions and no admin rights. It installs dist\JobPortal for the current user, adds Start menu and
; desktop shortcuts, and opens JobPortal when it's done. Uninstall it from Settings, Apps.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Keep this AppId forever: it's how a new version finds and replaces the old one.
AppId={{2C411ECF-64CC-4BF2-ABC8-F4454BC14F98}
AppName=JobPortal
AppVersion={#AppVersion}
AppPublisher=JobPortal contributors
AppPublisherURL=https://github.com/mattsaund/JobPortal
DefaultDirName={autopf}\JobPortal
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\out
OutputBaseFilename=JobPortal-Windows-Setup
SetupIconFile=..\icons\jobportal.ico
UninstallDisplayIcon={app}\JobPortal.exe
UninstallDisplayName=JobPortal
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[InstallDelete]
; Files from the previous version's bundle that this one doesn't ship anymore.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\JobPortal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\JobPortal"; Filename: "{app}\JobPortal.exe"
Name: "{autodesktop}\JobPortal"; Filename: "{app}\JobPortal.exe"

[Run]
Filename: "{app}\JobPortal.exe"; Flags: nowait skipifsilent
