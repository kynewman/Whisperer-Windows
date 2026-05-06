$ErrorActionPreference = "Continue"

function Get-WhispererLogDir {
    if ($env:WHISPERER_LOG_DIR) {
        return $env:WHISPERER_LOG_DIR
    }
    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA "Whisperer\logs")
    }
    return (Join-Path $env:TEMP "Whisperer\logs")
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Get-WhispererLogDir
$staging = Join-Path $env:TEMP "WhispererDiagnostics-$timestamp"
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop) {
    $desktop = $env:TEMP
}
$zipPath = Join-Path $desktop "Whisperer-Diagnostics-$timestamp.zip"

New-Item -ItemType Directory -Force -Path $staging | Out-Null

function Remove-PrivatePathText {
    param([string]$Text)
    if ($null -eq $Text) { return "" }
    $value = $Text
    if ($env:USERPROFILE) {
        $value = $value.Replace($env:USERPROFILE, "%USERPROFILE%")
    }
    if ($env:USERNAME) {
        $value = $value.Replace($env:USERNAME, "%USERNAME%")
    }
    return $value
}

$metadata = @()
$metadata += "Whisperer diagnostics collected: $(Get-Date -Format o)"
$metadata += "Log directory: $(Remove-PrivatePathText $logDir)"
$metadata += "Script directory: $(Remove-PrivatePathText $PSScriptRoot)"
$metadata += "OS: $((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption)"
$metadata += "OS version: $((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Version)"
$metadata += "PowerShell: $($PSVersionTable.PSVersion)"
$metadata += ""
$metadata += "Installed files:"
Get-ChildItem -LiteralPath $PSScriptRoot -Force -ErrorAction SilentlyContinue |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize |
    Out-String |
    ForEach-Object { $metadata += $_ }
$metadata += ""
$metadata += "Log files:"
if (Test-Path -LiteralPath $logDir) {
    Get-ChildItem -LiteralPath $logDir -Force -ErrorAction SilentlyContinue |
        Select-Object Name, Length, LastWriteTime |
        Format-Table -AutoSize |
        Out-String |
        ForEach-Object { $metadata += $_ }
} else {
    $metadata += "The log directory does not exist."
}

$metadata | Set-Content -LiteralPath (Join-Path $staging "system-info.txt") -Encoding UTF8

if (Test-Path -LiteralPath $logDir) {
    $targetLogCopy = Join-Path $staging "logs"
    New-Item -ItemType Directory -Force -Path $targetLogCopy | Out-Null
    Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue | ForEach-Object {
        $target = Join-Path $targetLogCopy $_.Name
        try {
            $content = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 -ErrorAction Stop
            Remove-PrivatePathText $content | Set-Content -LiteralPath $target -Encoding UTF8
        } catch {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force -ErrorAction SilentlyContinue
        }
    }
}

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Whisperer diagnostics were saved to:"
Write-Host $zipPath
Write-Host ""
Write-Host "Send this zip file for debugging."
Write-Host ""
Read-Host "Press Enter to close"
