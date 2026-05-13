$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

function Test-VenvPython {
    if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
        return $false
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & ".\.venv\Scripts\python.exe" -c "import sys" > $null 2> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

if ((Test-Path ".venv") -and -not (Test-VenvPython)) {
    Write-Host "Moi truong Python cu bi hong. Dang tao lai .venv..."
    Remove-Item -LiteralPath ".\.venv" -Recurse -Force
}

if (-not (Test-Path ".venv")) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv .venv
    } else {
        python -m venv .venv
    }
}

& ".\.venv\Scripts\python.exe" -X utf8 -m pip install -r requirements.txt

Write-Host ""
Write-Host "Da cai xong. Chay run.bat de mo tool."
