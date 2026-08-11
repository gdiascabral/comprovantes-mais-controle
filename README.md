# Comprovantes → Mais Controle

Aplicativo para Windows que organiza comprovantes bancários e os anexa nos
pagamentos do [Mais Controle ERP](https://maiscontroleerp.com.br) — sem
precisar saber programar. São **nove abas**, numa janela só:

| Aba | O que faz |
|---|---|
| **✂ Separar e Renomear** | Pega PDFs com vários comprovantes (uma página cada), separa cada página em um arquivo próprio e renomeia lendo o conteúdo — inclusive comprovantes "impressos" sem texto, via **OCR** embutido. |
| **📎 Anexar Comprovantes** | Busca os títulos **pagos** do período nas contas que você marcar, descobre quais ainda não têm comprovante e anexa o PDF certo em cada um (com a tag "Comprovante"). |
| **✅ Conferência** | Auditoria depois do anexo: lista os pagos que ficaram **sem** comprovante e, se você pedir, abre cada anexo para conferir se o valor e a data batem com o lançamento. |
| **💰 Aportes** | Lança aportes de capital e distribuições de lucro direto no ERP, sem planilha e sem importação. |
| **🗓 Pagamentos do Dia** | *(diário)* Excel de conferência dos pagamentos do período, com uma aba por conta bancária. |
| **⚖ Conciliação Diária** | *(diário)* Lê saldos e pagamentos a vencer e monta o painel do dia, com o aporte mínimo por conta. |
| **📊 Relatório Mensal** | *(mensal)* Baixa em PDF o extrato de cada conta bancária do ERP, arquivando na pasta da empresa. |
| **🏦 Extratos Sicoob** | *(mensal)* Cria a árvore de pastas do fechamento e baixa OFX + PDF de cada conta no SicoobNet. |
| **📑 Contratos** | *(mensal)* Acha o contrato de financiamento das casas que financiaram no mês, confere o conteúdo (rua, quadra/lote, casa, comprador e valor) e arquiva na pasta da empresa. |

As quatro primeiras ficam soltas na barra lateral; as outras vivem nos grupos
**DIÁRIO** e **MENSAL**, que abrem e fecham (o estado fica salvo).

Bancos suportados na leitura: **Sicoob** (PIX, boleto, convênio — layouts
antigo e novo do Internet Banking) e **Inter** (PIX, pagamento, boleto/guia,
convênio). Outros bancos podem ser adicionados em
`separar_renomear/separar_renomear.py`.

## Instalação (uma vez)

Baixe o **`Comprovantes Mais Controle.exe`** na página de
[**Releases**](https://github.com/gdiascabral/comprovantes-mais-controle/releases/latest)
e coloque numa pasta própria (ex.: `C:\Comprovantes`). Não precisa de Python —
só do **Google Chrome** instalado (usado pela aba Anexar).

- Na primeira execução o Windows SmartScreen pode avisar: clique em
  **"Mais informações" → "Executar assim mesmo"** (o exe não tem assinatura digital).
- **Atualização automática:** ao abrir, o app baixa sozinho o código novo
  quando há versão nova (~30 KB, segundos). Downloads grandes só quando entra
  componente novo — e aí ele pergunta antes, com barra de progresso.
- A versão em uso aparece no título da janela e no canto inferior direito.

## Aba 1 — Separar e Renomear

1. Escolha a pasta de **entrada** (PDFs originais) e a de **saída** (sugerida
   automaticamente: `ENTRADA/RENOMEADOS`).
2. Escolha o modelo do nome: **PADRÃO: VALOR - DESCRIÇÃO - DATA** (recomendado)
   ou personalizado, usando as palavras VALOR, DESCRIÇÃO, DATA, PAGADOR e
   RECEBEDOR na ordem que quiser. Inclua sempre o VALOR: é ele que permite o
   casamento automático na aba 2.
3. Clique em **Separar e Renomear**. Comprovantes sem camada de texto passam
   por OCR automaticamente (aparece `[OCR]` no registro).

Exemplos de nome gerado:

```
70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf
1890,00 - CONDOMÍNIO RESERVA DOS IPÊS OC 5428 - 01-07.pdf
1000,00 - Morais Empreendimentos - 20-07.pdf        (transferência: quem recebeu)
```

Dica: coloque o **centro de custo e o nº da OC/NF na descrição do PIX/boleto**
na hora de pagar — é isso que permite o casamento automático na aba 2.

## Aba 2 — Anexar Comprovantes

Antes da 1ª vez, clique em **🔑 Login** e guarde seu e-mail e senha do Mais
Controle: ficam cifrados neste computador (DPAPI do Windows) e o app passa a
**entrar sozinho** — não é mais preciso abrir o navegador à mão.

1. Informe o **período** (as datas completam as barras sozinhas; há um 📅
   para escolher no calendário), selecione a **pasta dos PDFs renomeados** e
   clique em **Carregar contas**. O Chrome abre, o app entra no Mais Controle
   e lista as contas — marque as desejadas. As opções de ignorar tarifas
   bancárias e aportes/distribuições são caixas separadas, opcionais.
2. **Casar e anexar** — com **Simular** marcado, nada é anexado de verdade
   (bom para conferir antes).

O botão **Abrir o Mais Controle** não faz parte do fluxo: use no primeiro
acesso (se ainda não guardou a senha) ou para destravar uma sessão caída.

Como o app decide (com segurança):

- pagamentos que **já têm** comprovante são pulados (não duplica);
- o casamento aceita tanto o **valor nominal** quanto o **valor pago**
  (com juros/multa/desconto);
- critérios, do mais forte ao mais fraco: nº de **OC/NF** → **centro de
  custo** → **data**; cada PDF é usado uma vez só;
- casamento ambíguo **nunca é chutado**: abre uma janela para **você escolher
  o PDF certo** (ou deixar em dúvida para depois);
- botões **Pausar/Parar** durante o processo, cronômetros ⏱ por etapa e, no
  fim, um **relatório Excel** (abas ANEXADOS, DUVIDA e SEM PAR) com botão
  **Abrir relatório** direto na janela.

Também dá para anexar por uma **lista pronta** (CSV `launchId,valor,arquivo_pdf`
ou o próprio relatório) no modo "Por lista" — a extensão `.pdf` é completada
automaticamente se faltar.

## Perguntas comuns

**A senha do Mais Controle passa pelo app?** Passa, se você escolher guardá-la.
São dois caminhos:

- **Login na janela do Chrome** (o padrão da primeira vez): você digita no site,
  o app não vê a senha e a sessão fica no perfil `.chrome_profile`, ao lado do
  executável.
- **Botão 🔑 Login** (opcional): você digita e-mail e senha num diálogo do
  próprio app, que os grava em `login.dat` cifrado com a **DPAPI do Windows** —
  só o SEU usuário, nessa máquina, consegue decifrar; nunca em texto puro. A
  partir daí o app entra sozinho. O mesmo `login.dat` é usado pela API de
  saldos da Conciliação Diária.

Para apagar a senha guardada: 🔑 Login → **Remover**. Trocou a senha no ERP?
Remova e cadastre de novo.

**O app pede uma senha ao abrir.** Só na primeira vez em cada computador: é a
senha de ativação, que libera o uso da máquina. Ela não é a senha do Mais
Controle e não vai para lugar nenhum — o app guarda apenas um marcador local
(`ativacao.dat`).

**E se rodar duas vezes?** Sem problema: pagamentos que já têm anexo são pulados.

**Funciona em qualquer conta do Mais Controle?** Sim — o app usa a mesma API
que a tela de Pagamentos, com o seu login, chamada de dentro da própria página.
Não há nada fixo da empresa no código.

## Para desenvolvedores

O executável é dividido em **motor** (Python + bibliotecas + OCR, muda raro) e
**código** (`codigo.zip`, publicado em cada release — é o que o app baixa ao
atualizar). Releases são geradas automaticamente pelo GitHub Actions a cada
commit na `main`.

Para rodar como script: Python 3.10+, `instalar.bat` (ou
`pip install -r requirements.txt` + `python -m playwright install chrome`;
para o OCR, instale o [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
com o idioma português) e `python comprovantes_app.py`.

```
motor.py            carregador do exe (atualiza e injeta o código)
atualizador.py      download do codigo.zip / troca do exe
comprovantes_app.py janela unificada (as nove abas)
ativacao.py         senha de primeira utilização (marcador por máquina)
util.py             formatos, normalização de nomes, pasta-base — SEM tkinter
widgets.py          widgets comuns (o campo de data com calendário)
separar_renomear/   separar páginas + renomear (extração, OCR, modelos de nome)
anexar/             buscar pagos, casar e anexar
  ├─ mc_api.py      leitura dos pagos e anexos (API, via página logada)
  ├─ mc_client.py   automação do Chrome para anexar (Playwright)
  ├─ matcher.py     casamento PDF ↔ pagamento
  ├─ conferencia.py auditoria pós-anexo
  ├─ planilha.py    leitura de lista CSV/XLSX
  └─ config.py      ajustes (tag, perfil do Chrome, etc.)
aportes/            aportes e distribuições (regras em Decimal + API do ERP)
relatorios/         extrato mensal por conta (PDF) + mapa conta → pasta
pagamentos_dia/     Excel de conferência dos pagamentos do dia
extratos_sicoob/    árvore do fechamento + OFX/PDF do SicoobNet
conciliacao/        painel do dia (pacote de verdade, com __init__.py)
contratos/          contratos de financiamento (idem)
```

### Arquivos de configuração (ficam AO LADO do exe, fora do repositório)

Todos carregam dado da empresa — nome, conta, CPF — e por isso nunca entram no
Git. O app funciona sem eles; cada aba avisa qual está faltando.

| Arquivo | Para quê | Sem ele |
|---|---|---|
| `login.dat` | e-mail/senha do ERP, cifrado pela DPAPI | login manual no Chrome |
| `ativacao.dat` | marcador da senha de primeira utilização | o app pergunta de novo |
| `preferencias.json` | tema e grupos abertos da barra lateral | volta ao padrão |
| `contas.csv` | contas dos Aportes (`nome_exibicao;nome_oficial;conta;nome_descricao`) | a aba Aportes fica vazia |
| `subcontas.json` | grupos de investidores por subconta + `_obra_padrao` | sem rateio |
| `contas_mc.json` | mapa conta do ERP → pasta do extrato | Relatório Mensal não roda |
| `contas_sicoob.json` | mapa conta Sicoob → pasta, árvore de empresas e `clientes_erp` | Extratos Sicoob e Contratos não rodam |
| `pix_reembolso.json` | chaves Pix dos avisos "PAGAR PARA" | a linha sai como pendente |
| `config.yaml`, `mapping.yaml`, `MODELO.xlsx` | painel da Conciliação Diária | a aba não gera a planilha |

`contas_mc.json` e `contas_sicoob.json` precisam usar o **mesmo nome de pasta**
para a mesma conta — senão o mês fica partido, com o PDF do ERP numa pasta e o
OFX do banco em outra. O app confere isso e avisa antes de baixar.

## Licença

MIT — use, modifique e distribua à vontade. Este projeto não tem vínculo com o
Mais Controle ERP; é uma automação de uso pessoal sobre a interface web.
