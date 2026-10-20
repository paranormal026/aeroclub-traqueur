# Captures d'ecran de l'assistant d'installation (GitHub Actions, machine jetable).
param([string]$Installateur, [string]$Sortie)
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
New-Item -ItemType Directory -Force $Sortie | Out-Null
$ws = New-Object -ComObject WScript.Shell
function Capture($nom) {
  Start-Sleep -Milliseconds 1500
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $img = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
  $g = [System.Drawing.Graphics]::FromImage($img); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); $g.Dispose()
  $img.Save((Join-Path $Sortie "$nom.png"), [System.Drawing.Imaging.ImageFormat]::Png); $img.Dispose()
}
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
$env:ACM_TRAQUEUR_URL_TEST = "http://127.0.0.1:9"   # adresse sans serveur : le traqueur ne joint aucun site (jamais le vrai) et ouvre la fenetre de secours
$perso = Join-Path $env:RUNNER_TEMP "AeroClubManager-Installation_K7P2QX.exe"
Copy-Item $Installateur $perso -Force
$p = Start-Process -PassThru -FilePath $perso
Start-Sleep 6
[void]$ws.AppActivate($p.Id); Capture "1_accueil"
[void]$ws.AppActivate($p.Id); $ws.SendKeys("{ENTER}"); Capture "2_pret"
[void]$ws.AppActivate($p.Id); $ws.SendKeys("{ENTER}"); Start-Sleep 8; Capture "3_termine"
# Terminer avec « Lancer le traqueur » coche : le traqueur s'ouvre
[void]$ws.AppActivate($p.Id); $ws.SendKeys("{ENTER}")
Start-Sleep 25
Capture "4_traqueur_premier_lancement"
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
$app = Join-Path $env:LOCALAPPDATA "AeroClubManager"
if (Test-Path "$app\unins000.exe") {
  $u = Start-Process -PassThru -FilePath "$app\unins000.exe"
  Start-Sleep 4; Capture "5_desinstaller_question"
  $ws.SendKeys("+{TAB}"); Start-Sleep 1; $ws.SendKeys("{ENTER}")   # « Oui »
  Start-Sleep 10; Capture "6_desinstalle"
  $ws.SendKeys("{ENTER}")
}
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
Get-ChildItem $Sortie
