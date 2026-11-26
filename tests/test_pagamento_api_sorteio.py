# -*- coding: utf-8 -*-
"""500 lotes sorteados, com quedas e recusas aleatórias e várias rodadas do robô:
nada passa do total aprovado e nenhum item é pago duas vezes."""
import random
from decimal import Decimal

from pagamento_api import executor as ex
from pagamento_api import lote as lt
from pagamento_api.sicoob import ErroSicoob

from test_pagamento_api_executor import DOC, Erp, Livro, _aberto, _item, _rodar


class SicoobSorteado:
    """Pix por chave: o confirmar às vezes cai (sem resposta ou 500) DEPOIS de
    ter pago, às vezes antes. O banco lembra o que de fato pagou."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.pagos: dict[str, int] = {}
        self.chamadas = []

    def pix_iniciar(self, chave):
        return {"endToEndId": f"E{self.rnd.random()}", "proprietario": {"identificador": DOC}}

    def pix_confirmar(self, e2e, valor, descricao):
        sorte = self.rnd.random()
        if sorte < 0.2:
            raise ErroSicoob(400, "recusado antes de pagar")
        self.pagos[e2e] = self.pagos.get(e2e, 0) + 1
        if sorte < 0.4:
            raise ErroSicoob(None if sorte < 0.3 else 500, "caiu depois de pagar")
        return {"estado": "REALIZADO"}

    def pix_consultar(self, e2e):
        return {"estado": "REALIZADO" if e2e in self.pagos else "NAO_REALIZADO"}


def test_sorteio_total_e_dobra(tmp_path):
    rnd = random.Random(20261126)
    for rodada in range(500):
        n = rnd.randint(1, 6)
        itens = [_item(i, lt.PIX_CHAVE, valor=f"{rnd.randint(1, 50000) / 100:.2f}") for i in range(1, n + 1)]
        soma = sum(i.valor for i in itens)
        total = (soma * Decimal(rnd.choice(["0.3", "0.7", "1"]))).quantize(Decimal("0.01"))
        s = SicoobSorteado(rnd)
        livro = Livro()
        erp = Erp({i.titulo: _aberto(str(i.valor)) for i in itens})
        for _ in range(3):              # o robô roda de novo depois de cada queda
            _rodar(itens, total, s, erp, tmp_path / str(rodada), livro)
        assert all(v == 1 for v in s.pagos.values()), f"rodada {rodada}: pago em dobro"
        u = ex.ultimos(livro.lista)
        pagos = [i for i in itens if u[i.ordem].estado in (ex.REALIZADO, ex.FALTA_ANEXAR, ex.CONCLUIDO)]
        assert sum((i.valor for i in pagos), Decimal("0")) <= total, f"rodada {rodada}: passou do total"
        assert len(s.pagos) == len(pagos), f"rodada {rodada}: banco e livro discordam"
