# Run a live event from a Windows laptop, without Docker.
#
#   .\scripts\event.ps1 up      start the poker server, a Cloudflare tunnel and the live site feed
#   .\scripts\event.ps1 status  what is running, the public address, who is in the lobby
#   .\scripts\event.ps1 url     print the address, join code and admin key
#   .\scripts\event.ps1 start   start the tournament (whoever is in the lobby)
#   .\scripts\event.ps1 down    stop everything this script started
#
# Options for `up`:
#   -Protocol quic|http2   tunnel transport (default quic; use http2 where UDP is blocked,
#                          and quic where the network intercepts HTTPS, see docs)
#   -Cloudflared PATH      the cloudflared.exe to use (default: PATH, then .\tools\cloudflared.exe)
#   -NoTunnel              server only (bots on the same network can connect to this PC)
#   -Site FOLDER           also publish the live view into this site folder (a git clone)
#   -GitPush               commit and push the site after each publication
#   -Delay SECONDS         how far behind the real game the site runs (default 360)
#   -Interval SECONDS      how often the site is published (default 300, minimum 60)
#   -FormUrl URL           the backup submission form (shown on the Info page)
#   -RegisterForm URL      the team-name registration form's prefilled link
#   -Registrations SRC     that form's sheet (CSV file or published https address)
#   -PublishCode           show the join code on the website's Info page
#   -Port N                server port (default 8000)
#
# Secrets (admin key, join code) are made once and kept in .event\event.env, which is
# git-ignored. Anyone with the join code can register a team, and anyone with the
# tunnel address can reach the server: share the code only with the teams.
[CmdletBinding()]
param(
    [Parameter(Position = 0)][ValidateSet('up', 'status', 'url', 'start', 'down')][string]$Command = 'status',
    [ValidateSet('quic', 'http2')][string]$Protocol = 'quic',
    [string]$Cloudflared = '',
    [switch]$NoTunnel,
    [string]$Site = '',
    [switch]$GitPush,
    [double]$Delay = 360,
    [double]$Interval = 300,
    [string]$FormUrl = '',
    [string]$RegisterForm = '',
    [string]$Registrations = '',
    [switch]$PublishCode,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$State = Join-Path $Root '.event'
$EnvFile = Join-Path $State 'event.env'
$PidFile = Join-Path $State 'pids.json'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = Join-Path $Root 'venv\Scripts\python.exe' }
if (-not (Test-Path $Python)) { $Python = 'python' }
New-Item -ItemType Directory -Force -Path $State | Out-Null

function New-Secret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return -join ($buffer | ForEach-Object { $_.ToString('x2') })
}

function Get-Settings {
    $settings = @{}
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match '^([A-Z_]+)=(.*)$') { $settings[$Matches[1]] = $Matches[2] }
        }
    }
    $changed = $false
    foreach ($pair in @(@('ADMIN_KEY', 16), @('JOIN_CODE', 3), @('BOT_PLACEHOLDER', 16))) {
        if (-not $settings.ContainsKey($pair[0])) { $settings[$pair[0]] = New-Secret $pair[1]; $changed = $true }
    }
    if ($changed) {
        ($settings.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -Encoding ascii $EnvFile
    }
    return $settings
}

function Get-Pids {
    if (Test-Path $PidFile) { return (Get-Content $PidFile -Raw | ConvertFrom-Json) }
    return $null
}

