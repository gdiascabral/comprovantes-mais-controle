# Registra (ou refaz) a tarefa do Agendador do Windows que roda a leitura das
# 07:30: saldo e extrato de ontem pela API (Sicoob e Inter), saldo do ERP pelo
# porteiro, pre-marcas de ontem na nuvem (python -m leitura_manha.rodar).
#
#   powershell -ExecutionPolicy Bypass -File registrar_leitura_manha.ps1 -Config C:\chaves\leitura-manha.json
#   powershell -ExecutionPolicy Bypass -File registrar_leitura_manha.ps1 -Config ... -Python C:\caminho\python.exe -Hora 07:30
#
# O que ela garante:
#   - roda todo dia na hora pedida (padrao 07:30), no usuario atual e com a
#     sessao dele aberta (o porteiro do ERP e um Chrome com janela);
#   - se o servidor estava desligado na hora, roda assim que ligar;
#   - no maximo 30 minutos; nao abre duas copias;
#   - roda na raiz do repositorio (python -m leitura_manha.rodar precisa dela).
# Esta tarefa NAO e registrada por nenhum teste nem pelo app: so por voce, aqui.
# O arquivo -Config mora na pasta de chaves, NUNCA no repositorio.
# Sem acentos neste arquivo de proposito: PowerShell 5.1 le .ps1 sem BOM como ANSI.

param(
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$Python = "",
    [string]$Hora = "07:30",
    [string]$Nome = "MoraisEng - Leitura das 07h30"
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (-not (Test-Path (Join-Path $raiz "leitura_manha\rodar.py"))) { throw "nao achei leitura_manha\rodar.py em $raiz" }
if (-not (Test-Path $Config)) { throw "nao achei o arquivo de configuracao $Config" }
$Config = (Resolve-Path $Config).Path
if ($Config.StartsWith($raiz + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "o arquivo de configuracao tem credenciais: guarde-o FORA do repositorio ($raiz)"
}

Write-Host "1) Python..."
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python nao esta no PATH deste usuario; use -Python <caminho>" }
    $Python = $cmd.Source
}
if (-not (Test-Path $Python)) { throw "nao achei $Python" }
& $Python -c "import requests, sys; print('   python', sys.version.split()[0], 'em', sys.executable)"
if ($LASTEXITCODE -ne 0) { throw "esse python nao tem requests. Instale: pip install -r requirements.txt" }

Write-Host "2) Removendo versao antiga da tarefa..."
if (Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
    Write-Host "   removida: $Nome"
}

Write-Host "3) Registrando '$Nome' todo dia as $Hora..."
$usuario = "$env:USERDOMAIN\$env:USERNAME"
$acao = New-ScheduledTaskAction -Execute $Python -Argument "-m leitura_manha.rodar --config `"$Config`"" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$conf = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$quem = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $gatilho -Settings $conf -Principal $quem `
    -Description "Leitura das 07:30: saldos e extrato de ontem (Sicoob, Inter, ERP) para a nuvem (python -m leitura_manha.rodar)" | Out-Null
Write-Host "   ok."

Write-Host ""
Write-Host "Para rodar agora (o porteiro do ERP tem de estar ligado): Start-ScheduledTask -TaskName '$Nome'"
Write-Host "Log: <campo 'pasta' do arquivo de configuracao>\leitura_manha.log"
