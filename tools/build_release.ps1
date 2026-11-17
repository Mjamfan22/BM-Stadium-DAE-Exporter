param(
    [string]$Version = "1.1.2"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $repositoryRoot "bm_stadium_dae"
$releaseRoot = Join-Path $repositoryRoot "dist"
$releasePath = Join-Path $releaseRoot "bm_stadium_dae_v${Version}_Blender_5.2.zip"

if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Missing add-on source: $sourceRoot"
}

$manifest = Get-Content -Raw -LiteralPath (Join-Path $sourceRoot "blender_manifest.toml")
if ($manifest -notmatch ('version\s*=\s*"' + [regex]::Escape($Version) + '"')) {
    throw "Manifest version does not match $Version"
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("bm-stadium-release-" + [guid]::NewGuid().ToString("N"))
$temporaryPackage = Join-Path $temporaryRoot "bm_stadium_dae"
New-Item -ItemType Directory -Path $temporaryPackage -Force | Out-Null
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

try {
    Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Where-Object {
        $_.FullName -notmatch "\\__pycache__\\" -and
        $_.Extension -ne ".pyc" -and
        $_.Name -ne "visibility.py"
    } | ForEach-Object {
        $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart("\\")
        $destination = Join-Path $temporaryPackage $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }

    if (Test-Path -LiteralPath $releasePath) {
        throw "Release already exists: $releasePath"
    }
    Compress-Archive -LiteralPath $temporaryPackage -DestinationPath $releasePath -CompressionLevel Optimal
    Get-FileHash -LiteralPath $releasePath -Algorithm SHA256
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
