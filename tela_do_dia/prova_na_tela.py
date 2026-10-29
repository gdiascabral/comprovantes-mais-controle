# -*- coding: utf-8 -*-
"""O botão "📸 Prova de saldos" no cartão Saldos (spec de 27/10/2026).

Todo dia alguém do financeiro tirava, à mão, o print do saldo de cada conta
no ERP e no banco para o grupo de conferência. Aqui o app lê os dois lados,
fotografa, compara em centavos (`prova_saldos`) e gera um PDF
(`prova_pdf`) em `Pagamentos do dia/`; a pessoa arrasta para o grupo. O app
NÃO mexe no WhatsApp.

**Duas threads, cada uma com o navegador do seu dono**, em paralelo:
- ERP: `anx.submeter(..., dona=tela)` — a vaga desta aba no Anexar, com o
  `MCClient` dela (`prova_erp.ler`); recusa antes pelo `avisar_se_ocupado`
  com a MESMA aba (guarda em `tests/test_abas_em_paralelo.py`). A aba do
  robô no ERP abre PRIMEIRO (`_esperar_aba_do_erp`): o Chrome a traz para a
  frente, e no meio do login do Sicoob ela roubaria o foco;
- bancos: `Thread` daemon `prova-saldos` — Sicoob (`prova_sicoob`, o
  `SicoobClient` nasce e morre lá) e depois cada Inter (`inter_saldo`, um
  Chrome e um QR por conta). No fim ela espera o ERP, monta as linhas e o
  PDF, e põe "pronto" na fila.

A tela só recebe pela fila (`_drain` + `after`). "Parar" vale entre contas;
parado, não sai PDF. **Trava**: recusa com o Chrome do Sicoob ou o Baixar
comprovantes em uso (`outros_no_sicoob`, ligado no `comprovantes_app.py`) e,
enquanto roda, é dona do Chrome do Sicoob (`TelaDoDiaFrame.sicoob_ocupado`) e
dos perfis do Inter (`ComprovantesFrame.inter_ocupado`).
"""
from __future__ import annotations

import datetime
import queue
import subprocess
import threading
import time
from tkinter import messagebox, ttk

import widgets

from . import prova_saldos as ps
from . import saldo_sicoob as ss
from . import saldos as sd

TITULO = "Prova de saldos"
OCUPADO = "Pagamentos do dia — prova de saldos"
#: Dentro de "Pagamentos do dia": os PDFs aqui e os PNGs de cada rodada em
#: `PASTA/prints/<data hora>` — uma pasta só, e não uma por rodada solta.
PASTA = "Prova de saldos"
ROTULO_ERP = "Pagamentos do dia — prova de saldos (ERP)"
ESPERA_ERP = 600               # segundos esperando o ERP depois dos bancos
ESPERA_ABA_ERP = 180           # segundos esperando a aba do ERP abrir antes dos bancos


def _saldo_do_autenticar(apelido, numero=""):
    """O saldo do Inter que o "Autenticar no banco" leu HOJE desta conta (com
    o print dele), ou None. Dono, 29/10/2026: um QR por conta de manhã serve
    ao saldo e à prova de pagamento — a Prova não pede o QR de novo."""
    try:
        from conciliacao.frame import RAIZ_SAIDA

        from . import autenticar_inter as ai
        hoje = _agora().date()
        return ai.saldo_do_dia(ai.caminho_dos_saldos(RAIZ_SAIDA, hoje), hoje, apelido,
                               numero, agora=_agora())
    except Exception:                                        # noqa: BLE001
        return None


def _agora() -> datetime.datetime:
    """Separado para o teste fixar a hora (vai no nome do PDF)."""
    return datetime.datetime.now()


def _carregar_cadastros():
    """(mapa_mc, empresas, contas_inter) — função à parte para o teste."""
    from baixar_comprovantes import contas_inter
    from pagamentos_dia import pagamentos_frame
    mapa_mc, empresas = pagamentos_frame._carregar_mapas()
    return mapa_mc, empresas, contas_inter.carregar()


