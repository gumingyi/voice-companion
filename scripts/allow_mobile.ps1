param(
    [Parameter(Mandatory=$true)][string]$ProgramPath,
    [Parameter(Mandatory=$true)][string]$LocalAddress,
    [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$Port
)
$ErrorActionPreference = 'Stop'
$programFile = Get-Item -LiteralPath $ProgramPath
if ($programFile.Extension -ne '.exe') { throw 'An executable path is required.' }
$parsedAddress = [System.Net.IPAddress]::Parse($LocalAddress)
if ($parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'IPv4 only.' }
if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq $LocalAddress })) { throw 'Address is not on this computer.' }
if ($LocalAddress -notmatch '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)') { throw 'Only a private LAN address is allowed.' }
$ruleName = 'VoiceCompanion-LAN-' + $Port + '-' + $LocalAddress
Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -LocalAddress $LocalAddress -RemoteAddress LocalSubnet -Program $programFile.FullName -Profile Private,Public -EdgeTraversalPolicy Block | Out-Null