function Test-Alive($ProcessId) {
    if (-not $ProcessId) { return $false }
    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Get-TunnelUrl {
    $log = Join-Path $State 'tunnel.log'
    if (-not (Test-Path $log)) { return $null }
    $m = [regex]::Matches((Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($m.Count -gt 0) { return $m[$m.Count - 1].Value }
    return $null
}

function Find-Cloudflared {
    if ($Cloudflared) { return $Cloudflared }
    $found = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $local = Join-Path $Root 'tools\cloudflared.exe'
    if (Test-Path $local) { return $local }
    return $null
}

function Invoke-Api($Method, $Path, $Body = $null, $Admin = $false) {
    $uri = "http://127.0.0.1:$Port$Path"
    $headers = @{}
    if ($Admin) { $headers['Authorization'] = "Bearer $((Get-Settings)['ADMIN_KEY'])" }
    if ($Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType 'application/json' -Body ($Body | ConvertTo-Json) -TimeoutSec 10
    }
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -TimeoutSec 10
}

function Show-Info {
    $s = Get-Settings
    $url = Get-TunnelUrl
    Write-Host ''
    Write-Host "Server (this PC):  http://127.0.0.1:$Port"
    if ($url) { Write-Host "Public address:    $url" } else { Write-Host 'Public address:    (no tunnel running)' }
    Write-Host "Join code:         $($s['JOIN_CODE'])"
    Write-Host "Admin key:         $($s['ADMIN_KEY'])   (keep private)"
    if ($url) {
        Write-Host ''
        Write-Host 'Players register with:'
        Write-Host "  Invoke-RestMethod -Method Post $url/v1/register -ContentType 'application/json' -Body '{`"player_id`":`"TEAM`",`"code`":`"$($s['JOIN_CODE'])`"}'"
    }
}

switch ($Command) {
    'up' {
        $existing = Get-Pids
        if ($existing -and (Test-Alive $existing.server)) { throw 'Already running. Use "down" first.' }
        $s = Get-Settings

        # 1. the poker server (its own random keys; the published dev keys are NOT active)
        $env:POKER_ADMIN_API_KEY = $s['ADMIN_KEY']
        $env:ADMIN_API_KEYS = "admin:$($s['ADMIN_KEY'])"
        $env:BOT_API_KEYS = "unused:$($s['BOT_PLACEHOLDER'])"
        $env:REGISTRATION_CODE = $s['JOIN_CODE']
        $env:PYTHONUNBUFFERED = '1'
        $server = Start-Process -FilePath $Python -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
            -ArgumentList @('-m', 'uvicorn', 'server.run_poker_server:app', '--host', '127.0.0.1', '--port', "$Port") `
            -RedirectStandardOutput (Join-Path $State 'server.log') -RedirectStandardError (Join-Path $State 'server.err.log')
        $pids = @{ server = $server.Id; tunnel = 0; live = 0 }
        $ok = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            try { if ((Invoke-Api 'Get' '/health').ok) { $ok = $true; break } } catch { }
        }
        if (-not $ok) { Stop-Process -Id $server.Id -Force; throw "The server did not start; see $State\server.err.log" }
        Write-Host 'Server is up.'

        # 2. the public tunnel
        if (-not $NoTunnel) {
            $exe = Find-Cloudflared
            if (-not $exe) {
                Write-Host 'cloudflared was not found: no public address. Put cloudflared.exe in .\tools\ (or use -Cloudflared PATH), or pass -NoTunnel.'
            } else {
                Remove-Item (Join-Path $State 'tunnel.log') -ErrorAction SilentlyContinue
                $tunnel = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru `
                    -ArgumentList @('tunnel', '--no-autoupdate', '--protocol', $Protocol, '--url', "http://127.0.0.1:$Port") `
                    -RedirectStandardError (Join-Path $State 'tunnel.log') -RedirectStandardOutput (Join-Path $State 'tunnel.out.log')
                $pids.tunnel = $tunnel.Id
                $connected = $false
                for ($i = 0; $i -lt 40; $i++) {
                    Start-Sleep -Seconds 1
                    $text = if (Test-Path (Join-Path $State 'tunnel.log')) { Get-Content (Join-Path $State 'tunnel.log') -Raw } else { '' }
                    if ($text -match 'Registered tunnel connection') { $connected = $true; break }
                    if ($text -match 'x509: certificate signed by unknown authority') { break }
                }
                if ($connected) { Write-Host "Tunnel is up ($Protocol)." }
                else {
                    Write-Host "The tunnel did not connect with -Protocol $Protocol. See $State\tunnel.log."
                    if ($Protocol -eq 'http2') { Write-Host 'If it says x509 / unknown authority, the network intercepts HTTPS: use -Protocol quic.' }
                    else { Write-Host 'If UDP is blocked here, try -Protocol http2.' }
                }
            }
        }

        # 3. the live feed for the website
        if ($Site) {
            $url = Get-TunnelUrl
            $liveArgs = @('-m', 'arena', 'live', '--server', "http://127.0.0.1:$Port", '--out', $Site,
                          '--delay', "$Delay", '--interval', "$Interval")
            if ($url) { $liveArgs += @('--server-url', $url) }
            if ($PublishCode) { $liveArgs += @('--join-code', $s['JOIN_CODE']) }
            if ($FormUrl) { $liveArgs += @('--form-url', $FormUrl) }
            if ($RegisterForm) { $liveArgs += @('--register-form', $RegisterForm) }
            if ($Registrations) { $liveArgs += @('--registrations', $Registrations) }
            if ($GitPush) { $liveArgs += '--git-push' }
            $live = Start-Process -FilePath $Python -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
                -ArgumentList $liveArgs `
                -RedirectStandardOutput (Join-Path $State 'live.log') -RedirectStandardError (Join-Path $State 'live.err.log')
            $pids.live = $live.Id
            Write-Host "Live feed publishing to $Site every $Interval s ($Delay s behind)."
        }
        $pids | ConvertTo-Json | Set-Content $PidFile
        Show-Info
    }
    'status' {
        $p = Get-Pids
        if (-not $p) { Write-Host 'Nothing started by this script.'; break }
        Write-Host ("server: {0}   tunnel: {1}   live feed: {2}" -f (Test-Alive $p.server), (Test-Alive $p.tunnel), (Test-Alive $p.live))
        try {
            Write-Host ("lobby: {0}" -f ((Invoke-Api 'Get' '/v1/lobby').players -join ', '))
            $t = Invoke-Api 'Get' '/v1/tournament'
            Write-Host ("tournament: {0}, round {1}, champion {2}" -f $t.status, $t.round, $t.champion)
        } catch { Write-Host 'The server is not answering.' }
        Show-Info
    }
    'url' { Show-Info }
    'start' {
        $lobby = (Invoke-Api 'Get' '/v1/lobby').players
        Write-Host ("In the lobby: {0}" -f ($lobby -join ', '))
        if ($lobby.Count -lt 2) { throw 'At least 2 bots must be in the lobby.' }
        $body = @{ starting_stack = 1000; small_blind = 10; big_blind = 20; turn_timeout_seconds = 15; blind_increase_every_hands = 10; max_hands = 500 }
        $result = Invoke-Api 'Post' '/v1/tournament/start' $body $true
        Write-Host ("Started: {0} tables in round 1." -f $result.tables.Count)
    }
    'down' {
        $p = Get-Pids
        if (-not $p) { Write-Host 'Nothing to stop.'; break }
        foreach ($name in @('live', 'tunnel', 'server')) {
            $id = $p.$name
            if ($id -and (Test-Alive $id)) { Stop-Process -Id $id -Force; Write-Host "stopped $name" }
        }
        Remove-Item $PidFile -ErrorAction SilentlyContinue
    }
}
