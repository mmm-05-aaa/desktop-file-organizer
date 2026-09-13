#ifndef AppVersion
  #define AppVersion "0.1.0-alpha"
#endif
#ifndef BuildDir
  #define BuildDir "."
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{B78F58E8-4C20-4D1A-86E2-6D82F9E3D7F0}
AppName=Desktop Organizer
AppVersion={#AppVersion}
AppPublisher=mmm-05-aaa
AppPublisherURL=https://github.com/mmm-05-aaa/desktop-file-organizer
DefaultDirName={autopf}\Desktop Organizer
DefaultGroupName=Desktop Organizer
OutputDir={#OutputDir}
OutputBaseFilename=DesktopOrganizer-{#AppVersion}-Windows-x64-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayName=Desktop Organizer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#BuildDir}\desktop-file-organizer.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Desktop Organizer"; Filename: "{app}\desktop-file-organizer.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Desktop Organizer"; Filename: "{app}\desktop-file-organizer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\desktop-file-organizer.exe"; Description: "Launch Desktop Organizer"; Flags: nowait postinstall skipifsilent
