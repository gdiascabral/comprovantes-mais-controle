# -*- coding: utf-8 -*-
"""
Aba "Pagamentos do Dia": gera o Excel de conferência dos pagamentos do período,
com uma aba por conta bancária.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo da Conferência, dos Aportes e do Relatório Mensal.

FLUXO EM DOIS PASSOS, de propósito
----------------------------------
1. Buscar    — lê os lançamentos e mostra as contas com os totais;
2. Gerar     — só as contas marcadas viram planilha.

Separado porque quem confere quer OLHAR a lista de contas antes (e quase
sempre tira uma ou outra: "APENAS LANÇAMENTO", conta pessoal, conta zerada).
Fazer tudo de uma vez obrigaria a rodar de novo — e cada rodada custa uma
sessão do ERP, que só aceita uma por usuário.
"""
from __future__ import annotations

import datetime
import os
import queue
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk


from . import baixa_erp
from . import ocr_boleto
from . import reembolso
from . import regras_pagamento as regras
from . import relatorio
from . import remessa_dia
from . import retorno_dia

import util

#: Duração e pasta-base vinham em cópias byte a byte por aba. Uma cópia de
#: regra de CAMINHO é como um app passa a procurar o mesmo arquivo em dois
#: lugares; uma de FORMATO é como a mesma duração aparece de dois jeitos.
_fmt_dur = util.fmt_dur
_pasta_base = util.pasta_base

import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px

CampoData = widgets.CampoData

# Cadastros de outras abas, reusados pela remessa: `contas_mc` diz de que
# EMPRESA é cada conta do ERP, e `sicoob_contas` traz CNPJ, agência, conta e
# convênio. Um mapa a mais seria uma divergência a mais esperando acontecer —
# julho de 2026 já ficou partido uma vez por dois mapas discordando.
from relatorios import contas_mc
from extratos_sicoob import sicoob_contas
# Os passos da remessa sobem para a auditoria da nuvem, e não só para o
# `atividade.jsonl`: o painel de Início é da máquina de quem rodou, e "quem
# gerou esta remessa?" é pergunta que se faz de outra máquina, depois.
from nuvem import auditoria



def _historico(avisar=None):
    """A memória das remessas: a NUVEM manda, o arquivo local acompanha.

    O `remessas.json` continua ao lado do exe e continua sendo escrito — é
    backup legível, e tem valor, favorecido e o de-para com o ERP, dado da
    empresa que por isso fica fora do repositório.

    O que ele NÃO pode mais ser é a autoridade do NSA. A trava dele é um
    arquivo `.lock` na mesma pasta, e protege dois processos, não dois
    computadores: cada máquina tem o seu arquivo, as duas leem "último = 5"
    antes de qualquer uma gravar 6, e NSA repetido pode significar pagamento
    em dobro. A prova apareceu sem precisar de duas pessoas — a instalação
    dizia que o próximo era 1 e a pasta de código dizia 2.

    Sem sessão na nuvem, isto levanta: gerar remessa com um contador que não
    dá para conferir é o desfecho que não pode acontecer em silêncio.
    """
    from cnab240 import Historico

    from nuvem import registro, sessao

    local = Historico(_pasta_base() / "remessas.json")
    nuvem = registro.Registro(sessao.token(_pasta_base()))
    return registro.Espelhado(nuvem, local, avisar)


def e_marcador_de_recorrencia(item: dict, fornecedores: dict) -> bool:
    """R$ 1,00 de fornecedor marcado como `so_marcador` — não é pagamento.

    A concessionária lança um valor simbólico por unidade consumidora para o
    título nascer no mês. A etapa 3 já sabe descartá-lo (`MOTIVO_SIMBOLICO`),
    mas ela roda DEPOIS desta janela: sem esta pergunta aqui, a linha aparece
    para ser desmarcada à mão, todo dia, e a janela gasta a atenção que
    deveria estar protegendo.

    A marca é por NOME e mora no cadastro (`regras_fornecedor.json`), não aqui:
    concessionária nova é uma linha lá, não uma versão nova do app.
    """
    return (regras.valor_simbolico(relatorio.valor_do_item(item))
            and bool(regras.regra_do_fornecedor(
                item.get("paidTo") or "", fornecedores).get("so_marcador")))


#: Banco, agência e conta dentro do texto livre do cadastro do ERP. Só é
#: usado quando a forma de pagar NÃO é Pix nem boleto — aí o campo
#: `paidToBankAccount` costuma trazer a conta escrita à mão, em meia dúzia de
#: feitios ("BANCO 756 AG 3007 CC 55696-3", "Sicoob ag. 3007 c/c 55696-3").
_AGENCIA = re.compile(r"\bag(?:[êe]ncia|\.)?\s*:?\s*(\d{3,5})", re.I)
_CONTA = re.compile(r"\b(?:c/c|cc|conta|c\.c\.)\s*:?\s*([\d.\-]{4,15})", re.I)
# Preguiçoso e com parada explícita: `[\w .]+` guloso engolia "Sicoob ag 3007
# c" inteiro, e o nome do banco saía com a agência dentro dele.
_BANCO = re.compile(
    r"\b(?:banco|bco)\.?\s*:?\s*(.{2,28}?)"
    r"(?=\s+(?:ag|ag[êe]ncia|c/c|cc|conta|c\.c\.)\b|\s*$)", re.I)


#: A cor do dado de pagamento, pelo que vai acontecer com o lançamento.
#: Mora fora da função porque o teste aponta para ela: é o mapa que garante
#: que `atencao` tem um estilo próprio, e não cai no vermelho por omissão.
ESTILO_DO_DADO = {
    "ok": "MonoMini.TLabel",
    "atencao": "MonoMiniAtencao.TLabel",
    "erro": "MonoMiniErro.TLabel",
}

def quem_recebe(item: dict, ja_lido: dict | None = None) -> tuple[str, str, str]:
    """Para quem vai o dinheiro e POR ONDE. Devolve (nome, dado, estado).

    O `dado` é a segunda linha da célula, em fonte de largura fixa: a chave
    Pix, a linha digitável ou o trio banco/agência/conta. É o que se confere
    contra o documento na mão antes de mandar pagar — e era exatamente o que
    a janela de confirmação não mostrava: ela listava valor, favorecido e
    descrição, e a pessoa confirmava um pagamento sem ver para onde ele ia.

    NÃO busca nada. Usa o que a busca de lançamentos já trouxe
    (`paidToBankAccount`, o método de pagamento) e, para o boleto, o que uma
    passagem anterior do passo 2 já leu — o `ja_lido`, que é `{id: dados}`
    montado do `self.resultado`. Ler o boleto exige baixar o PDF e às vezes
    passar OCR, e isso é trabalho do passo 2, com o navegador na mão; fazê-lo
    aqui abriria uma segunda coleta em rede no meio de uma janela modal.

    Boleto ainda não lido aparece com o recado no lugar do dado, e não em
    branco: "não sei a linha digitável" é uma informação sobre o pagamento, e
    quem confirma precisa dela para decidir se abre o boleto antes.

    **O estado diz o que vai acontecer, não o que está faltando.** Os três
    casos sem dado de pagamento saíam como `erro` — vermelhos —, e vermelho
    na frente de um item que continua marcado e gera assim mesmo é lido como
    defeito do app. Eles são `atencao`: o lançamento ENTRA na planilha, e o
    que ele não faz é entrar na remessa. Quem lê precisa da consequência
    ("pagar à mão"), não do diagnóstico. `erro` fica reservado para o que não
    sai de jeito nenhum.
    """
    favorecido = (item.get("paidTo") or "?").strip()
    pago_para = (item.get("paidToBankAccount") or "").strip()
    tipo = relatorio.tipo_de_pagamento(item)
    ident = str(item.get("id") or "")

    if tipo == "Pix":
        chave = relatorio.extrair_chave_pix(pago_para) if pago_para else ""
        if relatorio.parece_chave_pix(chave):
            return favorecido, f"PIX  {chave}", "ok"
        return (favorecido,
                "PIX  sem chave no cadastro — não entra na remessa: pagar à mão",
                "atencao")

    if tipo == "Boleto":
        linha = (ja_lido or {}).get(ident) or ""
        if linha:
            return favorecido, f"BOLETO  {ocr_boleto.formatar(linha)}", "ok"
        return (favorecido,
                "BOLETO  sem código de barras — não entra na remessa, "
                "só na planilha",
                "atencao")

    # TED e o que mais o ERP chamar de forma de pagamento. O texto do cadastro
    # é livre: quando dá para separar banco/agência/conta, separa; quando não
    # dá, mostra o que está lá — o que está lá é o que a pessoa vai usar.
    rotulo = (tipo or "TED").upper()
    if not pago_para:
        return (favorecido,
                f"{rotulo}  sem conta no cadastro — não entra na remessa: "
                "pagar à mão", "atencao")
    banco = _BANCO.search(pago_para)
    ag = _AGENCIA.search(pago_para)
    cc = _CONTA.search(pago_para)
    if ag and cc:
        nome_banco = (banco.group(1).strip() if banco
                      else pago_para.split()[0][:18])
        return (favorecido,
                f"{rotulo}  {nome_banco}  ag {ag.group(1)}  c/c {cc.group(1)}",
                "ok")
    return favorecido, f"{rotulo}  {pago_para[:64]}", "atencao"


def alvos_para_confirmar(lancamentos, escolhidas, fornecedores=None) -> list:
    """Que lançamentos a janela da etapa 2 lista.

    Era "só os fornecedores do `confirmar_antes.json`", e por isso a janela
    nem abria quando o arquivo estava vazio. Passou a ser TODO lançamento a
    pagar das contas marcadas: sem isso, tirar um pagamento do dia obrigava a
    desmarcar a conta inteira, junto com tudo o mais que ela tem. Aquele
    arquivo continua valendo — só mudou de função, de porteiro para destaque
    dentro da janela.

    Já pago fica de fora: não há o que decidir sobre ele. Se ele entra ou não
    na planilha é a caixa "incluir já pagos", que é outra pergunta.

    O marcador de recorrência das concessionárias também fica de fora, pelo
    mesmo motivo: `so_marcador` no cadastro já é a decisão tomada, e repeti-la
    aqui todo dia é o que a janela deixou de fazer. `fornecedores` é o
    `regras_pagamento.carregar_fornecedores()`; sem ele, nada é filtrado.

    Fora da classe porque é decisão, não tela — e assim tem teste.
    """
    escolha = {relatorio.chave(n) for n in escolhidas}
    marcados = fornecedores or {}
    return [i for i in lancamentos
            if relatorio.chave(relatorio.nome_da_conta(i)) in escolha
            and not i.get("paid")
            and not e_marcador_de_recorrencia(i, marcados)]


def _doc_legivel(documento: str) -> str:
    """CPF/CNPJ pontuado. Conferir 11 dígitos crus a olho não é conferir."""
    d = "".join(ch for ch in (documento or "") if ch.isdigit())
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d or "?"


def _carregar_reembolsos() -> dict:
    """Chaves Pix dos avisos "PAGAR PARA <nome>".

    Fica em arquivo, ao lado do exe, porque é CPF de gente — não entra no
    repositório. Ausente, o relatório só marca a linha como pendente.

    A leitura do arquivo mudou de dono: quem entende dele é o `reembolso`, que
    aceita o formato antigo (`{nome: chave}`) e o novo (com nome oficial e
    documento). O `str(v)` que estava aqui viraria a REPRESENTAÇÃO de um
    dicionário no formato novo — uma "chave Pix" com chaves e vírgulas, que
    nada recusaria por não parecer chave.
    """
    return reembolso.chaves(reembolso.carregar(_pasta_base()))


def resumo_da_prontidao(conferencias, erro: str = "") -> tuple[str, str]:
    """(estado, frase) da linha "contas prontas para remessa".

    Função de módulo, e não método, pelo mesmo motivo de
    `remessa_dia.contas_sem_remessa`: é a aritmética de um cartão, e dentro do
    frame ela só se testaria abrindo janela. Aqui basta uma lista de
    `Conferencia`.

    O estado é `ok` só quando NÃO SOBRA pendência — é a única leitura que
    autoriza seguir sem abrir a janela dos detalhes. Havendo qualquer conta
    incompleta é `atencao`, e não `erro`: nada falhou, o cadastro é que está
    pela metade — a mesma distinção que a tabela faz linha a linha. `info` é o
    "ainda não sei": ninguém conferiu ainda, ou o cadastro não abriu.

    A frase NOMEIA O ASSUNTO nos quatro casos ("prontas para remessa"), porque
    o cartão não tem cabeçalho para nomeá-lo — ela é a única linha que a aba
    mostra, e uma linha dizendo só "13 · 10 com pendência" não diz de quê.
    O DETALHE do erro fica de fora de propósito: o recado do `carregar` tem
    várias frases e ali viraria um bloco colorido de três linhas, que é
    exatamente a altura que este cartão não tem. Ele aparece inteiro na
    janela do "Ver detalhes"."""
    if erro:
        return "info", "Contas prontas para remessa: não consegui ler o cadastro"
    if not conferencias:
        return "info", ("Contas prontas para remessa: abra esta aba para "
                        "conferir o cadastro")
    prontas = sum(1 for c in conferencias if c.pronta)
    pendentes = len(conferencias) - prontas
    if not pendentes:
        return "ok", f"{prontas} conta(s) prontas para remessa"
    return "atencao", (f"{prontas} conta(s) prontas para remessa  ·  "
                       f"{pendentes} com pendência")


class PagamentosDiaFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.lancamentos: list[dict] = []
        self.anexos: dict = {}
        self.overviews: dict = {}
        #: {nome normalizado: CPF/CNPJ} do cadastro de Contatos do ERP.
        #: É o que libera o Pix por telefone, e-mail e chave aleatória.
        self.participantes: dict = {}
        self.contas: list[tuple] = []
        self.vars_contas: dict[str, tk.BooleanVar] = {}
        self.ultimo_arquivo: Path | None = None
        #: Os `.REM` da última geração. Guardados porque o passo seguinte é
        #: subir no SicoobNet, e chegar até eles pelo caminho digitado no
        #: campo "Onde salvar" é o tipo de coisa que se faz errado às 18h.
        self.ultimas_remessas: list[Path] = []
        #: O que o passo 2 montou. A remessa sai daqui, não do .xlsx — ler a
        #: planilha de volta seria reparsear texto formatado para reconstruir
        #: número, e ela é relatório, não fonte.
        self.resultado = None
        #: O período que gerou o `self.resultado`. Existe para o passo 3 poder
        #: recusar quando a pessoa trocou as datas na tela depois de gerar a
        #: planilha: o que está em memória seria de outro dia, e a janela da
        #: remessa não tem como saber disso sozinha.
        self._periodo_do_resultado = None
        #: O que o último `_conferir_prontidao` viu — a lista de `Conferencia`
        #: e, quando o cadastro não abriu, o recado do erro. Ficam aqui, e não
        #: dentro da janela do "Ver detalhes", porque quem os mostra são DOIS:
        #: a pílula do cartão (sempre) e a tabela da janela (quando abrem).
        self._prontidao = []
        self._prontidao_erro = ""

        hoje = datetime.date.today()
        self.v_ini = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_cruzar = tk.BooleanVar(value=True)
        self.v_incluir_pagos = tk.BooleanVar(value=False)
        self.v_pasta = tk.StringVar(
            value=str(_pasta_base() / "Pagamentos do dia").replace("\\", "/"))

        self._build()
        self.after(150, self._drain)

    #: As colunas da janela de prontidão: (chave, título, largura a 100%,
    #: alinhamento). A largura é escalada pelo `estilo_tabela`, num lugar só.
    COLUNAS_PRONTIDAO = (
        ("conta_erp", "CONTA (ERP)", 230, "w"),
        ("empresa", "EMPRESA", 150, "w"),
        ("agconta", "AG-CONTA", 140, "w"),
        ("convenio", "CONVÊNIO", 100, "w"),
        ("situacao", "SITUAÇÃO", 260, "w"),
    )

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)

        self.cab = widgets.Cabecalho(
            self, "Remessa/Retorno",
            "Planilha de conferência dos pagamentos do período, o arquivo de "
            "remessa para o banco e a leitura do retorno que ele devolve.",
            trilha="Diário  ›  Remessa e Retorno")
        self.cab.pack(fill="x", padx=PADX, pady=px((16, 12)))

        # Os botões do FLUXO ficam no cabeçalho, à direita do título; os que
        # não são do fluxo (parar, abrir, ler retorno) ficam embaixo, junto da
        # barra de execução. Antes os seis moravam no rodapé, e o "executar"
        # da tela ficava no canto de baixo — longe do que se acabou de
        # preencher, e do mesmo tamanho de "Abrir planilha".
        #
        # O verde é o TERCEIRO: a tela existe para o dinheiro sair, e é o
        # arquivo de remessa que faz isso acontecer. Buscar e gerar a planilha
        # são o caminho até ele.
        self.b1 = widgets.Botao(self.cab.acoes, "Buscar os lançamentos",
                                papel="passo", command=self.buscar)
        self.b1.pack(side="left", padx=px((0, 8)))
        self.b2 = widgets.Botao(self.cab.acoes, "Gerar a planilha",
                                papel="passo", command=self.gerar,
                                state="disabled")
        self.b2.pack(side="left", padx=px((0, 8)))
        self.b3 = widgets.Botao(self.cab.acoes, "Gerar remessa", papel="acao",
                                command=self.gerar_remessa, state="disabled")
        self.b3.pack(side="left")

        # Os cartões passam a ser NUMERADOS, e os botões deixam de ser: era o
        # "▶ 1." no botão e o "1." no cartão contando a mesma coisa duas vezes,
        # com contagens que não batiam ("2. Contas" era um campo, "2. Gerar" era
        # uma ação). Agora o número está num lugar só — o cartão —, e o botão
        # diz o VERBO.
        f1 = widgets.Cartao(self, "Período", 1)
        f1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        linha = ttk.Frame(f1)
        linha.pack(fill="x")
        widgets.Campo(linha, "De", lambda p: CampoData(p, self.v_ini)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Campo(linha, "Até", lambda p: CampoData(p, self.v_fim)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Botao(linha, "Hoje", papel="neutro", command=self._hoje
                      ).pack(side="left", pady=px((15, 0)))

        opc = ttk.Frame(f1)
        opc.pack(fill="x", pady=px((12, 0)))
        ttk.Checkbutton(opc, variable=self.v_cruzar,
                        text="Conferir os documentos anexados (baixa os PDFs; "
                             "mais lento, mas é a conferência de verdade)"
                        ).pack(anchor="w")
        ttk.Checkbutton(opc, variable=self.v_incluir_pagos,
                        text="Incluir também o que já foi pago no período"
                        ).pack(anchor="w", pady=px((4, 0)))

        # ---- card 2: contas
        # A lista também é elástica: antes de buscar ela tem uma frase, e um
        # quadro vazio de 170 px em volta de uma frase é o mesmo desperdício
        # que o Registro tinha. Cresce em `_montar_contas`.
        self.f_contas = f2 = widgets.Cartao(
            self, "Contas — marque as que entram no relatório", 2)
        f2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.rodape_contas = widgets.RodapeTabela(f2.acoes)
        self.rodape_contas.pack()
        self.canvas = tk.Canvas(f2, height=px(24), highlightthickness=0,
                                borderwidth=0)
        self.barra = barra = ttk.Scrollbar(f2, orient="vertical",
                                           command=self.canvas.yview)
        self.contas_box = ttk.Frame(self.canvas)
        self.contas_box.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.janela_lista = self.canvas.create_window((0, 0), window=self.contas_box,
                                                      anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self.janela_lista, width=e.width))
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        # A barra de rolagem só entra junto com a lista: numa faixa de 24 px
        # ela vira duas setinhas espremidas ao lado de uma frase.
        ttk.Label(self.contas_box, style="Tenue.TLabel",
                  text='Clique em "Buscar os lançamentos" para listar as contas.'
                  ).pack(anchor="w")

        # ---- card 3: pasta
        f3 = widgets.Cartao(self, "Onde salvar", 3)
        f3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Entry(f3, textvariable=self.v_pasta).pack(side="left", fill="x",
                                                      expand=True)
        widgets.Botao(f3, "Selecionar…", papel="neutro", command=self._sel_pasta
                      ).pack(side="left", padx=px((8, 0)))

        # ---- prontidão do cadastro: UMA LINHA, e SEM número nem título
        # Não é passo: ninguém preenche nada aqui, e numerá-la poria um "4"
        # entre "Onde salvar" e o botão verde, inventando uma ordem que não
        # existe (a mesma razão pela qual o Registro não é numerado).
        #
        # **Uma linha porque a aba não tem altura para mais que isso.** O
        # Registro é o último a ser empacotado nas onze telas, então é ele quem
        # fica com a SOBRA — e `tests/test_registro_visivel.py` cobra que a
        # sobra dê ao menos quatro linhas legíveis a 1.0x e a 1.25x, com o pé
        # dentro da janela. MEDIDO na moldura do teste (1920x1040, a 1.25x):
        # acima desse piso de quatro linhas sobram **103 px** para este cartão,
        # e a tabela de oito linhas que o PR #55 pôs aqui custava 149 — o
        # Registro caiu para 1,4 linha (48 px) e o cabeçalho da aba foi parar
        # abaixo dele. Daí as duas escolhas desta forma:
        #
        # - a lista inteira mudou-se para a janela do "Ver detalhes". É onde
        #   ela pertence: quem a lê está indo ao painel do Supabase corrigir
        #   cadastro, o que acontece raramente — enquanto o Registro, que
        #   pagava a conta, é lido em toda rodada;
        # - o cartão fica SEM cabeçalho. Um `Cartao` titulado custa 120 px só
        #   de moldura, título e filete, contra os 103 disponíveis: caberia a
        #   moldura e não o que ela emoldura. Sem o cabeçalho são 88 px, e o
        #   assunto passa a ser dito pela própria frase da pílula, que o nomeia
        #   nos quatro estados — a janela leva o título por escrito.
        #
        # O resumo é preenchido em `ao_abrir`, não na construção — ver o
        # docstring de `_conferir_prontidao`. Montar o esqueleto aqui custa
        # microssegundos; ler os dois JSON custa disco, e é isso que não pode
        # entrar na abertura do app.
        self.f_prontidao = f_pr = widgets.Cartao(self, padding=(16, 10))
        f_pr.pack(fill="x", padx=PADX, pady=px((0, 12)))
        linha_pr = ttk.Frame(f_pr)
        linha_pr.pack(fill="x")
        self.pilula_prontidao = widgets.Pilula(linha_pr, "", "info")
        self.pilula_prontidao.pack(side="left")
        # Link, e não botão sólido: a aba já tem três botões de passo no
        # cabeçalho, e um quarto botão cheio aqui embaixo disputaria o olho com
        # o verde que gera a remessa. É o mesmo papel que o `RodapeTabela` dá
        # ao "Conferir de novo" — e ele economiza 7 px, que aqui são meia linha
        # de Registro.
        widgets.Botao(linha_pr, "Ver detalhes", papel="link",
                      command=self._janela_prontidao).pack(side="right")
        self._mostrar_resumo_prontidao()

        # ---- barra de execução e o que não é passo
        # ACIMA do registro, e não no rodapé: a barra conta o trabalho que
        # está acontecendo, e o registro é a saída DELE. Embaixo, ela ficava
        # depois do resultado — e, com o registro cheio, fora da tela.
        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo",
                                    command=self._parar_click, state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = widgets.Botao(btns, "📂  Abrir planilha", papel="neutro",
                                     command=self._abrir, state="disabled")
        self.b_abrir.pack(side="left", padx=px((8, 0)))
        self.b_abrir_rem = widgets.Botao(btns, "📂  Abrir local da remessa",
                                         papel="neutro",
                                         command=self._abrir_remessa,
                                         state="disabled")
        self.b_abrir_rem.pack(side="left", padx=px((8, 0)))
        # SEM número e sempre habilitado, de propósito: ler retorno não é o
        # passo 4 de nada. O arquivo chega horas ou dias depois — às vezes
        # noutra máquina —, e exigir "buscar" e "gerar" antes obrigaria a
        # refazer o dia inteiro só para conferir o que o banco respondeu.
        self.b_ret = widgets.Botao(btns, "📥  Ler retorno", papel="neutro",
                                   command=self.ler_retorno)
        self.b_ret.pack(side="left", padx=px((8, 0)))

        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        # `lbl` e `pb` continuam existindo com os nomes de sempre: o `_drain`
        # e as seis chamadas de progresso não sabem (nem precisam saber) que a
        # barra virou outro widget.
        self.lbl = self.barra_exec.lbl
        self.pb = self.barra_exec.pb

        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

    def _hoje(self):
        hoje = datetime.date.today()
        self.v_ini.set(f"{hoje:%d/%m/%Y}")
        self.v_fim.set(f"{hoje:%d/%m/%Y}")

    def _sel_pasta(self):
        escolhida = filedialog.askdirectory(initialdir=self.v_pasta.get() or None)
        if escolhida:
            self.v_pasta.set(escolhida.replace("\\", "/"))

    def _abrir(self):
        if self.ultimo_arquivo and self.ultimo_arquivo.exists():
            try:
                os.startfile(self.ultimo_arquivo)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultimo_arquivo)])

    def _abrir_remessa(self):
        """Abre a pasta do `.REM` com o arquivo já selecionado.

        Selecionar, e não abrir: `.REM` é texto, e abri-lo escancararia o
        Bloco de Notas em cima de um arquivo que ninguém deve editar. O que se
        quer aqui é chegar até ele para arrastar ao SicoobNet.

        Vários arquivos (um por conta pagadora) caem na MESMA pasta, então
        selecionar o primeiro já põe os outros à vista.
        """
        vivos = [c for c in self.ultimas_remessas if c.exists()]
        if len(vivos) > 1 and len({c.parent for c in vivos}) > 1:
            # Várias contas, várias pastas: selecionar um arquivo esconderia
            # os outros. Abre o galho comum e deixa a pessoa escolher.
            comum = Path(os.path.commonpath([str(c.parent) for c in vivos]))
            try:
                os.startfile(comum)                          # noqa: S606
            except Exception as e:                           # noqa: BLE001
                messagebox.showwarning(
                    "Remessa",
                    widgets.recado_de_erro(e, "Não consegui abrir a pasta."))
            return
        if not vivos:
            messagebox.showinfo(
                "Remessa",
                "Não há arquivo de remessa desta rodada para abrir. Gere a "
                "remessa no passo 3 — ou procure na pasta de 'Onde salvar'.")
            return
        alvo = vivos[0]
        try:
            # String, e não lista: no Windows o `/select,` e o caminho são UM
            # argumento só, e a lista faria o Python enfiar aspas no meio dele
            # — o Explorer então abre "Documentos" e finge que obedeceu.
            subprocess.Popen(f'explorer /select,"{alvo}"')   # noqa: S606
        except Exception:
            # Sem o Explorer (ou fora do Windows), abrir a pasta já resolve o
            # que a pessoa veio fazer.
            try:
                os.startfile(alvo.parent)                    # noqa: S606
            except Exception as e:                           # noqa: BLE001
                messagebox.showwarning(
                    "Remessa",
                    widgets.recado_de_erro(e, "Não consegui abrir a pasta."))

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando...")
        self.b_stop.configure(state="disabled")

    def aplicar_cores(self, escuro: bool):
        # A tabela da prontidão não entra aqui: ela vive na janela do "Ver
        # detalhes", que é modal (`grab_set`) e nasce já no tema da vez —
        # ninguém troca de tema com ela aberta. A `Pilula` do cartão segue
        # estilo nomeado, que `aplicar_estilos` repinta sozinho.
        try:
            widgets.estilo_log(self.log, escuro)
            widgets.estilo_canvas(self.canvas)
        except tk.TclError:
            pass

    # ------------------------------------------------- prontidão do cadastro
    def ao_abrir(self):
        """Relê o cadastro e refaz o resumo da prontidão.

        A janela chama isto toda vez que esta aba volta à frente
        (`comprovantes_app.mostrar`), e é de propósito que não seja na
        CONSTRUÇÃO: as doze abas somam ~1,2 s na abertura do app, e ler dois
        JSON por uma linha que ninguém está olhando é justamente o tipo de
        custo que não se paga adiantado. Quem editou o cadastro no painel
        também não precisa reabrir a aba de propósito — trocar de aba e voltar
        já relê."""
        self._conferir_prontidao()

    def _conferir_prontidao(self):
        """Relê o cadastro e devolve a prontidão de cada conta.

        Roda na thread da INTERFACE, e pode: não há navegador, não há ERP e
        não há rede — são dois arquivos locais (`contas_mc.json` e
        `contas_sicoob.json`), que a sincronização da abertura já regravou.

        Existe porque a validação do cadastro acontecia tarde e sem sujeito: o
        `gerar_remessa` lia os dois mapas na hora de gerar, um dado ruim virava
        "Não consegui ler o cadastro" (sem dizer de qual conta) ou uma recusa
        por conta na janela de conferência — e, com doze empresas, isso é o dia
        parado. A regra é a mesma que o botão usa (`remessa_dia.prontidao`), e
        um teste impede as duas de divergirem em silêncio.

        O que aparece na ABA é o resumo de uma linha; a lista inteira é a
        janela do "Ver detalhes". Conferir custa o mesmo nos dois casos — os
        dois JSON —, então o resumo é sempre recalculado aqui e a janela, que
        abre por cima, apenas mostra o que já está apurado."""
        try:
            mapa_mc = contas_mc.carregar()
            cadastro = sicoob_contas.carregar()
        except Exception as e:                                # noqa: BLE001
            # Sem os mapas não há lista para mostrar — e o recado do
            # `contas_mc.carregar` já diz QUAL linha está torta e onde se
            # conserta, que é a informação que faltava.
            self._prontidao = []
            self._prontidao_erro = widgets.recado_de_erro(
                e, "Não consegui ler o cadastro.")
        else:
            self._prontidao = list(
                remessa_dia.prontidao(mapa_mc, cadastro.empresas))
            self._prontidao_erro = ""
        self._mostrar_resumo_prontidao()
        return self._prontidao

    def _mostrar_resumo_prontidao(self):
        estado, frase = resumo_da_prontidao(self._prontidao,
                                            self._prontidao_erro)
        try:
            self.pilula_prontidao.definir(
                f"{widgets.MARCAS_ESTADO[estado]}  {frase}", estado)
        except tk.TclError:
            pass                         # aba destruída enquanto isto rodava

    def _janela_prontidao(self):
        """A lista inteira, com TODOS os problemas de cada conta.

        Janela e não cartão: quem lê isto está indo ao painel do Supabase
        corrigir cadastro, e isso acontece raramente — enquanto o Registro,
        que perde a tela para cada linha desta tabela, é lido em toda rodada.
        """
        conferencias = self._conferir_prontidao()

        top = tk.Toplevel(self)
        top.title("Contas prontas para remessa")
        top.geometry(f"{px(940)}x{px(560)}")
        top.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(top)
        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)

        ttk.Label(moldura, style="Titulo.TLabel",
                  text="Contas prontas para remessa").pack(anchor="w")
        resumo = ttk.Label(moldura, style="Apoio.TLabel", wraplength=px(880),
                           justify="left")
        resumo.pack(anchor="w", pady=px((2, 8)))

        colunas = tuple(chave for chave, *_ in self.COLUNAS_PRONTIDAO)
        tabela = ttk.Treeview(moldura, columns=colunas, show="headings",
                              height=14, selectmode="browse")
        for chave, titulo, larg, ancora in self.COLUNAS_PRONTIDAO:
            tabela.heading(chave, text=titulo)
            tabela.column(chave, width=larg, anchor=ancora,
                          stretch=chave == "situacao")
        widgets.estilo_tabela(tabela)
        tabela.pack(fill="both", expand=True)

        def _encher(conferencias):
            tabela.delete(*tabela.get_children())
            for i, c in enumerate(conferencias):
                estado, texto = c.situacao
                tabela.insert(
                    "", "end",
                    values=(c.conta_erp, c.empresa,
                            f"{c.agencia or '—'} / {c.conta or '—'}",
                            c.convenio or "—",
                            f"{widgets.MARCAS_ESTADO[estado]}  {texto}"),
                    tags=widgets.linha_zebrada(i, estado))
            # Aqui, sim, o recado do erro INTEIRO: é ele que diz qual linha do
            # cadastro está torta, e a linha do cartão não tem altura para ele.
            marca, frase = resumo_da_prontidao(conferencias,
                                               self._prontidao_erro)
            resumo.configure(
                text=self._prontidao_erro
                or f"{widgets.MARCAS_ESTADO[marca]}  {frase}")

        _encher(conferencias)

        rodape = widgets.RodapeTabela(moldura)
        rodape.pack(fill="x", pady=px((10, 0)))
        # O cache só é regravado na ABERTURA (`nuvem.cadastro.sincronizar`),
        # então "reabra o app" não é zelo: sem isso a correção feita no painel
        # não chega a esta tela.
        rodape.definir(texto="corrija no painel do Supabase e reabra o app")
        rodape.link("Conferir de novo",
                    lambda: _encher(self._conferir_prontidao()))
        widgets.Botao(rodape, "Fechar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=px((10, 0)))

        top.grab_set()

    def _periodo(self) -> tuple[datetime.date, datetime.date]:
        ini = datetime.datetime.strptime(self.v_ini.get().strip(), "%d/%m/%Y").date()
        fim = datetime.datetime.strptime(self.v_fim.get().strip(), "%d/%m/%Y").date()
        return (fim, ini) if ini > fim else (ini, fim)

    # ------------------------------------------------------------- mensagens
    def _log(self, msg=""):
        self.q.put(("log", msg))

    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "log":
                    self.log.insert("end", f"{valor}\n")
                    self.log.see("end")
                elif tipo == "status":
                    self.lbl.configure(text=valor)
                elif tipo == "progresso":
                    feitos, total = valor
                    self.barra_exec.progresso(feitos, total)
                elif tipo == "contas":
                    self._montar_contas(valor)
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                    self.b2.configure(state="normal" if valor == "normal" and self.contas
                                      else "disabled")
                    # Basta ter BUSCADO: a remessa apura sozinha o que
                    # faltar. Era `and self.resultado`, e por isso o botão só
                    # acendia depois de a planilha ser escrita.
                    self.b3.configure(state="normal" if valor == "normal"
                                      and self.lancamentos else "disabled")
                    self.b_stop.configure(state="disabled" if valor == "normal" else "normal")
                elif tipo == "abrir_remessa":
                    # A apuração terminou na thread do navegador; a janela é
                    # aqui. `after_idle` para o `botoes normal` desta mesma
                    # rodada do drain já ter sido aplicado quando ela abrir.
                    self.after_idle(self.gerar_remessa)
                elif tipo == "arquivo":
                    self.ultimo_arquivo = valor
                    self.b_abrir.configure(state="normal")
                elif tipo == "remessa_gerada":
                    self.ultimas_remessas = list(valor)
                    self.b_abrir_rem.configure(state="normal")
                elif tipo == "baixa":
                    # A baixa mexe no ERP: o desfecho não pode ficar só no log,
                    # que rola e some. Falha aparece com o motivo de cada uma.
                    deram, falharam = valor
                    if falharam:
                        detalhe = "\n".join(
                            f"• {r.favorecido[:30]} ({r.seu_numero}): {r.erro}"
                            for r in falharam[:8])
                        messagebox.showwarning(
                            "Baixa no Mais Controle",
                            f"{deram} baixado(s).\n\n"
                            f"{len(falharam)} não deu(ram) certo:\n\n{detalhe}")
                    else:
                        messagebox.showinfo(
                            "Baixa no Mais Controle",
                            f"{deram} pagamento(s) baixado(s).")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    # --------------------------------------------------------------- etapa 1
    def buscar(self):
        if self.worker and not self.worker.done():
            return
        try:
            ini, fim = self._periodo()
        except ValueError:
            messagebox.showwarning("Período", "Use datas no formato dd/mm/aaaa.")
            return
        # Recusar ANTES de desabilitar os botões: quem sai por aqui não passa
        # mais pelo `_drain`, e a aba ficava travada — botões apagados, nada
        # rodando — até reiniciar o app.
        if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
            return
        # A planilha do período ANTERIOR morre aqui. Sem isto, `self.resultado`
        # sobrevivia à busca nova, o `_drain` reabilitava o passo 3 por causa
        # dele, e um clique em "3" no lugar de "2" abria a janela com a lista
        # de ONTEM — toda pré-marcada, e com o "seu número" recarimbado com a
        # data de hoje, o que driblava a única trava contra repetir. O passo 3
        # só volta a existir depois que o passo 2 rodar de novo.
        self.resultado = None
        self._periodo_do_resultado = None
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Abrindo o Mais Controle..."))
        self.worker = self.anx.submeter("Pagamentos do Dia — buscar",
                                        self._t_buscar, ini, fim, dona=self)

    def _t_buscar(self, ini, fim):
        comeco = time.time()
        try:
            api = self.anx.garantir_sessao(self._log)
            # garantir_sessao só abre o navegador: quem observa a tela de
            # Pagamentos e pega os cabeçalhos de autenticação é esta chamada.
            if not api.capturar_credenciais(self._log):
                raise RuntimeError("A tela de Pagamentos não carregou a lista no Chrome.")
            self._log(f"\nLançamentos previstos de {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")
            self.q.put(("status", "Lendo os lançamentos..."))
            brutos = api.listar_a_pagar(f"{ini:%Y-%m-%d}", f"{fim:%Y-%m-%d}", log=self._log)

            # Rede de segurança: se a API ignorar o filtro, não deixamos o
            # relatório sair errado em silêncio.
            self.lancamentos = relatorio.filtrar_periodo(brutos, ini, fim, log=self._log)
            self._log(f"{len(self.lancamentos)} lançamento(s) no período.")
            if not self.lancamentos:
                self.q.put(("status", "Nenhum lançamento no período."))
                return

            titulos = sorted({str(i.get("tradePayableId")) for i in self.lancamentos
                              if i.get("tradePayableId")})
            self.q.put(("status", f"Lendo os anexos de {len(titulos)} título(s)..."))
            if not api._req_anexos:
                api.capturar_credenciais_anexos(self.lancamentos[0].get("id"))
            self.anexos = api.anexos_de_titulos(
                titulos, log=self._log,
                progresso=lambda f, t: self.q.put(("progresso", (f, t))),
                cancelar=self._parar.is_set)
            com = sum(1 for v in self.anexos.values() if v)
            self._log(f"{com} título(s) com anexo, {len(titulos) - com} sem.")

            ids = [str(i.get("id")) for i in self.lancamentos if i.get("id")]
            self.q.put(("status", f"Lendo o detalhe de {len(ids)} lançamento(s)..."))
            self.overviews = api.listar_overviews(
                ids, log=self._log,
                progresso=lambda f, t: self.q.put(("progresso", (f, t))),
                cancelar=self._parar.is_set)
            com_oc = sum(1 for v in self.overviews.values()
                         if (v.get("purchaseOrder") or {}).get("number"))
            com_obs = sum(1 for v in self.overviews.values() if (v.get("comment") or "").strip())
            self._log(f"{len(self.overviews)} detalhe(s) — {com_oc} com OC, "
                      f"{com_obs} com observação.")

            # O cadastro de Contatos é o que permite o Pix por telefone,
            # e-mail e chave aleatória: o segmento B exige o CPF/CNPJ de quem
            # recebe, e o lançamento só traz o nome. Falhar aqui não derruba a
            # busca — sem o cadastro a planilha sai igual, só a remessa é que
            # fica mais pobre.
            self.q.put(("status", "Lendo o cadastro de Contatos..."))
            try:
                self.participantes = api.listar_participantes(log=self._log)
                casaram = sum(
                    1 for i in self.lancamentos
                    if util.norm_espaco(i.get("paidTo") or "") in self.participantes)
                self._log(f"{len(self.participantes)} contato(s) com documento; "
                          f"{casaram} de {len(self.lancamentos)} lançamento(s) "
                          "casaram pelo nome.")
            except Exception as e:
                self.participantes = {}
                self._log(f"[!] não consegui ler o cadastro de Contatos: {e}\n"
                          "    O Pix por telefone/e-mail/aleatória vai ficar de "
                          "fora da remessa.")

            self.contas = relatorio.resumo_por_conta(self.lancamentos)
            self.q.put(("contas", self.contas))
            self.q.put(("status", f"Pronto em {_fmt_dur(time.time() - comeco)}. "
                                  "Marque as contas e clique em Gerar."))
            # O que a tela de Início mostra sai daqui: quem contou os
            # lançamentos foi esta rotina, e contar de novo custaria outra
            # sessão do ERP.
            _no_dia = sum(t for _n, _q, t, _p, _i in self.contas)
            auditoria.registrar(
                "Buscar lançamentos",
                f"{len(self.lancamentos)} lançamento(s) · "
                f"{relatorio.brl(_no_dia)}",
                aba="pag", resultado="ok",
                numeros={"lancamentos": len(self.lancamentos),
                         "total": _no_dia})
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui buscar os lançamentos."))
            auditoria.registrar("Buscar lançamentos", str(e)[:120],
                                aba="pag", resultado="erro")
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
        # A lista que a tela mostra passa a ser a MESMA que o rodapé soma. O
        # `_t_buscar` já grava `self.contas` antes de enfileirar, mas quem
        # desenha recebe a lista por parâmetro: sem esta linha, o total do
        # rodapé dependia de as duas nunca se separarem.
        self.contas = list(contas)
        self.canvas.configure(height=px(170))
        self.barra.pack(side="right", fill="y")
        widgets.cartao_elastico(self.f_contas, cheio=True)
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        for nome, qtd, total, pagos, ignorada in contas:
            # Contas de ajuste começam desmarcadas: quase nunca entram, mas
            # ficam visíveis para o caso de precisarem entrar.
            v = tk.BooleanVar(value=not ignorada and qtd > 0)
            self.vars_contas[nome] = v
            extra = []
            if ignorada:
                extra.append("conta de ajuste")
            if pagos:
                extra.append(f"{pagos} já pago(s)")
            rotulo = (f"{nome}  —  {qtd} a pagar, {relatorio.brl(total)}"
                      + (f"  ({'; '.join(extra)})" if extra else ""))
            ttk.Checkbutton(self.contas_box, text=rotulo, variable=v).pack(anchor="w")

        # "Marcar/Desmarcar todas" e a contagem saem da lista e sobem para o
        # cabeçalho do cartão: dentro da lista, eles rolavam junto com ela e
        # sumiam da tela justamente quando havia contas demais para conferir.
        self.rodape_contas.limpar_links()
        self.rodape_contas.link("Marcar todas", lambda: self._todas_contas(True))
        self.rodape_contas.link("Desmarcar todas",
                                lambda: self._todas_contas(False))
        for _, v in self.vars_contas.items():
            v.trace_add("write", lambda *_a: self._contar_contas())
        self._contar_contas()
        self.b2.configure(state="normal")

    def _todas_contas(self, marcar: bool):
        for v in self.vars_contas.values():
            v.set(marcar)

    def _contar_contas(self):
        """A frase que se confere antes de gerar. O total é o das contas
        MARCADAS, e não o do dia: é ele que vira planilha."""
        try:
            marcadas = {n for n, v in self.vars_contas.items() if v.get()}
        except tk.TclError:
            return                       # aba fechando com o trace pendente
        total = sum(t for n, _q, t, _p, _i in (self.contas or ())
                    if n in marcadas)
        self.rodape_contas.definir(marcados=len(marcadas), total_reais=total,
                                   de_fora=len(self.vars_contas) - len(marcadas))

    # --------------------------------------------------------------- etapa 2
    def _linhas_ja_lidas(self) -> dict:
        """`{id do lançamento: linha digitável}` do que o passo 2 já leu.

        Existe porque o boleto só é lido com o navegador na mão, no passo 2, e
        a janela de confirmação roda ANTES dele. Quem já rodou o passo 2 uma
        vez no mesmo período volta a ver as linhas; quem não rodou vê o
        recado em vermelho, que é a verdade daquele momento."""
        if not self.resultado:
            return {}
        return {r.get("id"): r.get("dados")
                for regs in self.resultado.contas.values() for r in regs
                if r.get("id") and r.get("dados") and r.get("tipo") == "Boleto"}

    def _janela_confirmar(self, alvos, destacar=()) -> set | None:
        """Quais lançamentos entram hoje — um a um, antes de tudo.

        Ela nasceu só para os pagamentos que o dono do escritório quer ver
        antes (distribuição de lucro para os sócios, por exemplo), e por isso
        só abria quando o `confirmar_antes.json` tinha nomes. Marcar a linha
        de laranja na planilha não bastava: a planilha é lida DEPOIS de
        gerada, e a pergunta precisa acontecer antes.

        Mas o EFEITO dela sempre valeu para qualquer linha — o que se desmarca
        aqui sai da planilha E da remessa, com motivo, porque as duas
        descendem do mesmo `montar_registros`. Só o alcance é que era estreito:
        um lançamento de fornecedor não cadastrado não tinha onde ser tirado
        do dia, a não ser desmarcando a conta inteira.

        Agora ela lista tudo, e o `confirmar_antes.json` mudou de função: em
        vez de decidir se a janela abre, decide quem aparece com ⚠ e na frente
        dentro da conta. A regra já cadastrada não se perde — deixa de ser
        porteiro e vira destaque.

        Cada linha mostra QUEM RECEBE em duas alturas: o favorecido em negrito
        e, embaixo, a forma de pagar em fonte de largura fixa (a chave Pix, a
        linha digitável, o banco/agência/conta). Sem isso, confirmar era dizer
        sim a um nome e a um valor sem ver para onde o dinheiro ia — e é
        justamente o destino que a remessa não deixa mais ninguém conferir
        depois.

        Roda na thread da interface (é chamada de `gerar`, antes de submeter
        ao navegador), então pode abrir janela e esperar resposta à vontade.
        Devolve os ids NÃO confirmados, ou None se a pessoa cancelou tudo.
        """
        top = tk.Toplevel(self)
        top.title("Confirmar o que entra")
        top.geometry(f"{px(980)}x{px(680)}")
        top.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(top)
        top.configure(background=widgets.cores()["fundo"])

        moldura = ttk.Frame(top, padding=18, style="Fundo.TFrame")
        moldura.pack(fill="both", expand=True)
        cab = widgets.Cabecalho(
            moldura, "Confira o que entra hoje",
            "Já vem tudo marcado. Desmarque o que NÃO deve entrar — ele sai "
            "da planilha e da remessa, e aparece na aba NÃO ENTRARAM com o "
            "motivo. O ⚠ é quem você mandou conferir sempre.",
            trilha="Diário  ›  Remessa e Retorno  ›  Passo 2")
        # A legenda existe porque a cor sozinha não diz o que ela significa, e
        # a pergunta que ela responde ("âmbar me impede de gerar?") é a que
        # fazia a janela parecer quebrada.
        legenda = cab.rodape
        legenda.pack(anchor="w", pady=px((8, 0)))
        for texto, estilo in (
                ("●  entra", "FundoOk.TLabel"),
                ("●  entra com ressalva — a remessa não leva, pague à mão",
                 "FundoAtencao.TLabel"),
                ("●  fica de fora — desmarcado", "FundoErro.TLabel")):
            ttk.Label(legenda, text=texto, style=estilo
                      ).pack(side="left", padx=px((0, 18)))
        cab.pack(fill="x", pady=px((0, 14)))

        cartao = widgets.Cartao(moldura, "Lançamentos do dia")
        cartao.pack(fill="both", expand=True)

        # Rolagem, como na conferência da remessa: a janela era
        # `resizable(False, False)` e listava um punhado de nomes; listando o
        # dia inteiro (~300 lançamentos) ela sairia pela borda da tela, com o
        # botão de confirmar fora do alcance.
        painel = tk.Canvas(cartao, highlightthickness=0)
        barra = ttk.Scrollbar(cartao, orient="vertical", command=painel.yview)
        dentro = ttk.Frame(painel)
        dentro.bind("<Configure>",
                    lambda _e: painel.configure(scrollregion=painel.bbox("all")))
        janela = painel.create_window((0, 0), window=dentro, anchor="nw")
        painel.bind("<Configure>",
                    lambda e: painel.itemconfigure(janela, width=e.width))
        painel.configure(yscrollcommand=barra.set)
        widgets.estilo_canvas(painel)
        barra.pack(side="right", fill="y")
        painel.pack(side="left", fill="both", expand=True)

        def pede_olhada(item) -> bool:
            return regras.exige_confirmacao(item.get("paidTo") or "", destacar)

        por_conta: dict[str, list] = {}
        for item in alvos:
            por_conta.setdefault(relatorio.nome_da_conta(item), []).append(item)

        ja_lido = self._linhas_ja_lidas()
        por_id = {str(i.get("id")): i for i in alvos}
        marcas = []                       # [(id, var)]
        for conta in sorted(por_conta):
            itens = sorted(por_conta[conta],
                           key=lambda i: (not pede_olhada(i),
                                          relatorio.chave(i.get("paidTo") or "")))
            cabecalho = ttk.Frame(dentro)
            cabecalho.pack(fill="x", pady=px((14, 4)))
            ttk.Label(cabecalho, style="Secao.TLabel",
                      text=conta[:46]).pack(side="left")
            ttk.Label(cabecalho, style="Apoio.TLabel",
                      text=(f"{len(itens)} · " + relatorio.brl(
                          sum(relatorio.valor_do_item(i) for i in itens)))
                      ).pack(side="right")
            ttk.Separator(dentro, orient="horizontal").pack(fill="x")
            for pos, item in enumerate(itens):
                v = tk.BooleanVar(value=True)
                marcas.append((str(item.get("id")), v))
                self._linha_confirmar(dentro, item, v, pos,
                                      pede_olhada(item), ja_lido,
                                      lambda: atualizar())

        resposta = {"cancelou": True}

        def confirmar():
            resposta["cancelou"] = False
            top.destroy()

        rodape = widgets.RodapeTabela(cartao)
        rodape.pack(side="bottom", fill="x", pady=px((12, 0)))
        rodape.link("Marcar todas", lambda: todas(True))
        rodape.link("Desmarcar todas", lambda: todas(False))

        def atualizar():
            """Quantos e quanto, a cada clique. É o número que se confere
            antes de gerar; as outras ações irreversíveis do app (Aportes,
            Acessórias) já o mostram antes de perguntar."""
            vao = [i for i, v in marcas if v.get()]
            total = sum(relatorio.valor_do_item(por_id[i]) for i in vao
                        if i in por_id)
            rodape.definir(marcados=len(vao), total_reais=total,
                           de_fora=len(marcas) - len(vao))

        def todas(valor: bool):
            for _, v in marcas:
                v.set(valor)
            atualizar()

        atualizar()

        acoes = ttk.Frame(moldura, style="Fundo.TFrame")
        acoes.pack(fill="x", pady=px((14, 0)))
        widgets.Botao(acoes, "Confirmar e gerar", papel="acao",
                      command=confirmar).pack(side="right")
        widgets.Botao(acoes, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=px((0, 8)))

        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.bind("<Escape>", lambda _e: top.destroy())
        try:
            top.grab_set()
            top.focus_set()
        except tk.TclError:
            pass
        self.wait_window(top)

        if resposta["cancelou"]:
            return None
        return {ident for ident, v in marcas if not v.get()}

    def _linha_confirmar(self, pai, item, var, pos, olhar, ja_lido, ao_marcar):
        """Uma linha da janela: marca, valor, quem recebe (em duas alturas).

        NÃO é `ttk.Treeview`, e não por falta de tentativa: a tabela do Tk não
        aceita widget dentro de célula (então não há caixa de marcar), não faz
        duas fontes na mesma célula e não quebra a célula em duas linhas. As
        três coisas são exatamente o que esta lista precisa. Um `Frame` por
        linha custa mais widgets e entrega o que o mockup pede.
        """
        linha = ttk.Frame(pai)
        linha.pack(fill="x")
        # O `_marcou` é definido mais abaixo, junto do rótulo que ele repinta;
        # o Tk só o chama quando alguém clica, então a ordem não importa.
        ttk.Checkbutton(linha, variable=var, command=lambda: _marcou()
                        ).pack(side="left", padx=px((0, 8)), pady=px(6))
        # O valor primeiro e alinhado à direita, em fonte de largura fixa: é a
        # coluna que se lê de cima a baixo somando de cabeça.
        ttk.Label(linha, text=relatorio.brl(relatorio.valor_do_item(item)),
                  style="Num.TLabel", width=14, anchor="e"
                  ).pack(side="left", padx=px((0, 14)))

        quem = ttk.Frame(linha)
        quem.pack(side="left", fill="x", expand=True)
        nome, dado, estado = quem_recebe(item, ja_lido)
        topo = ttk.Frame(quem)
        topo.pack(fill="x")
        if olhar:
            ttk.Label(topo, text="⚠", style="Atencao.TLabel"
                      ).pack(side="left", padx=px((0, 5)))
        ttk.Label(topo, text=nome[:44], style="Forte.TLabel").pack(side="left")
        desc = (item.get("description") or "").strip()
        if desc:
            ttk.Label(topo, text="·  " + desc[:52], style="Tenue.TLabel"
                      ).pack(side="left", padx=px((8, 0)))
        # A segunda altura: a forma de pagar, na cor do que vai acontecer com
        # ela. Âmbar é "entra na planilha, mas a remessa não leva"; vermelho é
        # só para quem fica de fora — e quem fica de fora, nesta janela, é o
        # que a pessoa desmarcou. Sem essa amarração a legenda do topo teria
        # uma cor que nunca aparece.
        lbl_dado = ttk.Label(quem, text=dado, style=ESTILO_DO_DADO[estado])
        lbl_dado.pack(anchor="w", pady=px((1, 0)))

        def _pintar():
            lbl_dado.configure(
                style="MonoMiniErro.TLabel" if not var.get()
                else ESTILO_DO_DADO[estado])
        _pintar()
        # A terceira: vencimento, OC e centro de custo. Estavam só embutidos na
        # descrição, misturados com o resto da frase — e são justamente o que
        # se procura para decidir se o pagamento é DESTE dia e DESTA obra.
        # Saem do próprio lançamento, sem rede: `centro_de_custo` lê o item, e
        # o `achar_oc` cai na descrição quando o detalhe não carregou.
        venc = relatorio.data_do_item(item)
        partes = [f"vence {venc:%d/%m/%Y}" if venc else "sem vencimento"]
        oc = relatorio.achar_oc(item, self.anexos.get(
            str(item.get("tradePayableId"))) or [], "",
            self.overviews.get(str(item.get("id"))) or {})
        if oc:
            partes.append(f"OC {oc}")
        cc = relatorio.centro_de_custo(item)
        if cc:
            partes.append(cc[:44])
        ttk.Label(quem, text="  ·  ".join(partes), style="Tenue.TLabel"
                  ).pack(anchor="w", pady=px((1, 6)))

        def _marcou():
            _pintar()
            ao_marcar()

    def gerar(self):
        if self.worker and not self.worker.done():
            return
        escolhidas = [n for n, v in self.vars_contas.items() if v.get()]
        if not escolhidas:
            messagebox.showinfo("Pagamentos do Dia", "Marque ao menos uma conta.")
            return
        if not self.v_pasta.get().strip():
            messagebox.showwarning("Pasta", "Escolha onde salvar a planilha.")
            return

        # Antes até da janela de confirmação: com o navegador ocupado nada vai
        # rodar, e não se pede a alguém que confira pagamento por pagamento
        # para depois dizer que não dava.
        if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
            return

        # A pergunta vem ANTES de ocupar o navegador: quem cancela aqui não
        # deve ter consumido a sessão do ERP, que é uma só por usuário.
        nao_confirmados = self._confirmacoes_pendentes(escolhidas)
        if nao_confirmados is None:
            self.q.put(("status", "Cancelado — nada foi gerado."))
            return

        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.worker = self.anx.submeter("Pagamentos do Dia — gerar planilha",
                                        self._t_gerar, escolhidas,
                                        nao_confirmados, dona=self)

    def _confirmacoes_pendentes(self, escolhidas) -> set | None:
        """set() quando não há nada a perguntar; None quando cancelaram."""
        alvos = alvos_para_confirmar(self.lancamentos, escolhidas,
                                     regras.carregar_fornecedores())
        if not alvos:
            return set()
        return self._janela_confirmar(alvos, regras.carregar_confirmar())

    def _montar_resultado(self, escolhidas, nao_confirmados=()):
        """Apura os lançamentos das contas marcadas. NÃO escreve arquivo.

        Existe separado do `_t_gerar` desde 30/08/2026 porque a planilha e a
        remessa saem daqui — e antes só a planilha sabia chegar. `self.resultado`
        era preenchido dentro do passo 2, então "gerar remessa" exigia gerar o
        .xlsx primeiro, mesmo quando ninguém o queria. O laço não era regra: era
        onde a atribuição estava.

        Roda na thread do NAVEGADOR (é ela quem baixa os PDFs quando o cruzamento
        está ligado). Devolve o `Resultado`, ou None quando não há o que apurar —
        e nesse caso já deixou o recado no status.
        """
        ini, fim = self._periodo()
        escolha = {relatorio.chave(n) for n in escolhidas}
        selecionados = [i for i in self.lancamentos
                        if relatorio.chave(relatorio.nome_da_conta(i)) in escolha]

        a_pagar, pagos = relatorio.separar_pagos(selecionados)
        if pagos:
            self._log(f"\n{len(pagos)} já pago(s) no período"
                      + ("; incluídos." if self.v_incluir_pagos.get() else "; fora."))
        if not self.v_incluir_pagos.get():
            selecionados = a_pagar
        if not selecionados:
            self.q.put(("status", "Nada a pagar nas contas marcadas."))
            return None

        textos, urls_ocr = {}, set()
        if self.v_cruzar.get():
            textos, urls_ocr = self._baixar_textos(selecionados)

        # O cadastro local é lido UMA vez e serve aos dois: a chave Pix
        # (formato antigo) e a identidade de quem recebe (formato novo).
        cadastro_reembolso = reembolso.carregar(_pasta_base())
        resultado = relatorio.montar_registros(
            selecionados, self.anexos, self.overviews, textos,
            pix_reembolso=reembolso.chaves(cadastro_reembolso),
            urls_ocr=urls_ocr,
            regras_fornecedor=regras.carregar_fornecedores(),
            ids_nao_confirmados=nao_confirmados,
            # Os Contatos do ERP entram aqui porque é aqui que se descobre
            # QUEM recebe um reembolso. Para o fornecedor comum eles
            # continuam sendo consultados na remessa, onde sempre foram.
            participantes=self.participantes,
            cadastro_reembolso=cadastro_reembolso)
        self.resultado = resultado
        self._periodo_do_resultado = (ini, fim)
        if not resultado.contas and not resultado.omitidos:
            self.q.put(("status", "Nenhuma linha para as contas marcadas."))
            return None
        return resultado

    def _t_apurar_para_remessa(self, escolhidas, nao_confirmados=()):
        """Apura e devolve o controle à interface, que abre a conferência.

        É o caminho "Buscar -> Gerar remessa" sem passar pela planilha. O que
        ele NÃO faz é escrever o .xlsx — quem quiser a planilha clica no passo
        que a escreve.
        """
        try:
            resultado = self._montar_resultado(escolhidas, nao_confirmados)
            if resultado is None:
                return
            n = sum(len(r) for r in resultado.contas.values())
            self._log(f"\n{n} pagamento(s) apurado(s) em "
                      f"{len(resultado.contas)} conta(s). Abrindo a conferência "
                      f"da remessa.")
            self.q.put(("status", f"{n} pagamento(s) — confira a remessa."))
            # De volta à thread da interface: a conferência é uma janela, e
            # gravar .REM é disco local. Nada disso é assunto do navegador, e
            # segurá-lo enquanto alguém confere linha a linha bloquearia as
            # outras oito abas pelo tempo da leitura.
            self.q.put(("abrir_remessa", None))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui apurar os lançamentos."))
        finally:
            self.q.put(("botoes", "normal"))

    def _t_gerar(self, escolhidas, nao_confirmados=()):
        comeco = time.time()
        try:
            ini, fim = self._periodo()
            resultado = self._montar_resultado(escolhidas, nao_confirmados)
            if resultado is None:
                return
            registros, omitidos = resultado.contas, resultado.omitidos

            destino = (Path(self.v_pasta.get().strip())
                       / f"pagamentos_{ini:%Y-%m-%d}"
                       f"{'' if ini == fim else f'_a_{fim:%Y-%m-%d}'}.xlsx")
            arquivo = relatorio.gerar_excel(resultado, destino, log=self._log)

            n = sum(len(r) for r in registros.values())
            total = sum(x["valor"] for r in registros.values() for x in r)
            atencao = sum(1 for r in registros.values() for x in r
                          if x["status"].startswith("ATEN"))
            self._log(f"\n{n} pagamento(s) em {len(registros)} conta(s). "
                      f"Total {relatorio.brl(total)}")
            for conta, regs in registros.items():
                self._log(f"  {conta[:46]:46} {len(regs):>3}  "
                          f"{relatorio.brl(sum(x['valor'] for x in regs)):>16}")
            if atencao:
                self._log(f"\n{atencao} linha(s) em laranja para conferir na mão.")
            if omitidos:
                self._log(f"\n{len(omitidos)} lançamento(s) fora da planilha "
                          f'(aba "{relatorio.ABA_OMITIDOS}"):')
                for motivo in dict.fromkeys(o["motivo"] for o in omitidos):
                    quantos = sum(1 for o in omitidos if o["motivo"] == motivo)
                    self._log(f"  {quantos:>3}  {motivo}")
            self._log(f"\nPlanilha: {str(arquivo).replace(chr(92), '/')}  "
                      f"({_fmt_dur(time.time() - comeco)})")
            self.q.put(("arquivo", arquivo))
            self.q.put(("status", f"{n} pagamento(s) · {relatorio.brl(total)} · "
                                  f"{atencao} para conferir"
                                  + (f" · {len(omitidos)} fora" if omitidos else "")))
            _sem_anexo = sum(1 for r in registros.values() for x in r
                             if "sem anexo" in x["status"].lower())
            auditoria.registrar(
                "Gerar a planilha",
                f"{n} pagamento(s) · {relatorio.brl(total)}"
                + (f" · {atencao} para conferir" if atencao else ""),
                aba="pag",
                resultado="atencao" if (atencao or omitidos) else "ok",
                numeros={"lancamentos": n, "total": total,
                         "sem_anexo": _sem_anexo})
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar a planilha."))
            auditoria.registrar("Gerar a planilha", str(e)[:120],
                                aba="pag", resultado="erro")
        finally:
            self.q.put(("botoes", "normal"))

    def _diagnostico_documentos(self):
        """Onde, no que o ERP já mandou, existe CPF/CNPJ — e se ele varia.

        Pergunta em aberto do Pix: o segmento B exige o documento de quem
        recebe, e hoje só o temos quando a própria chave é o CPF/CNPJ. Este
        relatório diz se o dado já vem do ERP em algum campo que ninguém lia.

        Varre as TRÊS fontes que o passo 1 deixou em memória — a lista, o
        detalhe e os anexos —, porque são payloads diferentes: olhar só uma
        responderia sobre ela, e não sobre o ERP.

        **Não imprime documento nenhum** — só o caminho, a contagem e quantos
        valores distintos. É o "distintos" que decide: um caminho com um valor
        só em todos os lançamentos é a própria empresa; um que varia com o
        lançamento é o fornecedor, e esse serve.
        """
        fontes = (
            ("lista", {str(i.get("id") or n): i
                       for n, i in enumerate(self.lancamentos)}),
            ("detalhe", self.overviews),
            ("anexos", self.anexos),
        )
        houve = False
        for rotulo, payloads in fontes:
            try:
                achados = remessa_dia.diagnostico_documentos(payloads)
            except Exception:
                continue                 # diagnóstico nunca derruba a busca
            if not achados:
                continue
            houve = True
            self._log(f"\nCPF/CNPJ no {rotulo} do ERP "
                      "(campo · em quantos · valores distintos):")
            for caminho, quantos, distintos in achados[:8]:
                pista = ("varia por lançamento" if distintos > 1
                         else "sempre o mesmo")
                self._log(f"  {caminho[:50]:50} {quantos:>4}  {distintos:>4}  {pista}")
        if not houve:
            self._log("Documento do favorecido: nenhum CPF/CNPJ válido na lista, "
                      "no detalhe nem nos anexos — o Pix por telefone/e-mail/"
                      "aleatória seguirá saindo à mão.")

    # ------------------------------------------------------------- o retorno
    def ler_retorno(self):
        """Lê os arquivos que o banco devolve e mostra o que houve em cada um.

        Não é etapa do fluxo do dia: o retorno chega horas ou dias depois, e
        muitas vezes é preciso ler o MESMO arquivo duas vezes — a primeira só
        diz "recebi", e o desfecho real vem depois de o master assinar no
        SicoobNet. Por isso o botão não tem número e não depende dos passos.

        **São VÁRIOS arquivos, e é assim que eles chegam.** São até 18 contas
        no mesmo dia, cada uma lida duas vezes, e o SicoobNet ("Gerenciamento
        de Arquivos → Obter Retorno") baixa vários de uma vez — soltos ou num
        `.zip`. Escolher um, ler, fechar a janela e recomeçar 35 vezes é o
        caminho mais curto para alguém deixar de conferir uma conta.

        Um arquivo só e sem falha continua abrindo a janela de sempre: é o
        caso mais comum e o que já estava certo.
        """
        caminhos = filedialog.askopenfilenames(
            title="Escolha os arquivos de retorno do banco",
            filetypes=[("Retorno CNAB", "*.RET *.ret *.TXT *.txt *.zip *.ZIP"),
                       ("Todos", "*.*")])
        # O Tk devolve tupla no Windows e uma lista do Tcl em outros lugares;
        # `splitlist` entende as duas e devolve tupla nas duas.
        caminhos = self.tk.splitlist(caminhos) if caminhos else ()
        if not caminhos:
            return

        try:
            historico = _historico(self._log)
        except Exception as e:
            # Sem o registro central dá para LER o arquivo, mas não para dizer
            # de quais lançamentos ele fala nem para guardar a resposta. Ler
            # assim mesmo é melhor que não ler: o arquivo é a informação.
            historico = None
            self._log(f"\n[!] Sem o registro de remessas ({e}). Vou ler o "
                      f"arquivo assim mesmo, mas sem casar com o ERP e sem "
                      f"gravar o resultado.")

        resultados = retorno_dia.ler_varios(caminhos, historico)
        if not resultados:
            return
        validos = [r for r in resultados if isinstance(r, retorno_dia.Resumo)]
        falhas = [r for r in resultados if isinstance(r, retorno_dia.Falha)]

        # Um arquivo, um desfecho: as duas pontas do comportamento de antes
        # ficam exatamente como eram. Do segundo arquivo em diante — ou tendo
        # falha ao lado de resumo — a lista é que responde "e as outras?".
        if len(validos) == 1 and not falhas:
            self._janela_retorno(validos[0], historico)
            return
        if not validos and len(falhas) == 1:
            messagebox.showerror(
                "Retorno",
                f"Não consegui ler o arquivo de retorno.\n\n"
                f"{falhas[0].origem}: {falhas[0].motivo}")
            return
        self._janela_retornos(resultados, historico)

    def _copiar_retorno(self, resumo):
        """Guarda o `.RET` lido ao lado da remessa que ele responde.

        **Copiar, não mover.** O arquivo está onde o navegador o baixou, e é
        de lá que a pessoa o reabre se quiser conferir; movê-lo faria sumir da
        pasta de downloads o que ela acabou de baixar. E o `.RET` não estava
        guardado em lugar nenhum: passada a janela, a única prova do que o
        banco respondeu era o que tinha ido para o banco de dados.

        Vai para a pasta do `.REM` — pergunta e resposta juntas. Sem ela (ou
        com ela em outra máquina), cai no `_RETORNOS/` do destino da tela.

        **É best-effort**: falhar aqui vira uma linha no Registro, nunca uma
        exceção que impeça o `aplicar_retorno`. O que importa é o que foi
        gravado no banco; a cópia é conveniência.
        """
        try:
            pasta = (Path(resumo.pasta_da_remessa)
                     if resumo.pasta_da_remessa else None)
            if pasta is None or not pasta.is_dir():
                pasta = Path(self.v_pasta.get().strip() or ".") / "_RETORNOS"
            alvo = retorno_dia.guardar_copia(
                resumo.conteudo, pasta,
                retorno_dia.nome_da_copia(resumo, datetime.datetime.now()))
            self._log(f"  cópia do retorno: "
                      f"{str(alvo).replace(chr(92), '/')}")
        except Exception as e:
            self._log(f"  [!] não deu para guardar a cópia do retorno"
                      f"{f' ({resumo.origem})' if resumo.origem else ''}: {e}")

    def _seguir_para_a_baixa(self, linhas, fechar):
        """Do retorno lido até a thread do navegador — um caminho só.

        Recebe LINHAS e não um `Resumo` porque a janela de vários junta as de
        várias remessas numa lista: a baixa não depende da conta pagadora, ela
        casa pela `referencia` de cada item, que é o id do lançamento no ERP.
        """
        # `separar` só olha o `.linhas` do que recebe. O resumo montado aqui é
        # o saco que carrega as linhas até lá, e não um retorno de verdade —
        # daí o NSA zero, que nunca vai à tela nem ao banco.
        sep = baixa_erp.separar(retorno_dia.Resumo(
            convenio="", nsa=0, empresa="", linhas=list(linhas)))
        for linha, motivo in sep.de_fora:
            self._log(f"  fora da baixa: {linha.seu_numero} "
                      f"{linha.favorecido[:28]} — {motivo}")
        if not sep.baixaveis:
            messagebox.showinfo(
                "Baixa",
                "Nenhum pagamento deste retorno pode ser baixado agora.\n\n"
                "Só entra o que o banco marcou como PAGO. Aguardando "
                "assinatura não conta: o dinheiro ainda não saiu.")
            return
        escolhidos = self._janela_baixa(sep)
        if not escolhidos:
            return
        fechar()
        if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
            return
        self.q.put(("botoes", "disabled"))
        self.worker = self.anx.submeter(
            "Pagamentos do Dia — baixar no Mais Controle",
            self._t_baixar, escolhidos, dona=self)

    def _janela_retorno(self, resumo, historico):
        top = tk.Toplevel(self)
        top.title(f"Retorno do banco — arquivo nº {resumo.nsa:06d}")
        top.geometry(f"{px(980)}x{px(600)}")
        widgets.barra_de_titulo(top)
        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)

        pagos = resumo.quantos("ok")
        pendentes = resumo.quantos("pendente")
        rejeitados = resumo.quantos("rejeitado")

        ttk.Label(moldura, style="Titulo.TLabel",
                  text=f"{resumo.empresa.strip()} · arquivo nº {resumo.nsa:06d}"
                  ).pack(anchor="w")
        ttk.Label(moldura, style="Apoio.TLabel",
                  text=f"{len(resumo.linhas)} pagamento(s) · "
                       f"R$ {resumo.total:,.2f}".replace(",", "X")
                       .replace(".", ",").replace("X", ".")
                  ).pack(anchor="w", pady=px((2, 8)))

        # O recado que evita o susto: no fluxo desta empresa, o retorno do
        # mesmo dia vem com tudo pendente porque quem assina é outra pessoa.
        # Sem esta linha, "AGUARDA ASSINATURA" em 13 pagamentos parece falha.
        if pendentes and not rejeitados:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=px(920),
                      justify="left",
                      text=f"⚠  {pendentes} pagamento(s) aguardando assinatura "
                           f"no SicoobNet. Isso é o esperado logo depois de "
                           f"enviar: o arquivo foi aceito, mas o dinheiro só "
                           f"sai quando o master assinar. Baixe o retorno de "
                           f"novo depois disso para ver o desfecho."
                      ).pack(anchor="w", pady=px((0, 8)))
        if resumo.remessa_desconhecida:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=px(920),
                      justify="left",
                      text="⚠  Esta remessa não está no registro central — "
                           "pode ser de antes dele existir, ou de outra "
                           "máquina. Dá para ler o arquivo, mas não para "
                           "apontar os lançamentos do ERP nem guardar o "
                           "resultado.").pack(anchor="w", pady=px((0, 8)))
        # O casamento pelo "seu número" salva o retorno cujo header não bate
        # com o registro — mas os números da tela deixam de ser os do arquivo
        # que a pessoa tem aberto no SicoobNet. Dizer os DOIS é o que impede
        # que isso pareça a tela falando de outra conta.
        if resumo.casado_pelo_seu_numero:
            ttk.Label(moldura, style="Atencao.TLabel", wraplength=px(920),
                      justify="left",
                      text=f"⚠  Este retorno foi reencontrado pelo "
                           f"“seu número”: o header diz convênio "
                           f"{resumo.convenio_do_header or '—'} / arquivo nº "
                           f"{resumo.nsa_do_header:06d}, e o registro tem esta "
                           f"remessa como convênio {resumo.convenio or '—'} / "
                           f"arquivo nº {resumo.nsa:06d}."
                      ).pack(anchor="w", pady=px((0, 8)))

        colunas = ("estado", "favorecido", "valor", "seu_numero", "motivos")
        tabela = ttk.Treeview(moldura, columns=colunas, show="headings",
                              height=14)
        for chave, titulo, larg in (("estado", "Situação", 150),
                                    ("favorecido", "Favorecido", 250),
                                    ("valor", "Valor", 110),
                                    ("seu_numero", "Seu número", 120),
                                    ("motivos", "O que o banco disse", 320)):
            tabela.heading(chave, text=titulo)
            tabela.column(chave, width=larg,
                          anchor="e" if chave == "valor" else "w")
        # Faltava: esta tabela era a única da tela sem o visual do painel, e
        # por tabela nenhuma a mais ela ganha junto a zebra, a cor de estado e
        # o clique no cabeçalho que ordena. Ordenar importa aqui mais que na
        # média: o retorno chega na ordem do BANCO, e quem lê quer ver os
        # rejeitados juntos, ou o maior valor primeiro.
        widgets.estilo_tabela(tabela)
        tabela.pack(fill="both", expand=True)

        for i, linha in enumerate(resumo.linhas):
            valor = f"{linha.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            tabela.insert("", "end", values=(
                linha.rotulo, linha.favorecido[:40], valor,
                linha.seu_numero, linha.motivos or "—"),
                tags=widgets.linha_zebrada(i, widgets.estado_de(linha.rotulo)))

        if resumo.faltando:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=px(920),
                      justify="left",
                      text=f"⚠  {len(resumo.faltando)} pagamento(s) da remessa "
                           f"NÃO vieram neste retorno: "
                           f"{', '.join(resumo.faltando[:6])}"
                           f"{'…' if len(resumo.faltando) > 6 else ''}. "
                           f"O banco devolve o que processou — o que sumiu no "
                           f"caminho não aparece sozinho."
                      ).pack(anchor="w", pady=px((8, 0)))

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=px((10, 0)))
        ttk.Label(rodape, style="Apoio.TLabel",
                  text=f"{pagos} pago(s) · {pendentes} aguardando · "
                       f"{rejeitados} rejeitado(s)").pack(side="left")

        def _guardar():
            # A regra mora no `retorno_dia`, que é puro e testado: aqui ela
            # era reparseada da frase do `motivos` (`split("=")[0]`), o que
            # guardava só a PRIMEIRA ocorrência quando o banco mandava duas, e
            # jogava fora a classificação (`Linha.estado`) que a tela acabara
            # de usar para escrever "PAGO" na linha de cima.
            respostas = retorno_dia.respostas_para_registro(resumo)
            try:
                quantos = historico.aplicar_retorno(
                    resumo.convenio, resumo.nsa, respostas,
                    estado=resumo.estado_da_remessa)
            except Exception as e:
                messagebox.showerror(
                    "Retorno",
                    widgets.recado_de_erro(e, "Não deu para guardar o "
                                              "retorno."))
                return
            self._log(f"\nRetorno do arquivo nº {resumo.nsa:06d} guardado: "
                      f"{quantos} pagamento(s) com resposta, remessa marcada "
                      f"como '{resumo.estado_da_remessa}'.")
            # A cópia vem DEPOIS de gravar, e não antes: o que não pode faltar
            # é o registro. Se ela falhar, sai uma linha no Registro e o
            # retorno continua guardado.
            self._copiar_retorno(resumo)
            messagebox.showinfo("Retorno", f"Guardado: {quantos} pagamento(s).")
            top.destroy()

        def _baixar():
            self._seguir_para_a_baixa(resumo.linhas, top.destroy)

        if historico is not None and not resumo.remessa_desconhecida:
            widgets.Botao(rodape, "Guardar o resultado", papel="acao",
                          command=_guardar).pack(side="right")
        # A baixa precisa da `referencia` de cada linha — o id do lançamento
        # no ERP —, e ela só existe quando a remessa foi encontrada no
        # registro central. Com a remessa desconhecida, o botão aparecia,
        # `separar` mandava todo mundo para `de_fora` e o recado que sobrava
        # era "nenhum pagamento pode ser baixado agora", que parece problema
        # do banco. O aviso amarelo lá em cima já diz o que de fato houve.
        if resumo.quantos("ok") and not resumo.remessa_desconhecida:
            widgets.Botao(rodape, "Dar baixa no Mais Controle", papel="passo",
                          command=_baixar).pack(side="right", padx=px((0, 8)))
        widgets.Botao(rodape, "Fechar", papel="neutro", command=top.destroy
                   ).pack(side="right", padx=px((0, 8)))

        top.transient(self.winfo_toplevel())
        top.grab_set()
        # Devolvida para quem abriu esta janela COMO DETALHE de outra poder
        # esperá-la fechar (`_janela_retornos`). Quem só abre e segue continua
        # podendo ignorar o retorno.
        return top

    def _janela_retornos(self, resultados, historico):
        """Uma linha por retorno lido, com os números de cada um.

        A janela de UM retorno mostra pagamento a pagamento, e é a certa para
        conferir uma conta. Com 18 contas na mesa, a pergunta muda: não é
        "quem foi pago", é "qual conta ainda não fechou". Daí a tabela ser de
        ARQUIVOS, com o detalhe a um duplo clique de distância — a janela de
        sempre, reaproveitada, sem uma segunda tela dizendo a mesma coisa de
        outro jeito.

        As falhas entram na MESMA lista, em vermelho. Uma caixa de erro antes
        da tabela esconderia o que deu certo atrás de um OK, e o que se quer
        saber é justamente se sobrou alguma conta sem ler.
        """
        validos = [r for r in resultados if isinstance(r, retorno_dia.Resumo)]
        conhecidos = [r for r in validos if not r.remessa_desconhecida]

        top = tk.Toplevel(self)
        top.title(f"Retornos do banco — {len(validos)} arquivo(s)")
        # Larga porque são nove colunas: espremidas, o Treeview corta a
        # SITUAÇÃO, que é justamente a coluna que se lê primeiro.
        top.geometry(f"{px(1180)}x{px(560)}")
        widgets.barra_de_titulo(top)
        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)

        ttk.Label(moldura, style="Titulo.TLabel",
                  text=f"{len(resultados)} arquivo(s) de retorno"
                  ).pack(anchor="w")
        ttk.Label(moldura, style="Apoio.TLabel",
                  text="Duplo clique numa linha abre o detalhe daquele "
                       "arquivo, pagamento a pagamento."
                  ).pack(anchor="w", pady=px((2, 8)))

        # O mesmo aviso da janela de um retorno só, uma vez pela lista: os
        # números que a linha mostra são os do REGISTRO, e não os do header do
        # arquivo. Qual header cada um trazia está no detalhe — repetir os dois
        # pares por linha numa lista de 18 contas não caberia.
        reencontrados = [r for r in validos if r.casado_pelo_seu_numero]
        if reencontrados:
            ttk.Label(moldura, style="Atencao.TLabel", wraplength=px(1120),
                      justify="left",
                      text=f"⚠  {len(reencontrados)} retorno(s) reencontrado(s) "
                           f"pelo “seu número”: o convênio / arquivo nº do "
                           f"header não bate com o do registro, e o que a lista "
                           f"mostra é o do registro. Abra o detalhe para ver os "
                           f"dois."
                      ).pack(anchor="w", pady=px((0, 8)))

        colunas = ("empresa", "conta", "nsa", "pagos", "aguardando",
                   "rejeitados", "faltando", "total", "situacao")
        tabela = ttk.Treeview(moldura, columns=colunas, show="headings",
                              height=14)
        for chave, titulo, larg, ancora in (
                ("empresa", "Empresa", 210, "w"),
                ("conta", "Ag-Conta", 110, "w"),
                ("nsa", "Arquivo nº", 90, "w"),
                ("pagos", "Pagos", 70, "e"),
                ("aguardando", "Aguardando", 100, "e"),
                ("rejeitados", "Rejeitados", 90, "e"),
                ("faltando", "Faltando", 80, "e"),
                ("total", "Total", 120, "e"),
                ("situacao", "Situação", 250, "w")):
            tabela.heading(chave, text=titulo)
            tabela.column(chave, width=larg, anchor=ancora)
        widgets.estilo_tabela(tabela)
        tabela.pack(fill="both", expand=True)

        #: id da linha da tabela -> o resumo que ela mostra. As falhas não
        #: entram: não há detalhe para abrir.
        por_linha = {}
        for i, item in enumerate(resultados):
            if isinstance(item, retorno_dia.Falha):
                # Vermelho e com o motivo à vista: é a única linha da tabela
                # que representa uma conta que NÃO foi lida.
                tabela.insert("", "end", values=(
                    item.origem, "—", "—", "—", "—", "—", "—", "—",
                    item.motivo),
                    tags=widgets.linha_zebrada(i, "erro"))
                continue
            situacao, marca = self._situacao_do_retorno(item)
            iid = tabela.insert("", "end", values=(
                item.empresa.strip()[:34],
                f"{item.agencia}-{item.conta}".strip("-") or "—",
                f"{item.nsa:06d}",
                item.quantos("ok"), item.quantos("pendente"),
                item.quantos("rejeitado"), len(item.faltando),
                relatorio.brl(float(item.total)), situacao),
                tags=widgets.linha_zebrada(i, marca))
            por_linha[iid] = item

        def _detalhe(_evento=None):
            resumo = por_linha.get(tabela.focus())
            if resumo is None:
                return
            detalhe = self._janela_retorno(resumo, historico)
            # O Tk tem UM grab por vez: abrindo o detalhe, esta janela perde o
            # dela, e fechando aquele o grab não volta sozinho. Esperar e
            # retomar deixa a lista modal como as outras janelas do app.
            if detalhe is not None:
                self.wait_window(detalhe)
                if top.winfo_exists():
                    top.grab_set()

        tabela.bind("<Double-1>", _detalhe)

        pagos = sum(r.quantos("ok") for r in validos)
        pendentes = sum(r.quantos("pendente") for r in validos)
        rejeitados = sum(r.quantos("rejeitado") for r in validos)

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=px((10, 0)))
        ttk.Label(rodape, style="Apoio.TLabel",
                  text=f"{pagos} pago(s) · {pendentes} aguardando · "
                       f"{rejeitados} rejeitado(s)").pack(side="left")

        def _guardar_tudo():
            """Um `aplicar_retorno` por remessa conhecida.

            Uma que falhe não fala pelas outras: com 18 contas, parar na
            primeira recusa deixaria 17 retornos lidos e não guardados, e a
            leitura teria de ser refeita inteira.
            """
            guardados = falhou = 0
            for resumo in conhecidos:
                respostas = retorno_dia.respostas_para_registro(resumo)
                try:
                    quantos = historico.aplicar_retorno(
                        resumo.convenio, resumo.nsa, respostas,
                        estado=resumo.estado_da_remessa)
                except Exception as e:
                    falhou += 1
                    self._log(f"\n[!] arquivo nº {resumo.nsa:06d} "
                              f"({resumo.origem}): não deu para guardar — {e}")
                    continue
                guardados += 1
                self._log(f"\nRetorno do arquivo nº {resumo.nsa:06d} "
                          f"({resumo.empresa.strip()}) guardado: {quantos} "
                          f"pagamento(s) com resposta, remessa marcada como "
                          f"'{resumo.estado_da_remessa}'.")
                self._copiar_retorno(resumo)
            messagebox.showinfo(
                "Retorno",
                f"Guardado: {guardados} remessa(s)."
                + (f"\n{falhou} não deu — veja o Registro." if falhou else ""))
            if not falhou and top.winfo_exists():
                top.destroy()

        def _baixar_tudo():
            # As linhas de TODAS as remessas conhecidas num saco só. A baixa
            # não depende da conta pagadora: ela casa pela `referencia` do
            # item, que é o id do lançamento no ERP.
            self._seguir_para_a_baixa(
                [linha for r in conhecidos for linha in r.linhas], top.destroy)

        if historico is not None and conhecidos:
            widgets.Botao(rodape, "Guardar tudo", papel="acao",
                          command=_guardar_tudo).pack(side="right")
        # A baixa precisa da `referencia`, que só existe nas remessas que o
        # registro central conhece — a mesma razão da janela de um retorno só.
        if historico is not None and any(r.quantos("ok") for r in conhecidos):
            widgets.Botao(rodape, "Dar baixa no Mais Controle", papel="passo",
                          command=_baixar_tudo).pack(side="right",
                                                     padx=px((0, 8)))
        widgets.Botao(rodape, "Fechar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=px((0, 8)))

        top.transient(self.winfo_toplevel())
        top.grab_set()
        return top

    @staticmethod
    def _situacao_do_retorno(resumo):
        """(frase, tag da cor) de UM retorno, para a linha da lista.

        A tag vai explícita, e não por `widgets.estado_de` sobre a frase: a
        linha da remessa que o registro não conhece precisa ficar âmbar, e
        "remessa não registrada" não contém nenhum dos estados que aquela
        função sabe ler. As tags são as mesmas (`ok`/`atencao`/`erro`/`info`)
        e quem as pinta continua sendo o `estilo_tabela`.

        A remessa desconhecida vem PRIMEIRO mesmo havendo rejeitado, porque é
        ela que decide o que dá para fazer com a linha: sem o registro não há
        o que guardar nem como baixar. As contagens ao lado continuam à vista.

        O "reencontrado ·" é PREFIXO e não substitui a frase, porque as duas
        coisas são independentes: reencontrar diz como se chegou à remessa (e
        avisa que os números da linha não são os do header do arquivo), e a
        frase continua dizendo o que o banco respondeu. Trocar uma pela outra
        esconderia os rejeitados atrás de um detalhe de casamento.
        """
        if resumo.remessa_desconhecida:
            return "remessa não registrada", "atencao"
        rejeitados = resumo.quantos("rejeitado")
        if rejeitados:
            frase, marca = f"{rejeitados} rejeitado(s) — veja o detalhe", "erro"
        elif resumo.quantos("pendente"):
            frase, marca = "aguardando assinatura no SicoobNet", "atencao"
        elif resumo.linhas and resumo.quantos("ok") == len(resumo.linhas):
            frase, marca = "tudo pago", "ok"
        else:
            frase, marca = "o banco não respondeu por todos", "info"
        if resumo.casado_pelo_seu_numero:
            frase = f"reencontrado · {frase}"
        return frase, marca

    # ----------------------------------------------------- baixa no ERP
    def _janela_baixa(self, sep):
        """Quais pagos baixar. Devolve a lista escolhida, ou [] se desistir.

        Nasce tudo marcado — são os que o BANCO disse que pagou, e a baixa é o
        desfecho normal deles. O que se desmarca aqui simplesmente não é
        baixado; nada some do retorno por causa disso.
        """
        top = tk.Toplevel(self)
        top.title("Baixar no Mais Controle")
        top.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(top)
        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)

        ttk.Label(moldura, style="Secao.TLabel",
                  text="Estes o banco pagou").pack(anchor="w")
        ttk.Label(moldura, style="Apoio.TLabel", wraplength=px(620),
                  justify="left",
                  text="Vão ser dados como pagos no Mais Controle, na data em "
                       "que o dinheiro saiu. Desmarque o que não deve ser "
                       "baixado agora."
                  ).pack(anchor="w", pady=px((0, 10)))

        marcas = []
        for linha in sep.baixaveis:
            v = tk.BooleanVar(value=True)
            marcas.append((linha, v))
            quando = getattr(linha, "data_real", None)
            ttk.Checkbutton(
                moldura, variable=v,
                text=(f"{relatorio.brl(float(linha.valor)):>14}  "
                      f"{linha.favorecido[:34]:<34}  {linha.seu_numero}"
                      + (f"  ·  pago em {quando:%d/%m/%Y}" if quando else ""))
            ).pack(anchor="w")

        # Os que o banco pagou e o app não sabe onde baixar. Ficam à vista de
        # propósito: são dinheiro que saiu e vai continuar em aberto no ERP.
        if sep.de_fora:
            ttk.Label(moldura, style="Secao.TLabel", text="Ficam de fora"
                      ).pack(anchor="w", pady=px((12, 2)))
            for linha, motivo in sep.de_fora:
                ttk.Label(moldura, style="Apoio.TLabel", wraplength=px(620),
                          justify="left",
                          text=(f"    {relatorio.brl(float(linha.valor))}  "
                                f"{linha.favorecido[:30]} — {motivo}")
                          ).pack(anchor="w")

        escolha: list = []

        def confirmar():
            escolha.extend(l for l, v in marcas if v.get())
            top.destroy()

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=px((14, 0)))
        widgets.Botao(rodape, "Baixar", papel="acao", command=confirmar
                      ).pack(side="right")
        widgets.Botao(rodape, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=px((0, 8)))
        top.grab_set()
        self.wait_window(top)
        return escolha

    def _t_baixar(self, linhas):
        """Roda na thread do navegador: a baixa fala com o ERP pela página."""
        try:
            api = self.anx.garantir_sessao(self._log)
            if not api.capturar_credenciais(self._log):
                raise RuntimeError("A tela de Pagamentos não carregou a lista "
                                   "no Chrome — sem ela não há credencial "
                                   "para falar com o ERP.")
            # Os cabeçalhos capturados da tela de Pagamentos servem ao legado:
            # authorization, company-id, user-id e organization-unit-id.
            _url, cabecalhos = api._req_pagos
            from aportes.mc_catalogos import Catalogos
            transporte = Catalogos(api.page, cabecalhos, self._log)

            self._log(f"\nBaixando {len(linhas)} pagamento(s) no Mais Controle...")
            resultados = baixa_erp.baixar(transporte, linhas,
                                          datetime.date.today(), log=self._log)
            deram = [r for r in resultados if r.ok]
            falharam = [r for r in resultados if not r.ok]
            hosts = {r.host for r in resultados if r.host}
            if hosts:
                self._log(f"  (endereço que respondeu: {', '.join(sorted(hosts))})")
            self._log(f"{len(deram)} baixado(s), {len(falharam)} não.")
            self.q.put(("status", f"Baixa: {len(deram)} ok, {len(falharam)} não."))
            self.q.put(("baixa", (len(deram), falharam)))
        except Exception as e:
            self._log(f"\nA baixa parou: {e}")
            self.q.put(("status", f"A baixa parou: {e}"))
        finally:
            self.q.put(("botoes", "normal"))

    # --------------------------------------------------------------- etapa 3
    def gerar_remessa(self):
        """Abre a conferência e grava os .REM — um por conta pagadora.

        NÃO exige mais a planilha. Até 30/08/2026 exigia, e o laço era acidente
        de código: `self.resultado` só era preenchido pelo passo 2, que também
        escrevia o .xlsx — então quem só queria a remessa gerava uma planilha
        que ninguém ia abrir. A apuração virou `_montar_resultado`, e os dois
        passos leem dela.

        Quando o resultado já está em memória (o passo 2 rodou), roda inteiro na
        thread da INTERFACE: não há navegador nem ERP, e escrever arquivo de
        texto local não justifica ocupar a sessão que só aceita um por vez.
        Quando NÃO está, a apuração precisa do navegador — aí ela vai para a
        thread dele, e a conferência abre quando ela volta.
        """
        if not self.resultado:
            escolhidas = [n for n, v in self.vars_contas.items() if v.get()]
            if not escolhidas:
                messagebox.showinfo(
                    "Remessa",
                    "Busque os lançamentos e marque as contas primeiro.")
                return
            # A mesma pergunta do passo 2, e pelo mesmo motivo: o que se
            # desmarca aqui sai do arquivo. Vem ANTES de ocupar o navegador —
            # quem cancela não deve ter consumido a sessão do ERP.
            nao_confirmados = self._confirmacoes_pendentes(escolhidas)
            if nao_confirmados is None:
                self.q.put(("status", "Cancelado — nada foi gerado."))
                return
            if self.anx.avisar_se_ocupado("a remessa"):
                return
            self._parar.clear()
            self.q.put(("botoes", "disabled"))
            self.worker = self.anx.submeter(
                "Remessa — apurar os lançamentos",
                self._t_apurar_para_remessa, escolhidas, nao_confirmados,
                dona=self)
            return

        # O período na tela pode ter mudado depois do passo 2 sem que ninguém
        # tenha clicado em "1. Buscar" — trocar a data não invalida nada
        # sozinha. Gerar a remessa a partir de uma apuração de outro dia é o
        # caminho para reenviar o que já foi pago, então aqui se pergunta em
        # vez de supor.
        try:
            periodo_agora = self._periodo()
        except ValueError:
            periodo_agora = None
        if periodo_agora and self._periodo_do_resultado \
                and periodo_agora != self._periodo_do_resultado:
            ini, fim = self._periodo_do_resultado
            if not messagebox.askyesno(
                    "Remessa",
                    f"O que está em memória é de {ini:%d/%m/%Y} a {fim:%d/%m/%Y}, "
                    f"e as datas na tela são outras.\n\n"
                    "A remessa sai do que foi apurado, não das datas. Gerar "
                    "assim mesmo?",
                    default="no"):
                return
        try:
            mapa_mc = contas_mc.carregar()
            cadastro = sicoob_contas.carregar()
        except Exception as e:
            # Sem os mapas não dá para montar a lista de prontidão — não há
            # cadastro para conferir. O que dá, e é o que faltava, é dizer QUAL
            # linha está torta (o recado do `carregar` cita empresa, pasta e
            # conta do ERP) e onde se conserta.
            messagebox.showerror(
                "Remessa",
                widgets.recado_de_erro(e, "Não consegui ler o cadastro.")
                + "\n\nO cadastro é editado no painel do Supabase; depois "
                  "feche e abra o app. Em \"Contas prontas para remessa\", "
                  "nesta aba, o botão \"Ver detalhes\" mostra a lista "
                  "inteira.")
            self._conferir_prontidao()
            return

        # O histórico entra ANTES do preparo, e não depois: é ele quem responde
        # "este boleto já saiu numa remessa?", e essa resposta tem de virar
        # IMPEDIMENTO — linha que não aparece marcável —, não um aviso depois
        # de a pessoa já ter conferido a lista.
        try:
            historico = _historico(self._log)
        except Exception as e:
            # Sem o registro central não se gera remessa. É a única operação
            # do app que se recusa por falta de nuvem, e de propósito: o valor
            # inteiro de perguntar "que número é o próximo?" é a resposta valer
            # para as duas máquinas. Um contador local diria um número que a
            # outra pessoa já pode ter usado — e NSA repetido pode significar
            # pagamento em dobro.
            messagebox.showerror(
                "Remessa",
                widgets.recado_de_erro(
                    e, "Não consegui falar com o registro de remessas.")
                + "\n\nA remessa NÃO foi gerada. O número sequencial (NSA) "
                  "precisa vir de um lugar só, senão as duas máquinas podem "
                  "gerar o mesmo — e repetir NSA pode virar pagamento em "
                  "dobro.")
            return
        try:
            preparado = remessa_dia.preparar(self.resultado.contas,
                                             self.participantes,
                                             historico=historico)
        except remessa_dia.RegistroMudo as e:
            # Mesmo motivo do bloco acima, um passo adiante: a ordem do dia do
            # "seu número" também precisa vir de um lugar só. Ela não derrubava
            # a remessa enquanto valia 0 e a numeração recomeçava; desde o
            # índice único no banco, numerar sobre um "não sei" é o arquivo
            # recusado no registro DEPOIS de a lista inteira ter sido
            # conferida. Recusar aqui é o mesmo desfecho, mais cedo e barato.
            messagebox.showerror(
                "Remessa",
                widgets.recado_de_erro(
                    e, "Não consegui falar com o registro de remessas.")
                + "\n\nA remessa NÃO foi gerada. O número sequencial (NSA) e a "
                  "ordem do dia do “seu número” precisam vir de um lugar só, "
                  "senão as duas máquinas podem gerar os mesmos — e repetir "
                  "NSA pode virar pagamento em dobro, enquanto repetir “seu "
                  "número” faz o retorno do banco casar com o pagamento "
                  "errado.")
            return
        pagadores, recusadas = {}, []
        for conta in preparado:
            pagador, motivo = remessa_dia.resolver_pagador(
                conta, mapa_mc, cadastro.empresas)
            if pagador:
                pagadores[conta] = pagador
            else:
                recusadas.append((conta, motivo))

        if not pagadores:
            # A lista de prontidão no lugar do recado de uma linha: quem chegou
            # aqui vai CORRIGIR o cadastro, e corrigir um campo por vez é
            # descobrir o próximo problema só na tentativa seguinte.
            messagebox.showinfo(
                "Remessa",
                "Nenhuma conta marcada gera remessa.\n\n"
                + self._faltas_por_conta(recusadas, mapa_mc, cadastro.empresas)
                + "\n\nCorrija no painel do Supabase e reabra o app.")
            self._conferir_prontidao()
            return

        if not self._janela_remessa(preparado, pagadores, recusadas, historico):
            self.q.put(("status", "Remessa cancelada — nada foi gravado."))
            return
        self._gravar_remessas(preparado, pagadores, historico)

    def _faltas_por_conta(self, recusadas, mapa_mc, empresas) -> str:
        """"conta: falta; falta" para cada conta que não gerou remessa.

        As faltas saem da MESMA função que a tabela da aba
        (`remessa_dia.prontidao`), e são TODAS — o `motivo` que
        `resolver_pagador` devolve é só o primeiro, porque quem gera precisa de
        um veredito. Aqui quem lê vai consertar, e uma lista pela metade é uma
        segunda viagem ao painel.

        Conta que nem entra na prontidão (fora do mapa, ou de outro banco)
        continua com o motivo dela: ali não há cadastro a conferir."""
        try:
            por_conta = {util.norm_espaco(c.conta_erp): c
                         for c in remessa_dia.prontidao(mapa_mc, empresas)}
        except Exception:                                     # noqa: BLE001
            por_conta = {}
        linhas = []
        for conta, motivo in recusadas[:8]:
            c = por_conta.get(util.norm_espaco(conta))
            linhas.append(f"• {conta}: "
                          + ("; ".join(c.faltas) if c and c.faltas else motivo))
        if len(recusadas) > 8:
            linhas.append(f"… e mais {len(recusadas) - 8} conta(s).")
        return "\n".join(linhas)

    #: As colunas da conferência, na ordem: (chave, título, largura em
    #: caracteres, alinhamento). A largura é em caracteres e não em pixels
    #: porque a fonte vem do Windows e muda com a escala de exibição.
    COLUNAS_REMESSA = (
        ("venc", "VENCIMENTO", 11, "w"),
        ("fornecedor", "FORNECEDOR", 24, "w"),
        ("recebe", "QUEM RECEBE", 0, "w"),      # 0 = a coluna que se estica
        ("oc", "OC", 8, "w"),
        ("cc", "CENTRO DE CUSTO", 22, "w"),
        ("valor", "VALOR", 14, "e"),
        ("situacao", "SITUAÇÃO", 26, "w"),
    )

    def _cabecalho_tabela(self, pai, com_marca: bool):
        """A linha de títulos, e a configuração das colunas do `grid`.

        `grid` e não `ttk.Treeview`: a tabela precisa de caixa de marcar por
        linha, de duas fontes na MESMA célula (o nome em negrito e o código de
        barras em largura fixa embaixo) e de selo colorido na situação. O
        Treeview do Tk não faz nenhuma das três — não aceita widget dentro de
        célula, tem uma fonte por LINHA e não quebra célula em duas alturas.
        Foi por isso que a versão anterior era texto corrido: ela tentou caber
        numa linha só e saiu truncada.
        """
        # A coluna da marca existe nas DUAS tabelas: com caixa na de cima, vazia
        # na de baixo. Sem ela, "Fica de fora" começava 30 px à esquerda e as
        # colunas das duas seções não batiam — o olho que desce a coluna Valor
        # tropeçava no meio.
        ttk.Label(pai, text="", style="Rotulo.TLabel").grid(
            row=0, column=0, sticky="w", padx=px((0, 6)))
        # `minsize` e não `width`: na seção de cima quem manda na largura é a
        # caixa de marcar, e na de baixo não há caixa nenhuma. Sem um piso
        # igual nas duas, a coluna Vencimento começava 25 px mais à esquerda
        # em "Fica de fora" e as duas tabelas deixavam de se ler como uma.
        pai.columnconfigure(0, weight=0, minsize=px(30))
        col = 1
        for chave, titulo, largura, ancora in self.COLUNAS_REMESSA:
            ttk.Label(pai, text=titulo, style="Rotulo.TLabel",
                      anchor=("e" if ancora == "e" else "w")).grid(
                row=0, column=col, sticky="ew", padx=px((0, 10)),
                pady=px((0, 4)))
            # A coluna de largura 0 é a que absorve a sobra: é onde mora o
            # código de barras completo, que é o dado mais comprido da tela e
            # o que não pode ser cortado de jeito nenhum.
            pai.columnconfigure(col, weight=1 if largura == 0 else 0,
                                minsize=0 if largura == 0
                                else largura * px(7))
            col += 1
        # Um filete separando o cabeçalho do corpo, como nos cartões.
        ttk.Separator(pai, orient="horizontal").grid(
            row=1, column=0, columnspan=col, sticky="ew", pady=px((0, 4)))
        return col

    def _celula_quem_recebe(self, pai, c, linha: int, coluna: int):
        """Nome em negrito e, embaixo, POR ONDE o dinheiro sai — inteiro.

        Duas alturas porque as duas informações são de naturezas diferentes e
        as duas precisam ser lidas: o nome se confere de relance, o código de
        barras se confere dígito a dígito contra o documento na mão. Em fonte
        de largura fixa e sem corte — foi o corte que motivou esta tela.
        """
        cel = ttk.Frame(pai)
        cel.grid(row=linha, column=coluna, sticky="ew", padx=px((0, 10)))
        ttk.Label(cel, text=c.favorecido[:44] or "—", style="Forte.TLabel"
                  ).pack(anchor="w")
        if c.tipo == "Pix":
            rotulo, dado = "PIX", c.chave
        elif c.arrecadacao:
            # O produto aparece porque ele MUDA o que o banco faz com a linha
            # (segmento O, e não J) — e porque foi mandar ficha como boleto
            # que deu errado em 17/08/2026.
            rotulo, dado = "ARRECADAÇÃO", c.codigo_barras
        else:
            rotulo, dado = "BOLETO", c.codigo_barras
        ttk.Label(cel, text=f"{rotulo}  {dado or '—'}",
                  style="MonoMini.TLabel" if dado else "MonoMiniErro.TLabel"
                  ).pack(anchor="w")
        # O reembolso paga QUEM NÃO É o favorecido do lançamento, e o nome
        # acima já é o da pessoa — sem esta linha, a troca é invisível.
        if c.reembolso:
            ttk.Label(cel, style="Tenue.TLabel", justify="left",
                      text=(f"↳ reembolso de {c.reembolso_de[:30]} · documento "
                            f"{_doc_legivel(c.documento_favorecido)} "
                            f"({c.reembolso_origem})")).pack(anchor="w")
        if c.ja_enviado:
            ttk.Label(cel, style="Atencao.TLabel", justify="left",
                      text=f"↳ {c.ja_enviado} — marque para enviar de novo"
                      ).pack(anchor="w")
        if c.obs:
            ttk.Label(cel, text=f"↳ {c.obs[:110]}", style="Tenue.TLabel",
                      justify="left").pack(anchor="w")

    def _linha_tabela(self, pai, c, linha: int, *, var=None, motivo: str = ""):
        """Uma linha da tabela. `var` só existe na seção que vai no arquivo."""
        col = 1
        if var is not None:
            ttk.Checkbutton(pai, variable=var).grid(row=linha, column=0,
                                                    sticky="w",
                                                    padx=px((0, 6)))
        venc = f"{c.vencimento:%d/%m/%Y}" if c.vencimento else "—"
        ttk.Label(pai, text=venc, style="Num.TLabel").grid(
            row=linha, column=col, sticky="w", padx=px((0, 10))); col += 1
        # O favorecido do LANÇAMENTO. No reembolso ele não é quem recebe — a
        # coluna ao lado diz para quem o dinheiro vai de verdade.
        nome_lanc = (c.reembolso_de or c.favorecido) if c.reembolso else c.favorecido
        ttk.Label(pai, text=nome_lanc[:24] or "—").grid(
            row=linha, column=col, sticky="w", padx=px((0, 10))); col += 1
        self._celula_quem_recebe(pai, c, linha, col); col += 1
        ttk.Label(pai, text=c.oc or "—", style="Num.TLabel").grid(
            row=linha, column=col, sticky="w", padx=px((0, 10))); col += 1
        ttk.Label(pai, text=(c.centro_custo or "—")[:22]).grid(
            row=linha, column=col, sticky="w", padx=px((0, 10))); col += 1
        ttk.Label(pai, text=relatorio.brl(c.valor), style="Num.TLabel",
                  anchor="e").grid(row=linha, column=col, sticky="e",
                                   padx=px((0, 10))); col += 1
        if motivo:
            # Fica de fora: o selo é o MOTIVO, inteiro. Âmbar e não vermelho —
            # a linha não falhou, ela não vai; e uma seção inteira em vermelho
            # deixa de destacar o que quer que seja.
            #
            # QUEBRA em vez de cortar: os motivos são frases ("pagamento
            # parcial — boleto não se paga pela metade"), e cortá-las no meio
            # é o mesmo defeito que esta tela veio consertar, um selo menor.
            widgets.Pilula(pai, motivo, "atencao", wraplength=px(230),
                           justify="left").grid(row=linha, column=col,
                                                sticky="w")
        else:
            estado = "ok" if c.apto else "atencao"
            texto = "apto" if c.apto else c.status
            widgets.Pilula(pai, f"{widgets.MARCAS_ESTADO[estado]}  {texto}",
                           estado, wraplength=px(230), justify="left").grid(
                row=linha, column=col, sticky="w")

    def _janela_remessa(self, preparado, pagadores, recusadas, historico) -> bool:
        """A conferência. Devolve True se a pessoa confirmou.

        Uma TABELA por conta pagadora, em duas seções: o que vai no arquivo
        (com caixa de marcar) e o que fica de fora (com o motivo em selo, sem
        caixa — desmarcado é escolha sua, impedido é outra coisa).

        Vem marcado o que a apuração julgou APTO e desmarcado o que ela marcou
        com ATENÇÃO: o normal segue sozinho, o duvidoso exige um clique.

        Todas as colunas que se conferem antes de mandar dinheiro estão aqui —
        vencimento, favorecido, para onde vai (código de barras ou chave, por
        inteiro), OC, centro de custo, valor e situação. Antes era uma linha de
        texto com `wraplength`, e o que não coubesse sumia: o código de barras,
        que é justamente o que se confere contra o documento, nunca aparecia.
        """
        top = tk.Toplevel(self)
        top.title("Gerar remessa — conferência")
        top.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(top)
        top.configure(background=widgets.cores()["fundo"])
        # Grande de propósito: são sete colunas, e uma delas guarda 44 dígitos.
        # Numa janela pequena a tabela volta a truncar, que é o defeito que
        # esta tela existe para consertar.
        #
        # Medida contra a TELA, e não fixa: 1360x820 cabia no monitor onde foi
        # escrita e estourava embaixo num notebook — levando junto o rodapé,
        # que é onde estão o total e o botão de gravar.
        larg = min(px(1360),
                   max(int(top.winfo_screenwidth() * 0.92), px(1000)))
        alt = min(px(860),
                  max(int(top.winfo_screenheight() * 0.86), px(560)))
        top.geometry(f"{larg}x{alt}")
        top.minsize(px(1000), px(520))

        moldura = ttk.Frame(top, padding=18, style="Fundo.TFrame")
        moldura.pack(fill="both", expand=True)
        cab = widgets.Cabecalho(
            moldura, "Confira o que vai no arquivo",
            "Já vem marcado o que está apto. Desmarque o que não deve ir hoje. "
            "Depois de gravar, o envio ao SicoobNet é seu, à mão — o app nunca "
            "transmite.",
            trilha="Diário  ›  Remessa e Retorno  ›  Gerar remessa")
        cab.pack(fill="x", pady=px((0, 14)))

        # ---- rodapé FIXO, empacotado ANTES do corpo: no `pack`, quem chega
        # primeiro reserva o espaço. Com o corpo antes, a tabela crescia por
        # cima e empurrava o total e os botões para fora da janela — que é
        # exatamente o que não pode acontecer com o número que se confere
        # antes de mandar dinheiro.
        rodape = ttk.Frame(moldura, style="Fundo.TFrame")
        rodape.pack(side="bottom", fill="x", pady=px((14, 0)))

        # ---- corpo rolável
        painel = tk.Canvas(moldura, highlightthickness=0)
        barra = ttk.Scrollbar(moldura, orient="vertical", command=painel.yview)
        dentro = ttk.Frame(painel, style="Fundo.TFrame")
        dentro.bind("<Configure>",
                    lambda _e: painel.configure(scrollregion=painel.bbox("all")))
        janela = painel.create_window((0, 0), window=dentro, anchor="nw")
        painel.bind("<Configure>",
                    lambda e: painel.itemconfigure(janela, width=e.width))
        painel.configure(yscrollcommand=barra.set)
        widgets.estilo_canvas(painel)
        barra.pack(side="right", fill="y")
        painel.pack(side="top", fill="both", expand=True)

        # Duas contas da MESMA empresa dividem o convênio, e `proximo_nsa` é
        # CONSULTA, não reserva: as duas mostravam "arquivo nº 000031" enquanto
        # a gravação daria 31 a uma e 32 à outra. Quem conferisse pelo número
        # da tela procuraria um arquivo que não existe.
        #
        # Com o contador na nuvem, o número aqui é PREVISÃO: se a outra máquina
        # gerar entre esta tela e o Confirmar, o arquivo sai com um número mais
        # alto. Continua sendo consulta de propósito — reservar ao MOSTRAR
        # queimaria um NSA cada vez que alguém abrisse a janela e desistisse.
        proximos: dict[str, int] = {}
        marcas: list = []
        for conta, pagador in pagadores.items():
            linhas = preparado[conta]
            if pagador.convenio not in proximos:
                proximos[pagador.convenio] = historico.proximo_nsa(pagador.convenio)
            nsa = proximos[pagador.convenio]
            proximos[pagador.convenio] = nsa + 1

            vao = [c for c in linhas if c.pode]
            fora = [c for c in linhas if not c.pode]
            cartao = widgets.Cartao(
                dentro,
                f"{pagador.empresa} — ag {pagador.agencia}-{pagador.dv_agencia}"
                f" / {pagador.conta}-{pagador.dv_conta}")
            cartao.pack(fill="x", pady=px((0, 12)))
            ttk.Label(cartao.acoes, text=f"arquivo nº {nsa:06d}",
                      style="Mini.TLabel").pack(side="right")

            if vao:
                ttk.Label(cartao, text="VAI NO ARQUIVO", style="Rotulo.TLabel"
                          ).pack(anchor="w", pady=px((0, 4)))
                tab = ttk.Frame(cartao)
                tab.pack(fill="x")
                self._cabecalho_tabela(tab, com_marca=True)
                for i, c in enumerate(vao, start=2):
                    v = tk.BooleanVar(value=c.marcado)
                    c._var = v                  # lido de volta no confirmar()
                    v.trace_add("write", lambda *_a: atualizar())
                    marcas.append((c, v))
                    self._linha_tabela(tab, c, i, var=v)

            if fora:
                ttk.Label(cartao, text="FICA DE FORA", style="Rotulo.TLabel"
                          ).pack(anchor="w", pady=px((14, 4)))
                tab = ttk.Frame(cartao)
                tab.pack(fill="x")
                self._cabecalho_tabela(tab, com_marca=False)
                for i, c in enumerate(fora, start=2):
                    self._linha_tabela(tab, c, i, motivo=c.impedimento)

        if recusadas:
            cartao = widgets.Cartao(dentro, "Contas sem remessa")
            cartao.pack(fill="x", pady=px((0, 12)))
            for conta, motivo in recusadas:
                linha = ttk.Frame(cartao)
                linha.pack(fill="x", pady=px((0, 4)))
                ttk.Label(linha, text=conta[:48], style="Forte.TLabel"
                          ).pack(side="left")
                widgets.Pilula(linha, motivo[:60], "atencao"
                               ).pack(side="left", padx=px((10, 0)))

        resposta = {"ok": False}

        def confirmar():
            for linhas in preparado.values():
                for c in linhas:
                    if getattr(c, "_var", None) is not None:
                        c.marcado = bool(c._var.get())
            resposta["ok"] = True
            top.destroy()

        # O rodapé já foi empacotado lá em cima; aqui ele só se enche.
        resumo = ttk.Label(rodape, style="FundoApoio.TLabel")
        resumo.pack(side="left")
        widgets.Botao(rodape, "Gravar os arquivos", papel="acao",
                      command=confirmar).pack(side="right")
        widgets.Botao(rodape, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=px((0, 8)))

        def atualizar():
            try:
                vao = [c for c, v in marcas if v.get()]
            except tk.TclError:
                return                       # janela fechando com o trace vivo
            de_fora = sum(len([c for c in linhas if not c.pode])
                          for linhas in preparado.values())
            de_fora += len(marcas) - len(vao)
            resumo.configure(
                text=f"{len(vao)} pagamento(s)  ·  "
                     f"{relatorio.brl(sum(c.valor for c in vao))}  ·  "
                     f"{de_fora} de fora")
        atualizar()

        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.bind("<Escape>", lambda _e: top.destroy())
        try:
            top.grab_set()
        except tk.TclError:
            pass
        self.wait_window(top)
        return resposta["ok"]

    def _gravar_remessas(self, preparado, pagadores, historico):
        """Reserva o NSA, valida, grava e registra — nessa ordem, uma por vez.

        A reserva vem ANTES da validação porque o NSA entra no CONTEÚDO do
        arquivo: é o campo G018 do header, e é justamente ele que o validador
        confere. Não há como validar primeiro sem validar um arquivo sem
        número, nem como espiar o número aqui e reservá-lo depois — a janela
        entre espiar e reservar é a janela em que a outra máquina pega o mesmo
        NSA, e as duas geram arquivos legítimos que o banco vê como um só.

        A consequência é que **arquivo reprovado não é gravado, mas o NSA já
        está queimado**. É o lado certo de errar: pular número é inofensivo,
        repetir pode ser pagamento em dobro.

        E o número queimado não deixa rastro em lugar nenhum — o aviso na tela
        some com a janela, `alocar_nsa` só empurra o `remessa_contador` da
        nuvem, o `remessas.json` só aprende um NSA quando `registrar` é
        chamado, e `remessa_ajuste`/`ajustes` guardam só a correção manual do
        contador (`ajustar_nsa`, que exige motivo por escrito). O furo aparece
        como número faltando na sequência, e quem for conferir com a
        cooperativa depois não encontra a explicação escrita: é o preço de
        nunca repetir, e está pago de propósito.
        """
        from cnab240 import relatorio as _rel_cnab, validar

        destino = Path(self.v_pasta.get().strip() or ".")
        gerados, total_geral = [], 0.0
        for conta, pagador in pagadores.items():
            marcados = [c for c in preparado[conta] if c.marcado and c.pode]
            if not marcados:
                self._log(f"\n{pagador.empresa}: nada marcado — sem arquivo.")
                continue
            try:
                # RESERVA o número, não espia. O NSA entra no CONTEÚDO do
                # arquivo: espiar aqui e gravar depois deixaria uma janela em
                # que a outra máquina pega o mesmo número, e as duas gerariam
                # arquivos legítimos com o mesmo NSA. Se a geração falhar
                # depois desta linha, o número é queimado — e isso é o lado
                # certo de errar: pular número é inofensivo, repetir não.
                nsa = historico.alocar_nsa(pagador.convenio)
                arquivo = remessa_dia.montar_arquivo(pagador, marcados, nsa=nsa)
                problemas = validar(arquivo.gerar())
                if problemas:
                    self._log(f"\n[!] {pagador.empresa}: o arquivo não passou na "
                              f"validação, nada foi gravado.\n{_rel_cnab(problemas)}")
                    continue
                # Uma pasta por conta pagadora. Misturados, os arquivos são
                # parecidos demais — mesmo prefixo, NSA sequencial — e o erro
                # de subir o de uma conta no acesso de outra só apareceria no
                # SicoobNet, depois de enviado.
                pasta_da_conta = remessa_dia.pasta_do_pagador(destino, pagador)
                pasta_da_conta.mkdir(parents=True, exist_ok=True)
                caminho = pasta_da_conta / remessa_dia.nome_do_arquivo(pagador, nsa)
                # Grava num TEMPORÁRIO e só renomeia depois de o histórico
                # aceitar. Na ordem antiga (`salvar` e então `registrar`), um
                # registro recusado — NSA fora de ordem, "seu número" repetido,
                # trava ocupada, JSON corrompido — deixava o `.REM` no disco
                # com nome perfeitamente legítimo E sem consumir o NSA. Ficavam
                # dois arquivos válidos com os MESMOS pagamentos, e subir os
                # dois no SicoobNet é pagar duas vezes; pior, a remessa
                # seguinte reusava o número e sobrescrevia o órfão, apagando o
                # rastro. O `.tmp` não é zelo: é o que torna o par
                # "arquivo existe" e "histórico sabe dele" indivisível.
                provisorio = caminho.with_suffix(caminho.suffix + ".tmp")
                arquivo.salvar(provisorio)
                try:
                    historico.registrar(
                        arquivo, caminho_arquivo=caminho,
                        referencias=remessa_dia.referencias(marcados))
                except Exception:
                    provisorio.unlink(missing_ok=True)
                    raise
                os.replace(provisorio, caminho)
            except Exception as e:
                self._log(f"\n[!] {pagador.empresa}: {e}")
                continue

            soma = sum(c.valor for c in marcados)
            total_geral += soma
            gerados.append(caminho)
            self._log(f"\n{pagador.empresa} · arquivo nº {nsa:06d} · "
                      f"{len(marcados)} pagamento(s) · {relatorio.brl(soma)}"
                      f"\n  {str(caminho).replace(chr(92), '/')}")

        self._registrar_o_que_ficou_de_fora(preparado)

        if not gerados:
            self.q.put(("status", "Nenhum arquivo de remessa foi gravado."))
            # O dia em que NENHUM arquivo sai também é um dia em que alguém
            # rodou — e até 04/09/2026 ele não deixava rastro: a auditoria só
            # era chamada mais abaixo, no caminho em que houve arquivo. O
            # cartão "Contas sem remessa" do Início mostrava "—", que é
            # exatamente o que ele mostra quando ninguém rodou nada; o pior
            # dia do mês ficava indistinguível de um dia comum.
            #
            # `resultado="atencao"` e não "ok": a rotina terminou e achou
            # coisa para alguém olhar, que é como o Início lê essa palavra.
            auditoria.registrar(
                "Gerar remessa", "nenhum arquivo gravado", aba="pag",
                resultado="atencao",
                numeros={"contas_sem_remessa":
                         remessa_dia.contas_sem_remessa(preparado, gerados),
                         "total_remessa": 0.0})
            return
        self.q.put(("remessa_gerada", gerados))
        self._log("\nAgora suba os arquivos no SicoobNet: Empresarial → Gestão em "
                  "Lote → IntegraLote → Gestão de arquivos CNAB. O app não "
                  "transmite: gerar é reversível, enviar não é.")
        self.q.put(("status", f"{len(gerados)} arquivo(s) de remessa · "
                              f"{relatorio.brl(total_geral)}"))
        # "Contas sem remessa" do Início sai daqui: são as contas que TÊM
        # pagamento hoje e não viraram arquivo. É a única hora em que a
        # diferença existe — antes da remessa não há com o que comparar. A
        # aritmética mora em `remessa_dia.contas_sem_remessa`, que é pura e
        # tem teste: ela é chamada nos DOIS desfechos, e uma conta a mais aqui
        # e a menos ali seria o mesmo cartão dizendo duas coisas.
        auditoria.registrar(
            "Gerar remessa",
            f"{len(gerados)} arquivo(s) · {relatorio.brl(total_geral)}",
            aba="pag", resultado="ok",
            # `total_remessa` e não `total`: o Início junta os números das
            # várias execuções da mesma aba, e "total" já é o do dia inteiro
            # que o passo 1 apurou. Com o mesmo nome, o valor da remessa
            # (que exclui o que ficou de fora) sobrescrevia o do dia, e o
            # cartão "Pagamentos de hoje" passava a mostrar 87 lançamentos
            # somando menos do que eles somam.
            numeros={"contas_sem_remessa":
                     remessa_dia.contas_sem_remessa(preparado, gerados),
                     "total_remessa": total_geral})

    def _registrar_o_que_ficou_de_fora(self, preparado):
        """O que NÃO entrou na remessa, com o motivo — depois de gravar.

        Omitir não é apagar: é a regra da casa desde a aba "NÃO ENTRARAM" da
        planilha, e a remessa vinha sendo a exceção. A janela de conferência
        mostrava o impedimento e o fechamento a levava junto — quem olhasse a
        planilha depois via APTO, quem olhasse o arquivo não via o pagamento, e
        nada em lugar nenhum dizia por quê.

        Em 17/08/2026 foram R$ 13.532,56 em dois reembolsos que sumiram assim.
        Eles estavam certos em não sair (o aviso "PAGAR PARA" manda o dinheiro
        para quem não é o favorecido do lançamento); errado era o silêncio.

        A `remessa_dia.fora()` já existia e já tinha teste — só nunca tinha
        sido chamada.
        """
        de_fora = remessa_dia.fora(preparado)
        if not de_fora:
            return
        total = sum(f["valor"] for f in de_fora)
        self._log(f"\n{len(de_fora)} pagamento(s) NÃO entraram na remessa "
                  f"({relatorio.brl(total)}) — pague à mão ou resolva o motivo:")
        for motivo in dict.fromkeys(f["motivo"] for f in de_fora):
            linhas = [f for f in de_fora if f["motivo"] == motivo]
            soma = sum(f["valor"] for f in linhas)
            self._log(f"  {len(linhas):>3} · {relatorio.brl(soma):>14}  {motivo}")
            for f in linhas:
                self._log(f"        {f['tipo']:<7} {relatorio.brl(f['valor']):>14}  "
                          f"{f['favorecido'][:34]}")

    def _anexos_a_ler(self, selecionados) -> list[tuple[str, bool]]:
        """[(downloadUrl, é_pdf)] sem repetição.

        Os PDFs sempre entram. Anexo que é FOTO só entra quando é um aviso
        "PAGAR PARA": ali mora o CPF/celular de quem recebe o reembolso, e
        sem ler a imagem a linha volta a sair como "chave não cadastrada".
        Baixar toda foto de todo título seria pagar OCR por nada.
        """
        vistos, urls = set(), []
        for item in selecionados:
            for f in self.anexos.get(str(item.get("tradePayableId"))) or []:
                url = f.get("downloadUrl")
                if not url or url in vistos:
                    continue
                pdf = relatorio.eh_pdf(f)
                if pdf or relatorio._PAGAR_PARA.search(relatorio._rotulo(f)):
                    vistos.add(url)
                    urls.append((url, pdf))
        return urls

    def _baixar_textos(self, selecionados) -> tuple[dict, set]:
        """({downloadUrl: texto}, {urls lidas por OCR}).

        Um download serve para tudo: extrair a linha digitável do boleto,
        cruzar valor/fornecedor e achar a chave do aviso de reembolso.

        O OCR só roda no que veio sem texto — é ele que custa caro. Quem
        leu por OCR fica marcado, porque leitura de OCR não vale o mesmo
        que camada de texto: a linha digitável tirada dali só é aceita
        depois de fechar o dígito verificador e o valor (ver `ocr_boleto`).
        """
        alvos = self._anexos_a_ler(selecionados)
        if not alvos:
            return {}, set()

        self._log(f"\nBaixando e lendo {len(alvos)} anexo(s) para o cruzamento...")
        textos, urls_ocr, sem_texto = {}, set(), 0
        for i, (url, eh_pdf) in enumerate(alvos, 1):
            if self._parar.is_set():
                self._log("Interrompido a pedido — o cruzamento fica incompleto.")
                break
            dados = self.anx.api.baixar_anexo(url)
            texto = relatorio.texto_de_pdf(dados) if (dados and eh_pdf) else ""
            if dados and not texto.strip():
                self.q.put(("status", f"Lendo por OCR... {i}/{len(alvos)}"))
                texto = (ocr_boleto.texto_ocr_pdf(dados, self._log) if eh_pdf
                         else ocr_boleto.texto_ocr_imagem(dados))
                if texto.strip():
                    urls_ocr.add(url)
            textos[url] = texto
            if not texto.strip():
                sem_texto += 1
            self.q.put(("progresso", (i, len(alvos))))
            if i % 25 == 0:
                self.q.put(("status", f"Lendo anexos... {i}/{len(alvos)}"))
        if urls_ocr:
            self._log(f"  {len(urls_ocr)} anexo(s) sem texto lidos por OCR.")
        if sem_texto:
            self._log(f"  {sem_texto} anexo(s) que nem o OCR conseguiu ler — "
                      "esses não dá para cruzar.")
        return textos, urls_ocr
