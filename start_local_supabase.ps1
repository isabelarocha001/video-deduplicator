$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

Write-Host "Inicialização local do Video Deduplicator" -ForegroundColor Cyan
Write-Host "As chaves serão usadas somente nesta sessão e não serão gravadas em arquivo." -ForegroundColor DarkGray
Write-Host ""

$projectUrl = Read-Host "URL do projeto Supabase (ex.: https://seu-projeto.supabase.co)"
if ($null -eq $projectUrl) { $projectUrl = "" }
$projectUrl = $projectUrl.Trim().TrimEnd("/")
if ($projectUrl -notmatch '^https?://[^/]+$') {
    throw "URL do Supabase inválida. Use o endereço completo, por exemplo https://seu-projeto.supabase.co"
}

$secureServiceKey = Read-Host "Chave service_role do Supabase (não será exibida)" -AsSecureString
$keyPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureServiceKey)
try {
    $serviceKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPtr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPtr)
}
if ([string]::IsNullOrWhiteSpace($serviceKey)) {
    throw "A chave service_role não pode ficar vazia."
}

$bucket = Read-Host "Nome do bucket do Storage [vd-media]"
if ([string]::IsNullOrWhiteSpace($bucket)) { $bucket = "vd-media" }

$env:SUPABASE_URL = $projectUrl
$env:SUPABASE_SERVICE_ROLE_KEY = $serviceKey
$env:SUPABASE_STORAGE_BUCKET = $bucket.Trim()
$env:SUPABASE_STORAGE_PUBLIC = "false"
$env:SUPABASE_STORAGE_SIGNED_TTL = "86400"

# Recarrega o PATH do Windows para localizar FFmpeg/ffprobe instalados.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

$portInUse = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    throw "A porta 8000 já está em uso. Pare o servidor atual com Ctrl+C e execute este script novamente."
}

if (-not (Test-Path -LiteralPath ".\.venv\Scripts\uvicorn.exe")) {
    throw "Ambiente virtual não encontrado em .venv."
}

Write-Host "Supabase configurado apenas na memória deste processo." -ForegroundColor Green
Write-Host "Abrindo http://127.0.0.1:8000/process.html" -ForegroundColor Green
& ".\.venv\Scripts\uvicorn.exe" main:app --host 127.0.0.1 --port 8000
