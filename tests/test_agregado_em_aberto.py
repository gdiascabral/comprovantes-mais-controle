# -*- coding: utf-8 -*-
"""Testes da leitura do total "Em aberto" do mês na tela de pagamentos.

Caso real de 01/09/2026: a planilha do dia não saiu porque a validação acusou
"total de hoje (R$ 97.774,68) passou do 'Em aberto' do mês (R$ 45,50) — a
coleta provavelmente duplicou linhas". A coleta estava perfeita: 75 linhas, 75
ids distintos, todas vencendo em 01/09.

O R$ 45,50 não era o total do mês — era o valor da PRIMEIRA LINHA da grade. A
busca varria o `innerText` do corpo inteiro e parava na primeira ocorrência de
"Em aberto ... R$ x", e toda linha da grade escreve exatamente isso:

    01/09/2026 | Em aberto | R$ 45,50 | Reembolso ...

Funcionou até 31/08 por acaso, só porque o cartão de totais costuma renderizar
antes da grade. Naquele dia ele não tinha chegado ainda — no mesmo instante em
que o dropdown de status também não respondeu.
"""
from decimal import Decimal

from conciliacao.erp.payments import (
    _JS_TEXTO_FORA_DA_GRADE,
    extrair_agregado_em_aberto,
    ler_agregado_em_aberto,
)

#: Como o cartão de totais aparece no texto da tela.
CARTAO = "Pagamentos Total do mês Em aberto R$ 316.509,77 Pago R$ 84.201,10"

#: Como uma linha da grade aparece. É o texto que NÃO pode chegar à extração.
LINHA_DA_GRADE = "01/09/2026 Em aberto R$ 45,50 Reembolso Eng Guilherme Gouveia"


class PaginaFalsa:
    """Página de mentira: devolve um texto por chamada de `evaluate`."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.esperas = 0

    def evaluate(self, _js):
        # Depois da última resposta, repete a última (tela que nunca carrega).
        return self.respostas.pop(0) if len(self.respostas) > 1 \
            else self.respostas[0]

    def wait_for_timeout(self, _ms):
        self.esperas += 1  # nenhum teste dorme de verdade


def test_le_o_total_do_cartao():
    assert extrair_agregado_em_aberto(CARTAO) == Decimal("316509.77")


def test_sem_total_na_tela_devolve_nada():
    assert extrair_agregado_em_aberto("Pagamentos Total do mês — —") is None
    assert extrair_agregado_em_aberto("") is None
    assert extrair_agregado_em_aberto(None) is None


def test_a_grade_fica_fora_da_busca():
    """A defesa contra 01/09 é estrutural: a grade nem entra no texto.

    A extração é uma regex e, se a linha da grade chegar até ela, ela casa —
    como casou naquele dia. Quem impede isso é o JS, e é ele que este teste
    guarda: se alguém tirar os papéis da grade da lista, o total volta a poder
    ser o valor de uma linha qualquer.
    """
    for papel in ("[role=grid]", "[role=row]", "[role=gridcell]"):
        assert papel in _JS_TEXTO_FORA_DA_GRADE

    # E a prova de que a regex sozinha não protege: entregue a linha a ela e
    # sai o R$ 45,50 do dia real.
    assert extrair_agregado_em_aberto(LINHA_DA_GRADE) == Decimal("45.50")


def test_total_que_nao_chega_vira_nada_e_nunca_outro_numero():
    """A propriedade que teria salvado o dia 01/09.

    `validate.py` só dispensa a conferência cruzada quando o agregado é None.
    Devolver um número em que não dá para confiar não deixa a conferência
    fraca: deixa ela ERRADA, barrando um dia inteiro que estava correto.
    """
    recados = []
    pagina = PaginaFalsa(["Pagamentos Total do mês carregando..."])

    assert ler_agregado_em_aberto(pagina, timeout_s=0, log=recados.append) is None
    assert any("nao achei" in r for r in recados)


def test_espera_o_cartao_de_totais_chegar():
    """O cartão carrega por conta própria e pode chegar depois da grade."""
    recados = []
    pagina = PaginaFalsa(["Pagamentos Total do mês", "", CARTAO])

    valor = ler_agregado_em_aberto(pagina, timeout_s=30, log=recados.append)

    assert valor == Decimal("316509.77")
    assert pagina.esperas == 2
    assert any("316.509,77" in r for r in recados)


def test_tela_que_explode_na_leitura_nao_derruba_a_coleta():
    """Ler o total é conferência, não é a coleta. Falhar aqui vira None."""

    class PaginaQuebrada(PaginaFalsa):
        def evaluate(self, _js):
            raise RuntimeError("Execution context was destroyed")

    pagina = PaginaQuebrada([""])
    assert ler_agregado_em_aberto(pagina, timeout_s=0, log=lambda _m: None) is None
