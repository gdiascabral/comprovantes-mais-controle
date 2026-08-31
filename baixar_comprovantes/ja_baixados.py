# -*- coding: utf-8 -*-
"""O que já foi baixado, para a segunda rodada não trazer tudo de novo.

Rodar o mesmo período duas vezes traz o mesmo comprovante duas vezes. O
desempate de nome (`_1`, `_2`) impede a sobrescrita, então nada se perde — mas
a pasta enche de cópias e o Anexar passa a ver dois comprovantes onde houve um
pagamento. Foi o que aconteceu na primeira rodada de verdade.

**O identificador vem de graça**, e essa é a parte boa: o plano previa extrair
o id fim-a-fim de dentro do PDF, e a API entrega cada um num campo próprio —
`endToEnd` no Pix, `codigoLancamento` na 2ª via do Inter, `idAgendamento` no
Sicoob. Não é preciso abrir arquivo nenhum para saber se ele já veio.

O registro mora na RAIZ da pasta de comprovantes, e não dentro da subpasta do
dia: a pergunta é "eu já baixei este comprovante alguma vez?", e ela atravessa
as rodadas. Guardado na subpasta, cada dia recomeçaria do zero e o arquivo
duplicaria na primeira repetição de período.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ARQUIVO = ".ja-baixados.json"

#: Teto de linhas guardadas. Um ano de trabalho pesado não chega perto disso, e
#: o arquivo é lido inteiro a cada rodada — deixá-lo crescer sem limite
#: transformaria a memória num custo.
TETO = 20000


def chave(origem: str, identificador: str, conta: str = "") -> str:
    """`sicoob:50.019-4:15057364` — o que identifica UM comprovante.

    A origem entra porque nada garante que o `idAgendamento` do Sicoob e o
    `codigoLancamento` do Inter não colidam: são numeradores de bancos
    diferentes, e um acerto por acaso silenciaria um comprovante de verdade.

    A conta entra pelo mesmo motivo, um nível abaixo: o Sicoob numera por
    conta, então o mesmo número pode existir em duas.
    """
    limpo = lambda t: re.sub(r"\s+", "", str(t or ""))       # noqa: E731
    partes = [limpo(origem), limpo(conta), limpo(identificador)]
    return ":".join(p for p in partes if p)


class Registro:
    """Os identificadores já baixados. Nunca levanta.

    Falhar aqui não pode parar um lote: o pior caso de um registro ilegível é
    baixar de novo o que já se tinha — chato, e reversível. O contrário —
    deixar de baixar por causa de um arquivo corrompido — perderia comprovante
    sem ninguém notar.
    """

    def __init__(self, pasta):
        self.caminho = Path(pasta) / ARQUIVO
        self._dados = self._ler()

    def _ler(self) -> dict:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            return dados if isinstance(dados, dict) else {}
        except (OSError, ValueError):
            return {}

    def tem(self, chave_do_item: str) -> bool:
        return bool(chave_do_item) and chave_do_item in self._dados

    def anotar(self, chave_do_item: str, arquivo) -> None:
        if not chave_do_item:
            return
        self._dados[chave_do_item] = {
            "arquivo": Path(arquivo).name,
            "quando": datetime.now().replace(microsecond=0).isoformat(),
        }

    def gravar(self) -> None:
        """Grava no fim do lote, e não a cada item: são dezenas de
        comprovantes, e reescrever o arquivo inteiro a cada um seria pagar o
        preço do histórico em toda linha."""
        if len(self._dados) > TETO:
            # Os mais novos ficam. Comprovante de um ano atrás não vai voltar
            # a ser oferecido por um filtro de período de dias.
            recentes = sorted(self._dados.items(),
                              key=lambda kv: kv[1].get("quando", ""),
                              reverse=True)[:TETO]
            self._dados = dict(recentes)
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            self.caminho.write_text(
                json.dumps(self._dados, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass                         # ver o docstring da classe

    def __len__(self) -> int:
        return len(self._dados)
