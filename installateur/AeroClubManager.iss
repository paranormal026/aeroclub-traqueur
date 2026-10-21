; Installateur AeroClubManager (Inno Setup 6, licence gratuite y compris usage commercial)
; Compile par GitHub Actions : ISCC /DVersionTraqueur=17 installateur\AeroClubManager.iss
;
; - Installation PAR UTILISATEUR, sans droits administrateur : %LOCALAPPDATA%\AeroClubManager
; - Raccourcis « AeroClubManager Traqueur » (menu Demarrer + Bureau), desinstalleur, interface en francais
; - Code de liaison : lu dans le NOM du fichier (AeroClubManager-Installation_K7P2QX.exe), ecrit dans appairage.txt ;
;   le traqueur l'echange contre la cle du pilote au premier lancement. Le binaire n'est jamais modifie par le site :
;   une signature numerique (Authenticode) pourra etre ajoutee plus tard sans rien changer (voir #ifdef Signer).
; - Desinstallation : « traqueur.exe --desinstaller » retire uniquement les paquets AeroClubManager que ce traqueur
;   a installes (liste blanche, dossier Community verifie) et sa propre ligne du exe.xml, puis les fichiers listes ici.

#ifndef VersionTraqueur
  #define VersionTraqueur "16"
#endif

[Setup]
AppId={{BB80F071-2FDD-488C-941B-AA6B80D2CB40}
AppName=AeroClubManager Traqueur
AppVersion=1.{#VersionTraqueur}
AppVerName=AeroClubManager Traqueur (version {#VersionTraqueur})
AppPublisher=AeroClubManager
AppPublisherURL=https://aeroclubmanager.fr/
AppSupportURL=https://aeroclubmanager.fr/msfs/installer.php
VersionInfoCompany=AeroClubManager
VersionInfoDescription=Installation du traqueur AeroClubManager
VersionInfoProductName=AeroClubManager
VersionInfoVersion=1.{#VersionTraqueur}.0.0
PrivilegesRequired=lowest
DefaultDirName={localappdata}\AeroClubManager
DisableDirPage=yes
UsePreviousAppDir=no
DefaultGroupName=AeroClubManager
DisableProgramGroupPage=yes
DisableReadyPage=no
DisableWelcomePage=no
OutputDir=..\sortie
OutputBaseFilename=AeroClubManager-Installation
SetupIconFile=acm.ico
UninstallDisplayIcon={app}\acm.ico
UninstallDisplayName=AeroClubManager Traqueur
WizardStyle=modern
WizardImageFile=assistant_grand.bmp,assistant_grand_200.bmp
WizardSmallImageFile=assistant_petit.bmp,assistant_petit_200.bmp
Compression=lzma2/max
SolidCompression=yes
; Un traqueur deja ouvert (meme mutex que traqueur.py) : l'assistant demande de le fermer
AppMutex=AeroClubManagerTraqueur
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no
#ifdef Signer
SignTool=acmsign $f
SignedUninstaller=yes
#endif

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Messages]
fr.WelcomeLabel1=Bienvenue dans l'installation d'AeroClubManager
fr.WelcomeLabel2=Cet assistant installe le traqueur AeroClubManager sur votre ordinateur, dans votre dossier personnel (aucun droit administrateur n'est demandé).%n%nEnsuite, le traqueur s'occupe de tout : il se relie à votre compte, installe la tablette, les personnages et les avions AeroClubManager dans Microsoft Flight Simulator 2024, et se lancera tout seul avec le simulateur.
fr.FinishedHeadingLabel=AeroClubManager est installé
fr.ClickFinish=Cliquez sur Terminer : le traqueur va s'ouvrir et finir l'installation tout seul.

[Files]
Source: "..\dist\traqueur.exe"; DestDir: "{app}"; Flags: ignoreversion
; v18 : veilleur (lance avec Windows, demarre le traqueur s'il voit MSFS ouvert sans lui ; voix Piper incluses dans l'exe)
Source: "..\dist\acm_veilleur.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\voix_veilleur\CREDITS_VOIX.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "acm.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "LISEZ-MOI.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AeroClubManager Traqueur"; Filename: "{app}\traqueur.exe"; WorkingDir: "{app}"; IconFilename: "{app}\acm.ico"; Comment: "Traqueur de vol AeroClubManager"
Name: "{group}\Désinstaller AeroClubManager"; Filename: "{uninstallexe}"; IconFilename: "{app}\acm.ico"
Name: "{userdesktop}\AeroClubManager Traqueur"; Filename: "{app}\traqueur.exe"; WorkingDir: "{app}"; IconFilename: "{app}\acm.ico"; Comment: "Traqueur de vol AeroClubManager"

[Run]
Filename: "{app}\traqueur.exe"; WorkingDir: "{app}"; Description: "Lancer le traqueur AeroClubManager maintenant (recommandé)"; Flags: postinstall nowait skipifsilent

[Registry]
; v18 : veilleur au demarrage de la session Windows (utilisateur courant, sans administrateur) ; seule cette valeur est retiree
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AeroClubManager Veilleur"; ValueData: """{app}\acm_veilleur.exe"""; Flags: uninsdeletevalue

[UninstallRun]
Filename: "{app}\traqueur.exe"; Parameters: "--desinstaller"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "NettoyageAeroClubManager"

[UninstallDelete]
; Uniquement les fichiers crees par le traqueur dans SON dossier (jamais un dossier entier choisi par l'utilisateur)
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\appairage.txt"
Type: files; Name: "{app}\live_status.json"
Type: files; Name: "{app}\traqueur_maj.exe"
Type: files; Name: "{app}\_maj.bat"
Type: filesandordirs; Name: "{app}\services_sol"
; v18 : veilleur, journaux, plans de vol recus du site
Type: files; Name: "{app}\acm_veilleur.exe"
Type: files; Name: "{app}\acm_veilleur.exe.tmp"
Type: files; Name: "{app}\veilleur_journal.txt*"
Type: files; Name: "{app}\traqueur_journal.txt*"
Type: filesandordirs; Name: "{app}\plans_de_vol"
Type: dirifempty; Name: "{app}"

[Code]
const
  AlphabetCode = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

var
  CodeLiaison: String;

function EstAlnum(C: Char): Boolean;
begin
  Result := ((C >= 'A') and (C <= 'Z')) or ((C >= 'a') and (C <= 'z')) or ((C >= '0') and (C <= '9'));
end;

function CodeValide(S: String): Boolean;
var
  I: Integer;
begin
  Result := Length(S) = 6;
  if Result then
    for I := 1 to 6 do
      if Pos(S[I], AlphabetCode) = 0 then
        Result := False;
end;

{ Code a 6 caracteres apres « _ » ou « - » dans le nom du fichier, ex. AeroClubManager-Installation_K7P2QX (1).exe }
function CodeDepuisNom(Nom: String): String;
var
  I: Integer;
  Candidat: String;
  Suivant: Boolean;
begin
  Result := '';
  Nom := ExtractFileName(Nom);
  for I := 1 to Length(Nom) - 6 do
    if (Nom[I] = '_') or (Nom[I] = '-') then
    begin
      Candidat := Uppercase(Copy(Nom, I + 1, 6));
      Suivant := True;
      if I + 7 <= Length(Nom) then
        Suivant := not EstAlnum(Nom[I + 7]);
      if Suivant and CodeValide(Candidat) then
      begin
        Result := Candidat;
        Exit;
      end;
    end;
end;

function InitializeSetup(): Boolean;
begin
  { /CODE=XXXXXX en ligne de commande (tests, ou plus tard un lien de telechargement) a priorite sur le nom du fichier }
  CodeLiaison := Uppercase(ExpandConstant('{param:CODE|}'));
  if not CodeValide(CodeLiaison) then
    CodeLiaison := CodeDepuisNom(ExpandConstant('{srcexe}'));
  Result := True;
end;

{ v18 : un veilleur deja lance garde acm_veilleur.exe ouvert : on l'arrete avant de copier les fichiers (le traqueur le relance) }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM acm_veilleur.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (CodeLiaison <> '') then
    SaveStringToFile(ExpandConstant('{app}\appairage.txt'), CodeLiaison, False);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if CodeLiaison <> '' then
      WizardForm.FinishedLabel.Caption :=
        'Votre traqueur sera relié automatiquement à votre compte AeroClubManager (code ' + CodeLiaison + ').' + #13#10 + #13#10 +
        'Laissez la fenêtre du traqueur ouverte : il installe la tablette, les personnages et les avions dans le simulateur, ' +
        'puis la page du site affichera « Votre traqueur est connecté ».'
    else
      WizardForm.FinishedLabel.Caption :=
        'Au premier lancement, le traqueur vous demandera votre code de liaison à 6 caractères : ' +
        'il est affiché sur la page « Installer AeroClubManager » du site.';
  end;
end;
