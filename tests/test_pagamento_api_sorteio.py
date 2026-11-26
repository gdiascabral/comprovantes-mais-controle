# -*- coding: utf-8 -*-
"""800 lotes sorteados (Pix por chave, Pix por QR e boleto), com quedas e
recusas aleatórias antes e DEPOIS de o dinheiro sair, consultas que também
falham, e várias rodadas do robô. Conta-se pelo que o BANCO pagou:
- nenhum item é pago duas vezes;
- o que o banco pagou nunca passa do total aprovado;
- nada que o banco pagou fica marcado como "não pago"."""
import random
from decimal import Decimal

from pagamento_api import executor as ex
from pagamento_api import lote as lt
from pagamento_api.sicoob import ErroSicoob

from test_pagamento_api_executor import DOC, Erp, Livro, _aberto, _item, _rodar


class BancoSorteado:
    def __init__(self, rnd):
        self.rnd = rnd
        self.pagos: dict[int, int] = {}          # ordem do item -> vezes que o dinheiro saiu
        self.por_codigo: dict[str, int] = {}     # e2e/chave -> ordem
        self.ordem_da_chave: dict[str, int] = {}
        self.chamadas = []

    def _sai(self, ordem):
        self.pagos[ordem] = self.pagos.get(ordem, 0) + 1

    def _talvez_caia(self, pagou: bool):
        sorte = self.rnd.random()
        if sorte < 0.25:
            raise ErroSicoob(None if sorte < 0.12 else 500, "caiu" + (" depois de pagar" if pagou else ""))

    # Pix por chave
    def pix_iniciar(self, chave):
        e2e = f"E{self.rnd.random()}"
        self.ordem_da_chave[e2e] = int(chave.split(":")[1])
        return {"endToEndId": e2e, "proprietario": {"identificador": DOC}}

    def pix_confirmar(self, e2e, valor, descricao):
        if self.rnd.random() < 0.15:
            raise ErroSicoob(400, "recusado antes de pagar")
        self._sai(self.ordem_da_chave[e2e])
        self.por_codigo[e2e] = self.ordem_da_chave[e2e]
        self._talvez_caia(True)
        return {"estado": "REALIZADO"}

    def pix_consultar(self, e2e):
        if self.rnd.random() < 0.2:
            raise ErroSicoob(503, "consulta fora")
        return {"estado": "REALIZADO" if e2e in self.por_codigo else "NAO_REALIZADO"}

    # Pix por QR (sem código nosso)
    def pix_qrcode(self, qr, valor, doc):
        ordem = int(qr.split(":")[1])
        if self.rnd.random() < 0.15:
            raise ErroSicoob(400, "recusado antes de pagar")
        self._sai(ordem)
        e2e = f"Q{self.rnd.random()}"
        self.por_codigo[e2e] = ordem
        self._talvez_caia(True)
        return {"estado": "REALIZADO", "endToEndId": e2e}

    # Boleto
    def boleto_consultar(self, codigo, conta):
        return {"valorPagamento": self.valor_de[codigo], "numeroCpfCnpjBeneficiario": DOC}

    def boleto_pagar(self, codigo, conta, consulta, valor, descricao, chave, dia):
        if self.rnd.random() < 0.15:
            raise ErroSicoob(400, "recusado antes de pagar")
        if chave not in self.por_codigo:          # idempotência do banco
            self._sai(self.ordem_de[codigo])
        self.por_codigo[chave] = self.ordem_de[codigo]
        self._talvez_caia(True)
        return {"idPagamento": 1}

    def boleto_comprovante(self, chave):
        if self.rnd.random() < 0.2:
            raise ErroSicoob(503, "consulta fora")
        return {"situacaoPagamento": "EFETIVADO"} if chave in self.por_codigo else {}


def _lote(rnd, n):
    itens, valor_de, ordem_de = [], {}, {}
    for o in range(1, n + 1):
        tipo = rnd.choice([lt.PIX_CHAVE, lt.PIX_QR, lt.BOLETO])
        valor = f"{rnd.randint(1, 50000) / 100:.2f}"
        dados = {lt.PIX_CHAVE: f"chave:{o}", lt.PIX_QR: f"qr:{o}", lt.BOLETO: f"{o:044d}"}[tipo]
        itens.append(_item(o, tipo, valor=valor, dados=dados))
        valor_de[dados], ordem_de[dados] = Decimal(valor), o
    return itens, valor_de, ordem_de


def test_sorteio_pelo_que_o_banco_pagou(tmp_path):
    rnd = random.Random(20261126)
    for rodada in range(800):
        itens, valor_de, ordem_de = _lote(rnd, rnd.randint(1, 6))
        soma = sum(i.valor for i in itens)
        total = (soma * Decimal(rnd.choice(["0.3", "0.7", "1"]))).quantize(Decimal("0.01"))
        banco = BancoSorteado(rnd)
        banco.valor_de, banco.ordem_de = valor_de, ordem_de
        livro = Livro()
        erp = Erp({i.titulo: _aberto(str(i.valor)) for i in itens})
        for _ in range(4):
            _rodar(itens, total, banco, erp, tmp_path / str(rodada), livro)
        assert all(v == 1 for v in banco.pagos.values()), f"rodada {rodada}: pago em dobro"
        pago = sum((i.valor for i in itens if i.ordem in banco.pagos), Decimal("0"))
        assert pago <= total, f"rodada {rodada}: o banco pagou {pago} > aprovado {total}"
        u = ex.ultimos(livro.lista)
        for i in itens:
            if i.ordem in banco.pagos:
                assert u[i.ordem].estado != ex.NAO_PAGO, f"rodada {rodada}: item {i.ordem} pago e marcado não pago"
