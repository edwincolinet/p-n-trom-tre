; Inno Setup — Pénétromètre Silvavenir
; Buildé par GitHub Actions (.github/workflows/build.yml).
; Usage local :
;   iscc /DMyAppVersion="3.6.0" build\installer.iss
;
; La version est injectée via /DMyAppVersion par le workflow CI ;
; la valeur ci-dessous sert uniquement de fallback local.
#ifndef MyAppVersion
  #define MyAppVersion "3.6.0"
#endif

#define MyAppName      "Pénétromètre"
#define MyAppExe       "Penetrometre.exe"
#define MyAppPublisher "Silvavenir"
#define MyAppURL       "https://www.silvavenir.fr"

[Setup]
AppId={{F3A2C1D4-7E8B-4F5A-9C2D-1B3E6F7A8D9C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Installation par utilisateur (sans droits admin / UAC)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Penetrometre
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist\installer
OutputBaseFilename=Penetrometre-{#MyAppVersion}-Setup
SetupIconFile=build\icons\Icone.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExe}
; Empêche l'ouverture de plusieurs instances de l'installeur
AppMutex=PenetrometerSetupMutex

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Icônes supplémentaires :"

[Files]
Source: "dist\Penetrometre\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
