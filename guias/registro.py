# -*- coding: utf-8 -*-
"""O que cada rodada de guias fez, uma linha por ação.

Mora em `_app/guias_lancadas.jsonl`. Serve a três coisas: a trava contra
lançar duas vezes, a conferência do mês seguinte, e responder "o que a rodada
de ontem fez" sem abrir o ERP.

Formato de linha, e não JSON único: a rodada grava uma linha por ação, logo
depois de cada gravação no ERP. Se o app fechar no meio, o que já foi feito
está no arquivo — um JSON reescrito no fim perderia tudo.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import util
from guias.modelos import ALTERADO, ANEXO_PENDENTE, CRIADO, DIVERGE, ERRO

log = util.log(__name__)

NOME_ARQUIVO = "guias_lancadas.jsonl"

#: Estados que significam "o título existe no ERP". Repetir criaria um segundo.
#: `diverge` entra porque gravou (só não bateu na releitura) e `anexo_pendente`
#: porque o que falta é o PDF, não o lançamento. Os nomes vêm de
#: `guias.modelos`: uma segunda cópia deles aqui é uma divergência esperando
#: acontecer, e a divergência faria a trava falhar ABERTA — duplicando título.
FEITOS = (ALTERADO, CRIADO, DIVERGE, ANEXO_PENDENTE)

#: Todos os estados que este módulo conhece. Estado fora daqui é aviso, e não
#: silêncio: a trava falha ABERTA para o que não reconhece, então um estado
#: novo que ninguém registrou aqui vira lançamento duplicado.
CONHECIDOS = FEITOS + (ERRO,)


def caminho_padrao() -> Path:
    return util.pasta_base() / NOME_ARQUIVO


class Registro:
    def __init__(self, caminho: Path, linhas: list[dict]):
        self.caminho = Path(caminho)
        self.linhas = linhas
        self._indice = {}
        for linha in linhas:
            self._indexar(linha)

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Registro":
        caminho = Path(caminho or caminho_padrao())
        linhas = []
        if caminho.exists():
            for crua in caminho.read_text(encoding="utf-8").splitlines():
                crua = crua.strip()
                if not crua:
                    continue
                try:
                    linhas.append(json.loads(crua))
                except ValueError:
                    # Linha truncada por queda no meio da escrita. Perder uma
                    # linha é ruim; perder o arquivo inteiro é pior.
                    log.warning("linha ilegível no registro de guias")
        return cls(caminho, linhas)

    def _chave(self, vip_id: str, anx_id: str, competencia: str) -> tuple:
        return (str(vip_id), str(anx_id), str(competencia))

    def _indexar(self, linha: dict) -> None:
        estado = str(linha.get("estado") or "")
        if estado and estado not in CONHECIDOS:
            log.warning("estado de guia desconhecido no registro: %r — a trava "
                        "não o reconhece e a guia pode ser lançada de novo",
                        estado)
        if estado not in FEITOS:
            return
        self._indice[self._chave(linha.get("vip_id"), linha.get("anx_id"),
                                 linha.get("competencia"))] = linha

    def ja_feito(self, vip_id: str, anx_id: str, competencia: str) -> dict | None:
        """A linha que prova que esta guia já virou título, ou None."""
        return self._indice.get(self._chave(vip_id, anx_id, competencia))

    def anotar(self, **campos) -> None:
        campos.setdefault("quando", dt.datetime.now().isoformat(timespec="seconds"))
        self.linhas.append(campos)
        self._indexar(campos)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho, "a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(campos, ensure_ascii=False) + "\n")
