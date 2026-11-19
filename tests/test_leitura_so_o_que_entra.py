"""Leitura das contas escolhidas (aba PF): so se pede ao ERP o anexo e o
detalhe do que vai ser pago, e o tempo de cada etapa fica na leitura.
Lancamentos ficticios, no formato de tests/test_leitura_do_dia.py."""
from datetime import date

from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import regras_pagamento as regras

from test_leitura_do_dia import LEITORES, ApiFalsa, _anexo, _lanc, _sem_cadastro, _sem_nuvem

DIA = date(2026, 10, 21)
PF = "PESSOA FISICA - CONTA MODELO"


class ApiQueAnota(ApiFalsa):
    """Guarda o que foi pedido; `depois` e a lista da SEGUNDA leitura."""

    def __init__(self, lancamentos, depois=None, **k):
        super().__init__(lancamentos, **k)
        self._depois, self.listas = depois, 0
        self.pediu_anexos, self.pediu_detalhes = [], []

    def listar_a_pagar(self, ini, fim, log=print):
        self.listas += 1
        if self.listas > 1 and self._depois is not None:
            return list(self._depois)
        return list(self._lanc)

    def anexos_de_titulos(self, ids, **k):
        self.pediu_anexos.extend(ids)
        return super().anexos_de_titulos(ids, **k)

    def listar_overviews(self, ids, **k):
        self.pediu_detalhes.extend(ids)
        return super().listar_overviews(ids, **k)


def _ler(api, **k):
    return ld.ler_pagamentos(api, DIA, DIA, abrir_historico=_sem_nuvem,
                             carregar_mapas=_sem_cadastro, **LEITORES, **k)


def _dia():
    return [_lanc("L1", conta=PF), _lanc("L2", conta=PF, paid=True, sumOfPaidValues=100.0),
            _lanc("L3"), _lanc("L4", paid=True, sumOfPaidValues=100.0)]


def test_com_contas_escolhidas_so_pede_o_que_vai_ser_pago():
    api = ApiQueAnota(_dia(), anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, contas_escolhidas=[PF])
    assert api.pediu_anexos == ["T-L1"] and api.pediu_detalhes == ["L1"]
    assert [r["id"] for regs in leitura.resultado.contas.values() for r in regs] == ["L1"]
    # A lista inteira continua na leitura (o HTML mostra o que nao entrou).
    assert len(leitura.lancamentos) == 4


def test_sem_contas_escolhidas_le_tudo_como_sempre():
    api = ApiQueAnota(_dia(), anexos={"T-L1": [_anexo("nota 1234")]})
    _ler(api)
    assert sorted(api.pediu_anexos) == ["T-L1", "T-L2", "T-L3", "T-L4"]
    assert sorted(api.pediu_detalhes) == ["L1", "L2", "L3", "L4"]


def test_o_que_virou_a_pagar_no_meio_da_leitura_nao_sai_como_sem_anexo():
    antes = [_lanc("L1", conta=PF), _lanc("L2", conta=PF, paid=True, sumOfPaidValues=100.0)]
    depois = [_lanc("L1", conta=PF), _lanc("L2", conta=PF)]      # a baixa foi desfeita
    api = ApiQueAnota(antes, depois=depois, anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, contas_escolhidas=[PF])
    assert api.pediu_anexos == ["T-L1"]
    assert "T-L2" in leitura.entradas.titulos_nao_lidos
    assert "L2" in leitura.alterados
    motivos = [o.get("motivo") for o in leitura.resultado.omitidos if str(o.get("id")) == "L2"]
    assert regras.MOTIVO_SEM_ANEXO not in motivos


def test_parcela_que_entrou_no_meio_em_titulo_ja_pedido_tambem_e_nao_lida():
    antes = [_lanc("L1", conta=PF),
             _lanc("L2", conta=PF, tradePayableId="T-L1", paid=True, sumOfPaidValues=100.0)]
    depois = [_lanc("L1", conta=PF), _lanc("L2", conta=PF, tradePayableId="T-L1")]
    api = ApiQueAnota(antes, depois=depois, anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, contas_escolhidas=[PF])
    assert api.pediu_detalhes == ["L1"]                      # o detalhe da L2 nao veio
    assert "T-L1" in leitura.entradas.titulos_nao_lidos


def test_o_tempo_de_cada_etapa_fica_na_leitura():
    tiques = iter(range(0, 1000, 5))
    api = ApiQueAnota(_dia(), anexos={"T-L1": [_anexo("nota 1234")]})
    leitura = _ler(api, relogio=lambda: next(tiques))
    assert list(leitura.tempos) == ["lista", "anexos e detalhes", "contatos",
                                    "baixar e ler anexos", "conferir a lista", "apurar"]
    assert all(v == 5 for v in leitura.tempos.values())
    assert "lista 5 s" in ld.resumo_dos_tempos(leitura.tempos)


def test_leitura_interrompida_guarda_o_tempo_ate_ali():
    api = ApiQueAnota(_dia())
    leitura = _ler(api, cancelar=lambda: True)
    assert leitura.interrompida and "lista" in leitura.tempos
