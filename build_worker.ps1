param([Parameter(Mandatory=$true)][string]$VendorDir)
$ErrorActionPreference = 'Stop'
$runtimeDirectory = (Resolve-Path -LiteralPath $VendorDir).Path
$nativeDirectory = Join-Path $PSScriptRoot 'ingetrazo_twinmotion_sync/native'
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $compilerPath /nologo /target:exe /platform:x64 "/out:$nativeDirectory/DirectLinkWorker.exe" "/reference:$runtimeDirectory/DatasmithRhino6.rhp" /reference:System.Web.Extensions.dll "$nativeDirectory/DirectLinkWorker.cs"
if ($LASTEXITCODE -ne 0) { throw 'Direct Link worker compilation failed.' }
