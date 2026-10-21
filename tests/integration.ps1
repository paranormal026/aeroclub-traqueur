# Test de bout en bout de l'installateur (GitHub Actions, machine jetable windows-latest).
# Faux MSFS 2024 (Steam), faux Community avec un add-on etranger, faux site sur 127.0.0.1.
param([string]$Installateur, [string]$Python = "python")
$ErrorActionPreference = "Stop"
$ok = 0; $ko = 0
function Verif($cond, $texte) {
  if ($cond) { $script:ok++; Write-Host "   OK $texte" } else { $script:ko++; Write-Host "   ECHEC : $texte" }
}
$racine = (Resolve-Path "$PSScriptRoot\..").Path
$travail = Join-Path $env:RUNNER_TEMP "acm_integration"
New-Item -ItemType Directory -Force $travail | Out-Null
$app = Join-Path $env:LOCALAPPDATA "AeroClubManager"
$menu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\AeroClubManager"
$bureau = [Environment]::GetFolderPath("Desktop")

# --- faux MSFS 2024 Steam + Community ---
$msfs = Join-Path $env:APPDATA "Microsoft Flight Simulator 2024"
$paquets = "C:\FauxMSFS\Paquets"
$comm = Join-Path $paquets "Community"
New-Item -ItemType Directory -Force $msfs, $comm | Out-Null
Set-Content -Path "$msfs\UserCfg.opt" -Value "Version 1`r`nInstalledPackagesPath `"$paquets`"`r`n" -Encoding ascii
'<?xml version="1.0" encoding="utf-8"?><SimBase.Document Type="SimConnect" version="1,0"><Descr>SimConnect</Descr><Filename>SimConnect.xml</Filename><Disabled>False</Disabled><Launch.Addon><Name>Autre addon</Name><Disabled>False</Disabled><Path>C:\Autre\autre.exe</Path></Launch.Addon></SimBase.Document>' | Set-Content "$msfs\exe.xml" -Encoding utf8
foreach ($n in "un-autre-addon", "aeroclubmanager-acm400") {
  New-Item -ItemType Directory -Force "$comm\$n" | Out-Null; '{}' | Set-Content "$comm\$n\manifest.json"
}

# --- faux site ---
$journal = Join-Path $travail "site.json"
$site = Start-Process -PassThru -WindowStyle Hidden -FilePath $Python -ArgumentList "-I", "$racine\tests\faux_site.py", "8765", $journal
Start-Sleep 2

Write-Host "1. Installation silencieuse avec le code dans le nom du fichier"
$perso = Join-Path $travail "AeroClubManager-Installation_K7P2QX (1).exe"
Copy-Item $Installateur $perso
$p = Start-Process -PassThru -Wait -FilePath $perso -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$travail\installation.log`""
Verif ($p.ExitCode -eq 0) "code de sortie 0 ($($p.ExitCode))"
Verif (Test-Path "$app\traqueur.exe") "traqueur.exe dans %LOCALAPPDATA%\AeroClubManager"
Verif (Test-Path "$app\unins000.exe") "desinstalleur present"
Verif ((Get-Content "$app\appairage.txt" -Raw).Trim() -eq "K7P2QX") "code K7P2QX lu dans le nom du fichier"
Verif (Test-Path "$menu\AeroClubManager Traqueur.lnk") "raccourci menu Demarrer"
Verif (Test-Path "$bureau\AeroClubManager Traqueur.lnk") "raccourci Bureau"
Verif (-not (Test-Path "$app\config.json")) "aucune cle ecrite par l'installateur"
$reg = Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" | Where-Object { $_.PSChildName -like "*BB80F071*" }
Verif ($null -ne $reg) "inscrit dans Applications (HKCU, sans droits administrateur)"
# v18 : veilleur
$cleRun = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Verif (Test-Path "$app\acm_veilleur.exe") "veilleur acm_veilleur.exe installe"
$run = (Get-ItemProperty $cleRun -ErrorAction SilentlyContinue)."AeroClubManager Veilleur"
Verif ($run -eq "`"$app\acm_veilleur.exe`"") "veilleur inscrit au demarrage de Windows (HKCU Run) : $run"

Write-Host "2. Premier lancement du traqueur : liaison, premier contact, lancement automatique"
$env:ACM_TRAQUEUR_URL_TEST = "http://127.0.0.1:8765"
$env:ACM_VEILLEUR_TEST_RAPIDE = "1"   # veilleur : 3 s d'attente au lieu de 45 s (tests seulement)
$t = Start-Process -PassThru -FilePath "$app\traqueur.exe" -WorkingDirectory $app -RedirectStandardOutput "$travail\traqueur.txt" -RedirectStandardError "$travail\traqueur_err.txt"
$fin = (Get-Date).AddSeconds(90); $ev = @()
while ((Get-Date) -lt $fin) {
  Start-Sleep 2
  if (Test-Path $journal) { try { $ev = Get-Content $journal -Raw | ConvertFrom-Json } catch {} }
  if (@($ev | Where-Object { $_.action -eq "contact" -and $_.etape -eq "pret" }).Count -ge 1) { break }
}
# traqueur.exe (PyInstaller) = 2 processus : le lanceur ET le programme. On ferme les deux, comme la croix de la fenetre.
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
Get-Content "$travail\traqueur.txt" -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { Write-Host "      | $_" }
$ech = @($ev | Where-Object { $_.action -eq "echanger" })
Verif ($ech.Count -eq 1 -and $ech[0].code -eq "K7P2QX") "code echange une seule fois (POST)"
Verif (@($ev | Where-Object { $_.url_contient_code }).Count -eq 0) "le code n'apparait dans aucune adresse"
$cfg = Get-Content "$app\config.json" -Raw | ConvertFrom-Json
Verif ($cfg.api_token -eq ("a" * 40)) "cle enregistree dans config.json"
Verif (-not (Test-Path "$app\appairage.txt")) "appairage.txt efface apres usage"
$c1 = @($ev | Where-Object { $_.action -eq "contact" -and $_.etape -eq "demarrage" })
$c2 = @($ev | Where-Object { $_.action -eq "contact" -and $_.etape -eq "pret" })
Verif ($c1.Count -ge 1 -and $c1[0].cle_ok -and ($c1[0].msfs -contains "steam2024")) "premier contact avec MSFS 2024 Steam detecte"
Verif ($c2.Count -ge 1 -and $c2[0].community) "second contact : dossier Community trouve"
$xml = Get-Content "$msfs\exe.xml" -Raw
Verif ($xml -match [regex]::Escape("$app\traqueur.exe")) "lancement automatique inscrit dans exe.xml"
Verif ($xml -match "Autre addon") "autre add-on du exe.xml conserve"

Write-Host "2b. Veilleur : faux simulateur ouvert sans traqueur -> le veilleur lance le traqueur (une seule fois)"
$fin = (Get-Date).AddSeconds(20)
while (-not (Get-Process acm_veilleur -ErrorAction SilentlyContinue) -and (Get-Date) -lt $fin) { Start-Sleep 1 }
Verif (@(Get-Process acm_veilleur -ErrorAction SilentlyContinue).Count -ge 1) "veilleur lance par le traqueur"
Verif (@(Get-Process traqueur -ErrorAction SilentlyContinue).Count -eq 0) "aucun traqueur ouvert au depart"
Copy-Item "$env:SystemRoot\System32\PING.EXE" "$travail\FlightSimulator2024.exe" -Force
$fauxSim = Start-Process -PassThru -WindowStyle Hidden -FilePath "$travail\FlightSimulator2024.exe" -ArgumentList "-n", "120", "127.0.0.1"
$fin = (Get-Date).AddSeconds(60)
while (-not (Get-Process traqueur -ErrorAction SilentlyContinue) -and (Get-Date) -lt $fin) { Start-Sleep 1 }
Verif (@(Get-Process traqueur -ErrorAction SilentlyContinue).Count -ge 1) "traqueur lance par le veilleur"
Start-Sleep 15
$n = @(Get-Process traqueur -ErrorAction SilentlyContinue).Count
Verif ($n -le 2) "un seul traqueur (lanceur PyInstaller + programme) : $n processus"
$jv = Get-Content "$app\veilleur_journal.txt" -Raw -ErrorAction SilentlyContinue
Write-Host "      | $jv"
Verif ($jv -match "lanc. par le veilleur") "journal du veilleur : traqueur lance"
# second lancement manuel pendant que le premier tourne : il se ferme tout seul (verrou du traqueur)
$t2 = Start-Process -PassThru -FilePath "$app\traqueur.exe" -WorkingDirectory $app
Start-Sleep 12
Verif ($t2.HasExited) "un second traqueur se ferme tout seul (jamais deux traqueurs)"
Stop-Process -Id $fauxSim.Id -Force -ErrorAction SilentlyContinue
Get-Process traqueur -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2

Write-Host "3. Desinstallation : seulement ce que le traqueur a installe"
# le faux site ne sert aucun paquet : on simule ceux que le traqueur aurait installes
foreach ($n in "aeroclubmanager-efb", "aeroclubmanager-persos") {
  New-Item -ItemType Directory -Force "$comm\$n\SimObjects" | Out-Null; '{}' | Set-Content "$comm\$n\manifest.json"
}
$cfg | Add-Member -Force efb_installe @{ $comm = "0.7.9" }
$cfg | Add-Member -Force persos_installe @{ $comm = "1.65.0" }
$cfg | ConvertTo-Json -Depth 5 | Set-Content "$app\config.json" -Encoding utf8
New-Item -ItemType Directory -Force "$app\services_sol\radio" | Out-Null; "x" | Set-Content "$app\services_sol\AcmSol.exe"
"{}" | Set-Content "$app\live_status.json"
Verif (@(Get-Process traqueur -ErrorAction SilentlyContinue).Count -eq 0) "aucun traqueur ouvert avant la desinstallation"
$u = Start-Process -PassThru -Wait -FilePath "$app\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$travail\desinstallation.log`""
$fin = (Get-Date).AddSeconds(60)
while ((Test-Path $app) -and (Get-Date) -lt $fin) { Start-Sleep 1 }
Verif (-not (Test-Path $app)) "dossier AeroClubManager supprime"
Verif (-not (Test-Path "$menu\AeroClubManager Traqueur.lnk") -and -not (Test-Path "$bureau\AeroClubManager Traqueur.lnk")) "raccourcis supprimes"
Verif (-not (Test-Path "$comm\aeroclubmanager-efb") -and -not (Test-Path "$comm\aeroclubmanager-persos")) "paquets installes par le traqueur retires"
Verif (Test-Path "$comm\aeroclubmanager-acm400\manifest.json") "paquet ACM non installe par ce traqueur conserve"
Verif (Test-Path "$comm\un-autre-addon\manifest.json") "add-on etranger conserve"
Verif (Test-Path "$msfs\UserCfg.opt") "UserCfg.opt intact"
$xml = Get-Content "$msfs\exe.xml" -Raw
Verif (($xml -notmatch "AeroClubManager Traqueur") -and ($xml -match "Autre addon")) "exe.xml : seule notre ligne retiree"
$run = (Get-ItemProperty $cleRun -ErrorAction SilentlyContinue)."AeroClubManager Veilleur"
Verif ($null -eq $run) "veilleur retire du demarrage de Windows"
Verif (@(Get-Process acm_veilleur -ErrorAction SilentlyContinue).Count -eq 0) "veilleur arrete"

Write-Host "4. Installateur renomme sans code : pas de code, la fenetre de secours prendra le relais"
$sans = Join-Path $travail "setup.exe"
Copy-Item $Installateur $sans
Start-Process -Wait -FilePath $sans -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" | Out-Null
Verif ((Test-Path "$app\traqueur.exe") -and -not (Test-Path "$app\appairage.txt")) "installe sans appairage.txt"
Start-Process -Wait -FilePath "$app\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" | Out-Null
$fin = (Get-Date).AddSeconds(60)
while ((Test-Path $app) -and (Get-Date) -lt $fin) { Start-Sleep 1 }
Verif (-not (Test-Path $app)) "desinstalle"

Stop-Process -Id $site.Id -Force -ErrorAction SilentlyContinue
Write-Host "`nResultat : $ok OK, $ko echec(s)"
if ($ko -gt 0) { exit 1 }
