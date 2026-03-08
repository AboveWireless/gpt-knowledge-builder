param(
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Assert-Success([string]$StepName) {
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE."
    }
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$SpecPath = Join-Path $RepoRoot "packaging\windows\GPTKnowledgeBuilder.spec"
$InstallerScript = Join-Path $RepoRoot "packaging\windows\GPTKnowledgeBuilder.iss"
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$IconPath = Join-Path $RepoRoot "packaging\windows\assets\app.ico"

if ($Clean) {
    if (Test-Path $DistDir) { Remove-Item $DistDir -Recurse -Force }
    if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
}

Set-Location $RepoRoot

Write-Host "Installing build dependencies..."
python -m pip install -e ".[windows-build,extractors,ocr,ai]"
Assert-Success "Dependency installation"

$VersionJson = python -c "import json; from knowledge_builder.version import APP_VERSION, APP_NAME, COMPANY_NAME, EXECUTABLE_NAME, APP_COPYRIGHT; print(json.dumps({'version': APP_VERSION, 'name': APP_NAME, 'company': COMPANY_NAME, 'exe': EXECUTABLE_NAME, 'copyright': APP_COPYRIGHT}))"
$VersionMeta = $VersionJson | ConvertFrom-Json
$VersionParts = $VersionMeta.version.Split(".") | ForEach-Object { [int]$_ }
while ($VersionParts.Count -lt 4) { $VersionParts += 0 }

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$VersionFile = Join-Path $BuildDir "windows-version-info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($VersionParts[0]), $($VersionParts[1]), $($VersionParts[2]), $($VersionParts[3])),
    prodvers=($($VersionParts[0]), $($VersionParts[1]), $($VersionParts[2]), $($VersionParts[3])),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '$($VersionMeta.company)'),
          StringStruct('FileDescription', '$($VersionMeta.name)'),
          StringStruct('FileVersion', '$($VersionMeta.version)'),
          StringStruct('InternalName', '$($VersionMeta.exe)'),
          StringStruct('OriginalFilename', '$($VersionMeta.exe).exe'),
          StringStruct('ProductName', '$($VersionMeta.name)'),
          StringStruct('ProductVersion', '$($VersionMeta.version)'),
          StringStruct('LegalCopyright', '$($VersionMeta.copyright)')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Path $VersionFile -Encoding UTF8
$env:PYINSTALLER_VERSION_FILE = $VersionFile

if (-not $SkipTests) {
    Write-Host "Running tests..."
    python -m pytest
    Assert-Success "Test run"
}

Write-Host "Building Windows app with PyInstaller..."
python -m PyInstaller --noconfirm --clean $SpecPath
Assert-Success "PyInstaller build"

if ($SkipInstaller) {
    Write-Host "Skipping installer build."
    exit 0
}

$Iscc = Get-Command "iscc" -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $DefaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $DefaultIscc) {
        $Iscc = Get-Item $DefaultIscc
    }
}

if (-not $Iscc) {
    Write-Warning "Inno Setup compiler not found. Install Inno Setup 6 or rerun with -SkipInstaller."
    exit 0
}

Write-Host "Building installer..."
& $Iscc `
    "/DMyAppVersion=$($VersionMeta.version)" `
    "/DMyAppPublisher=$($VersionMeta.company)" `
    "/DMyAppExeName=$($VersionMeta.exe).exe" `
    "/DMyOutputBaseFilename=GPTKnowledgeBuilder-$($VersionMeta.version)-Setup" `
    "/DMyAppIconPath=$IconPath" `
    $InstallerScript
Assert-Success "Inno Setup build"

Write-Host "Build complete."
Write-Host "App folder: $(Join-Path $DistDir 'GPT Knowledge Builder')"
Write-Host "Installer: $(Join-Path $DistDir "installer\GPTKnowledgeBuilder-$($VersionMeta.version)-Setup.exe")"
