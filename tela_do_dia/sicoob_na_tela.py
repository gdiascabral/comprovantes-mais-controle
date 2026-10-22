# -*- coding: utf-8 -*-
"""O "Reler Sicoob" e a hora da leitura — a entrada da entrega 4 na aba.

Isolado do `frame.py` de propósito (outras entregas mexem nele): o frame só
o cria no cartão 1, chama `aplicar` no recálculo, `ler_se_faltar` depois do
Buscar e `ligar` junto com os botões dele. A regra é `saldo_sicoob` (puro);
quem fala com o banco é `extratos_sicoob.saldo`.

**Thread própria, nunca a do ERP** (o executor do `AnexarFrame`): o Sicoob é outro site e
outro login, e o Playwright síncrono só vive na thread que o criou — o
`SicoobClient` nasce e morre dentro de `_t_ler`. Uma `Thread` daemon por vez,
como o "Conferir agendamentos" (`pagamentos_frame._t_agendamentos`), e não
`ThreadPoolExecutor`: as threads dele não são daemon, e fechar o app com o
Chrome esperando o login (até 10 min) deixaria o processo vivo
(`acessorias/frame.py`, `fechar`). A tela só recebe pela fila.

**Botão:** segue a regra dos botões da tela (`passo2.botoes`): sem leitura
do ERP, lendo o ERP ou gravando na nuvem, apagado (`ligar(b.dia)`); e,
enquanto o Sicoob é lido, apagado também — o "fim" da fila só o religa se a
tela deixar (`_pode`).
"""
from __future__ import annotations

import datetime
import queue
import threading
from tkinter import messagebox, ttk

import widgets

from . import saldo_sicoob as ss

TITULO = "Reler Sicoob"
#: O que a barra lateral e a Remessa ("Conferir agendamentos") mostram quando
#: recusam por causa desta aba (achado 19: a mensagem diz QUEM usa o Sicoob).
OCUPADO = "Pagamentos do dia — lendo o saldo do Sicoob"
#: A aba Baixar comprovantes abre o MESMO perfil do Chrome do Sicoob.
BAIXAR_COMPROVANTES = "Baixar comprovantes — baixando do banco"


def _hoje() -> datetime.date:
    """Separado para o teste fixar o dia (virada da meia-noite)."""
    return datetime.date.today()


def baixar_comprovantes_no_sicoob(aba) -> str | None:
    """A aba Baixar comprovantes está rodando? Ela não tem `ocupado()`: a
    pergunta é a mesma que ela própria faz antes de começar (`_comecar`), o
    `worker` vivo. Aba sem o atributo, ou que falha ao responder, não trava
    ninguém."""
    try:
        w = getattr(aba, "worker", None)
        return BAIXAR_COMPROVANTES if w is not None and not w.done() else None
    except Exception:                                        # noqa: BLE001
        return None


