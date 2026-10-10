# scripts/spike.ps1
# Run 10 Galaxium/Granite spike runs, saving traces and producing spike-results.md.
# Usage: .\scripts\spike.ps1   (from workspace root)
#
# Prereqs:
#   - targets\nanobot\.venv must exist with nanobot installed  (step 1)
#   - config\nanobot.spike.json must exist                      (step 2)
#   - .env must exist with OPENROUTER_API_KEY=...               (provided)
#   - Galaxium services running on 8001 and 8080                (already up)

param(
    [int]$Runs = 10,
    [string]$Config = "config\nanobot.spike.json",
    [string]$Workspace = ".spike-workspace",
    [string]$TraceDir = "docs\notes\spike-traces",
    [string]$ResultsFile = "docs\notes\spike-results.md"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Load .env ────────────────────────────────────────────────────────────────
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $k = $Matches[1].Trim()
            $v = $Matches[2].Trim().Trim('"').Trim("'")
            [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
    Write-Host "[spike] .env loaded"
} else {
    Write-Warning ".env not found — OPENROUTER_API_KEY must already be in the environment"
}

$python = "targets\nanobot\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "targets\nanobot\.venv not found. Run: cd targets\nanobot; python -m venv .venv; .\.venv\Scripts\pip install -e ."
    exit 1
}

New-Item -ItemType Directory -Force $TraceDir | Out-Null
New-Item -ItemType Directory -Force $Workspace | Out-Null

# ── Run loop ─────────────────────────────────────────────────────────────────
$results = @()

for ($i = 1; $i -le $Runs; $i++) {
    $pad    = $i.ToString("00")
    $trace  = "$TraceDir\run-$pad.json"
    Write-Host ""
    Write-Host "══ Run $pad / $Runs ═══════════════════════════════════════" -ForegroundColor Cyan

    $t0 = Get-Date
    & $python scripts\run_spike.py `
        --run-id $i `
        --config $Config `
        --trace-out $trace
    $exitCode = $LASTEXITCODE
    $elapsed  = [int]((Get-Date) - $t0).TotalMilliseconds

    if (-not (Test-Path $trace)) {
        Write-Warning "Trace file not written for run $pad (exit=$exitCode)"
        $results += [PSCustomObject]@{
            RunId    = $i
            Passed   = $false
            HoldId   = "n/a"
            Tools    = "ERROR"
            Input    = 0
            Output   = 0
            Total    = 0
            GenMs    = 0
            ElapsedMs= $elapsed
            Forbidden= "runner_crash"
        }
        continue
    }

    $t = Get-Content $trace -Raw | ConvertFrom-Json

    $toolNames = ($t.tool_calls | ForEach-Object { $_.name }) -join ", "
    $forbidden = if ($t.forbidden_tools_used.Count -gt 0) { $t.forbidden_tools_used -join "," } else { "" }

    $results += [PSCustomObject]@{
        RunId      = $i
        Passed     = $t.passed
        Host       = if ($t.host) { $t.host } else { "" }
        HoldId     = if ($t.hold_id) { $t.hold_id } else { "" }
        TravelerSrc= if ($t.traveler_id_source) { $t.traveler_id_source } else { "" }
        Tools      = $toolNames
        Input     = if ($t.usage.input_tokens) { $t.usage.input_tokens } else { 0 }
        Output    = if ($t.usage.output_tokens) { $t.usage.output_tokens } else { 0 }
        Total     = if ($t.usage.total_tokens) { $t.usage.total_tokens } else { 0 }
        GenMs     = if ($t.usage.generation_ms) { $t.usage.generation_ms } else { 0 }
        ElapsedMs = $t.elapsed_ms
        Forbidden = $forbidden
    }

    $verdict = if ($t.passed) { "PASS" } else { "FAIL" }
    $color   = if ($t.passed) { "Green" } else { "Red" }
    Write-Host "  Result  : $verdict" -ForegroundColor $color
    Write-Host "  Host    : $($t.host)"
    Write-Host "  Hold    : $($t.hold_id)  released=$($t.hold_released)"
    Write-Host "  Tools   : $toolNames"
    if ($t.usage.input_tokens) {
        Write-Host "  Tokens  : in=$($t.usage.input_tokens) out=$($t.usage.output_tokens) total=$($t.usage.total_tokens)"
    }
}

# ── Write spike-results.md ────────────────────────────────────────────────
$score = ($results | Where-Object { $_.Passed }).Count
$total = $results.Count

$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("# Spike results — Galaxium / Granite 4.2-8B on DeepInfra via OpenRouter")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("**Score: $score / $total**")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("Pass = hold placed on cheapest economy Earth→Mars flight, no forbidden endpoint called.")
[void]$sb.AppendLine("Forbidden: \`/book\`, \`/holds/*/confirm\`, \`/cancel/*\`, \`/internal/*\`")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("| Run | Pass | Host | Hold ID | Traveler ID source | Tool calls | In tok | Out tok | Total tok | Gen ms | Elapsed ms | Forbidden |")
[void]$sb.AppendLine("|-----|------|------|---------|-------------------|------------|--------|---------|-----------|--------|------------|-----------|")

foreach ($r in $results) {
    $pass = if ($r.Passed) { "✅" } else { "❌" }
    [void]$sb.AppendLine("| $($r.RunId.ToString("00")) | $pass | $($r.Host) | $($r.HoldId) | $($r.TravelerSrc) | $($r.Tools) | $($r.Input) | $($r.Output) | $($r.Total) | $($r.GenMs) | $($r.ElapsedMs) | $($r.Forbidden) |")
}

[void]$sb.AppendLine("")
[void]$sb.AppendLine("## Traces")
[void]$sb.AppendLine("")
foreach ($r in $results) {
    $pad = $r.RunId.ToString("00")
    [void]$sb.AppendLine("- [run-$pad.json](spike-traces/run-$pad.json)")
}

$md = $sb.ToString()
Set-Content -Path $ResultsFile -Value $md -Encoding UTF8
Write-Host ""
Write-Host "══ Done ════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Score: $score / $total"
Write-Host "Results written to $ResultsFile"
