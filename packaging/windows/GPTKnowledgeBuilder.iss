#define MyAppName "GPT Knowledge Builder"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#ifndef MyAppPublisher
#define MyAppPublisher "GPT Knowledge Builder"
#endif
#ifndef MyAppExeName
#define MyAppExeName "GPTKnowledgeBuilder.exe"
#endif
#ifndef MyAppDirName
#define MyAppDirName "GPT Knowledge Builder"
#endif
#ifndef MyAppIconPath
#define MyAppIconPath "..\assets\app.ico"
#endif
#ifndef MyOutputBaseFilename
#define MyOutputBaseFilename "GPTKnowledgeBuilder-" + MyAppVersion + "-Setup"
#endif

[Setup]
AppId={{A40E1B99-EBA0-4B30-9611-F4D3A3E2D0A8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppDirName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#MyAppIconPath}
AppPublisherURL=https://github.com/AboveWireless/gpt-knowledge-builder
AppSupportURL=https://github.com/AboveWireless/gpt-knowledge-builder/issues
AppUpdatesURL=https://github.com/AboveWireless/gpt-knowledge-builder/releases

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\..\dist\GPT Knowledge Builder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
