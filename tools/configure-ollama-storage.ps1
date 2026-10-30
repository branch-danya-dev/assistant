<#
.SYNOPSIS
Preview, then explicitly apply a verified copy of an existing Ollama model cache.
No download, source deletion, overwrite of differing files, or machine-wide setting.
#>
[CmdletBinding()]
param(
    [string]$AssistantRoot = 'G:\Assistant',
    [string]$SourceModels = (Join-Path $env:USERPROFILE '.ollama\models'),
    [string]$OllamaApp = 'G:\Ollama\ollama app.exe',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($AssistantRoot).TrimEnd('\')
$sourcePath = [IO.Path]::GetFullPath($SourceModels).TrimEnd('\')
$targetPath = [IO.Path]::Combine($rootPath, 'models', 'ollama')
if (-not [IO.Path]::IsPathRooted($AssistantRoot) -or -not (Test-Path -LiteralPath $rootPath -PathType Container)) {
    throw 'Initialize the absolute assistant root first.'
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw 'Source cache is absent.' }
if ($targetPath.StartsWith($sourcePath + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $sourcePath.StartsWith($targetPath + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $sourcePath -eq $targetPath) { throw 'Source and target must be separate directories.' }
foreach ($candidate in @($sourcePath, $rootPath, $targetPath)) {
    $cursor = $candidate
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and
            ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Reparse points are not supported for model migration.'
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
$entries = @(Get-ChildItem -LiteralPath $sourcePath -Recurse -Force)
if ($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
    throw 'Source contains a reparse point.'
}
$files = @($entries | Where-Object { -not $_.PSIsContainer })
if ($files.Count -eq 0) { throw 'Source cache is empty.' }
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
[pscustomobject]@{
    Source = $sourcePath; Target = $targetPath; Files = $files.Count; Bytes = $bytes
    Changes = 'Copy and SHA256-verify files; set User ASSISTANT_ROOT/OLLAMA_MODELS; restart Ollama Desktop'
    SourceDeletion = $false; ApplyRequested = [bool]$Apply
} | Format-List
if (-not $Apply) { return }
if (-not (Test-Path -LiteralPath $OllamaApp -PathType Leaf)) { throw 'Ollama Desktop executable is absent.' }
# User explicitly accepts interruption by invoking -Apply. No startup registration is changed.
$installPath = [IO.Path]::GetDirectoryName($OllamaApp)
foreach ($processName in @('ollama app', 'ollama')) {
    Get-Process -Name $processName -ErrorAction SilentlyContinue | ForEach-Object {
        if ([IO.Path]::GetDirectoryName($_.Path) -ne $installPath) { throw 'Unexpected Ollama executable location.' }
        Stop-Process -Id $_.Id -ErrorAction Stop
        $_.WaitForExit(10000) | Out-Null
    }
}
New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
foreach ($file in $files) {
    $relative = $file.FullName.Substring($sourcePath.Length).TrimStart('\')
    $destination = [IO.Path]::GetFullPath([IO.Path]::Combine($targetPath, $relative))
    if (-not $destination.StartsWith($targetPath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target escaped the model cache.'
    }
    $parent = [IO.Path]::GetDirectoryName($destination)
    $cursor = $parent
    while ($cursor -and $cursor.StartsWith($targetPath, [StringComparison]::OrdinalIgnoreCase)) {
        if ((Test-Path -LiteralPath $cursor) -and
            ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Target contains a reparse point.'
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    if ((Test-Path -LiteralPath $destination) -and
        ((Get-Item -LiteralPath $destination -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Target file is a reparse point.'
    }
    if (-not (Test-Path -LiteralPath $destination)) {
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sourceHash) {
        throw 'Copy verification failed; settings unchanged. Original files retained.'
    }
}
[Environment]::SetEnvironmentVariable('ASSISTANT_ROOT', $rootPath, 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $targetPath, 'User')
$env:ASSISTANT_ROOT = $rootPath
$env:OLLAMA_MODELS = $targetPath
Start-Process -FilePath $OllamaApp -WindowStyle Hidden
Write-Output 'Verified copy complete. Original cache retained. Check doctor and smoke before using live tasks.'
