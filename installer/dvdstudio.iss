; Installer for DVD Stüdyo. Built by scripts/package.py; needs Inno Setup 6.
; Per-user install: no administrator rights, no system-wide changes.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\DVDStudio"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{FEF63211-EFC6-5D09-9FF8-EC39DCDC5555}
AppName=DVD Stüdyo
AppVersion={#AppVersion}
AppPublisher=fusion-enjoyer
AppPublisherURL=https://github.com/fusion-enjoyer/dvd
DefaultDirName={localappdata}\Programs\DVD Studyo
DefaultGroupName=DVD Stüdyo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=DVDStudyo-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#SourceDir}\licenses\DVD-Studyo-GPL-3.0.txt
UninstallDisplayIcon={app}\DVD Studyo.exe
UninstallDisplayName=DVD Stüdyo

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\DVD Stüdyo"; Filename: "{app}\DVD Studyo.exe"
Name: "{userdesktop}\DVD Stüdyo"; Filename: "{app}\DVD Studyo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DVD Studyo.exe"; Description: "{cm:LaunchProgram,DVD Stüdyo}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
