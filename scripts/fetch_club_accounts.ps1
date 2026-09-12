<#
    Fetch each mapped club's two most recent sets of statutory accounts.

    Stage 2 of docs/club-accounts.md. Stage 1 decided WHICH company files
    a club's accounts; this fetches what that company filed, and makes no
    judgement of its own. The parsing happens in the repository, under
    test, in scripts/parse_club_accounts.py.

    WHAT IT READS. data/club-companies.tsv, committed, filtered to the
    rows stage 1 marked `chosen`. The rows marked `review` are skipped on
    purpose: a filing fetched against the wrong company is worse than no
    filing, because the figures in it are real and belong to someone else.

    WHAT IT WRITES, per club, into the output directory:

        <club_id>__filings.json   the accounts filing history
        <club_id>__<n>.xhtml      the nth filing as iXBRL, machine-readable
        <club_id>__<n>.pdf        the nth filing where only a PDF exists

    The extension is the finding. A scanned PDF carries no tagged figures
    and cannot be parsed; recording that as a PDF says so, where silently
    writing nothing would look like a fetch that failed.

    YOUR API KEY STAYS HERE, read from CH_API_KEY, never written to a
    file. The same key works for both APIs this uses.

    HOW TO RUN IT (PowerShell, from the repository root):

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
        $env:CH_API_KEY = "your-key-here"
        ./scripts/fetch_club_accounts.ps1
        Compress-Archive -Path ch-accounts\* -DestinationPath ch-accounts.zip -Force

    178 companies, about 1,300 requests, fifteen to twenty minutes. The
    documents are the bulk of it - expect a few hundred MB on disk and a
    far smaller zip, because iXBRL is XHTML and compresses hard.
#>

param(
    [string]$Mapping = "data/club-companies.tsv",
    [string]$Out = "ch-accounts",
    # Two filings gives the year-on-year change the club pages already
    # know how to show. More is not wanted: the brief was more clubs, not
    # more history.
    [int]$Filings = 2,
    [int]$DelayMs = 550
)

$ErrorActionPreference = "Stop"

# See the note in fetch_company_candidates.ps1: Windows PowerShell 5.1
# will not negotiate up to TLS 1.2 on its own, and the failure is a
# connection that never completes rather than an HTTP error.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $env:CH_API_KEY) {
    Write-Error "Set CH_API_KEY first:  `$env:CH_API_KEY = 'your-key'"
    exit 1
}

$pair = [System.Text.Encoding]::ASCII.GetBytes($env:CH_API_KEY + ":")
$auth = "Basic " + [System.Convert]::ToBase64String($pair)
$agent = "english-ftbl26 club-accounts (github.com/petedilworth/english-ftbl26)"
$headers = @{ Authorization = $auth; "User-Agent" = $agent }

