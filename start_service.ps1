# Deep Work AI — Service Launcher
# Kills any stale service on port 57321, starts fresh v2 service.
# Called by the Windows Startup shortcut on every login.

$pythonw  = "C:\Users\Vignesh Kumar U\AppData\Local\Programs\Python\Python310\pythonw.exe"
$python   = "C:\Users\Vignesh Kumar U\AppData\Local\Programs\Python\Python310\python.exe"
$service  = "D:\Deepworkai-main\deepworkai\service\deepwork_service.py"
$cwd      = "D:\Deepworkai-main"
$logFile  = "D:\Deepworkai-main\data\service_launcher.log"

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Add-Content $logFile
}

Write-Log "Launcher started"

# Kill any existing process on port 57321
$conns = netstat -ano 2>$null | Select-String ":57321\s"
foreach ($line in $conns) {
    if ($line -match "\s+(\d+)$") {
        $pid = $Matches[1]
        Write-Log "Killing PID $pid on port 57321"
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

# Use pythonw if available, else python
$interp = if (Test-Path $pythonw) { $pythonw } else { $python }
Write-Log "Starting service: $interp $service"

Start-Process $interp -ArgumentList "`"$service`"" -WorkingDirectory $cwd -WindowStyle Hidden
Start-Sleep -Seconds 5

# Verify
try {
    $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 57321)
    $client.Close()
    Write-Log "Service running OK on port 57321"
} catch {
    Write-Log "WARNING: Service did not start — check service.log"
}
