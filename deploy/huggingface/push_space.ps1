<#
.SYNOPSIS  Stage a clean copy of PolicyC and force-push it to a Hugging Face Space.
.EXAMPLE   .\deploy\huggingface\push_space.ps1 -Space myuser/policyc
Credentials: git prompts (username + HF write token) or uses your credential manager. No secret is
ever written to the staged folder or the remote URL.
#>
param(
  [Parameter(Mandatory = $true)][string]$Space,   # "<hf-user>/<space-name>"
  [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stage = Join-Path ([IO.Path]::GetTempPath()) ("policyc-space-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
  Copy-Item (Join-Path $root "Dockerfile.full") (Join-Path $stage "Dockerfile")
  Copy-Item (Join-Path $root ".dockerignore") $stage
  Copy-Item (Join-Path $PSScriptRoot "README_SPACE.md") (Join-Path $stage "README.md")

  # backend/ minus venv, secrets, runtime data, model weights, tests, caches
  $null = robocopy (Join-Path $root "backend") (Join-Path $stage "backend") /E /NFL /NDL /NJH /NJS /NP `
    /XD .venv data models tests __pycache__ .pytest_cache .ruff_cache `
    /XF .env .env.* *.log *.db *.sqlite
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
  $global:LASTEXITCODE = 0

  # The Dockerfile COPYs these paths unconditionally
  $seed = Join-Path $stage "backend\seed"
  New-Item -ItemType Directory -Force $seed | Out-Null
  if (-not (Get-ChildItem $seed -Force)) { New-Item -ItemType File (Join-Path $seed ".keep") | Out-Null }
  $dist = Join-Path $root "frontend\dist"
  $stageDist = Join-Path $stage "frontend\dist"
  if (Test-Path (Join-Path $dist "index.html")) { Copy-Item $dist $stageDist -Recurse }
  else { New-Item -ItemType Directory -Force $stageDist | Out-Null; New-Item -ItemType File (Join-Path $stageDist ".keep") | Out-Null }

  # Safety net: refuse to push if a secret-looking file slipped in
  $bad = Get-ChildItem $stage -Recurse -Force -File | Where-Object { $_.Name -like ".env*" -or $_.Extension -in ".pem", ".key" }
  if ($bad) { throw "Refusing to push, sensitive files staged: $($bad.FullName -join ', ')" }

  Push-Location $stage
  $ErrorActionPreference = "Continue"   # git writes warnings/progress to stderr
  git init -q -b $Branch
  git config core.autocrlf false
  git add -A
  git -c user.name="policyc-deploy" -c user.email="deploy@localhost" commit -q -m "Deploy PolicyC backend"
  if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
  git remote add space "https://huggingface.co/spaces/$Space"
  git push --force space "${Branch}:main"
  if ($LASTEXITCODE -ne 0) { throw "git push failed" }
  Pop-Location
  Write-Host "Pushed. Logs: https://huggingface.co/spaces/$Space  API: https://$($Space.Replace('/','-').ToLower()).hf.space/api/health"
}
finally {
  Set-Location $root
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
