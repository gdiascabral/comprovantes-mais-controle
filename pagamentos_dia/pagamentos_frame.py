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
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import baixa_erp                                              # noqa: E402
import ocr_boleto                                             # noqa: E402
import reembolso                                              # noqa: E402
import regras_pagamento as regras                             # noqa: E402
import relatorio                                              # noqa: E402
import remessa_dia                                            # noqa: E402
import retorno_dia                                            # noqa: E402

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

#: Duração e pasta-base vinham em cópias byte a byte por aba. Uma cópia de
#: regra de CAMINHO é como um app passa a procurar o mesmo arquivo em dois
#: lugares; uma de FORMATO é como a mesma duração aparece de dois jeitos.
_fmt_dur = util.fmt_dur
_pasta_base = util.pasta_base

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets

CampoData = widgets.CampoData

# Cadastros de outras abas, reusados pela remessa: `contas_mc` diz de que
# EMPRESA é cada conta do ERP, e `sicoob_contas` traz CNPJ, agência, conta e
# convênio. Um mapa a mais seria uma divergência a mais esperando acontecer —
# julho de 2026 já ficou partido uma vez por dois mapas discordando.
#
# Import PLANO, como o `relatorio_frame` e o `extratos_frame` fazem: o app põe
# cada pasta de aba direto no sys.path. `from extratos_sicoob import ...` até
# resolveria o nome, mas o próprio `sicoob_contas` faz `import sicoob_config`
# — que só existe com a pasta dele no caminho.
for _aba in ("relatorios", "extratos_sicoob"):
    _p = Path(__file__).resolve().parent.parent / _aba
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import contas_mc                                              # noqa: E402
import sicoob_contas                                          # noqa: E402



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

    Boleto ainda não lido aparece com o recado em vermelho, e não em branco:
    "não sei a linha digitável" é uma informação sobre o pagamento, e quem
    confirma precisa dela para decidir se abre o boleto antes.
    """
    favorecido = (item.get("paidTo") or "?").strip()
    pago_para = (item.get("paidToBankAccount") or "").strip()
    tipo = relatorio.tipo_de_pagamento(item)
    ident = str(item.get("id") or "")

    if tipo == "Pix":
        chave = relatorio.extrair_chave_pix(pago_para) if pago_para else ""
        if relatorio.parece_chave_pix(chave):
            return favorecido, f"PIX  {chave}", "ok"
        return (favorecido, "sem chave Pix no cadastro — abrir o lançamento",
                "erro")

    if tipo == "Boleto":
        linha = (ja_lido or {}).get(ident) or ""
        if linha:
            return favorecido, f"BOLETO  {ocr_boleto.formatar(linha)}", "ok"
        return (favorecido, "linha digitável não lida — abrir o boleto",
                "erro")

    # TED e o que mais o ERP chamar de forma de pagamento. O texto do cadastro
    # é livre: quando dá para separar banco/agência/conta, separa; quando não
    # dá, mostra o que está lá — o que está lá é o que a pessoa vai usar.
    rotulo = (tipo or "TED").upper()
    if not pago_para:
        return favorecido, f"{rotulo}  sem conta no cadastro", "erro"
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
        #: O que o passo 2 montou. A remessa sai daqui, não do .xlsx — ler a
        #: planilha de volta seria reparsear texto formatado para reconstruir
        #: número, e ela é relatório, não fonte.
        self.resultado = None
        #: O período que gerou o `self.resultado`. Existe para o passo 3 poder
        #: recusar quando a pessoa trocou as datas na tela depois de gerar a
        #: planilha: o que está em memória seria de outro dia, e a janela da
        #: remessa não tem como saber disso sozinha.
        self._periodo_do_resultado = None

        hoje = datetime.date.today()
        self.v_ini = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_cruzar = tk.BooleanVar(value=True)
        self.v_incluir_pagos = tk.BooleanVar(value=False)
        self.v_pasta = tk.StringVar(
            value=str(_pasta_base() / "Pagamentos do dia").replace("\\", "/"))

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        self.cab = widgets.Cabecalho(
            self, "Remessa/Retorno",
            "Planilha de conferência dos pagamentos do período, o arquivo de "
            "remessa para o banco e a leitura do retorno que ele devolve.",
            trilha="Diário  ›  Remessa e Retorno")
        self.cab.pack(fill="x", padx=PADX, pady=(16, 12))

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
        self.b1.pack(side="left", padx=(0, 8))
        self.b2 = widgets.Botao(self.cab.acoes, "Gerar a planilha",
                                papel="passo", command=self.gerar,
                                state="disabled")
        self.b2.pack(side="left", padx=(0, 8))
        self.b3 = widgets.Botao(self.cab.acoes, "Gerar remessa", papel="acao",
                                command=self.gerar_remessa, state="disabled")
        self.b3.pack(side="left")

        # Os cartões passam a ser NUMERADOS, e os botões deixam de ser: era o
        # "▶ 1." no botão e o "1." no cartão contando a mesma coisa duas vezes,
        # com contagens que não batiam ("2. Contas" era um campo, "2. Gerar" era
        # uma ação). Agora o número está num lugar só — o cartão —, e o botão
        # diz o VERBO.
        f1 = widgets.Cartao(self, "Período", 1)
        f1.pack(fill="x", padx=PADX, pady=(0, 12))
        linha = ttk.Frame(f1)
        linha.pack(fill="x")
        widgets.Campo(linha, "De", lambda p: CampoData(p, self.v_ini)
                      ).pack(side="left", padx=(0, 16))
        widgets.Campo(linha, "Até", lambda p: CampoData(p, self.v_fim)
                      ).pack(side="left", padx=(0, 16))
        widgets.Botao(linha, "Hoje", papel="neutro", command=self._hoje
                      ).pack(side="left", pady=(15, 0))

        opc = ttk.Frame(f1)
        opc.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(opc, variable=self.v_cruzar,
                        text="Conferir os documentos anexados (baixa os PDFs; "
                             "mais lento, mas é a conferência de verdade)"
                        ).pack(anchor="w")
        ttk.Checkbutton(opc, variable=self.v_incluir_pagos,
                        text="Incluir também o que já foi pago no período"
                        ).pack(anchor="w", pady=(4, 0))

        # ---- card 2: contas
        # A lista também é elástica: antes de buscar ela tem uma frase, e um
        # quadro vazio de 170 px em volta de uma frase é o mesmo desperdício
        # que o Registro tinha. Cresce em `_montar_contas`.
        self.f_contas = f2 = widgets.Cartao(
            self, "Contas — marque as que entram no relatório", 2)
        f2.pack(fill="x", padx=PADX, pady=(0, 12))
        self.rodape_contas = widgets.RodapeTabela(f2.acoes)
        self.rodape_contas.pack()
        self.canvas = tk.Canvas(f2, height=24, highlightthickness=0, borderwidth=0)
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
        f3.pack(fill="x", padx=PADX, pady=(0, 12))
        ttk.Entry(f3, textvariable=self.v_pasta).pack(side="left", fill="x",
                                                      expand=True)
        widgets.Botao(f3, "Selecionar…", papel="neutro", command=self._sel_pasta
                      ).pack(side="left", padx=(8, 0))

        # ---- barra de execução e o que não é passo
        # ACIMA do registro, e não no rodapé: a barra conta o trabalho que
        # está acontecendo, e o registro é a saída DELE. Embaixo, ela ficava
        # depois do resultado — e, com o registro cheio, fora da tela.
        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=(0, 10))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=(16, 0))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo",
                                    command=self._parar_click, state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = widgets.Botao(btns, "📂  Abrir planilha", papel="neutro",
                                     command=self._abrir, state="disabled")
        self.b_abrir.pack(side="left", padx=(8, 0))
        # SEM número e sempre habilitado, de propósito: ler retorno não é o
        # passo 4 de nada. O arquivo chega horas ou dias depois — às vezes
        # noutra máquina —, e exigir "buscar" e "gerar" antes obrigaria a
        # refazer o dia inteiro só para conferir o que o banco respondeu.
        self.b_ret = widgets.Botao(btns, "📥  Ler retorno", papel="neutro",
                                   command=self.ler_retorno)
        self.b_ret.pack(side="left", padx=(8, 0))

        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        # `lbl` e `pb` continuam existindo com os nomes de sempre: o `_drain`
        # e as seis chamadas de progresso não sabem (nem precisam saber) que a
        # barra virou outro widget.
        self.lbl = self.barra_exec.lbl
        self.pb = self.barra_exec.pb

        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=(0, 12))
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

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando...")
        self.b_stop.configure(state="disabled")

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
            widgets.estilo_canvas(self.canvas)
        except tk.TclError:
            pass

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
                    # A remessa sai do que o passo 2 já montou em memória, e
                    # não do disco: sem planilha gerada não há o que mandar.
                    self.b3.configure(state="normal" if valor == "normal"
                                      and self.resultado else "disabled")
                    self.b_stop.configure(state="disabled" if valor == "normal" else "normal")
                elif tipo == "arquivo":
                    self.ultimo_arquivo = valor
                    self.b_abrir.configure(state="normal")
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
            widgets.registrar_atividade(
                "pag", "Buscar lançamentos", "ok",
                f"{len(self.lancamentos)} lançamento(s) · "
                f"{relatorio.brl(_no_dia)}",
                {"lancamentos": len(self.lancamentos), "total": _no_dia})
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui buscar os lançamentos."))
            widgets.registrar_atividade("pag", "Buscar lançamentos", "erro",
                                        str(e)[:120])
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
        # A lista que a tela mostra passa a ser a MESMA que o rodapé soma. O
        # `_t_buscar` já grava `self.contas` antes de enfileirar, mas quem
        # desenha recebe a lista por parâmetro: sem esta linha, o total do
        # rodapé dependia de as duas nunca se separarem.
        self.contas = list(contas)
        self.canvas.configure(height=170)
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
        top.geometry("980x680")
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
        cab.pack(fill="x", pady=(0, 14))

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
            cabecalho.pack(fill="x", pady=(14, 4))
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
        rodape.pack(side="bottom", fill="x", pady=(12, 0))
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
        acoes.pack(fill="x", pady=(14, 0))
        widgets.Botao(acoes, "Confirmar e gerar", papel="acao",
                      command=confirmar).pack(side="right")
        widgets.Botao(acoes, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=(0, 8))

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
        c = widgets.cores()
        linha = ttk.Frame(pai)
        linha.pack(fill="x")
        ttk.Checkbutton(linha, variable=var, command=ao_marcar
                        ).pack(side="left", padx=(0, 8), pady=6)
        # O valor primeiro e alinhado à direita, em fonte de largura fixa: é a
        # coluna que se lê de cima a baixo somando de cabeça.
        ttk.Label(linha, text=relatorio.brl(relatorio.valor_do_item(item)),
                  style="Num.TLabel", width=14, anchor="e"
                  ).pack(side="left", padx=(0, 14))

        quem = ttk.Frame(linha)
        quem.pack(side="left", fill="x", expand=True)
        nome, dado, estado = quem_recebe(item, ja_lido)
        topo = ttk.Frame(quem)
        topo.pack(fill="x")
        if olhar:
            ttk.Label(topo, text="⚠", style="Atencao.TLabel"
                      ).pack(side="left", padx=(0, 5))
        ttk.Label(topo, text=nome[:44], style="Forte.TLabel").pack(side="left")
        desc = (item.get("description") or "").strip()
        if desc:
            ttk.Label(topo, text="·  " + desc[:52], style="Tenue.TLabel"
                      ).pack(side="left", padx=(8, 0))
        # A segunda altura: a forma de pagar. Vermelha quando não se sabe qual
        # é — o vazio ali seria lido como "não tem nada a conferir".
        ttk.Label(quem, text=dado,
                  style="MonoMiniErro.TLabel" if estado == "erro"
                  else "MonoMini.TLabel").pack(anchor="w", pady=(1, 6))

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

    def _t_gerar(self, escolhidas, nao_confirmados=()):
        comeco = time.time()
        try:
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
                return

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
            registros, omitidos = resultado.contas, resultado.omitidos
            if not registros and not omitidos:
                self.q.put(("status", "Nenhuma linha para as contas marcadas."))
                return

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
            widgets.registrar_atividade(
                "pag", "Gerar a planilha",
                "atencao" if (atencao or omitidos) else "ok",
                f"{n} pagamento(s) · {relatorio.brl(total)}"
                + (f" · {atencao} para conferir" if atencao else ""),
                {"lancamentos": n, "total": total, "sem_anexo": _sem_anexo})
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar a planilha."))
            widgets.registrar_atividade("pag", "Gerar a planilha", "erro",
                                        str(e)[:120])
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
        """Lê o arquivo que o banco devolve e mostra o que houve com cada
        pagamento.

        Não é etapa do fluxo do dia: o retorno chega horas ou dias depois, e
        muitas vezes é preciso ler o MESMO arquivo duas vezes — a primeira só
        diz "recebi", e o desfecho real vem depois de o master assinar no
        SicoobNet. Por isso o botão não tem número e não depende dos passos.
        """
        caminho = filedialog.askopenfilename(
            title="Escolha o arquivo de retorno do banco",
            filetypes=[("Retorno CNAB", "*.RET *.ret *.TXT *.txt"),
                       ("Todos", "*.*")])
        if not caminho:
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

        try:
            resumo = retorno_dia.ler(caminho, historico)
        except Exception as e:
            messagebox.showerror("Retorno", f"Não consegui ler o arquivo:\n\n{e}")
            return

        self._janela_retorno(resumo, historico)

    def _janela_retorno(self, resumo, historico):
        top = tk.Toplevel(self)
        top.title(f"Retorno do banco — arquivo nº {resumo.nsa:06d}")
        top.geometry("980x600")
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
                  ).pack(anchor="w", pady=(2, 8))

        # O recado que evita o susto: no fluxo desta empresa, o retorno do
        # mesmo dia vem com tudo pendente porque quem assina é outra pessoa.
        # Sem esta linha, "AGUARDA ASSINATURA" em 13 pagamentos parece falha.
        if pendentes and not rejeitados:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=920,
                      justify="left",
                      text=f"⚠  {pendentes} pagamento(s) aguardando assinatura "
                           f"no SicoobNet. Isso é o esperado logo depois de "
                           f"enviar: o arquivo foi aceito, mas o dinheiro só "
                           f"sai quando o master assinar. Baixe o retorno de "
                           f"novo depois disso para ver o desfecho."
                      ).pack(anchor="w", pady=(0, 8))
        if resumo.remessa_desconhecida:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=920,
                      justify="left",
                      text="⚠  Esta remessa não está no registro central — "
                           "pode ser de antes dele existir, ou de outra "
                           "máquina. Dá para ler o arquivo, mas não para "
                           "apontar os lançamentos do ERP nem guardar o "
                           "resultado.").pack(anchor="w", pady=(0, 8))

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
        tabela.pack(fill="both", expand=True)

        for linha in resumo.linhas:
            valor = f"{linha.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            tabela.insert("", "end", values=(
                linha.rotulo, linha.favorecido[:40], valor,
                linha.seu_numero, linha.motivos or "—"))

        if resumo.faltando:
            ttk.Label(moldura, style="Erro.TLabel", wraplength=920,
                      justify="left",
                      text=f"⚠  {len(resumo.faltando)} pagamento(s) da remessa "
                           f"NÃO vieram neste retorno: "
                           f"{', '.join(resumo.faltando[:6])}"
                           f"{'…' if len(resumo.faltando) > 6 else ''}. "
                           f"O banco devolve o que processou — o que sumiu no "
                           f"caminho não aparece sozinho."
                      ).pack(anchor="w", pady=(8, 0))

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=(10, 0))
        ttk.Label(rodape, style="Apoio.TLabel",
                  text=f"{pagos} pago(s) · {pendentes} aguardando · "
                       f"{rejeitados} rejeitado(s)").pack(side="left")

        def _guardar():
            respostas = {l.seu_numero: (l.motivos.split("=")[0] or "")
                         for l in resumo.linhas if l.motivos}
            try:
                quantos = historico.aplicar_retorno(
                    resumo.convenio, resumo.nsa, respostas,
                    estado=resumo.estado_da_remessa)
            except Exception as e:
                messagebox.showerror("Retorno", f"Não deu para guardar:\n\n{e}")
                return
            self._log(f"\nRetorno do arquivo nº {resumo.nsa:06d} guardado: "
                      f"{quantos} pagamento(s) com resposta, remessa marcada "
                      f"como '{resumo.estado_da_remessa}'.")
            messagebox.showinfo("Retorno", f"Guardado: {quantos} pagamento(s).")
            top.destroy()

        def _baixar():
            sep = baixa_erp.separar(resumo)
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
            top.destroy()
            if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
                return
            self.q.put(("botoes", "disabled"))
            self.worker = self.anx.submeter(
                "Pagamentos do Dia — baixar no Mais Controle",
                self._t_baixar, escolhidos, dona=self)

        if historico is not None and not resumo.remessa_desconhecida:
            widgets.Botao(rodape, "Guardar o resultado", papel="acao",
                          command=_guardar).pack(side="right")
        if resumo.quantos("ok"):
            widgets.Botao(rodape, "Dar baixa no Mais Controle", papel="passo",
                          command=_baixar).pack(side="right", padx=(0, 8))
        widgets.Botao(rodape, "Fechar", papel="neutro", command=top.destroy
                   ).pack(side="right", padx=(0, 8))

        top.transient(self.winfo_toplevel())
        top.grab_set()

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
        ttk.Label(moldura, style="Apoio.TLabel", wraplength=620, justify="left",
                  text="Vão ser dados como pagos no Mais Controle, na data em "
                       "que o dinheiro saiu. Desmarque o que não deve ser "
                       "baixado agora."
                  ).pack(anchor="w", pady=(0, 10))

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
                      ).pack(anchor="w", pady=(12, 2))
            for linha, motivo in sep.de_fora:
                ttk.Label(moldura, style="Apoio.TLabel", wraplength=620,
                          justify="left",
                          text=(f"    {relatorio.brl(float(linha.valor))}  "
                                f"{linha.favorecido[:30]} — {motivo}")
                          ).pack(anchor="w")

        escolha: list = []

        def confirmar():
            escolha.extend(l for l, v in marcas if v.get())
            top.destroy()

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=(14, 0))
        widgets.Botao(rodape, "Baixar", papel="acao", command=confirmar
                      ).pack(side="right")
        widgets.Botao(rodape, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=(0, 8))
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
            from mc_catalogos import Catalogos
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

        Roda inteiro na thread da INTERFACE, e não passa pelo `anx.submeter`:
        ao contrário dos passos 1 e 2, aqui não há navegador nem ERP. Tudo o
        que a remessa precisa já está em `self.resultado`, e escrever arquivo
        de texto local não justifica ocupar a sessão que só aceita um por vez.
        """
        if not self.resultado:
            messagebox.showinfo("Remessa", "Gere a planilha primeiro (passo 2).")
            return
        # O período na tela pode ter mudado depois do passo 2 sem que ninguém
        # tenha clicado em "1. Buscar" — trocar a data não invalida nada
        # sozinha. Gerar a remessa a partir de uma planilha de outro dia é o
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
                    f"A planilha em memória é de {ini:%d/%m/%Y} a {fim:%d/%m/%Y}, "
                    f"e as datas na tela são outras.\n\n"
                    "A remessa sai da planilha, não das datas. Gerar assim mesmo?",
                    default="no"):
                return
        try:
            mapa_mc = contas_mc.carregar()
            cadastro = sicoob_contas.carregar()
        except Exception as e:
            messagebox.showerror("Remessa", f"Não consegui ler o cadastro:\n{e}")
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
                "Não consegui falar com o registro de remessas.\n\n"
                f"{e}\n\n"
                "A remessa não foi gerada. O número sequencial (NSA) precisa "
                "vir de um lugar só, senão as duas máquinas podem gerar o "
                "mesmo — e repetir NSA pode virar pagamento em dobro.\n\n"
                "Conecte-se e tente de novo.")
            return
        preparado = remessa_dia.preparar(self.resultado.contas,
                                         self.participantes,
                                         historico=historico)
        pagadores, recusadas = {}, []
        for conta in preparado:
            pagador, motivo = remessa_dia.resolver_pagador(
                conta, mapa_mc, cadastro.empresas)
            if pagador:
                pagadores[conta] = pagador
            else:
                recusadas.append((conta, motivo))

        if not pagadores:
            messagebox.showinfo(
                "Remessa",
                "Nenhuma conta marcada gera remessa.\n\n"
                + "\n".join(f"• {c}: {m}" for c, m in recusadas[:8]))
            return

        if not self._janela_remessa(preparado, pagadores, recusadas, historico):
            self.q.put(("status", "Remessa cancelada — nada foi gravado."))
            return
        self._gravar_remessas(preparado, pagadores, historico)

    def _janela_remessa(self, preparado, pagadores, recusadas, historico) -> bool:
        """A conferência. Devolve True se a pessoa confirmou.

        Vem marcado o que a planilha julgou APTO e desmarcado o que ela marcou
        com ATENÇÃO: o normal segue sozinho, o duvidoso exige um clique. O que
        NÃO PODE sair aparece sem caixa, com o motivo — desmarcado é escolha
        sua, impedido é outra coisa.
        """
        top = tk.Toplevel(self)
        top.title("3. Gerar remessa — conferência")
        top.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(top)

        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)
        ttk.Label(moldura, style="Secao.TLabel",
                  text="Confira o que vai no arquivo").pack(anchor="w")
        ttk.Label(moldura, style="Apoio.TLabel", wraplength=680, justify="left",
                  text="Já vem marcado o que está APTO. Desmarque o que não deve "
                       "ir hoje. Depois de gravar, o envio ao SicoobNet é seu, "
                       "à mão — o app nunca transmite."
                  ).pack(anchor="w", pady=(0, 10))

        painel = tk.Canvas(moldura, highlightthickness=0, height=380)
        barra = ttk.Scrollbar(moldura, orient="vertical", command=painel.yview)
        dentro = ttk.Frame(painel)
        dentro.bind("<Configure>",
                    lambda _e: painel.configure(scrollregion=painel.bbox("all")))
        painel.create_window((0, 0), window=dentro, anchor="nw")
        painel.configure(yscrollcommand=barra.set)
        widgets.estilo_canvas(painel)
        painel.pack(side="left", fill="both", expand=True)
        barra.pack(side="left", fill="y")

        # Duas contas da MESMA empresa dividem o convênio, e `proximo_nsa` é
        # CONSULTA, não reserva: as duas mostravam "arquivo nº 000031" enquanto
        # a gravação daria 31 a uma e 32 à outra. Quem conferisse pelo número
        # da tela procuraria um arquivo que não existe.
        #
        # Com o contador na nuvem, o número aqui é PREVISÃO: se a outra máquina
        # gerar entre esta tela e o Confirmar, o arquivo sai com um número mais
        # alto. Continua sendo consulta de propósito — reservar ao MOSTRAR
        # queimaria um NSA cada vez que alguém abrisse a janela e desistisse.
        # A previsão errar para cima é inofensiva; o nome do arquivo gravado é
        # o que vale, e ele aparece no registro ao fim.
        proximos: dict[str, int] = {}
        for conta, pagador in pagadores.items():
            linhas = preparado[conta]
            if pagador.convenio not in proximos:
                proximos[pagador.convenio] = historico.proximo_nsa(pagador.convenio)
            nsa = proximos[pagador.convenio]
            proximos[pagador.convenio] = nsa + 1

            vao = [c for c in linhas if c.pode and c.marcado]
            cabecalho = ttk.Frame(dentro)
            cabecalho.pack(fill="x", pady=(10, 2))
            ttk.Label(cabecalho, style="Secao.TLabel",
                      text=f"{pagador.empresa} — ag {pagador.agencia}-"
                           f"{pagador.dv_agencia} / {pagador.conta}-{pagador.dv_conta}"
                      ).pack(side="left")
            # Contagem e total ao lado do número do arquivo. Eles só existiam
            # DEPOIS de gravar, no registro — então conferir "bate com o que eu
            # esperava?" antes de mandar dinheiro dependia de somar na
            # calculadora. As outras duas ações irreversíveis do app (Aportes e
            # Acessórias) já dizem quantos e quanto antes de perguntar.
            ttk.Label(cabecalho, style="Apoio.TLabel",
                      text=(f"{len(vao)} de {len([c for c in linhas if c.pode])} "
                            f"· {relatorio.brl(sum(c.valor for c in vao))} "
                            f"· arquivo nº {nsa:06d}")).pack(side="right")

            for c in linhas:
                if not c.pode:
                    ttk.Label(dentro, style="Apoio.TLabel", wraplength=660,
                              justify="left",
                              text=(f"       —  {c.tipo}  {relatorio.brl(c.valor)}  "
                                    f"{c.favorecido[:28]}  ·  não vai: {c.impedimento}")
                              ).pack(anchor="w")
                    continue
                v = tk.BooleanVar(value=c.marcado)
                c._var = v                      # lido de volta no confirmar()
                # O `status` e a `obs` existiam no Candidato e NÃO apareciam: a
                # linha com "ATENÇÃO — valor do boleto diverge" era visualmente
                # idêntica a uma linha limpa, e o único sinal era vir
                # desmarcada — a um clique de ser marcada por quem está
                # marcando todas. Agora o motivo vem escrito, e o alerta vem
                # antes do resto para o olho bater nele primeiro.
                alerta = "" if c.apto else f"⚠ {c.status}  "
                detalhe = f"  ·  {c.obs[:70]}" if c.obs else ""
                ttk.Checkbutton(
                    dentro, variable=v,
                    text=(f"{alerta}{c.tipo:<7} {relatorio.brl(c.valor):>14}  "
                          f"{c.favorecido[:30]:<30}  {c.descricao[:40]}{detalhe}")
                ).pack(anchor="w")
                # O reembolso paga QUEM NÃO É o favorecido do lançamento, e o
                # nome acima já é o da pessoa — quem só olha a lista não teria
                # como perceber a troca. Esta linha diz de onde veio o nome, de
                # que compra o reembolso é, e com que documento o dinheiro vai
                # sair. É a conferência que justifica a linha nascer desmarcada.
                if c.reembolso:
                    ttk.Label(
                        dentro, style="Apoio.TLabel", wraplength=640,
                        justify="left",
                        text=(f"            ↳ reembolso de {c.reembolso_de[:30]}  ·  "
                              f"documento {_doc_legivel(c.documento_favorecido)} "
                              f"({c.reembolso_origem})")).pack(anchor="w")
                # Este pagamento já saiu numa remessa viva. Era impedimento —
                # a linha vinha sem caixa, e reenviar obrigava a descartar a
                # remessa inteira, grosso demais quando o que falhou foi um
                # pagamento. Agora é aviso: a caixa existe e nasce VAZIA,
                # porque marcá-la é dinheiro saindo duas vezes.
                if c.ja_enviado:
                    ttk.Label(
                        dentro, style="Apoio.TLabel", wraplength=640,
                        justify="left",
                        text=(f"            ↳ {c.ja_enviado} — marque para "
                              "enviar de novo")).pack(anchor="w")

        if recusadas:
            ttk.Label(dentro, style="Secao.TLabel",
                      text="Contas sem remessa").pack(anchor="w", pady=(12, 2))
            for conta, motivo in recusadas:
                ttk.Label(dentro, style="Apoio.TLabel", wraplength=660,
                          justify="left", text=f"       {conta[:40]}: {motivo}"
                          ).pack(anchor="w")

        resposta = {"ok": False}

        def confirmar():
            for linhas in preparado.values():
                for c in linhas:
                    if getattr(c, "_var", None) is not None:
                        c.marcado = bool(c._var.get())
            resposta["ok"] = True
            top.destroy()

        rodape = ttk.Frame(moldura)
        rodape.pack(side="bottom", fill="x", pady=(14, 0))
        widgets.Botao(rodape, "Gravar os arquivos", papel="acao",
                      command=confirmar).pack(side="right")
        widgets.Botao(rodape, "Cancelar", papel="neutro", command=top.destroy
                      ).pack(side="right", padx=(0, 8))

        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.bind("<Escape>", lambda _e: top.destroy())
        try:
            top.grab_set()
        except tk.TclError:
            pass
        self.wait_window(top)
        return resposta["ok"]

    def _gravar_remessas(self, preparado, pagadores, historico):
        """Valida, grava e registra — nessa ordem, uma conta por vez.

        Arquivo que não passa no validador não é gravado E não consome o NSA:
        número gasto por arquivo que não existe vira furo sem explicação, e o
        histórico é justamente quem tem de explicar os furos.
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
                caminho = destino / remessa_dia.nome_do_arquivo(pagador, nsa)
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
            return
        self._log("\nAgora suba os arquivos no SicoobNet: Empresarial → Gestão em "
                  "Lote → IntegraLote → Gestão de arquivos CNAB. O app não "
                  "transmite: gerar é reversível, enviar não é.")
        self.q.put(("status", f"{len(gerados)} arquivo(s) de remessa · "
                              f"{relatorio.brl(total_geral)}"))
        # "Contas sem remessa" do Início sai daqui: são as contas que TÊM
        # pagamento hoje e não viraram arquivo. É a única hora em que a
        # diferença existe — antes da remessa não há com o que comparar.
        _com_remessa = len(gerados)
        _com_pagamento = len([c for c in (self.resultado.contas if
                                          self.resultado else {})])
        widgets.registrar_atividade(
            "pag", "Gerar remessa", "ok",
            f"{len(gerados)} arquivo(s) · {relatorio.brl(total_geral)}",
            # `total_remessa` e não `total`: o Início junta os números das
            # várias execuções da mesma aba, e "total" já é o do dia inteiro
            # que o passo 1 apurou. Com o mesmo nome, o valor da remessa
            # (que exclui o que ficou de fora) sobrescrevia o do dia, e o
            # cartão "Pagamentos de hoje" passava a mostrar 87 lançamentos
            # somando menos do que eles somam.
            {"contas_sem_remessa": max(_com_pagamento - _com_remessa, 0),
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
