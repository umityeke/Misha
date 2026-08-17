$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw "This installer is only for Windows."
}

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

$Python = $env:MISHA_PYTHON_BIN
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    throw "Python 3.11-3.13 is required."
}

if (-not (Test-Path "venv\Scripts\python.exe" -PathType Leaf)) {
    & $Python -m venv venv
}
$VenvPython = (Resolve-Path "venv\Scripts\python.exe").Path
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m playwright install chromium

foreach ($CommandName in @("ollama", "whisper-cli")) {
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        Write-Warning "Missing required command: $CommandName"
    }
}
& $VenvPython -m scripts.doctor
