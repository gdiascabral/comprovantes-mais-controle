# Registra (ou refaz) a tarefa do Agendador do Windows que mantem o porteiro do
# ERP de pe: sobe o Chrome central e mantem o login (erp/porteiro.py, "vigiar").
#
#   powershell -ExecutionPolicy Bypass -File registrar_porteiro.ps1
#   powershell -ExecutionPolicy Bypass -File registrar_porteiro.ps1 -Python C:\caminho\python.exe
#
# O que ela garante:
#   - dispara ao fazer LOGON do usuario atual (o Chrome precisa de janela);
#   - sem limite de duracao: o porteiro e um laco que nunca termina;
#   - se cair, o Agendador o reinicia ate 3 vezes, uma por minuto;
#   - roda na raiz do repositorio (python -m erp.porteiro precisa dela);
#   - pode iniciar e continuar na bateria; nao abre duas copias.
# Esta tarefa NAO e registrada por nenhum teste nem pelo app: so por voce, aqui.
# Para desligar o porteiro sem desregistrar: MC_CENTRAL=off (ver docs/PORTEIRO.md).
# Sem acentos neste arquivo de proposito: PowerShell 5.1 le .ps1 sem BOM como ANSI.

param(
    [string]$Python = "",
    [string]$Nome = "MoraisEng - Porteiro do ERP"
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (-not (Test-Path (Join-Path $raiz "erp\porteiro.py"))) { throw "nao achei erp\porteiro.py em $raiz" }

Write-Host "1) Python..."
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python nao esta no PATH deste usuario; use -Python <caminho>" }
    $Python = $cmd.Source
}
if (-not (Test-Path $Python)) { throw "nao achei $Python" }
& $Python -c "import playwright, sys; print('   python', sys.version.split()[0], 'em', sys.executable)"
if ($LASTEXITCODE -ne 0) {
    throw "esse python nao tem playwright. Instale: pip install -r requirements.txt (e o Google Chrome)"
}

Write-Host "2) Removendo versao antiga da tarefa..."
if (Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
    Write-Host "   removida: $Nome"
}

Write-Host "3) Registrando '$Nome' ao fazer logon..."
$usuario = "$env:USERDOMAIN\$env:USERNAME"
$acao = New-ScheduledTaskAction -Execute $Python -Argument "-m erp.porteiro vigiar" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$conf = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$quem = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $Nome -Action $acao -Trigger $gatilho -Settings $conf -Principal $quem `
    -Description "Porteiro do ERP: mantem o Chrome central de pe e logado (python -m erp.porteiro vigiar)" | Out-Null
Write-Host "   ok."

Write-Host ""
Write-Host "Para iniciar agora (abre o Chrome; deixe a tela livre): Start-ScheduledTask -TaskName '$Nome'"
Write-Host "Estado: python -m erp.porteiro estado"
Write-Host "Log: <pasta central>\porteiro.log"
