# v25 (GitHub Actions) : traqueur.exe et acm_veilleur.exe construits se decompressent dans %LOCALAPPDATA%\AeroClubManager\runtime
# (cree s'il manque), jamais dans TEMP ; un dossier de decompression en service n'est jamais retire par le nettoyage.
param([string]$Dist = "dist", [string]$Python = "python")
$ErrorActionPreference = "Stop"
$ok = 0; $ko = 0
function Verif($cond, $texte) {
  if ($cond) { $script:ok++; Write-Host "   OK $texte" } else { $script:ko++; Write-Host "   ECHEC : $texte" }
}
$racine = (Resolve-Path "$PSScriptRoot\..").Path
$dist = (Resolve-Path $Dist).Path
$ancienLAD = $env:LOCALAPPDATA
$lad = Join-Path $env:RUNNER_TEMP "lad_v25_$(Get-Random)"
$runtime = Join-Path $lad "AeroClubManager\runtime"
$tempAvant = @(Get-ChildItem $env:TEMP -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue).FullName
try {
  $env:LOCALAPPDATA = $lad   # dossier neuf : le lanceur PyInstaller doit creer AeroClubManager\runtime lui-meme

  Write-Host "1. traqueur.exe --diag-runtime"
  $sortie = & "$dist\traqueur.exe" --diag-runtime
  Write-Host "      | $sortie"
  $d = ($sortie | Select-Object -Last 1) | ConvertFrom-Json
  Verif $d.frozen "exe compile"
  Verif ($d.meipass -and $d.meipass.StartsWith("$runtime\_MEI", [StringComparison]::OrdinalIgnoreCase)) "decompresse dans $runtime : $($d.meipass)"
  Verif ($d.sous_localappdata -and -not $d.sous_temp) "sous LOCALAPPDATA, pas sous TEMP"
  Verif ($d.certificats -eq "$lad\AeroClubManager\certificats\cacert.pem" -and $d.origine_certificats -eq "copie") "certificats : $($d.certificats) ($($d.origine_certificats))"
  Start-Sleep 2
  Verif (@(Get-ChildItem $runtime -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue).Count -eq 0) "dossier de decompression retire a la fermeture"

  Write-Host "2. acm_veilleur.exe --diag-runtime=..."
  $f = Join-Path $lad "diag_veilleur.json"
  Start-Process -Wait -FilePath "$dist\acm_veilleur.exe" -ArgumentList "--diag-runtime=`"$f`""
  $v = Get-Content $f -Raw | ConvertFrom-Json
  Verif ($v.meipass -and $v.meipass.StartsWith("$runtime\_MEI", [StringComparison]::OrdinalIgnoreCase) -and -not $v.sous_temp) "veilleur decompresse dans $runtime : $($v.meipass)"

  Write-Host "3. veilleur en service : son dossier ne peut pas etre renomme ni retire"
  $p = Start-Process -PassThru -FilePath "$dist\acm_veilleur.exe"
  Start-Sleep 6
  $mei = @(Get-ChildItem $runtime -Directory -Filter "_MEI*")
  Verif ($mei.Count -eq 1) "un dossier de decompression : $($mei.FullName -join ', ')"
  # (Windows accepte de renommer un dossier dont les DLL sont chargees : la protection est le PID du lanceur dans le nom)
  Verif ($mei[0].Name -like ("_MEI{0:x8}*" -f $p.Id)) "nom du dossier = PID du lanceur ($($p.Id)) : $($mei[0].Name)"
  $retires = & $Python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import acm_robustesse as R; print(R.nettoyer_runtime(sys.argv[2], age_min_s=0))" $racine $runtime
  Verif ($retires -eq "[]" -and (Test-Path "$($mei[0].FullName)\python312.dll")) "nettoyer_runtime laisse le dossier du veilleur en service : $retires"
  # arret du veilleur lance par CE test (lanceur PyInstaller + programme), par PID
  $enfants = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($p.Id)" | ForEach-Object { $_.ProcessId })
  foreach ($id in @($p.Id) + $enfants) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
  Start-Sleep 2
  $retires = & $Python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import acm_robustesse as R; print(R.nettoyer_runtime(sys.argv[2], age_min_s=0))" $racine $runtime
  Verif (-not (Test-Path $mei[0].FullName)) "reste du veilleur arrete brutalement retire : $retires"

  $tempApres = @(Get-ChildItem $env:TEMP -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue).FullName | Where-Object { $tempAvant -notcontains $_ }
  Verif (@($tempApres).Count -eq 0) "aucun _MEI cree dans TEMP : $($tempApres -join ', ')"
} finally {
  $env:LOCALAPPDATA = $ancienLAD
  Remove-Item -Recurse -Force $lad -ErrorAction SilentlyContinue
}
Write-Host "`nResultat : $ok OK, $ko echec(s)"
if ($ko -gt 0) { exit 1 }
