; Windows installer for sushTun -- built by .github/workflows/release.yml with:
;   iscc /DAppVersion=<x.y.z> tools\installer.iss
;
; Packages the one-dir PyInstaller build (SUSHTUN_ONEDIR=1), not the portable
; one-file exe: the one-file build re-extracts ~170 MB to %TEMP% on every
; launch, which is a fair price for carrying one file around on a USB stick
; and a silly one for something already installed on the disk.
;
; The portable exe stays exactly as it was. This is a second, separate
; artifact; neither replaces the other.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "sushTun"
#define AppPublisher "sushTun"
#define AppUrl "https://github.com/soroushdeimi/sushTun"
#define AppExe "sushtun.exe"

[Setup]
AppId={{8B1F2C1A-6F1C-4C64-9E0B-2B3C5D7A9E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; sushTun changes routes, DNS and the tunnel adapter, so it runs elevated and
; installs for every user of the machine. Per-user would install into a
; directory the elevated process cannot be trusted to run from anyway.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=sushTun-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Lets the in-app updater run this over a running copy: the restart manager
; closes sushTun and /RESTARTAPPLICATIONS brings it back on the new version.
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\sushtun\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// The marker xrayui/paths.py looks for. With it present the app keeps its
// settings, profiles and logs in %PROGRAMDATA%\sushTun instead of next to the
// executable, because Program Files is not writable and must not be.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\.installed'), '', False);
end;

[UninstallDelete]
Type: files; Name: "{app}\.installed"
; Everything the app wrote at runtime, which lives outside {app}. Profiles
; hold server credentials, so leaving them behind after an uninstall would be
; the wrong default.
Type: filesandordirs; Name: "{commonappdata}\{#AppName}"
