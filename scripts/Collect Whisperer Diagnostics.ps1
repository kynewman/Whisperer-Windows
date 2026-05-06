$ErrorActionPreference = "Continue"

function Get-TempRoot {
    if ($env:TEMP) {
        return $env:TEMP
    }
    if ($env:TMP) {
        return $env:TMP
    }
    return ([System.IO.Path]::GetTempPath())
}

function Get-WhispererLogDir {
    if ($env:WHISPERER_LOG_DIR) {
        return $env:WHISPERER_LOG_DIR
    }
    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA "Whisperer\logs")
    }
    return (Join-Path (Get-TempRoot) "Whisperer\logs")
}

function Add-CommandOutput {
    param(
        [System.Collections.ArrayList]$Target,
        [string]$Title,
        [scriptblock]$Command
    )
    [void]$Target.Add("")
    [void]$Target.Add($Title)
    try {
        $output = & $Command | Out-String
        if ($output) {
            $output.TrimEnd() -split "`r?`n" | ForEach-Object { [void]$Target.Add($_) }
        } else {
            [void]$Target.Add("(no output)")
        }
    } catch {
        [void]$Target.Add("Failed: $($_.Exception.Message)")
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logDir = Get-WhispererLogDir
$tempRoot = Get-TempRoot
$staging = Join-Path $tempRoot "WhispererDiagnostics-$timestamp"
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not $desktop) {
    $desktop = $tempRoot
}
$zipPath = Join-Path $desktop "Whisperer-Diagnostics-$timestamp.zip"

New-Item -ItemType Directory -Force -Path $staging | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

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

$metadata = [System.Collections.ArrayList]::new()
[void]$metadata.Add("Whisperer diagnostics collected: $(Get-Date -Format o)")
[void]$metadata.Add("Log directory: $(Remove-PrivatePathText $logDir)")
[void]$metadata.Add("Script directory: $(Remove-PrivatePathText $PSScriptRoot)")
[void]$metadata.Add("Temp directory: $(Remove-PrivatePathText $tempRoot)")
[void]$metadata.Add("OS: $((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption)")
[void]$metadata.Add("OS version: $((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Version)")
[void]$metadata.Add("Architecture: $env:PROCESSOR_ARCHITECTURE")
[void]$metadata.Add("PowerShell: $($PSVersionTable.PSVersion)")

Add-CommandOutput $metadata "Installed files:" {
    Get-ChildItem -LiteralPath $PSScriptRoot -Force -ErrorAction SilentlyContinue |
        Select-Object Name, Length, LastWriteTime |
        Format-Table -AutoSize
}

$exePath = Join-Path $PSScriptRoot "Whisperer.exe"
Add-CommandOutput $metadata "Installed executable:" {
    if (Test-Path -LiteralPath $exePath) {
        Get-Item -LiteralPath $exePath |
            Select-Object FullName, Length, LastWriteTime |
            Format-List
        Get-FileHash -Algorithm SHA256 -LiteralPath $exePath |
            Select-Object Algorithm, Hash |
            Format-List
        Get-AuthenticodeSignature -LiteralPath $exePath |
            Select-Object Status, StatusMessage, SignerCertificate |
            Format-List
    } else {
        "Whisperer.exe was not found beside the diagnostics script."
    }
}

Add-CommandOutput $metadata "Whisperer processes:" {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -like "*Whisperer*") -or
            ($_.CommandLine -like "*Whisperer*")
        } |
        Select-Object ProcessId, Name, ExecutablePath, CommandLine |
        Format-List
}

Add-CommandOutput $metadata "Recent application crash events:" {
    Get-WinEvent -FilterHashtable @{LogName="Application"; StartTime=(Get-Date).AddDays(-7)} -MaxEvents 300 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProviderName -in @("Application Error", "Windows Error Reporting") -and
            ($_.Message -like "*Whisperer*" -or $_.Message -like "*QtWebEngine*" -or $_.Message -like "*python*")
        } |
        Select-Object TimeCreated, ProviderName, Id, LevelDisplayName, Message |
        Format-List
}

[void]$metadata.Add("")
[void]$metadata.Add("Log files:")
if (Test-Path -LiteralPath $logDir) {
    Get-ChildItem -LiteralPath $logDir -Force -ErrorAction SilentlyContinue |
        Select-Object Name, Length, LastWriteTime |
        Format-Table -AutoSize |
        Out-String |
        ForEach-Object { [void]$metadata.Add($_) }
} else {
    [void]$metadata.Add("The log directory does not exist.")
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
