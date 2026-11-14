param(
    [string]$Apk = 'inputs/MiFitness-3.59.2.apk',
    [string]$Jadx = 'inputs/jadx-headless-mcp-0.7.1-all.jar',
    [string]$ReaScript
)

$ErrorActionPreference = 'Stop'
$apkPath = (Resolve-Path -LiteralPath $Apk).Path
$jarPath = (Resolve-Path -LiteralPath $Jadx).Path
if ((Get-FileHash -LiteralPath $apkPath).Hash -ne '112e603b8342cb134402a6dcabdf3ec16fd5171ec65a1d5f7cb7efd83cb0995d') {
    throw 'Unexpected APK SHA-256. Use Mi Fitness 3.59.2 from the documented sample.'
}
if ((Get-FileHash -LiteralPath $jarPath).Hash -ne '6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75') {
    throw 'Unexpected JADX JAR SHA-256.'
}

$oldJadx = $env:REA_JADX_MCP_JAR
$env:REA_JADX_MCP_JAR = $jarPath
$results = New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot '../build/apk-analysis')
try {
    $runner = 'npx.cmd'
    $prefixArgs = @('--yes', 'rea-agents@6.5.0')
    if ($ReaScript) {
        $runner = 'node'
        $prefixArgs = @((Resolve-Path -LiteralPath $ReaScript).Path)
    }
    & $runner @prefixArgs inspect-android-package $apkPath --format json |
        Set-Content -Encoding utf8 (Join-Path $results.FullName 'package.json')
    if ($LASTEXITCODE -ne 0) { throw 'REA package inspection failed.' }
    $methods = @(
        @('bind-mode', 'com.xiaomi.device.binder.WearBinderV2', 'g'),
        @('psk-binding', 'com.xiaomi.device.binder.PSKWearBinderV2', 'G'),
        @('transport-selection', 'com.xiaomi.wearable.core.server.ApiCallFactory', 'createApiCall'),
        @('spp-version', 'com.xiaomi.wearable.spp.SppVersionReader', 'readVersion'),
        @('wear-auth', 'com.xiaomi.wearable.wear.api.WearAuthV2', 'k'),
        @('notify', 'com.xiaomi.fitness.notify.util.BlueToothSender', 'addNotifications')
    )
    foreach ($entry in $methods) {
        $name, $class, $method = $entry
        & $runner @prefixArgs inspect-android-method $apkPath $class $method --overload-index 0 --format json |
            Set-Content -Encoding utf8 (Join-Path $results.FullName "$name.json")
        if ($LASTEXITCODE -ne 0) { throw "REA inspection failed for $class.$method." }
    }
    Write-Output $results.FullName
} finally {
    $env:REA_JADX_MCP_JAR = $oldJadx
}
