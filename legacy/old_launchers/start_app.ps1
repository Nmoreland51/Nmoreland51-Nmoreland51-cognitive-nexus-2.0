# Cognitive Nexus AI Launcher
Write-Host "🧠 Cognitive Nexus AI - Starting..." -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "🚀 Launching your AI assistant..." -ForegroundColor Green
Write-Host "📱 The app will open in your browser at http://localhost:8501" -ForegroundColor Yellow
Write-Host "⏹️  Press Ctrl+C to stop the server" -ForegroundColor Red
Write-Host ""

# Start the Streamlit app
$process = Start-Process -FilePath "python" -ArgumentList "-m", "streamlit", "run", "cognitive_nexus_ai.py", "--server.port", "8501", "--server.address", "localhost" -PassThru -NoNewWindow

# Wait a moment for the app to start
Start-Sleep -Seconds 10

# Open the browser in Microsoft Edge
Write-Host "🌐 Opening Microsoft Edge..." -ForegroundColor Green
$edgePaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
    "${env:LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe"
)

$edgeFound = $false
foreach ($path in $edgePaths) {
    if (Test-Path $path) {
        Start-Process -FilePath $path -ArgumentList "http://localhost:8501"
        $edgeFound = $true
        break
    }
}

if (-not $edgeFound) {
    Write-Host "⚠️  Microsoft Edge not found, using default browser" -ForegroundColor Yellow
    Start-Process "http://localhost:8501"
}

# Wait for the process
$process.WaitForExit()
