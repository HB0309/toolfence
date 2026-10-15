# scripts/setup.ps1
# Fetch both target repos at their pinned commits and apply patches.
# Usage: .\scripts\setup.ps1   (from workspace root)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GALAXIUM_URL  = "https://github.com/IBM/galaxium-travels.git"
$GALAXIUM_HASH = "6163380cdb4ba50caee0b82c66afc4700d90546a"
$GALAXIUM_DIR  = "targets\galaxium"

$NANOBOT_URL   = "https://github.com/HKUDS/nanobot.git"
$NANOBOT_HASH  = "948ce3824653d55b18ff1c618613fb642679bab7"
$NANOBOT_DIR   = "targets\nanobot"

$PassCount = 0
$FailCount = 0

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )
    try {
        & $Action
        Write-Host "[PASS] $Label" -ForegroundColor Green
        $script:PassCount++
    } catch {
        Write-Host "[FAIL] $Label - $_" -ForegroundColor Red
        $script:FailCount++
        throw
    }
}

function Fetch-Target {
    param(
        [string]$Name,
        [string]$Url,
        [string]$Hash,
        [string]$Dir
    )
    if (Test-Path $Dir) {
        Invoke-Step "Verify $Name at pinned commit" {
            $head = (git -C $Dir rev-parse HEAD).Trim()
            if ($LASTEXITCODE -ne 0) { throw "git rev-parse failed" }
            if ($head -ne $Hash) {
                throw "$Dir exists but HEAD is $head, expected $Hash"
            }
        }
    } else {
        Invoke-Step "Clone $Name" {
            git clone $Url $Dir
            if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
        }
        Invoke-Step "Checkout $Name $($Hash.Substring(0,7))" {
            git -C $Dir checkout $Hash
            if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
        }
    }
}

function Apply-Patches {
    param(
        [string]$Name,
        [string]$TargetDir,
        [string]$PatchDir
    )
    if (-not (Test-Path $PatchDir)) {
        Write-Host "[SKIP] No patch directory found for $Name ($PatchDir)" -ForegroundColor Yellow
        return
    }

    $patches = @(Get-ChildItem -Path $PatchDir -Filter "*.patch" | Sort-Object Name)

    if ($patches.Count -eq 0) {
        Write-Host "[SKIP] No patches found in $PatchDir" -ForegroundColor Yellow
        return
    }

    # Find the highest-numbered patch that is already applied by scanning
    # newest-to-oldest with "git apply --check --reverse".  A single per-patch
    # reverse-check breaks when a later patch changes lines adjacent to an
    # earlier patch's context, so we walk from the end and stop at the first
    # match.  Every patch at or before that index is considered applied; only
    # patches after it are applied.
    $firstToApply = 0   # index into $patches; 0 = apply everything

    $ErrorActionPreference = "Continue"
    for ($i = $patches.Count - 1; $i -ge 0; $i--) {
        $patchPath = Resolve-Path $patches[$i].FullName
        git -C $TargetDir apply --check --reverse $patchPath 2>$null
        if ($LASTEXITCODE -eq 0) {
            # This patch (and all before it) are applied.
            $firstToApply = $i + 1
            break
        }
    }
    $ErrorActionPreference = "Stop"

    # Report skipped patches.
    for ($i = 0; $i -lt $firstToApply; $i++) {
        Write-Host "[SKIP] $($patches[$i].Name) already applied" -ForegroundColor Yellow
    }

    # Apply remaining patches in order.
    for ($i = $firstToApply; $i -lt $patches.Count; $i++) {
        $patch     = $patches[$i]
        $patchPath = Resolve-Path $patch.FullName
        Invoke-Step "Apply $($patch.Name)" {
            git -C $TargetDir apply $patchPath
            if ($LASTEXITCODE -ne 0) { throw "git apply failed" }
        }
    }
}

# == Fetch targets ==
Fetch-Target -Name "galaxium" -Url $GALAXIUM_URL -Hash $GALAXIUM_HASH -Dir $GALAXIUM_DIR
Fetch-Target -Name "nanobot"  -Url $NANOBOT_URL  -Hash $NANOBOT_HASH  -Dir $NANOBOT_DIR

# == Apply patches ==
Apply-Patches -Name "galaxium" -TargetDir $GALAXIUM_DIR -PatchDir "targets\galaxium-patches"
Apply-Patches -Name "nanobot"  -TargetDir $NANOBOT_DIR  -PatchDir "targets\nanobot-patches"

# == Summary ==
Write-Host ""
Write-Host "== Setup complete - $PassCount passed, $FailCount failed ==" -ForegroundColor Cyan
