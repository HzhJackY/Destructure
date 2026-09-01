<#!
.SYNOPSIS
Builds the fixed-input Windows x64 portable public pre-release bundle.

.DESCRIPTION
The bundle contains the official CPython 3.14.5 embeddable runtime, a hashed
Windows wheel set, the exact conda-forge Tesseract 5.5.3 runtime closure and
fixed tessdata_fast language files. It remains a public pre-release rather than
a production-certified release: it does not include real documents, user
DATA_HOME, Golden evidence, LLM credentials or an OCR accuracy claim.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $PythonRuntimeHome,
    [Parameter(Mandatory = $true)] [string] $BuildPythonExe,
    [Parameter(Mandatory = $true)] [string] $PythonWheelhouse,
    [Parameter(Mandatory = $true)] [string] $PythonRequirementsLock,
    [Parameter(Mandatory = $true)] [string] $TesseractRuntimeHome,
    [Parameter(Mandatory = $true)] [string] $TesseractRuntimeClosureCsv,
    [Parameter(Mandatory = $true)] [string] $TessdataSourceHome,
    [Parameter(Mandatory = $true)] [string] $ThirdPartyEvidenceHome,
    [Parameter(Mandatory = $true)] [string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PythonExe = Join-Path $PythonRuntimeHome 'python.exe'
$TesseractExe = Join-Path $TesseractRuntimeHome 'tesseract.exe'
$Destination = [System.IO.Path]::GetFullPath($OutputDirectory)

if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Python executable not found: $PythonExe" }
if (-not (Test-Path -LiteralPath $BuildPythonExe -PathType Leaf)) { throw "Build Python executable not found: $BuildPythonExe" }
if (-not (Test-Path -LiteralPath $TesseractExe)) { throw "Tesseract executable not found: $TesseractExe" }
if (-not (Test-Path -LiteralPath $PythonWheelhouse -PathType Container)) { throw "Python wheelhouse not found: $PythonWheelhouse" }
if (-not (Test-Path -LiteralPath $PythonRequirementsLock -PathType Leaf)) { throw "Python wheel lock not found: $PythonRequirementsLock" }
if (-not (Test-Path -LiteralPath $TesseractRuntimeClosureCsv -PathType Leaf)) { throw "Tesseract closure CSV not found: $TesseractRuntimeClosureCsv" }
if (-not (Test-Path -LiteralPath $ThirdPartyEvidenceHome -PathType Container)) { throw "Third-party evidence directory not found: $ThirdPartyEvidenceHome" }
if (Test-Path -LiteralPath $Destination) { throw "Refusing to overwrite existing portable directory: $Destination" }
foreach ($name in @('chi_sim.traineddata', 'eng.traineddata', 'osd.traineddata')) {
    if (-not (Test-Path -LiteralPath (Join-Path $TessdataSourceHome $name))) { throw "Required tessdata file not found: $name" }
}

New-Item -ItemType Directory -Path $Destination | Out-Null
$AppRoot = Join-Path $Destination 'app'
$RuntimeRoot = Join-Path $Destination 'runtime'
$PortablePython = Join-Path $RuntimeRoot 'python'
$PortableTesseract = Join-Path $RuntimeRoot 'tesseract'
New-Item -ItemType Directory -Force -Path $AppRoot, $RuntimeRoot, $PortablePython, $PortableTesseract | Out-Null

# Copy source only. Runtime/data patterns are excluded even if a staging copy is
# accidentally contaminated later.
$excludedDirs = @('.git', '.venv', '__pycache__', '.pytest_cache', 'data_home', 'DATA_HOME', 'output', 'cache', 'scratch', 'tmp', 'temp', 'archive')
$excludedExtensions = @('.pdf', '.db', '.sqlite', '.sqlite3', '.parquet', '.xlsx', '.xls', '.csv', '.tsv', '.log', '.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.pyc', '.pyd', '.pem', '.key', '.p12')
$sourceFiles = Get-ChildItem -LiteralPath $SourceRoot -File -Recurse -Force | Where-Object {
    $relative = $_.FullName.Substring($SourceRoot.Length).TrimStart('\')
    $parts = $relative -split '\\'
    -not ($parts | Where-Object { $excludedDirs -contains $_ }) -and
    -not ($excludedExtensions -contains $_.Extension.ToLowerInvariant())
}
foreach ($file in $sourceFiles) {
    $relative = $file.FullName.Substring($SourceRoot.Length).TrimStart('\')
    $target = Join-Path $AppRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}

# Copy the already assembled CPython embeddable runtime. The input itself is
# fixed by the public provenance bundle; no build-host site-packages are read.
Get-ChildItem -LiteralPath $PythonRuntimeHome -Force | Copy-Item -Destination $PortablePython -Recurse -Force
$portablePythonExe = Join-Path $PortablePython 'python.exe'
if (-not (Test-Path -LiteralPath $portablePythonExe)) { throw 'Portable Python copy is incomplete.' }

# Reinstall every Python distribution from the local wheelhouse under
# --require-hashes. This deliberately refuses network access and dependency
# resolution, so a changed or missing wheel is a hard build failure.
$portableSitePackages = Join-Path $PortablePython 'Lib\site-packages'
if (Test-Path -LiteralPath $portableSitePackages) { Remove-Item -LiteralPath $portableSitePackages -Recurse -Force }
New-Item -ItemType Directory -Force -Path $portableSitePackages | Out-Null
$buildPythonVersion = (& $BuildPythonExe -c "import platform; print(platform.python_version())").Trim()
if ($buildPythonVersion -ne '3.14.5') { throw "Build Python must be 3.14.5, found: $buildPythonVersion" }
& $BuildPythonExe -m pip install --disable-pip-version-check --no-index --find-links $PythonWheelhouse --require-hashes --no-deps --no-compile --target $portableSitePackages -r $PythonRequirementsLock
if ($LASTEXITCODE -ne 0) { throw "hashed local Python dependency install failed: exit $LASTEXITCODE" }

# pip's Windows entry-point wrappers embed the absolute path of the build
# interpreter. The portable launchers call embedded Python with `-m`, so these
# machine-bound wrappers are unnecessary and must not be distributed.
$machineBoundEntryPoints = Join-Path $portableSitePackages 'bin'
if (Test-Path -LiteralPath $machineBoundEntryPoints) {
    Remove-Item -LiteralPath $machineBoundEntryPoints -Recurse -Force
}
# Remove stale RECORD entries for the deleted machine-bound launchers. Their
# hashes encode the build-interpreter absolute path and would make two builds
# from identical inputs differ solely by work-directory location.
Get-ChildItem -LiteralPath $portableSitePackages -Directory -Filter '*.dist-info' |
    ForEach-Object {
        $record = Join-Path $_.FullName 'RECORD'
        if (Test-Path -LiteralPath $record) {
            $kept = Get-Content -LiteralPath $record | Where-Object { $_ -notmatch '^\.\./\.\./bin/' }
            Set-Content -LiteralPath $record -Value $kept -Encoding utf8
        }
    }

# Copy only the dependency-closed, individually hashed Tesseract runtime files.
# Training tools and unrelated conda packages are intentionally excluded.
$closure = Import-Csv -LiteralPath $TesseractRuntimeClosureCsv
if ($closure.Count -ne 42) { throw "Unexpected Tesseract runtime closure count: $($closure.Count)" }
foreach ($row in $closure) {
    $source = Join-Path $TesseractRuntimeHome $row.filename
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Tesseract closure file missing: $($row.filename)" }
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actual -ne $row.sha256) { throw "Tesseract closure hash mismatch: $($row.filename)" }
    Copy-Item -LiteralPath $source -Destination $PortableTesseract
}
$Tessdata = Join-Path $PortableTesseract 'tessdata'
New-Item -ItemType Directory -Force -Path $Tessdata | Out-Null
$expectedTessdataHashes = @{
    'chi_sim.traineddata' = 'A5FCB6F0DB1E1D6D8522F39DB4E848F05984669172E584E8D76B6B3141E1F730'
    'eng.traineddata' = '7D4322BD2A7749724879683FC3912CB542F19906C83BCC1A52132556427170B2'
    'osd.traineddata' = '9CF5D576FCC47564F11265841E5CA839001E7E6F38FF7F7AACF46D15A96B00FF'
}
foreach ($name in @('chi_sim.traineddata', 'eng.traineddata', 'osd.traineddata')) {
    $source = Join-Path $TessdataSourceHome $name
    $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    if ($actual -ne $expectedTessdataHashes[$name]) { throw "tessdata hash mismatch: $name" }
    Copy-Item -LiteralPath $source -Destination $Tessdata
}
foreach ($directory in @('configs', 'tessconfigs')) {
    $source = Join-Path $TessdataSourceHome $directory
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination $Tessdata -Recurse }
}

Copy-Item -LiteralPath (Join-Path $PythonRuntimeHome 'LICENSE.txt') -Destination (Join-Path $Destination 'THIRD_PARTY_PYTHON_LICENSE.txt')
Copy-Item -LiteralPath $ThirdPartyEvidenceHome -Destination (Join-Path $Destination 'THIRD_PARTY') -Recurse
Copy-Item -LiteralPath (Join-Path $SourceRoot 'LICENSE') -Destination (Join-Path $Destination 'LICENSE')
Copy-Item -LiteralPath (Join-Path $SourceRoot 'NOTICE') -Destination (Join-Path $Destination 'NOTICE')

$launcher = @'
@echo off
setlocal
set "ROOT=%~dp0"
set "PATH=%ROOT%runtime\tesseract;%ROOT%runtime\python;%PATH%"
set "TESSDATA_PREFIX=%ROOT%runtime\tesseract\tessdata"
if "%FIN_METRIC_DATA_HOME%"=="" set "FIN_METRIC_DATA_HOME=%LOCALAPPDATA%\AXAResearch\v6.12.1\data_home"
if not exist "%FIN_METRIC_DATA_HOME%" mkdir "%FIN_METRIC_DATA_HOME%"
"%ROOT%runtime\python\python.exe" "%ROOT%app\launcher.py"
if errorlevel 1 pause
'@
Set-Content -LiteralPath (Join-Path $Destination 'Launch_AXA_Research.cmd') -Value $launcher -Encoding ascii

$selfCheck = @'
@echo off
setlocal
set "ROOT=%~dp0"
set "PATH=%ROOT%runtime\tesseract;%ROOT%runtime\python;%PATH%"
set "TESSDATA_PREFIX=%ROOT%runtime\tesseract\tessdata"
"%ROOT%runtime\python\python.exe" -c "import fitz, pandas, streamlit; print('PYTHON_CORE_IMPORTS_OK')"
if errorlevel 1 pause & exit /b 1
tesseract --list-langs
if errorlevel 1 pause & exit /b 1
"%ROOT%runtime\python\python.exe" "%ROOT%app\examples\synthetic\run_smoke.py"
if errorlevel 1 pause & exit /b 1
echo PORTABLE_SELF_CHECK_PASS
pause
'@
Set-Content -LiteralPath (Join-Path $Destination 'Portable_Self_Check.cmd') -Value $selfCheck -Encoding ascii

$readme = @'
# AXA Research v6.12.1 Windows x64 Portable Public Pre-release

This package includes CPython 3.14.5, a hashed 55-wheel runtime, conda-forge
Tesseract 5.5.3, Leptonica 1.87.0, and `chi_sim`, `eng`, `osd` language data.
Double-click `Portable_Self_Check.cmd` first, then `Launch_AXA_Research.cmd`.

It is approved only as a public pre-release, not as a production-certified
release. It includes no PDF, Golden corpus, user data, LLM credential or cached
OCR result. The first launch creates DATA_HOME at
`%LOCALAPPDATA%\AXAResearch\v6.12.1\data_home` unless
`FIN_METRIC_DATA_HOME` is already set.

The project is AGPL-3.0-only. Component package records, hashes, license texts,
recipes, Python wheel hashes and source directions are under `THIRD_PARTY`.
Real-PDF, Golden, browser E2E and production DATA_HOME acceptance were not run;
the package therefore makes no OCR-accuracy or production-readiness claim.
'@
Set-Content -LiteralPath (Join-Path $Destination 'PORTABLE_PRE_RELEASE.md') -Value $readme -Encoding utf8

$manifest = Get-ChildItem -LiteralPath $Destination -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($Destination.Length).TrimStart('\').Replace('\', '/')
    [pscustomobject]@{ path = $relative; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
} | Sort-Object path
$manifest | Export-Csv -LiteralPath (Join-Path $Destination 'portable_file_manifest.csv') -NoTypeInformation -Encoding utf8
Write-Host "PORTABLE_BUILD_OK $Destination"
