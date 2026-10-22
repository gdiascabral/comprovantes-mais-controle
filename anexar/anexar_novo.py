# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + N comprovantes que somam um pagamento.

Decisão do dono (21/10/2026): a aba Anexar atual NÃO muda e fica como plano B;
esta é a CÓPIA com o casamento novo. Ela tem de fazer tudo o que a atual faz —
inclusive o modo "Por lista" e o casamento de um PDF por pagamento, porque
pagamento de PF é feito pelo celular e não se automatiza. Por isso é uma
subclasse: os dois modos, a janela de dúvidas e o relatório são os MESMOS
métodos do `AnexarFrame`, sem cópia.

UM NAVEGADOR SÓ. Esta aba NÃO é dona de navegador (`DONO_DO_NAVEGADOR =
False`): não cria executor, não pulsa e não fecha o Chrome. Todo trabalho vai
para o `AnexarFrame` de sempre (`self.anx.submeter(..., dona=self)`), como a
Conferência, os Aportes e as outras; `mc`/`api` são os dele (no modo central,
os da vaga desta aba, que o dono cria e fecha).

"Casar e anexar" em DUAS fases, as duas na MESMA chamada, dentro do
`submeter` do dono — o Playwright síncrono só aceita a thread que o criou:
1. `AnexarFrame._t_auto`, INTEIRO e sem cópia — a Anexar de hoje, com a
   janela de dúvidas e o relatório dela;
2. `varios_comprovantes.fase_das_somas` sobre quem ficou SEM PAR.
O ("fim", …) da fase 1 é segurado (`_FilaComDesvio`) e sai UMA vez, somado.

