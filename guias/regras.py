# -*- coding: utf-8 -*-
"""O cadastro que diz o que fazer com cada documento do calendário.

Mora em `_app/guias_regras.json`, e NÃO no repositório: carrega nome de
fornecedor e de obra, e o repositório é público — a mesma decisão já tomada
para o `contas_sicoob.json`.

Não existe conta bancária aqui. Em todo lançamento do Mais Controle, escolher
a obra já seleciona a conta, e a equipe deixa a que vem (decisão do dono,
21/09/2026). Conta é campo DERIVADO, e cadastro de campo derivado é uma
segunda fonte de verdade esperando divergir.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import util

log = util.log(__name__)

#: A versão que este código entende. Arquivo de versão maior foi escrito por
#: um app mais novo: recusar é melhor que ler metade e lançar com ela.
VERSAO = 1

NOME_ARQUIVO = "guias_regras.json"


class RegraInvalida(RuntimeError):
    """O arquivo de regras não serve. A mensagem é para o usuário final ler."""


def caminho_padrao() -> Path:
    return util.pasta_base() / NOME_ARQUIVO


def _chave(texto: str) -> str:
    return util.sem_acento(str(texto or "")).upper()


def tem_palavra(texto: str, palavra: str) -> bool:
    """Casa PALAVRA INTEIRA, sem acento. "RET" não casa com "RETENCAO".

    Casar por pedaço de palavra já produziu erro neste projeto (o lote 1
    casando com o lote 10); aqui o estrago seria lançar o documento de um
    tipo com a categoria de outro. Pública porque `guias/casamento.sugerir_obra`
    precisa da MESMA regra: duas cópias de um casamento de texto é uma
    divergência esperando acontecer."""
    if not palavra:
        return False
    return re.search(rf"(?<![0-9A-Z]){re.escape(_chave(palavra))}(?![0-9A-Z])",
                     _chave(texto)) is not None


class Regras:
    def __init__(self, caminho: Path, dados: dict):
        self.caminho = Path(caminho)
        self.dados = dados
        self.tipos: list[dict] = list(dados.get("tipos") or [])

    # ------------------------------------------------------------- leitura

    @classmethod
    def carregar(cls, caminho: Path | None = None) -> "Regras":
        caminho = Path(caminho or caminho_padrao())
        if not caminho.exists():
            # Primeiro mês: sem regra, toda guia cai em "você decide", que é
            # o comportamento correto — e não um erro para mostrar na tela.
            return cls(caminho, {"versao": VERSAO, "tipos": []})
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RegraInvalida(f"não deu para ler {caminho.as_posix()}: {e}")
        versao = dados.get("versao")
        if versao != VERSAO:
            raise RegraInvalida(
                f"{caminho.as_posix()} está na versão {versao!r} e este app "
                f"entende a {VERSAO}. Atualize o app.")
        for tipo in dados.get("tipos") or []:
            if "conta" in tipo:
                raise RegraInvalida(
                    f"o tipo {tipo.get('nome')!r} tem \"conta\", e regra de "
                    "lançamento não tem conta bancária: a conta vem da obra. "
                    "Tire o campo do arquivo.")
        return cls(caminho, dados)

    def classificar(self, desc: str) -> dict | None:
        """O tipo cujo `desc_contem` casa com a descrição, ou None."""
        for tipo in self.tipos:
            termos = (tipo.get("quando") or {}).get("desc_contem") or []
            if any(tem_palavra(desc, t) for t in termos):
                return tipo
        return None

    def recorrencia(self, tipo: str, vip_id: str) -> dict:
        """O que já se aprendeu sobre a recorrência deste tipo nesta empresa."""
        for t in self.tipos:
            if t.get("nome") == tipo:
                return dict((t.get("recorrencia") or {}).get(vip_id) or {})
        return {}

    def obra(self, tipo: str, vip_id: str) -> str:
        for t in self.tipos:
            if t.get("nome") == tipo:
                return str((t.get("obra") or {}).get(vip_id) or "")
        return ""

    # ----------------------------------------------------------- aprendizado

    def _tipo(self, nome: str) -> dict:
        for t in self.tipos:
            if t.get("nome") == nome:
                return t
        novo = {"nome": nome, "quando": {"desc_contem": []}}
        self.tipos.append(novo)
        self.dados["tipos"] = self.tipos
        return novo

    def aprender_recorrencia(self, tipo: str, vip_id: str,
                             trade_payable_id: str, obra_id: str = "") -> None:
        """Grava "esta guia é esta recorrência". É o que faz o casamento do mês
        seguinte ser exato, e não adivinhado pelo valor (que muda)."""
        alvo = self._tipo(tipo).setdefault("recorrencia", {})
        alvo[vip_id] = {"trade_payable_id": trade_payable_id, "obra": obra_id}

    def aprender_obra(self, tipo: str, vip_id: str, obra_id: str) -> None:
        self._tipo(tipo).setdefault("obra", {})[vip_id] = obra_id

    def gravar(self) -> None:
        self.dados["versao"] = VERSAO
        self.dados["tipos"] = self.tipos
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(
            json.dumps(self.dados, ensure_ascii=False, indent=1),
            encoding="utf-8")
        log.info("regras de guias gravadas (%d tipos)", len(self.tipos))
