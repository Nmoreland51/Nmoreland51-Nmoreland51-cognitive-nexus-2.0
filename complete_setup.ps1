# Cognitive Nexus AI - Complete Setup Script
# This script will install Python, dependencies, and launch the app

Write-Host "🧠 Cognitive Nexus AI - Complete Setup" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# Function to check if Python is installed
function Test-Python {
    try {
        $pythonVersion = python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
            return $true
        }
    }
    catch {
        Write-Host "❌ Python not found" -ForegroundColor Red
        return $false
    }
    return $false
}

# Function to install Python via winget
function Install-Python {
    Write-Host "📦 Installing Python via winget..." -ForegroundColor Yellow
    
    try {
        # Try to install Python using winget
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        Write-Host "✅ Python installation initiated" -ForegroundColor Green
        Write-Host "⏳ Please wait for installation to complete..." -ForegroundColor Yellow
        
        # Wait a bit for installation
        Start-Sleep -Seconds 10
        
        # Refresh PATH
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
        
        return $true
    }
    catch {
        Write-Host "❌ Failed to install Python via winget" -ForegroundColor Red
        return $false
    }
}

# Function to install dependencies
function Install-Dependencies {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
    
    try {
        # Upgrade pip first
        python -m pip install --upgrade pip
        
        # Install requirements
        pip install -r requirements.txt
        
        Write-Host "✅ Dependencies installed successfully" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "❌ Failed to install dependencies: $_" -ForegroundColor Red
        return $false
    }
}

# Function to fix code issues
function Fix-CodeIssues {
    Write-Host "🔧 Fixing critical code issues..." -ForegroundColor Yellow
    
    $codeFile = "cognitive_nexus_ai.py"
    $content = Get-Content $codeFile -Raw
    
    # Fix 1: Add missing return statement in _detect_best_provider
    $content = $content -replace '(\s+else:\s*)(\s*return "fallback")', '$1$2'
    if ($content -notmatch 'return "fallback"') {
        $content = $content -replace '(\s+else:\s*)(\s*$)', '$1        return "fallback"'
    }
    
    # Fix 2: Add missing return statement in should_use_web_search
    $content = $content -replace '(\s+break\s*)(\s*return True, search_query)', '$1$2'
    if ($content -notmatch 'return True, search_query') {
        $content = $content -replace '(\s+break\s*)(\s*$)', '$1            return True, search_query'
    }
    
    Set-Content $codeFile $content
    Write-Host "✅ Code issues fixed" -ForegroundColor Green
}

# Function to launch Streamlit
function Launch-Streamlit {
    Write-Host "🚀 Launching Cognitive Nexus AI..." -ForegroundColor Green
    Write-Host "The app will open in your browser at http://localhost:8501" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
    Write-Host ""
    
    try {
        streamlit run cognitive_nexus_ai.py
    }
    catch {
        Write-Host "❌ Failed to launch Streamlit: $_" -ForegroundColor Red
        Write-Host "Try running manually: streamlit run cognitive_nexus_ai.py" -ForegroundColor Yellow
    }
}

# Main execution
Write-Host "🔍 Checking Python installation..." -ForegroundColor Yellow

if (-not (Test-Python)) {
    Write-Host "📥 Python not found. Installing..." -ForegroundColor Yellow
    
    if (-not (Install-Python)) {
        Write-Host "❌ Could not install Python automatically" -ForegroundColor Red
        Write-Host "Please install Python manually from:" -ForegroundColor Yellow
        Write-Host "1. Microsoft Store: https://aka.ms/python-store" -ForegroundColor Cyan
        Write-Host "2. Or download from: https://www.python.org/downloads/" -ForegroundColor Cyan
        Write-Host "Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
        Read-Host "Press Enter after installing Python"
        
        if (-not (Test-Python)) {
            Write-Host "❌ Python still not found. Please restart your terminal and try again." -ForegroundColor Red
            exit 1
        }
    }
}

Write-Host ""
Write-Host "🔧 Fixing code issues..." -ForegroundColor Yellow
Fix-CodeIssues

Write-Host ""
Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
if (-not (Install-Dependencies)) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "🚀 Ready to launch!" -ForegroundColor Green
Write-Host ""

# Launch the application
Launch-Streamlit
