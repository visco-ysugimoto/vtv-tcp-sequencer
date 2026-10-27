# Windows Defender exclusion helper (admin required).
# Corporate AV (Trend Micro etc.) is not affected; ask IT for exclusion.
$ErrorActionPreference = "Stop"

$candidates = @(
    (Split-Path -Parent $PSScriptRoot),
    $PSScriptRoot,
    (Get-Location).Path
)
$appDir = $null
foreach ($candidate in $candidates) {
    if (Test-Path (Join-Path $candidate "VTV_TCP_Sequencer.exe")) {
        $appDir = $candidate
        break
    }
}
if (-not $appDir) {
    Write-Error "Run this from the extracted VTV_TCP_Sequencer folder (packaging\Add-DefenderExclusion.ps1)."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Relaunching as administrator..."
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )
    exit
}

Add-MpPreference -ExclusionPath $appDir
Write-Host "Added Windows Defender exclusion:"
Write-Host "  $appDir"
Write-Host "If your PC uses company antivirus, request an exclusion from IT."
Pause