# Absolute, so the raw .NET writes below cannot land in whatever
# directory .NET thinks is current - see fetch_company_candidates.ps1.
$Out = Join-Path (Get-Location).Path $Out
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Get-Json($url, $path) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $url -Headers $headers `
                -UseBasicParsing -TimeoutSec 30
        } catch {
            $code = 0
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            if ($code -eq 401 -or $code -eq 403) {
                Write-Error "Companies House rejected the key (HTTP $code). Stopping."
                exit 1
            }
            if ($code -eq 404) { return $null }
            $wait = [math]::Pow(2, $attempt)
            if ($code -eq 0) {
                Write-Host ("    connection failed ({0}); waiting {1}s" -f $_.Exception.Message, $wait)
            } else {
                Write-Host ("    HTTP {0}; waiting {1}s" -f $code, $wait)
            }
            Start-Sleep -Seconds $wait
            continue
        }
        [System.IO.File]::WriteAllText($path, $response.Content)
        return $response.Content
    }
    return $null
}

<#
    Fetching one filing takes two requests, and both have a trap in them.

    FIRST, WHICH FORMAT. The document API does not serve every filing in
    every format: asking for application/xhtml+xml when a filing was
    submitted on paper returns 406 Not Acceptable, which is what this
    script did on every document of its first run. The metadata resource
    lists what actually exists for that filing, so it is read first and
    the Accept header is chosen from it - iXBRL where there is iXBRL, PDF
    where that is all there is.

    SECOND, THE REDIRECT. The content endpoint answers with a 302 to a
    pre-signed S3 URL, and S3 refuses a request carrying an Authorization
    header alongside its own signature ("only one auth mechanism
    allowed"). Invoke-WebRequest follows redirects AND re-sends headers,
    so the obvious spelling fails there too. Hence HttpWebRequest with
    redirects switched off, and no credentials on the second leg.
#>
function Invoke-Ch($url, $accept) {
    $req = [System.Net.HttpWebRequest]::Create($url)
    $req.Method = "GET"
    $req.Headers.Add("Authorization", $auth)
    $req.UserAgent = $agent
    if ($accept) { $req.Accept = $accept }
    $req.AllowAutoRedirect = $false
    $req.Timeout = 30000
    return $req.GetResponse()
}

function Get-Document($metadataUrl, $stem) {
    # What formats exist for this filing.
    $formats = @()
    try {
        $res = Invoke-Ch $metadataUrl "application/json"
        $reader = New-Object System.IO.StreamReader($res.GetResponseStream())
        $meta = ConvertFrom-Json $reader.ReadToEnd()
        $reader.Close(); $res.Close()
        if ($meta.resources) {
            $formats = @($meta.resources.PSObject.Properties.Name)
        }
    } catch {
        Write-Host ("    metadata request failed: {0}" -f $_.Exception.Message)
        return $false
    }

    # iXBRL is tagged and machine-readable; a PDF is a picture of
    # accounts. Take the first only where it exists.
    $accept = $null
    foreach ($candidate in @("application/xhtml+xml", "application/xml", "application/pdf")) {
        if ($formats -contains $candidate) { $accept = $candidate; break }
    }
    if (-not $accept) {
        Write-Host ("    no usable format ({0})" -f ($formats -join ", "))
        return $false
    }

    Start-Sleep -Milliseconds $DelayMs
    try {
        $res = Invoke-Ch "$metadataUrl/content" $accept
        $code = [int]$res.StatusCode
        $location = $res.Headers["Location"]
        $res.Close()
    } catch {
        Write-Host ("    document request failed: {0}" -f $_.Exception.Message)
        return $false
    }
    if ($code -lt 300 -or $code -ge 400 -or -not $location) {
        Write-Host ("    unexpected document response (HTTP {0})" -f $code)
        return $false
    }

    try {
        # No headers on this one. The signature in the URL is the auth.
        $signed = Invoke-WebRequest -Uri $location -UseBasicParsing -TimeoutSec 60
    } catch {
        Write-Host ("    document download failed: {0}" -f $_.Exception.Message)
        return $false
    }

    # The extension records what was actually served, because it is the
    # finding: a PDF carries no tagged figures and cannot be parsed.
    $ext = if ($accept -match "xhtml|xml") { "xhtml" } else { "pdf" }
    $path = "$stem.$ext"
    if ($signed.Content -is [string]) {
        [System.IO.File]::WriteAllText($path, $signed.Content)
    } else {
        [System.IO.File]::WriteAllBytes($path, $signed.Content)
    }
    return $true
}

$rows = @(Import-Csv -Path $Mapping -Delimiter "`t" | Where-Object { $_.state -eq "chosen" })
$api = "https://api.company-information.service.gov.uk"
$done = 0; $got = 0; $skipped = 0; $none = @()
$total = $rows.Count
Write-Host ("{0} clubs with a chosen company" -f $total)

foreach ($row in $rows) {
    $done++
    $listPath = Join-Path $Out ("{0}__filings.json" -f $row.club_id)

    if (Test-Path $listPath) {
        $body = [System.IO.File]::ReadAllText($listPath)
        $skipped++
    } else {
        $url = "$api/company/$($row.company_number)/filing-history?category=accounts&items_per_page=20"
        $body = Get-Json $url $listPath
        Start-Sleep -Milliseconds $DelayMs
    }
    if (-not $body) { $none += "$($row.club_id) (no filing history)"; continue }

    $items = @()
    try { $items = @((ConvertFrom-Json $body).items) } catch { }
    $items = @($items | Where-Object { $_ -and $_.links -and $_.links.document_metadata })
    if ($items.Count -eq 0) { $none += "$($row.club_id) (no accounts filed)"; continue }

    $n = 0
    foreach ($item in ($items | Select-Object -First $Filings)) {
        $n++
        $stem = Join-Path $Out ("{0}__{1}" -f $row.club_id, $n)
        if ((Test-Path "$stem.xhtml") -or (Test-Path "$stem.pdf")) {
            $skipped++
            continue
        }
        if (Get-Document $item.links.document_metadata $stem) { $got++ }
        Start-Sleep -Milliseconds $DelayMs
    }

    if ($done % 20 -eq 0) { Write-Host ("{0}/{1} clubs, {2} documents" -f $done, $total, $got) }
}

Write-Host ("Done: {0} clubs, {1} documents fetched, {2} already present" -f $done, $got, $skipped)
if ($none.Count) {
    Write-Host ("{0} clubs had nothing to fetch:" -f $none.Count)
    $none | ForEach-Object { Write-Host "    $_" }
}
