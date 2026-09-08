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

    WHAT IT WRITES. One JSON file per query, named <club_id>__<n>.json, in
    the output directory. Re-running skips files that already exist, so an
    interrupted run resumes rather than starting over.

    HOW TO RUN IT (PowerShell, from the repository root). The list of
    clubs to look up is committed at data/companies/targets.tsv, so no
    Python is needed on this side:

        $env:CH_API_KEY = "your-key-here"
        ./scripts/fetch_company_candidates.ps1
        Compress-Archive -Path ch-json\* -DestinationPath ch-json.zip

    Then attach ch-json.zip. About 660 requests, six to eight minutes.
#>

param(
    [string]$Targets = "data/companies/targets.tsv",
    [string]$Out = "ch-json",
    # The published limit is 600 requests per five minutes per API key,
    # which is one every 500 ms. 550 ms leaves room for the retries.
    [int]$DelayMs = 550
)

$ErrorActionPreference = "Stop"

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

New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Get-Json($url, $path) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $url -Headers $headers `
                -UseBasicParsing -TimeoutSec 30
            [System.IO.File]::WriteAllText($path, $response.Content)
            return "ok"
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
            # 429 and the 5xx family: back off and try again.
            $wait = [math]::Pow(2, $attempt)
            Write-Host ("    HTTP {0}; waiting {1}s" -f $code, $wait)
            Start-Sleep -Seconds $wait
        }
    }
    return "failed"
}

$rows = Import-Csv -Path $Targets -Delimiter "`t"
$done = 0; $skipped = 0; $failed = @()
$total = $rows.Count

foreach ($row in $rows) {
    $terms = $row.terms -split '\|'
    $n = 0
    foreach ($term in $terms) {
        $n++
        $encoded = [uri]::EscapeDataString($term)

        # The advanced search is the one that matters: its results carry
        # sic_codes, and SIC 93120 is the strongest signal that a company
        # is a club rather than something named after one.
        $path = Join-Path $Out ("{0}__{1}.json" -f $row.club_id, $n)
        if (Test-Path $path) {
            $skipped++
        } else {
            $url = "https://api.company-information.service.gov.uk/advanced-search/companies?company_name_includes=$encoded&size=100"
            $state = Get-Json $url $path
            if ($state -eq "failed") { $failed += "$($row.club_id) advanced '$term'" }
            Start-Sleep -Milliseconds $DelayMs
        }

        # The plain search finds companies whose name does not contain
        # every word of the club's - only worth one extra call, on the
        # club's full name.
        if ($n -eq 1) {
            $path = Join-Path $Out ("{0}__0.json" -f $row.club_id)
            if (Test-Path $path) {
                $skipped++
            } else {
                $url = "https://api.company-information.service.gov.uk/search/companies?q=$encoded&items_per_page=30"
                $state = Get-Json $url $path
                if ($state -eq "failed") { $failed += "$($row.club_id) search '$term'" }
                Start-Sleep -Milliseconds $DelayMs
            }
        }
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
