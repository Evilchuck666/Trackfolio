# Start from a checkout or ZIP, including Windows PowerShell 5.1.
# Raw arguments let Python receive --core, --platform, and uv's own flags unchanged.
$SetupArguments = @($args)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = $PSScriptRoot

function Fail([string] $Message) {
    throw "ERROR: $Message"
}

if ($SetupArguments.Count -gt 0 -and $SetupArguments[0] -in @("--help", "-h")) {
    Write-Output @"
Trackfolio: preparación completa desde las fuentes.
Uso: powershell -ExecutionPolicy Bypass -File setup.ps1 [--core | --gui]
     [--platform offscreen|xcb|wayland] [--skip-editor] [--non-interactive]
     [--yes] [--open-code] [--qt-timeout SEGUNDOS]
Por defecto prepara la GUI, las herramientas de desarrollo y VS Code.
Las instalaciones del sistema y de un editor nuevo requieren confirmación.
Para ejecutar uv sin repetir la preparación: setup.ps1 --run-uv COMANDO ...
"@
    exit 0
}

try {
    Set-Location -LiteralPath $Root
    foreach ($File in @("pyproject.toml", ".python-version", "uv.lock", "scripts/setup.py")) {
        $Path = Join-Path $Root $File
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path -Force).Length -eq 0) {
            Fail "Falta $File. Descarga el repositorio completo."
        }
    }
    $Manifest = Get-Content -LiteralPath (Join-Path $Root "pyproject.toml") -Raw -Force
    $Section = [regex]::Match($Manifest, '(?ms)^\s*\[tool\.uv\]\s*\r?\n(?<body>.*?)(?=^\s*\[|\z)')
    $RequirementMatch = [regex]::Match($Section.Groups['body'].Value, '(?m)^\s*required-version\s*=\s*["''](?<value>[^"'']+)["'']')
    $Requirement = $RequirementMatch.Groups['value'].Value -replace '\s', ''
    $Range = [regex]::Match($Requirement, '^>=(?<minimum>\d+\.\d+\.\d+),<(?<maximum>\d+\.\d+(?:\.\d+)?)$')
    if (-not $Range.Success) { Fail "Rango de uv inválido en pyproject.toml." }
    $Minimum = $Range.Groups['minimum'].Value
    $Maximum = $Range.Groups['maximum'].Value
    if ([version] $Minimum -ge [version] $Maximum) { Fail "El mínimo de uv debe ser inferior al máximo exclusivo." }
    $PythonVersion = (Get-Content -LiteralPath (Join-Path $Root ".python-version") -Raw -Force).Trim()
    if ($PythonVersion -notmatch '^\d+\.\d+\.\d+$') { Fail ".python-version inválido." }

    $LocalUv = Join-Path $Root ".tools/uv"
    $LocalExecutable = Join-Path $LocalUv "uv.exe"
    function Test-Compatible([string] $Candidate) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
        try {
            & $Candidate version --short --offline --project $Root *> $null
            return $LASTEXITCODE -eq 0
        } catch { return $false }
    }
    $Uv = $null
    $Installed = @(Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)
    foreach ($Item in $Installed) {
        if (Test-Compatible $Item.Source) {
            $Uv = $Item.Source
            break
        }
    }
    if (-not $Uv -and (Test-Compatible $LocalExecutable)) {
        $Uv = $LocalExecutable
    }

    if ($SetupArguments.Count -gt 0 -and $SetupArguments[0] -eq "--run-uv") {
        if (-not $Uv) { Fail "No hay uv compatible. Ejecuta primero setup.ps1." }
        if ($SetupArguments.Count -lt 2) { Fail "Indica el comando de uv después de --run-uv." }
        $Forward = $SetupArguments[1..($SetupArguments.Count - 1)]
        & $Uv @Forward
        exit $LASTEXITCODE
    }

    if (-not $Uv) {
        New-Item -ItemType Directory -Force -Path $LocalUv | Out-Null
        $Installer = Join-Path $LocalUv (".installer-" + [guid]::NewGuid().ToString() + ".ps1")
        $PreviousUnmanaged = $env:UV_UNMANAGED_INSTALL
        $PreviousNoModify = $env:UV_NO_MODIFY_PATH
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Write-Output "Descargando uv $Minimum para este proyecto, sin modificar el sistema ni el shell."
            Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/$Minimum/install.ps1" -OutFile $Installer -TimeoutSec 120
            $env:UV_UNMANAGED_INSTALL = $LocalUv
            $env:UV_NO_MODIFY_PATH = "1"
            # A child process contains the installer's exit and environment changes.
            $PowerShellExecutable = (Get-Process -Id $PID).Path
            & $PowerShellExecutable -NoProfile -ExecutionPolicy Bypass -File $Installer
            if ($LASTEXITCODE -ne 0) { Fail "El instalador de uv falló ($LASTEXITCODE)." }
        } finally {
            $env:UV_UNMANAGED_INSTALL = $PreviousUnmanaged
            $env:UV_NO_MODIFY_PATH = $PreviousNoModify
            if (Test-Path -LiteralPath $Installer) { Remove-Item -LiteralPath $Installer -Force }
        }
        if (-not (Test-Compatible $LocalExecutable)) { Fail "La instalación de uv no cumple $Requirement." }
        $Uv = $LocalExecutable
    }
    Write-Output "Usando uv: $Uv"
    & $Uv run --no-project --managed-python --python $PythonVersion python -m scripts.setup --uv $Uv @SetupArguments
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
