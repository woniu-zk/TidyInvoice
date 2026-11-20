#define AppName "TidyInvoice"
#define AppPublisher "蜗牛"

#ifndef AppVersion
  #define AppVersion "0.0.0.0"
#endif

#ifndef SourceDir
  #error "SourceDir define is required."
#endif

#ifndef OutputDir
  #error "OutputDir define is required."
#endif

#ifndef OutputBaseName
  #define OutputBaseName "TidyInvoice-Setup-unsigned"
#endif

[Setup]
AppId={{B5054758-8A0C-48AA-A135-F4350D026A2B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\整票
DefaultGroupName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=admin
UninstallDisplayIcon={app}\TidyInvoice.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\TidyInvoice.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\TidyInvoice.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TidyInvoice.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
