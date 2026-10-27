param(
    [ValidateSet("smoke", "thesis")]
    [string]$Profile = "smoke"
)

$ErrorActionPreference = "Stop"
$Repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Repository ".venv\Scripts\python.exe"
$Dataset = Join-Path $Repository "data\raw\uci-heart-disease\heart-disease.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Scientific environment is missing. Create .venv and install requirements-scientific.txt."
}
if (-not (Test-Path -LiteralPath $Dataset)) {
    throw "UCI archive is missing. Run scripts\download_uci_heart.py first."
}

$env:PYTHONPATH = Join-Path $Repository "src"
Push-Location $Repository
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }

    if ($Profile -eq "thesis") {
        & $Python -m healthfl.scientific.real_uci_experiment --seeds 101 202 303 --rounds 10 --output results/uci-heart
        if ($LASTEXITCODE -ne 0) { throw "UCI utility experiment failed." }
        & $Python -m healthfl.ckks_benchmark --lengths 49 361 1024 4096 4097 --clients 4 --trials 3 --output results/ckks
        if ($LASTEXITCODE -ne 0) { throw "CKKS benchmark failed." }
        & $Python -m healthfl.scientific.secure_uci_experiment --seed 101 --rounds 10 --output results/secure-uci
        if ($LASTEXITCODE -ne 0) { throw "Secure UCI experiment failed." }
        & $Python -m healthfl.scientific.poisoning_experiment --seed 101 --rounds 5 --output results/poisoning
        if ($LASTEXITCODE -ne 0) { throw "Poisoning experiment failed." }
        & $Python -m healthfl.scientific.governed_inference_experiment --seed 101 --training-rounds 3 --output results/governed-inference/summary.json
        if ($LASTEXITCODE -ne 0) { throw "Governed inference experiment failed." }
    }

    & $Python scripts/build_thesis_artifacts.py
    if ($LASTEXITCODE -ne 0) { throw "Thesis artifact build failed." }
}
finally {
    Pop-Location
}
