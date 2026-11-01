# Disposable hosted-runner VHD only. Never changes global/host NTFS policy.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'This provisioning harness is restricted to disposable GitHub-hosted Windows runners.'
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runRoot = [IO.Path]::GetFullPath((Join-Path $env:RUNNER_TEMP ('task044-' + [guid]::NewGuid())))
$tempRoot = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\') + '\'
if (-not $runRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe root' }
New-Item -ItemType Directory -Path $runRoot | Out-Null
$vhd = Join-Path $runRoot 'synthetic.vhd'
$drive = @('R','S','T','U','V') | Where-Object { -not (Test-Path "${_}:\") } | Select-Object -First 1
if (-not $drive -or (Test-Path $vhd)) { throw 'No unused volume/path' }
$volumeRoot = "${drive}:\"
$attach = Join-Path $runRoot 'attach.txt'
@"
create vdisk file="$vhd" maximum=256 type=expandable
select vdisk file="$vhd"
attach vdisk
create partition primary
format fs=ntfs label=TASK044 quick
assign letter=$drive
"@ | Set-Content -LiteralPath $attach -Encoding ascii
$testExit = 1
try {
    & diskpart /s $attach | Tee-Object -FilePath (Join-Path $runRoot 'diskpart.log')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $volumeRoot)) { throw 'VHD provisioning failed' }
    $info = [IO.DriveInfo]::new($volumeRoot)
    if ($info.DriveFormat -ne 'NTFS' -or $info.VolumeLabel -ne 'TASK044') { throw 'Unexpected volume' }
    'synthetic-only' | Set-Content -LiteralPath (Join-Path $volumeRoot 'task044-isolated-volume') -NoNewline
    & fsutil 8dot3name query
    # Only the new VHD's volume setting. Never run `fsutil 8dot3name set 0|2`.
    & fsutil 8dot3name set "${drive}:" 0
    Write-Output "PER_VOLUME_8DOT3_EXIT=$LASTEXITCODE"
    & fsutil 8dot3name query "${drive}:"
    $env:ASSISTANT_TEST_ROOT = Join-Path $volumeRoot 'fixtures'
    $env:ASSISTANT_NTFS_VHD = $volumeRoot
    Push-Location $repo
    try {
        $env:PYTHONPATH = Join-Path $repo 'tests'
        & python -m unittest test_file_aliases test_windows_ntfs test_security test_m1_create -v
        $testExit = $LASTEXITCODE
    } finally { Pop-Location }
} finally {
    Remove-Item Env:ASSISTANT_TEST_ROOT,Env:ASSISTANT_NTFS_VHD,Env:PYTHONPATH -ErrorAction SilentlyContinue
    # Select only our exact new image; never select a physical disk number.
    if (-not ([IO.Path]::GetFullPath($vhd)).StartsWith($runRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe detach target'
    }
    $detach = Join-Path $runRoot 'detach.txt'
    "select vdisk file=`"$vhd`"`ndetach vdisk" | Set-Content -LiteralPath $detach -Encoding ascii
    & diskpart /s $detach
    if (Test-Path $volumeRoot) { throw 'VHD detach not confirmed' }
}
exit $testExit
