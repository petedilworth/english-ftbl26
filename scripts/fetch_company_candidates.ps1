<#
    Fetch Companies House search results for every club that needs one.

    WHY THIS RUNS ON YOUR MACHINE. api.company-information.service.gov.uk
    is refused at the agent environment's proxy, exactly as en.wikipedia.org
    was. So this script does the fetching and nothing else: it makes no
    judgement about which company is which club. That happens in
    scripts/find_club_companies.py, in the repository, under test.

    YOUR API KEY STAYS HERE. It is read from the CH_API_KEY environment
    variable, is never written to a file, and must not be pasted into the
    chat. Register a free one at developer.company-information.service.gov.uk.

    WHAT IT WRITES. One JSON file per query, named
    <club_id>__<kind><n>.json, in
    the output directory. Re-running skips files that already exist, so an
    interrupted run resumes rather than starting over.

    HOW TO RUN IT (PowerShell, from the repository root). The list of
    clubs to look up is committed at data/companies/targets.tsv, so no
    Python is needed on this side:

        $env:CH_API_KEY = "your-key-here"
        ./scripts/fetch_company_candidates.ps1
        Compress-Archive -Path ch-json\* -DestinationPath ch-json.zip

    Then attach ch-json.zip. About 1,540 requests, fifteen minutes.
#>

param(
    [string]$Targets = "data/companies/targets.tsv",
    [string]$Out = "ch-json",
    # The published limit is 600 requests per five minutes per API key,
    # which is one every 500 ms. 550 ms leaves room for the retries.
    [int]$DelayMs = 550
)

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 (as opposed to PowerShell 7+) defaults its HTTPS
# client to an older TLS version on many machines and never negotiates up
# to TLS 1.2 on its own. Companies House requires TLS 1.2, and the failure
# this produces is not an HTTP error - the connection never completes, so
# Invoke-WebRequest throws with no response object at all, which reads
# below as "HTTP 0" on every attempt. Forcing it here means the person
# running this never has to diagnose that by hand.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $env:CH_API_KEY) {
    Write-Error "Set CH_API_KEY first:  `$env:CH_API_KEY = 'your-key'"
    exit 1
}

# Companies House uses HTTP Basic with the key as the username and an
# empty password.
$pair = [System.Text.Encoding]::ASCII.GetBytes($env:CH_API_KEY + ":")
$headers = @{
    Authorization = "Basic " + [System.Convert]::ToBase64String($pair)
    # A real User-Agent naming the project. The Wikipedia fetch was rate
    # limited into silence without one.
    "User-Agent"  = "english-ftbl26 club-accounts (github.com/petedilworth/english-ftbl26)"
}

# $PWD follows `cd`, but [Environment]::CurrentDirectory - what a raw
# .NET call like [System.IO.File]::WriteAllText resolves a RELATIVE path
# against, as opposed to a cmdlet like New-Item or Test-Path, which both
# follow $PWD correctly - does not reliably track it in Windows
# PowerShell 5.1. A relative $Out silently wrote under the user's profile
# directory instead of the repository, and that write failure was then
# caught by the same try/catch as the network call below and misreported
# as a dropped connection. Resolving it to an absolute path here removes
# the ambiguity regardless of which "current directory" anything uses.
$Out = Join-Path (Get-Location).Path $Out

New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Get-Json($url, $path) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $url -Headers $headers `
                -UseBasicParsing -TimeoutSec 30
        } catch {
            $code = 0
            if ($_.Exception.Response) {
                $code = [int]$_.Exception.Response.StatusCode
            }
            if ($code -eq 401 -or $code -eq 403) {
                Write-Error "Companies House rejected the key (HTTP $code). Stopping."
                exit 1
            }
            if ($code -eq 404) { return "missing" }
            # 429 and the 5xx family: back off and try again. Code 0 means
            # the connection itself never completed - no HTTP response at
            # all - which is not something retrying fixes on its own, so
            # the underlying error is shown once rather than just "HTTP 0"
            # five times in a row.
            $wait = [math]::Pow(2, $attempt)
            if ($code -eq 0) {
                Write-Host ("    connection failed ({0}); waiting {1}s" -f `
                    $_.Exception.Message, $wait)
            } else {
                Write-Host ("    HTTP {0}; waiting {1}s" -f $code, $wait)
            }
            Start-Sleep -Seconds $wait
            continue
        }
        # Outside the catch on purpose: a response came back, so writing
        # it to disk is not a network failure and must not be retried as
        # one. If this throws - a bad path, a full disk, a file locked by
        # antivirus - it should stop the run and say so plainly rather
        # than being absorbed into five identical "connection failed"
        # lines that had nothing to do with the connection.
        [System.IO.File]::WriteAllText($path, $response.Content)
        return "ok"
    }
    return "failed"
}

$rows = Import-Csv -Path $Targets -Delimiter "`t"
$done = 0; $skipped = 0; $failed = @()
$total = $rows.Count
$api = "https://api.company-information.service.gov.uk"

foreach ($row in $rows) {
    $n = 0
    foreach ($query in ($row.queries -split '\|')) {
        $n++
        # Each query is "kind:term". The kind decides the endpoint,
        # because no one of them finds every club - see the comment on
        # queries() in scripts/find_club_companies.py.
        $kind, $term = $query -split ':', 2
        $encoded = [uri]::EscapeDataString($term)

        # Cleared first. `continue` inside a PowerShell switch leaves the
        # switch rather than the enclosing loop, so an unrecognised kind
        # would otherwise fall through to the PREVIOUS query's $url and
        # save that response under this query's filename.
        $url = $null
        switch ($kind) {
            # Relevance-ranked. The one that finds a club whose
            # registered name is nothing like its football name.
            "plain" { $url = "$api/search/companies?q=$encoded&items_per_page=30" }
            # Name contains every word given. Alphabetical, so the term
            # has to be specific enough to fit inside 100 results.
            "adv"   { $url = "$api/advanced-search/companies?company_name_includes=$encoded&size=100" }
            # Sport clubs of that name only: 93120 cuts thousands of
            # companies down to a handful, and carries the SIC codes the
            # scorer wants anyway.
            "sic"   { $url = "$api/advanced-search/companies?company_name_includes=$encoded&sic_codes=93120&size=100" }
            default { Write-Host ("    unknown query kind '{0}' - skipping" -f $kind) }
        }
        if (-not $url) { continue }

        $path = Join-Path $Out ("{0}__{1}{2}.json" -f $row.club_id, $kind, $n)
        if (Test-Path $path) {
            $skipped++
            continue
        }
        $state = Get-Json $url $path
        if ($state -eq "failed") { $failed += "$($row.club_id) $kind '$term'" }
        Start-Sleep -Milliseconds $DelayMs
    }
    $done++
    if ($done % 20 -eq 0) {
        Write-Host ("{0}/{1} clubs" -f $done, $total)
    }
}

Write-Host ("Done: {0} clubs, {1} files already present, {2} failed" -f `
    $done, $skipped, $failed.Count)
if ($failed.Count) {
    Write-Host "Failed queries (re-run the script to retry them):"
    $failed | ForEach-Object { Write-Host "    $_" }
}
