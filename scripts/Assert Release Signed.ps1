$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path
)

$failed = @()
foreach ($item in $Path) {
    $resolved = Resolve-Path -LiteralPath $item
    $signature = Get-AuthenticodeSignature -LiteralPath $resolved
    if ($signature.Status -ne "Valid") {
        $failed += [pscustomobject]@{
            Path = $resolved.Path
            Status = $signature.Status
            Subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { "" }
        }
    }
}

if ($failed.Count -gt 0) {
    $failed | Format-Table -AutoSize | Out-String | Write-Error
    exit 1
}

Write-Host "All release files have valid Authenticode signatures."
