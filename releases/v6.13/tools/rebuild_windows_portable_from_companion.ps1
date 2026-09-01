<#!
.SYNOPSIS
Rebuilds the Windows x64 portable pre-release entirely from fixed release inputs.

.DESCRIPTION
Requires only PowerShell 7, the public source tree and the corresponding-source
companion tree. It never contacts the network. It verifies every input hash,
assembles the official CPython 3.14.5 embeddable runtime, bootstraps the fixed
pip wheel, creates the exact portable evidence subset and calls the governed
portable builder.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $SourceRoot,
    [Parameter(Mandatory = $true)] [string] $CompanionRoot,
    [Parameter(Mandatory = $true)] [string] $WorkDirectory,
    [Parameter(Mandatory = $true)] [string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$SourceRoot = (Resolve-Path $SourceRoot).Path
$CompanionRoot = (Resolve-Path $CompanionRoot).Path
$WorkDirectory = [IO.Path]::GetFullPath($WorkDirectory)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
function Test-IsWithin([string] $Child, [string] $Parent) {
    $prefix = $Parent.TrimEnd('\') + '\'
    return $Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or
        $Child.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}
foreach ($pair in @(
    @($WorkDirectory, $SourceRoot, 'work directory inside source root'),
    @($WorkDirectory, $CompanionRoot, 'work directory inside companion root'),
    @($OutputDirectory, $SourceRoot, 'output directory inside source root'),
    @($OutputDirectory, $CompanionRoot, 'output directory inside companion root'),
    @($OutputDirectory, $WorkDirectory, 'output directory inside work directory'),
    @($WorkDirectory, $OutputDirectory, 'work directory inside output directory')
)) {
    if (Test-IsWithin $pair[0] $pair[1]) { throw "Unsafe path relationship: $($pair[2])" }
}
if (Test-Path -LiteralPath $WorkDirectory) { throw "Refusing to overwrite work directory: $WorkDirectory" }
if (Test-Path -LiteralPath $OutputDirectory) { throw "Refusing to overwrite output directory: $OutputDirectory" }
New-Item -ItemType Directory -Path $WorkDirectory | Out-Null

function Assert-Hash([string] $Path, [string] $Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing fixed input: $Path" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected) { throw "SHA-256 mismatch: $Path" }
}

# Assemble official embeddable CPython and enable site-packages.
$pythonLock = Import-Csv -LiteralPath (Join-Path $CompanionRoot 'python_runtime_input_lock.csv')
if ($pythonLock.Count -ne 1) { throw 'Expected one CPython runtime input' }
$pythonZip = Join-Path $CompanionRoot (Join-Path 'python_runtime_inputs' $pythonLock.artifact)
Assert-Hash $pythonZip $pythonLock.sha256
$pythonHome = Join-Path $WorkDirectory 'python_runtime'
Expand-Archive -LiteralPath $pythonZip -DestinationPath $pythonHome
$pth = Join-Path $pythonHome 'python314._pth'
if (-not (Test-Path -LiteralPath $pth)) { throw 'python314._pth missing from embeddable runtime' }
$lines = @(Get-Content -LiteralPath $pth | Where-Object { $_ -notin @('#import site', 'import site', 'Lib\site-packages') })
$lines += 'Lib\site-packages'
$lines += 'import site'
Set-Content -LiteralPath $pth -Value $lines -Encoding ascii
$pythonExe = Join-Path $pythonHome 'python.exe'

# Bootstrap fixed pip without network, then the governed builder installs the
# 55 locked runtime distributions from the same wheelhouse.
$pipLock = Import-Csv -LiteralPath (Join-Path $CompanionRoot 'pip_bootstrap_lock.csv')
if ($pipLock.Count -ne 1) { throw 'Expected one pip bootstrap input' }
$wheelhouse = Join-Path $CompanionRoot 'python_wheels_win_cp314_x64'
$pipWheel = Join-Path (Join-Path $CompanionRoot 'build_tools') $pipLock.filename
Assert-Hash $pipWheel $pipLock.sha256
$pipTarget = Join-Path $pythonHome 'Lib\site-packages'
New-Item -ItemType Directory -Path $pipTarget -Force | Out-Null
[IO.Compression.ZipFile]::ExtractToDirectory($pipWheel, $pipTarget)
& $pythonExe -m pip --version
if ($LASTEXITCODE -ne 0) { throw "Offline pip bootstrap failed: $LASTEXITCODE" }

# Verify the ready-to-copy OCR runtime and fixed language models.
$closureCsv = Join-Path $CompanionRoot 'conda_tesseract_runtime_closure_inventory.csv'
$runtimeHome = Join-Path $CompanionRoot 'tesseract_runtime_files'
$closure = Import-Csv -LiteralPath $closureCsv
if ($closure.Count -ne 42) { throw "Unexpected OCR closure count: $($closure.Count)" }
foreach ($row in $closure) { Assert-Hash (Join-Path $runtimeHome $row.filename) $row.sha256 }
$tessdataLock = Import-Csv -LiteralPath (Join-Path $CompanionRoot 'tessdata_fast_lock.csv')
if ($tessdataLock.Count -ne 3) { throw "Unexpected tessdata count: $($tessdataLock.Count)" }
$tessdataHome = Join-Path $CompanionRoot ('tessdata_fast_' + $tessdataLock[0].commit)
foreach ($row in $tessdataLock) { Assert-Hash (Join-Path $tessdataHome $row.filename) $row.sha256 }

# Keep portable evidence small and deterministic. Large wheels, package inputs
# and corresponding source remain in the companion release asset.
$evidence = Join-Path $WorkDirectory 'portable_evidence'
New-Item -ItemType Directory -Path $evidence | Out-Null
$evidenceFiles = @(
    'README.md','OCR_COPYLEFT_NOTICE.md','conda_package_lock.csv',
    'conda_runtime_file_owners.csv','conda_tesseract_package_records.csv',
    'conda_tesseract_runtime_closure_inventory.csv','python_runtime_distribution_metadata.csv',
    'python_windows_cp314_requirements.lock','python_windows_cp314_wheel_lock.csv',
    'statically_linked_component_evidence.csv','upstream_source_index.csv'
)
foreach ($name in $evidenceFiles) { Copy-Item -LiteralPath (Join-Path $CompanionRoot $name) -Destination (Join-Path $evidence $name) }
foreach ($name in @('licenses','recipes')) { Copy-Item -LiteralPath (Join-Path $CompanionRoot $name) -Destination (Join-Path $evidence $name) -Recurse }

$builder = Join-Path $SourceRoot 'tools\build_windows_portable_prerelease.ps1'
& $builder -PythonRuntimeHome $pythonHome -BuildPythonExe $pythonExe `
    -PythonWheelhouse $wheelhouse `
    -PythonRequirementsLock (Join-Path $CompanionRoot 'python_windows_cp314_requirements.lock') `
    -TesseractRuntimeHome $runtimeHome -TesseractRuntimeClosureCsv $closureCsv `
    -TessdataSourceHome $tessdataHome -ThirdPartyEvidenceHome $evidence `
    -OutputDirectory $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Portable builder failed: $LASTEXITCODE" }
Write-Host "OFFLINE_PORTABLE_REBUILD_OK $OutputDirectory"
