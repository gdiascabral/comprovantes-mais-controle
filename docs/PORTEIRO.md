# Porteiro do ERP

O porteiro (`erp/porteiro.py`) é o único que entra no ERP pela tela: sobe o
Chrome central de cada acesso, mantém o login de pé e guarda a credencial. Os
robôs não logam; abrem a própria aba nesse Chrome (ver `erp/central.py`). O ERP
aceita uma sessão por usuário, e abas do mesmo perfil dividem a sessão.

## Regra: robô nunca fecha o Chrome central

Nenhum robô fecha o Chrome central, nem o navegador, nem o contexto: com
`connect_over_cdp`, isso derrubaria as abas dos outros e a sessão. Cada cliente
fecha só as abas que abriu. O porteiro também: ao parar, fecha só a própria
aba. Quem quiser encerrar o Chrome central fecha a janela, à mão.

O porteiro fecha a própria aba ao parar por Ctrl+C, por SIGTERM/SIGBREAK
(parada da tarefa, fechar o console) ou no fim normal do processo (`atexit`).
"Finalizar tarefa" no Agendador ou no Gerenciador mata o processo sem aviso:
aí a aba fica aberta no Chrome central até alguém fechá-la. O app faz o mesmo
com a aba da sessão pela página (`erp/sessao.py`, `_fechar_centrais`).

## Ligar

1. Crie `acessos.json` na pasta central (padrão
   `C:\AUTOMAÇÕES MAIS CONTROLE\_central`, ou `MC_CENTRAL=<pasta>`):

   ```json
   {"acessos": [{"nome": "principal", "perfil": "perfis/principal",
                 "porta": 9230, "credencial": "principal.login.dat"}]}
   ```

2. Guarde o login (e-mail e senha cifrados com a DPAPI, só este usuário do
   Windows decifra; a senha não aparece nem é impressa):
   `python -m erp.porteiro guardar-login --acesso principal`
3. Suba uma vez e confira: `python -m erp.porteiro subir`

   **No 1º login de um perfil novo** o ERP manda um código de "dispositivo
   novo" ao e-mail do usuário. Uma pessoa lê o código e o digita na janela do
   Chrome central, uma vez só; o perfil passa a ser conhecido e os logins
   seguintes entram sozinhos.
4. Registre a tarefa que o liga no logon (rode à mão, neste PC):
   `powershell -ExecutionPolicy Bypass -File ferramentas\porteiro\registrar_porteiro.ps1`

## Conferir

`python -m erp.porteiro estado` imprime JSON com cada acesso e se o Chrome
responde. Só lê; não sobe nada. O que o `vigiar` faz fica em
`<pasta central>\porteiro.log` (rotativo, 1 MB x 4).

## Desligar

- Numa sessão ou máquina: variável `MC_CENTRAL=off` — o app volta a ser o de
  antes, cada robô com o próprio Chrome.
- Na máquina inteira, sem apagar nada: renomeie `acessos.json` para
  `acessos.json.off`. Para religar, o nome de volta.
- De vez: apague o `acessos.json` e a tarefa "MoraisEng - Porteiro do ERP".

## Com o central ligado, NÃO rodar o que loga por fora

O `POST /users/login` feito fora do Chrome central derruba a sessão dele (uma
por usuário no ERP), e todos os robôs perdem o acesso até o porteiro entrar de
novo. Estas ferramentas ainda logam por conta própria — não as rode com o
central ligado (ou rode com `MC_CENTRAL=off` e o porteiro parado):

- o plano B da Conciliação pela tela (`pagamentos_via_api: false` no
  `config.yaml`);
- `aportes/conferir_contas.py`;
- `aportes/teste_lancamento.py`;
- `dispositivo_erp.py`, do água e energia.

## Comandos

| Comando | O que faz |
|---|---|
| `estado` | JSON de cada acesso, sem subir nada |
| `guardar-login --acesso X` | cifra e grava a credencial do acesso (exige `credencial` no JSON) |
| `subir` | um ciclo: sobe o Chrome fechado e confere o login |
| `vigiar [--intervalo 120]` | `subir` e repete a cada intervalo; erro num acesso não para os outros |

`--acesso NOME` restringe o comando a um acesso.
