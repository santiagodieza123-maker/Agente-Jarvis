# Crea la tarea programada "Jarvis" (privilegios máximos) y un acceso directo en el escritorio que la lanza:
# Jarvis abre como administrador sin aviso UAC. Ejecutar una vez desde PowerShell como administrador.
# Quitar: Unregister-ScheduledTask -TaskName Jarvis -Confirm:$false; y borrar el acceso directo.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = (Get-Command python).Source }

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$repo\tools\launch.py`"" -WorkingDirectory $repo
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Jarvis" -Action $action -Principal $principal -Settings $settings -Force | Out-Null

$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Jarvis.lnk"
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = "$env:SystemRoot\System32\schtasks.exe"
$sc.Arguments = "/run /tn Jarvis"
$sc.WindowStyle = 7
$ico = Join-Path $repo "hud\src-tauri\icons\icon.ico"
if (Test-Path $ico) { $sc.IconLocation = $ico }
$sc.Save()
Write-Host "Listo: tarea 'Jarvis' y acceso directo $lnk"
