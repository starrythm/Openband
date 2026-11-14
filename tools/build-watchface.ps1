param(
    [string]$PackerSource = (Join-Path $PSScriptRoot '..\build\Mi8WfBinTool'),
    [string]$ObserverFile
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildArgs = @()
$build = 'build/watchface'
if ($ObserverFile) {
    $buildArgs = @('--observer-file', (Resolve-Path -LiteralPath $ObserverFile).Path)
    $build = 'build/watchface-local'
}
Push-Location $repoRoot
try {
    $toolFile = Join-Path $PackerSource 'Mi8WfBinTool.java'
    if (-not (Test-Path -LiteralPath $toolFile -PathType Leaf)) {
        throw 'Fetch the pinned Mi8WfBinTool source and apply tools/o66-unpack.patch first.'
    }
    python watchface/build.py @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'Lua source and preview generation failed.' }
    $classes = Join-Path $repoRoot "$build/classes"
    New-Item -ItemType Directory -Path $classes -Force | Out-Null
    javac -encoding UTF-8 -d $classes $toolFile
    if ($LASTEXITCODE -ne 0) { throw 'Watchface packer compilation failed.' }
    java -cp $classes Mi8WfBinTool pack "$build/native-face" "$build/micro-star-v2.bin" o66
    if ($LASTEXITCODE -ne 0) { throw 'Watchface packing failed.' }
    java -cp $classes Mi8WfBinTool unpack "$build/micro-star-v2.bin" "$build/roundtrip" o66
    if ($LASTEXITCODE -ne 0) { throw 'Watchface round-trip unpack failed.' }
    $generated = (Get-FileHash "$build/native-face/images/_lua/microstar/main.lua").Hash
    $unpacked = (Get-FileHash "$build/roundtrip/images/_lua/microstar/main.lua").Hash
    if ($generated -ne $unpacked) { throw 'Lua bytes changed in the watchface round trip.' }
    Get-FileHash "$build/micro-star-v2.bin"
} finally {
    Pop-Location
}