def pergunta_de_abrir(contas) -> str:
    sicoob = sum(1 for c in contas if c.banco == ps.SICOOB and not c.motivo)
    inter = [c.apelido for c in contas if c.banco == ps.INTER and not c.motivo]
    partes = [f"Vou tirar a prova de {len(contas)} conta(s): o saldo atual no ERP e "
              "no banco, com um print de cada tela."]
    if sicoob:
        partes.append(f"Sicoob: {sicoob} conta(s) — faça o login quando o Chrome do "
                      "Sicoob abrir.")
    if inter:
        partes.append("Inter: um QR por conta, nesta ordem: " + ", ".join(inter) + ".")
    partes.append("É só leitura: nada é pago, agendado nem alterado no banco ou no "
                  f"ERP. No fim sai um PDF na pasta Pagamentos do dia, em '{PASTA}'.")
    return "\n\n".join(partes)


class ProvaNaTela:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._erp = None
        self._contas = []
        self._parar = threading.Event()
        self._aba_erp = threading.Event()
        self._pode = False
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob ou o Baixar
        #: comprovantes (que abre os perfis do Inter).
        self.outros_no_sicoob = lambda: None
        self.barra = ttk.Frame(pai)
        self.lbl = ttk.Label(self.barra, style="Secao.TLabel", text="")
        self.lbl.pack(side="left")
        self.b_parar = widgets.Botao(self.barra, "Parar", papel="neutro",
                                     state="disabled", command=self.parar)
        self.b_parar.pack(side="right")
        self.b_prova = widgets.Botao(self.barra, "📸  Prova de saldos", papel="neutro",
                                     state="disabled", command=self.comecar)
        self.b_prova.pack(side="right", padx=widgets.px((0, 8)))
        self.barra.after(200, self._drain)

    # ------------------------------------------------------------ perguntas
    def ocupado(self) -> str | None:
        t = self._thread
        return OCUPADO if t is not None and t.is_alive() else None

    def ligar(self, pode: bool) -> None:
        self._pode = bool(pode)
        self.b_prova.configure(state="normal" if self._pode and not self.ocupado()
                               else "disabled")

    # ------------------------------------------------------------- ações
    def _banco_em_uso(self) -> bool:
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do banco está em uso ({quem}). Espere "
                                        "terminar: os dois usariam o mesmo perfil.")
            return True
        return False

    def comecar(self):
        if self.ocupado():
            return
        tela = self.tela
        if tela.mapping is None or not tela.contas_erp:
            messagebox.showinfo(TITULO, "Busque os pagamentos e saldos primeiro: é a "
                                        "leitura do ERP que diz quais contas do painel "
                                        "são do Sicoob e do Inter.")
            return
        try:
            mapa_mc, empresas, inter = _carregar_cadastros()
        except Exception as e:                               # noqa: BLE001
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o cadastro de contas."))
            return
        linhas = sd.montar_saldos(tela.contas_erp, tela.mapping)
        contas = ps.contas_da_prova(linhas, tela.contas_erp, tela.mapping,
                                    mapa_mc, empresas, inter)
        if not contas:
            messagebox.showinfo(TITULO, "Nenhuma conta do painel é do Sicoob ou do "
                                        "Inter — não há o que provar.")
            return
        if self._banco_em_uso():
            return
        if tela.anx.avisar_se_ocupado("a Prova de saldos", aba=tela):
            return
        if not messagebox.askokcancel(TITULO, pergunta_de_abrir(contas)):
            return
        # De novo depois da pergunta: com ela aberta, o fim do Buscar pode ter
        # aberto o Chrome do Sicoob no MESMO perfil.
        if self._banco_em_uso():
            return
        agora = _agora()
        base = ps.nome_base(agora)
        pasta_pdf = tela._pasta_pagamentos() / PASTA
        pasta_prints = pasta_pdf / "prints" / f"{agora:%Y-%m-%d %Hh%M}"
        self._contas = contas            # para a pergunta do outro acesso
        self._parar.clear()
        self._aba_erp = threading.Event()
        self.b_prova.configure(state="disabled")
        self.b_parar.configure(state="normal")
        self.lbl.configure(text="Prova de saldos: lendo o ERP…")
        tela._log("")
        tela._log(f"{TITULO}: {len(contas)} conta(s)")
        from . import prova_erp
        self._erp = tela.anx.submeter(ROTULO_ERP, prova_erp.ler, tela.anx, tela.cfg,
                                      tela.mapping, contas, pasta_prints,
                                      log=tela._log, parar=self._parar.is_set,
                                      ao_abrir_aba=self._aba_erp.set, dona=tela)
        self._thread = threading.Thread(
            target=self._t_prova, name="prova-saldos", daemon=True,
            args=(contas, pasta_prints, pasta_pdf / f"{base}.pdf", agora))
        self._thread.start()

    def parar(self):
        self._parar.set()
        self.b_parar.configure(state="disabled")
        self.lbl.configure(text="Prova de saldos: parando… (se o Chrome do Sicoob "
                                "estiver no login, feche-o para parar já)")

    # ------------------------------------------------------- thread dos bancos
    def _t_prova(self, contas, pasta_prints, destino, agora):
        """Thread `prova-saldos`. Só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            pasta_prints.mkdir(parents=True, exist_ok=True)
            self._esperar_aba_do_erp()
            bancos = self._ler_bancos(contas, pasta_prints)
            if self._erp is not None and not self._erp.done():
                self.q.put(("estado", "Esperando o ERP…"))
            erp = self._esperar_erp(contas)
            if self._parar.is_set():
                self.q.put(("falhou", "Prova interrompida — nenhum PDF foi gerado."))
                return
            linhas = ps.montar(contas, erp, bancos)
            self.q.put(("estado", "Gerando o PDF…"))
            from . import prova_pdf
            pdf = prova_pdf.gerar(linhas, agora, destino)
            for linha in linhas:
                self.q.put(("log", ps.texto_do_registro(linha)))
            self.q.put(("pronto", (pdf, ps.texto_da_contagem(linhas))))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", f"Prova de saldos: {type(e).__name__}: {e}"))
        finally:
            self.q.put(("fim", None))

    def _esperar_aba_do_erp(self):
        """O Chrome traz a aba nova do robô para a frente: ela abre ANTES dos
        bancos, e não no meio do login do Sicoob ou do QR do Inter. Termina
        também com o ERP já pronto (falhou ou sem conta a fotografar), com o
        Parar ou no estouro do tempo — aí os bancos seguem do mesmo jeito."""
        fut = self._erp
        limite = time.monotonic() + ESPERA_ABA_ERP
        while (fut is not None and not fut.done() and not self._aba_erp.is_set()
               and not self._parar.is_set() and time.monotonic() < limite):
            self._aba_erp.wait(0.2)

    def _registrar_sicoob(self, msg):
        self.tela._log(f"  Sicoob: {msg}")

    def _progresso_sicoob(self, feitas, total):
        texto = (f"Sicoob: lendo a conta {feitas + 1} de {total}…" if feitas < total
                 else f"Sicoob: {total} de {total} conta(s) lidas")
        self.q.put(("estado", texto))

    def _ler_bancos(self, contas, pasta) -> dict:
        sicoob, inter = {}, {}
        numeros = [c.numero for c in contas
                   if c.banco == ps.SICOOB and c.numero and not c.motivo]
        if numeros and not self._parar.is_set():
            self.q.put(("estado", f"Sicoob: lendo {len(numeros)} conta(s)…"))
            from extratos_sicoob.sicoob_client import SicoobClient

            from . import prova_sicoob
            try:
                sicoob = prova_sicoob.ler_com_prints(
                    lambda: SicoobClient(log=self._registrar_sicoob), numeros, pasta,
                    perguntar=self._perguntar_outro_acesso, parar=self._parar.is_set,
                    log=self._registrar_sicoob,
                    progresso=self._progresso_sicoob)
            except Exception as e:                           # noqa: BLE001
                motivo = ss.recado_da_falha(e, "tente de novo a Prova de saldos.")
                sicoob = {ps.digitos(n): ps.Leitura(None, motivo=motivo) for n in numeros}
        for c in contas:
            if c.banco != ps.INTER or c.motivo or not c.apelido:
                continue
            if self._parar.is_set():
                inter[ps.chave_inter(c.apelido)] = ps.Leitura(None, motivo=ps.INTERROMPIDA)
                continue
            do_dia = _saldo_do_autenticar(c.apelido, c.numero)
            if do_dia is not None:
                inter[ps.chave_inter(c.apelido)] = do_dia
                self.q.put(("log", f"  Inter {c.apelido}: saldo lido pelo Autenticar no "
                                   f"banco às {do_dia.lido_em:%H:%M} (sem novo QR)"))
                continue
            from baixar_comprovantes import inter_saldo
            self.q.put(("estado", f"Inter: abrindo a conta {c.apelido}…"))
            lido = inter_saldo.ler_conta(
                c.apelido, c.numero, c.nomes, pasta / ps.nome_do_print(c.linha, "banco"),
                razoes=c.razoes, parar=self._parar.is_set,
                ao_entrar=lambda apelido: self.q.put(
                    ("estado", f"Inter {apelido}: lendo o saldo…")),
                log=lambda msg, a=c.apelido: self.tela._log(f"  Inter {a}: {msg}"),
                avisar_qr=lambda apelido: self.q.put(("qr", apelido)))
            inter[ps.chave_inter(c.apelido)] = ps.Leitura(
                lido.saldo, lido.lido_em, lido.motivo, lido.imagem, lido.sem_imagem)
            if lido.saldo is not None:
                self.q.put(("estado", f"Inter {c.apelido}: lido"))
            else:
                # QR que estourou o tempo, conta errada, sessão vencida: a
                # tela diz na hora, e não só no PDF do fim.
                self.q.put(("estado", f"Inter {c.apelido}: não lido"))
                self.q.put(("log", f"  ⚠ Inter {c.apelido}: {lido.motivo}"))
        return ps.banco_por_linha(contas, sicoob, inter)

    def _esperar_erp(self, contas) -> dict:
        fut = self._erp
        if fut is None:
            motivo = "a leitura do ERP não começou"
        else:
            # Em fatias, olhando o Parar: parado, não se espera o ERP (a vaga
            # dele vê o mesmo `parar` e fecha a aba sozinha).
            limite = time.monotonic() + ESPERA_ERP
            motivo = f"o ERP não respondeu em {max(1, ESPERA_ERP // 60)} minuto(s)"
            while not self._parar.is_set() and time.monotonic() < limite:
                try:
                    return fut.result(timeout=min(0.2, max(0.0, limite - time.monotonic())))
                except TimeoutError as e:
                    if not fut.done():
                        continue             # só a fatia acabou: espera mais
                    primeira = (str(e).strip().splitlines() or [""])[0][:160]
                    motivo = f"{type(e).__name__}: {primeira}"
                    break
                except Exception as e:                       # noqa: BLE001
                    primeira = (str(e).strip().splitlines() or [""])[0][:160]
                    motivo = f"{type(e).__name__}: {primeira}"
                    break
            if self._parar.is_set():
                motivo = ps.PARADO
        return {c.linha: ps.Leitura(None, motivo=motivo) for c in contas}

    def _perguntar_outro_acesso(self, faltam) -> bool:
        """Da thread dos bancos: a pergunta vai pela fila e a thread espera.
        Parar (ou fechar o app) responde "não"."""
        caixa = {"ev": threading.Event(), "sim": False}
        self.q.put(("perguntar", (ss.pergunta_outro_acesso(faltam, self._contas), caixa)))
        while not caixa["ev"].wait(0.2):
            if self._parar.is_set():
                return False
        return bool(caixa["sim"]) and not self._parar.is_set()

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "perguntar":
                    texto, caixa = valor
                    try:
                        caixa["sim"] = bool(messagebox.askyesno(
                            TITULO, texto, default=messagebox.YES))
                    finally:
                        caixa["ev"].set()
                elif tipo == "estado":
                    self.lbl.configure(text=valor)
                elif tipo == "qr":
                    self.lbl.configure(text=f"Leia o QR da {valor} no Chrome do Inter")
                    self.tela._log(f"  Inter: leia o QR da {valor}")
                elif tipo == "log":
                    self.tela._log(valor)
                elif tipo == "pronto":
                    pdf, contagem = valor
                    self.lbl.configure(text=f"Prova pronta: {contagem}")
                    self.tela._log(f"{TITULO}: {pdf.as_posix()} — {contagem}")
                    self._abrir_com_o_pdf(pdf)
                elif tipo == "falhou":
                    self.tela._log(f"[!] {valor}")
                    self.lbl.configure(text=valor[:120])
                elif tipo == "fim":
                    self.b_parar.configure(state="disabled")
                    self.b_prova.configure(state="normal" if self._pode else "disabled")
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar a prova de saldos: {e!r}")
        finally:
            self.barra.after(200, self._drain)

    def _abrir_com_o_pdf(self, pdf):
        """Abre a pasta com o PDF já selecionado, pronto para arrastar ao
        grupo; sem o Explorer, abre só a pasta."""
        try:
            subprocess.Popen(f'explorer /select,"{pdf}"')
        except Exception:                                    # noqa: BLE001
            self.tela._abrir(pdf.parent)

    def fechar(self):
        self._parar.set()
