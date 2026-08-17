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
import json
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocr_boleto                                             # noqa: E402
import regras_pagamento as regras                             # noqa: E402
import relatorio                                              # noqa: E402
import remessa_dia                                            # noqa: E402

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


def _carregar_reembolsos() -> dict:
    """Chaves Pix dos avisos "PAGAR PARA <nome>".

    Fica em arquivo, ao lado do exe, porque é CPF de gente — não entra no
    repositório. Ausente, o relatório só marca a linha como pendente.
    """
    try:
        dados = json.loads((_pasta_base() / "pix_reembolso.json")
                           .read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
    except Exception:
        return {}


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
            self, "Pagamentos do Dia",
            "Planilha de conferência dos pagamentos do período: como pagar "
            "cada um e se o documento anexado bate com o lançamento.")
        self.cab.pack(fill="x", padx=PADX, pady=(12, 4))

        # Cartões SEM número: quem numera é a trilha de ações, montada no fim
        # do `_build` (os botões dela ainda não existem aqui).
        f1 = widgets.Cartao(self, "Período")
        f1.pack(fill="x", padx=PADX, pady=6)
        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="De:").pack(side="left")
        CampoData(linha, self.v_ini).pack(side="left", padx=(6, 12))
        ttk.Label(linha, text="até:").pack(side="left")
        CampoData(linha, self.v_fim).pack(side="left", padx=(6, 8))
        ttk.Label(linha, text="(dd/mm/aaaa)", style="Apoio.TLabel").pack(side="left")
        ttk.Button(linha, text="Hoje", command=self._hoje).pack(side="left", padx=(12, 0))

        opc = ttk.Frame(f1); opc.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(opc, variable=self.v_cruzar,
                        text="Conferir os documentos anexados (baixa os PDFs; "
                             "mais lento, mas é a conferência de verdade)"
                        ).pack(anchor="w")
        ttk.Checkbutton(opc, variable=self.v_incluir_pagos,
                        text="Incluir também o que já foi pago no período"
                        ).pack(anchor="w")

        # ---- card 2: contas
        # A lista também é elástica: antes de buscar ela tem uma frase, e um
        # quadro vazio de 170 px em volta de uma frase é o mesmo desperdício
        # que o Registro tinha. Cresce em `_montar_contas`.
        self.f_contas = f2 = widgets.Cartao(
            self, "Contas (marque as que entram no relatório)")
        f2.pack(fill="x", padx=PADX, pady=6)
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
        ttk.Label(self.contas_box,
                  text='Clique em "1. Buscar os lançamentos" para listar as contas.'
                  ).pack(anchor="w")

        # ---- card 3: pasta
        f3 = widgets.Cartao(self, "Onde salvar")
        f3.pack(fill="x", padx=PADX, pady=6)
        ttk.Entry(f3, textvariable=self.v_pasta).pack(side="left", fill="x", expand=True)
        ttk.Button(f3, text="Selecionar…", command=self._sel_pasta
                   ).pack(side="left", padx=(6, 0))

        # ---- barra de ação
        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao); prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao); btns.pack(fill="x")
        self.b1 = ttk.Button(btns, text="▶ 1. Buscar os lançamentos", command=self.buscar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(btns, text="▶ 2. Gerar a planilha", command=self.gerar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b3 = ttk.Button(btns, text="▶ 3. Gerar remessa",
                             command=self.gerar_remessa, state="disabled")
        self.b3.pack(side="left", padx=(0, 10))
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = ttk.Button(btns, text="📂 Abrir planilha", command=self._abrir,
                                  state="disabled")
        self.b_abrir.pack(side="left", padx=(10, 0))
        for b in (self.b1, self.b2):
            try:
                b.configure(style="Accent.TButton")
            except tk.TclError:
                pass

        self.reg = widgets.Cartao(self, "Registro", padding=(10, 6, 10, 10))
        self.reg.pack(fill="x", padx=PADX, pady=6)
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

        widgets.Passos(self.cab, (("Buscar os lançamentos", self.b1),
                                  ("Gerar a planilha", self.b2))
                       ).pack(anchor="w", pady=(8, 0))

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
                    self.pb.configure(maximum=max(total, 1), value=feitos)
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
                                  "Marque as contas e clique em 2."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui buscar os lançamentos."))
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
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

        rodape = ttk.Frame(self.contas_box)
        rodape.pack(anchor="w", pady=(6, 0))
        ttk.Button(rodape, text="Marcar todas",
                   command=lambda: [v.set(True) for v in self.vars_contas.values()]
                   ).pack(side="left")
        ttk.Button(rodape, text="Desmarcar todas",
                   command=lambda: [v.set(False) for v in self.vars_contas.values()]
                   ).pack(side="left", padx=6)
        self.b2.configure(state="normal")

    # --------------------------------------------------------------- etapa 2
    def _janela_confirmar(self, alvos) -> set | None:
        """Pergunta, um a um, quais desses pagamentos entram.

        Existe para os pagamentos que o dono do escritório quer ver antes —
        distribuição de lucro para os sócios, por exemplo. Marcar a linha de
        laranja na planilha não bastava: a planilha é lida DEPOIS de gerada,
        e a pergunta precisa acontecer antes.

        Roda na thread da interface (é chamada de `gerar`, antes de submeter
        ao navegador), então pode abrir janela e esperar resposta à vontade.
        Devolve os ids NÃO confirmados, ou None se a pessoa cancelou tudo.
        """
        top = tk.Toplevel(self)
        top.title("Confirmar antes de gerar")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        widgets.barra_de_titulo(top)

        moldura = ttk.Frame(top, padding=14)
        moldura.pack(fill="both", expand=True)
        ttk.Label(moldura, style="Secao.TLabel",
                  text="Estes pagamentos pedem a sua confirmação").pack(anchor="w")
        ttk.Label(moldura, style="Apoio.TLabel", wraplength=560, justify="left",
                  text="Desmarque o que NÃO deve entrar na planilha de hoje. O que "
                       "for desmarcado vai para a aba NÃO ENTRARAM, com o motivo."
                  ).pack(anchor="w", pady=(0, 10))

        marcas = []
        for item in alvos:
            v = tk.BooleanVar(value=True)
            marcas.append((str(item.get("id")), v))
            desc = (item.get("description") or "").strip()[:70]
            ttk.Checkbutton(
                moldura, variable=v,
                text=(f"{(item.get('paidTo') or '?').strip()}  —  "
                      f"{relatorio.brl(relatorio.valor_do_item(item))}"
                      + (f"  ·  {desc}" if desc else ""))).pack(anchor="w", pady=1)

        resposta = {"cancelou": True}

        def confirmar():
            resposta["cancelou"] = False
            top.destroy()

        rodape = ttk.Frame(moldura)
        rodape.pack(fill="x", pady=(14, 0))
        ttk.Button(rodape, text="Cancelar", command=top.destroy).pack(side="right")
        b = ttk.Button(rodape, text="Confirmar e gerar", command=confirmar)
        b.pack(side="right", padx=(0, 8))
        try:
            b.configure(style="Accent.TButton")
        except tk.TclError:
            pass

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
        nomes = regras.carregar_confirmar()
        if not nomes:
            return set()
        escolha = {relatorio.chave(n) for n in escolhidas}
        alvos = [i for i in self.lancamentos
                 if relatorio.chave(relatorio.nome_da_conta(i)) in escolha
                 and not i.get("paid")
                 and regras.exige_confirmacao(i.get("paidTo") or "", nomes)]
        return self._janela_confirmar(alvos) if alvos else set()

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

            resultado = relatorio.montar_registros(
                selecionados, self.anexos, self.overviews, textos,
                pix_reembolso=_carregar_reembolsos(), urls_ocr=urls_ocr,
                regras_fornecedor=regras.carregar_fornecedores(),
                ids_nao_confirmados=nao_confirmados)
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
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar a planilha."))
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
        ttk.Button(rodape, text="Cancelar", command=top.destroy).pack(side="right")
        b = ttk.Button(rodape, text="Gravar os arquivos", command=confirmar)
        b.pack(side="right", padx=(0, 8))
        try:
            b.configure(style="Accent.TButton")
        except tk.TclError:
            pass

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
