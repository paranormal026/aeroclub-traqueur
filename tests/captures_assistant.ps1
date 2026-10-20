# Captures d'ecran de l'assistant d'installation (GitHub Actions). Installe dans un dossier de test puis desinstalle.
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
$perso = Join-Path $env:RUNNER_TEMP "AeroClubManager-Installation_K7P2QX.exe"
Copy-Item $Installateur $perso
$p = Start-Process -PassThru -FilePath $perso
Start-Sleep 6
$titre = "Installation"
[void]$ws.AppActivate($p.Id); Capture "1_accueil"
[void]$ws.AppActivate($p.Id); $ws.SendKeys("{ENTER}"); Capture "2_pret"
[void]$ws.AppActivate($p.Id); $ws.SendKeys("{ENTER}"); Start-Sleep 8; Capture "3_termine"
# decocher « Lancer le traqueur » puis Terminer
[void]$ws.AppActivate($p.Id); $ws.SendKeys(" "); Start-Sleep 1; $ws.SendKeys("{ENTER}")
Start-Sleep 3
$app = Join-Path $env:LOCALAPPDATA "AeroClubManager"
if (Test-Path "$app\unins000.exe") {
  $u = Start-Process -PassThru -FilePath "$app\unins000.exe"
  Start-Sleep 4; [void]$ws.AppActivate($u.Id); Capture "4_desinstaller_question"
  $ws.SendKeys("{ENTER}")   # Oui
  Start-Sleep 8; Capture "5_desinstalle"
  $ws.SendKeys("{ENTER}")
}
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
Get-ChildItem $Sortie