Cada rodada começa dos pagos como a busca os trouxe (`_remontar_pagos`): a
fase 1 escreve status, PDF e motivos nos próprios registros, e um
`motivo_soma` que sobrasse de uma rodada anterior prenderia a seguinte.
"""
from __future__ import annotations

import copy
import queue
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from . import codigo_barras, matcher, origem, varios_comprovantes
from .anexar_comprovantes import AnexarFrame, _texto_do_erro


class _FilaComDesvio(queue.Queue):
    """A fila da interface que, com `desviar`, guarda o ("fim", …) em vez de
    entregá-lo — o "Concluído" só aparece depois da fase das somas."""

    def __init__(self):
        super().__init__()
        self.desviar = False
        self.fim_desviado = None

    def put(self, item, block=True, timeout=None):
        if self.desviar and isinstance(item, tuple) and item and item[0] == "fim":
            self.fim_desviado = item[1]
            return
        super().put(item, block, timeout)


class AnexarNovoFrame(AnexarFrame):
    TITULO = "Anexar (novo)"
    TRILHA = "Comprovantes  ›  Anexar (novo)"
    DONO_DO_NAVEGADOR = False
    ATIVIDADE = "anx2"

    def __init__(self, master, dono: AnexarFrame):
        self.anx = dono                  # antes do super: tudo abaixo pode perguntar
        super().__init__(master)
        self.q = _FilaComDesvio()        # antes do 1º `_drain` (150 ms)

    # ------------------------------------------- os pagos de cada rodada
    @property
    def pagos(self) -> list:
        return self.__dict__.get("_pagos", [])

    @pagos.setter
    def pagos(self, valor):
        """Quem atribui é a busca (`_t_conectar`, com o `montar_pagos`): guarda
        também o molde intocado, de onde cada rodada recomeça."""
        self._pagos = valor
        self._molde_dos_pagos = copy.deepcopy(valor)

    def _remontar_pagos(self):
        """Os pagos de novo como o `montar_pagos` os deu na busca — registros
        novos, sem nada que a rodada anterior escreveu neles. Cópia funda do
        molde: o `montar_pagos` é função pura, então dá o mesmo que rodá-lo
        de novo sobre a mesma listagem, sem voltar ao ERP."""
        self._pagos = copy.deepcopy(self.__dict__.get("_molde_dos_pagos", []))

    # ------------------------------------------- o navegador é do dono
    @property
    def mc(self):
        return self.anx.mc

    @mc.setter
    def mc(self, valor):
        self.anx.mc = valor

    @property
    def api(self):
        return self.anx.api

    @api.setter
    def api(self, valor):
        self.anx.api = valor

    def submeter(self, rotulo: str, fn, *a, dona=None, **k):
        return self.anx.submeter(rotulo, fn, *a, dona=self, **k)

    def ocupado(self, aba=AnexarFrame._QUALQUER):
        return self.anx.ocupado(aba=self)

    def dona_ocupada(self, aba=AnexarFrame._QUALQUER):
        return self.anx.dona_ocupada(aba=self)

    def avisar_se_ocupado(self, dona: str, *, aba=None) -> bool:
        return self.anx.avisar_se_ocupado(dona, aba=self)

    def abrir_minha_aba(self):
        self.anx.abrir_minha_aba()

    def garantir_sessao(self, log=None):
        return self.anx.garantir_sessao(log or self._log)

    def _pulsar_navegador(self):
        return                           # quem pulsa é o dono

    def fechar(self):
        """Solta quem espera nesta aba (pausa, janela de dúvidas). O Chrome é
        do dono e fecha com ele — o `_sair` chama esta antes da dele."""
        self._encerrando = True
        try:
            self._parar.set()
            self._pausa.clear()
        except Exception:                                   # noqa: BLE001
            pass
        for ev in list(getattr(self, "_esperas", ())):
            try:
                ev.set()
            except Exception:                               # noqa: BLE001
                pass
        for filho in list(self.winfo_children()):
            if isinstance(filho, tk.Toplevel):
                try:
                    filho.grab_release()
                    filho.destroy()
                except Exception:                           # noqa: BLE001
                    pass

    # ------------------------------------------- casar e anexar
    def executar(self):
        """O "Casar e anexar" da cópia, com uma recusa a mais.

        No modo central a Anexar de sempre e esta têm vagas (threads)
        diferentes e não se esperam: as duas casando ao mesmo tempo podiam
        subir o MESMO PDF em dois lugares, ou duas vezes no mesmo. A cópia não
        começa enquanto a Anexar de sempre trabalha. (O inverso — a Anexar
        recusar enquanto a cópia trabalha — mexeria na aba de sempre, que
        fica idêntica.) A pergunta vem antes de tocar em qualquer botão."""
        if self.worker and not self.worker.done():
            return
        dono = self.anx
        if dono.dona_ocupada(aba=dono) is dono:
            messagebox.showwarning(
                "Anexar trabalhando",
                f"A aba Anexar está em: {dono.ocupado(aba=dono) or 'outra tarefa'}.\n\n"
                "As duas casam e anexam os mesmos comprovantes: espere a Anexar "
                "terminar e clique de novo aqui.")
            return
        super().executar()

    def _preparar_somas(self, pendentes, pdfs, pasta: Path) -> None:
        """As réguas da fase 2, nos PDFs que ela recarregou da pasta.

        Os pendentes NÃO passam pelo `origem.preencher` de novo: são os mesmos
        registros da fase 1, que já trazem a origem e o `doc_favorecido` lido
        do cadastro de Contatos do ERP. Chamado sem `documentos`, o
        `preencher` APAGAVA esse documento — e com ele a regra "recebedor ≠
        favorecido", que segura PDFs pagos a Y no pagamento de X."""
        try:
            origem.preencher([], pdfs, pasta)
        except Exception:                                   # noqa: BLE001
            self._log("[aviso] não deu para saber a conta de origem dos "
                      "comprovantes — as somas seguem sem essa regra.")
        self._ler_barras_da_soma(pendentes, pdfs, pasta)

    def _ler_barras_da_soma(self, pendentes, pdfs, pasta: Path) -> None:
        """O código de barras dos PDFs que podem ser PARCELA de uma soma.

        Os PDFs da fase 2 chegam da pasta sem `barras`, e sem elas a guarda
        "o código é do título de OUTRO pagamento" do `matcher_somado` nunca
        vale. O `_ler_codigos_de_barras` da fase 1 não serve aqui: ele só lê
        PDF cujo valor é o de um pendente, e a parcela nunca é. Lê os de valor
        abaixo do maior pendente; o código dos títulos ficou da fase 1, nos
        mesmos registros. Opcional como as outras réguas."""
        teto = max((v for pe in pendentes for v in matcher._vals(pe)), default=0)
        try:
            for pd in pdfs:
                pd.setdefault("barras", set())
                if not 0 < (pd.get("valor") or 0) < teto:
                    continue
                if self._checar_pausa():
                    return
                try:
                    dados = (Path(pasta) / pd["fn"]).read_bytes()
                except OSError:
                    continue
                texto, ocr = codigo_barras.texto_do_arquivo(pd["fn"], dados)
                pd["barras"] = codigo_barras.codigos_no_texto(texto, {pd["valor"]}, ocr)
        except Exception:                                   # noqa: BLE001
            self._log("[aviso] não li os códigos de barras dos comprovantes da "
                      "soma — as somas seguem sem essa regra.")

    def _t_auto(self, contas_sel: set, termos: list, pasta_pdfs: str, simular: bool):
        # Roda na thread do navegador (`self.submeter` → dono): as duas fases
        # aqui dentro, na mesma chamada — nada de `submeter` novo no meio.
        self._remontar_pagos()
        self.q.fim_desviado, self.q.desviar = None, True
        try:
            super()._t_auto(contas_sel, termos, pasta_pdfs, simular)
        finally:
            self.q.desviar = False
        fim1 = self.q.fim_desviado
        if fim1 is None:
            return                       # a fase 1 parou com erro: "reabilitar2" já passou
        if self._parar.is_set():
            self.q.put(("fim", fim1))
            return
        fim = fim1
        try:
            self._log("\nProcurando comprovantes que SOMAM um pagamento sem par...")
            pasta = Path(pasta_pdfs)
            somas = varios_comprovantes.fase_das_somas(
                self.api, self.pagos, pasta, simular=simular,
                preencher_origem=lambda pend, pdfs: self._preparar_somas(pend, pdfs, pasta),
                log=self._log, cancelar=self._checar_pausa)
            # A conta vem ANTES do Excel: um relatório que não grava (aberto na
            # máquina) não pode apagar do "Concluído" o anexo que já foi feito.
            fim = varios_comprovantes.juntar_fim(fim1, somas)
            for linha in varios_comprovantes.resumo_das_somas(somas):
                self._log(linha)
            try:
                varios_comprovantes.acrescentar_ao_relatorio(fim1[4], somas)
            except Exception as e:                          # noqa: BLE001
                self._log("[aviso] não gravei as somas no relatório: "
                          + _texto_do_erro(e))
        except Exception as e:                              # noqa: BLE001
            self._log(_texto_do_erro(e))
        self.q.put(("fim", fim))