class LeitorSicoob:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._parar = threading.Event()
        self.leitura = None
        self.contas = []
        self._lendo = None
        self._carregada_de = None
        self._chave_contas = None
        #: A tela deixa o botão ligado? (`ligar`, a partir de `passo2.botoes`)
        self._pode = False
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob (Extratos,
        #: Conferir agendamentos da Remessa).
        self.outros_no_sicoob = lambda: None
        self.barra = ttk.Frame(pai)
        self.lbl = ttk.Label(self.barra, style="Secao.TLabel", text="")
        self.lbl.pack(side="left")
        self.b_reler = widgets.Botao(self.barra, TITULO, papel="neutro", state="disabled",
                                     command=self.reler)
        self.b_reler.pack(side="right")
        self._mostrar_hora()
        self.barra.after(200, self._drain)

    # ------------------------------------------------------------ perguntas
    def ocupado(self) -> str | None:
        t = self._thread
        return OCUPADO if t is not None and t.is_alive() else None

    @staticmethod
    def _ligado() -> bool:
        try:
            from extratos_sicoob import saldo
            return saldo.medido()
        except Exception:                                    # noqa: BLE001
            return False

    def _data(self) -> datetime.date:
        periodo = getattr(self.tela, "periodo", None)
        return periodo.fim if periodo is not None else datetime.date.today()

    def _gravando(self) -> bool:
        return bool(getattr(self.tela, "_gravando", False))

    # ----------------------------------------------- chamado pela tela (botões)
    def ligar(self, pode: bool) -> None:
        """A mesma regra dos botões da tela; lendo o Sicoob, fica apagado."""
        self._pode = bool(pode)
        self.b_reler.configure(state="normal" if self._pode and not self.ocupado()
                               else "disabled")

    # ----------------------------------------- chamado pelo recálculo (tela)
    def aplicar(self, linhas, contas_erp, mapping):
        from conciliacao.frame import RAIZ_SAIDA
        data = self._data()
        if self._carregada_de != data:
            self._carregada_de = data
            if self.leitura is None or self.leitura.data != data:
                self.leitura, aviso = ss.ler(ss.caminho(RAIZ_SAIDA, data), data)
                if aviso:
                    self.tela._log(f"[!] {aviso}")
        # Os objetos da última leitura do ERP (e não o `id`, que o Python
        # reaproveita): o cadastro só é relido quando o Buscar trouxe outros.
        chave = self._chave_contas
        if chave is None or chave[0] is not contas_erp or chave[1] is not mapping:
            self._chave_contas = (contas_erp, mapping)
            try:
                from pagamentos_dia import pagamentos_frame
                mapa_mc, empresas = pagamentos_frame._carregar_mapas()
                self.contas = ss.contas_do_painel(linhas, contas_erp, mapping, mapa_mc, empresas)
            except Exception as e:                           # noqa: BLE001
                self.contas = []
                self.tela._log(f"[!] Sicoob: não consegui ler o cadastro de contas ({e}); "
                               "o saldo do banco fica digitado.")
        self._mostrar_hora()
        leitura = self.leitura if self.leitura is not None and self.leitura.data == data else None
        return ss.aplicar(linhas, self.contas, leitura)

    # ------------------------------------------------------------- ações
    def ler_se_faltar(self):
        """Fim do Buscar (spec: o Buscar também lê o Sicoob) — só quando ainda
        não há leitura de hoje, e nunca com o endereço ainda não medido."""
        if self.leitura is None and self._ligado() and not self.ocupado() \
                and not self._gravando() and ss.numeros_a_ler(self.contas):
            self.reler(perguntar=False, automatico=True)

    def reler(self, perguntar=True, automatico=False):
        if self.ocupado():
            return

        def recusar(texto):
            # O automático (fim do Buscar) não abre janela: só o Registro.
            if not automatico:
                messagebox.showinfo(TITULO, texto)
            else:
                self.tela._log(f"[!] {TITULO}: {texto}")

        data = self._data()
        if data != _hoje():
            # Virada da meia-noite: a tela é de ontem, e a leitura seria
            # guardada no dia errado.
            recusar(f"Busque de novo: a tela é de {data:%d/%m}.")
            return
        if not self._ligado():
            from extratos_sicoob import saldo
            messagebox.showinfo(TITULO, saldo.NAO_MEDIDO[0].upper() + saldo.NAO_MEDIDO[1:] + ".")
            return
        if self._gravando():
            recusar("Espere a gravação na nuvem terminar.")
            return
        if self.tela.mapping is None or self.tela.dia is None:
            recusar("Busque os pagamentos e saldos primeiro: é a leitura "
                    "do ERP que diz quais contas do painel são do Sicoob.")
            return
        numeros = ss.numeros_a_ler(self.contas)
        if not numeros:
            recusar("Nenhuma conta do painel é do Sicoob (ou o cadastro não "
                    "diz qual é) — o saldo do banco fica digitado.")
            return
        quem = self.outros_no_sicoob()
        if quem:
            recusar(f"O Chrome do Sicoob está em uso ({quem}). Espere "
                    "terminar: os dois usariam o mesmo perfil do banco.")
            return
        if perguntar and not messagebox.askokcancel(
                TITULO, f"Vou abrir o Chrome do Sicoob e ler o saldo de {len(numeros)} "
                        "conta(s), trocando de conta uma a uma.\n\nÉ só leitura: nada é "
                        "pago, agendado nem alterado no banco.\n\nFaça o login quando a "
                        "janela abrir."):
            return
        self._parar.clear()
        self.b_reler.configure(state="disabled")
        self._lendo = (0, len(numeros))
        self._mostrar_hora()
        self._thread = threading.Thread(target=self._t_ler, args=(numeros, data),
                                        name="sicoob-saldo", daemon=True)
        self._thread.start()

    def _t_ler(self, numeros, data):
        """Thread do Sicoob. Só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            from extratos_sicoob import saldo
            from extratos_sicoob.sicoob_client import SicoobClient

            def registrar(msg):
                self.tela._log(f"  Sicoob: {msg}")

            with SicoobClient(log=registrar) as cli:
                cli.aguardar_login()
                lidos = saldo.ler_contas(
                    cli, numeros, parar=self._parar.is_set, log=registrar,
                    progresso=lambda f, t: self.q.put(("lendo", (f, t))))
            self.q.put(("lida", ss.LeituraSicoob.de_resultados(data, lidos)))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", ss.recado_da_falha(e)))
        finally:
            self.q.put(("fim", None))

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "lendo":
                    self._lendo = valor
                elif tipo == "lida":
                    self._receber(valor)
                elif tipo == "falhou":
                    self.tela._log(f"[!] {valor}")
                elif tipo == "fim":
                    self._lendo = None
                    self.b_reler.configure(state="normal" if self._pode else "disabled")
                self._mostrar_hora()
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar o Sicoob na tela: {e!r}")
        finally:
            self.barra.after(200, self._drain)

    def _receber(self, leitura):
        from conciliacao.frame import RAIZ_SAIDA
        self.leitura, self._carregada_de = leitura, leitura.data
        try:
            ss.gravar(leitura, ss.caminho(RAIZ_SAIDA, leitura.data))
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] não consegui guardar a leitura do Sicoob ({e}); "
                           "ela vale até fechar o app.")
        for lido in leitura.contas.values():
            if lido.saldo is None:
                self.tela._log(f"  Sicoob {lido.numero}: não lido — {lido.motivo}")
        if self.tela.dia is not None and self.tela.leitura is not None:
            self.tela._recalcular()

    def _mostrar_hora(self):
        self.lbl.configure(text=ss.texto_da_hora(self.leitura, self.contas,
                                                 lendo=self._lendo, ligado=self._ligado()))

    def fechar(self):
        self._parar.set()
