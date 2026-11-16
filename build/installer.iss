; Inno Setup — Pénétromètre Silvavenir (Edwin Colinet)
; Buildé par GitHub Actions (.github/workflows/build.yml).
; Usage local :
;   iscc /DMyAppVersion="3.7.0" build\installer.iss
;
; La version est injectée via /DMyAppVersion par le workflow CI ;
; la valeur ci-dessous sert uniquement de fallback local.
#ifndef MyAppVersion
  #define MyAppVersion "3.7.0"
#endif

#define MyAppName      "Pénétromètre Silvavenir"
#define MyAppExe       "Penetrometre.exe"
#define MyAppPublisher "Edwin Colinet"
#define MyAppURL       "https://github.com/edwincolinet/p-n-trom-tre"

[Setup]
AppId={{F3A2C1D4-7E8B-4F5A-9C2D-1B3E6F7A8D9C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
; Tous les chemins relatifs ci-dessous (SetupIconFile,
; OutputDir, [Files] Source) sont résolus depuis SourceDir — sans cette
; ligne, le défaut est le dossier du script (build\), pas la racine du
; dépôt où tournent PyInstaller et ce workflow.
SourceDir=..
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
UninstallDisplayIcon={app}\Penetrometre.ico
; Empêche l'ouverture de plusieurs instances de l'installeur
AppMutex=PenetrometerSetupMutex

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le Bureau"; GroupDescription: "Icônes supplémentaires :"

[Files]
Source: "dist\Penetrometre\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Icône multi-tailles (16 → 256 px) livrée À PART : les raccourcis la
; référencent directement (IconFilename) au lieu de dépendre de l'icône
; embarquée dans l'exe — et un nouveau chemin évite le cache d'icônes Windows
; qui conservait l'ancienne (pixélisée) après une réinstallation.
Source: "build\icons\Icone.ico"; DestDir: "{app}"; DestName: "Penetrometre.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\Penetrometre.ico"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\Penetrometre.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
