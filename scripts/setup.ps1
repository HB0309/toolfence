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

    foreach ($patch in $patches) {
        $patchPath = Resolve-Path $patch.FullName

        # Check if the patch is already applied; skip if so.
        # Use a local Continue scope so the git stderr output does not trip Stop mode.
        $alreadyApplied = $false
        $ErrorActionPreference = "Continue"
        git -C $TargetDir apply --check --reverse $patchPath 2>$null
        if ($LASTEXITCODE -eq 0) { $alreadyApplied = $true }
        $ErrorActionPreference = "Stop"

        if ($alreadyApplied) {
            Write-Host "[SKIP] $($patch.Name) already applied" -ForegroundColor Yellow
            continue
        }

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
