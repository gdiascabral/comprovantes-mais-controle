"""A leitura da nuvem do dia: falha da nuvem trava tudo; ERP/registro mudos só tiram provas."""
from datetime import date, datetime
from types import SimpleNamespace

from tela_do_dia import nuvem_do_dia as nd

DIA = HOJE = date(2026, 10, 23)
ABERTO = {"id": 1, "dia": "2026-10-22", "conta": "Conta Alfa - Banco", "alvo": "L1",
          "lancamento_id": "L1", "favorecido": "Fornecedor Modelo Ltda", "valor": "100.00",
          "foto": {"em_aberto": "100.00", "vencimento": "2026-10-22"}}


class _Nuvem:
    def __init__(self, falhar=False, respostas=()):
        self.falhar, self._respostas = falhar, list(respostas)

    def decisoes_do_dia(self, dia):
        if self.falhar:
            raise RuntimeError("HTTP 500")
        return [{"id": 1, "alvo": "L5", "acao": "liberar", "motivo": "ok"}]

    def pagamentos_a_mao(self, dia): return []
    def agendados_do_dia(self, dia): return []
    def agendados_em_aberto(self): return [ABERTO]
    def respostas(self, ids): return [r for r in self._respostas if r["agendado_id"] in ids]
    def nomes_curtos(self): return {"Conta Alfa - Banco": "Alfa"}
    def lista_anterior(self, dia): return [{"conta": "Conta Alfa - Banco", "ordinal": 1}]


class _Api:
    def __init__(self, itens=None, falhar=False):
        self.itens, self.falhar = itens or [], falhar

    def listar_a_pagar(self, ini, fim, log=print):
        if self.falhar:
            raise RuntimeError("sessão caiu")
        return self.itens


def _registro(retorno="ok", gerado_em=datetime(2026, 10, 22, 15, 0), falhar=False):
    def lote(ids, refs):
        if falhar:
            raise RuntimeError("rede")
        envio = SimpleNamespace(retorno_estado=retorno, gerado_em=gerado_em)
        return {}, {"L1": (envio, None)}
    return SimpleNamespace(envios_em_lote=lote)


ABERTO_NO_ERP = [{"id": "L1", "paid": False, "remainingValue": 100.0}]


def test_nuvem_muda_trava_tudo():
    lido = nd.ler(_Nuvem(falhar=True), DIA, HOJE)
    assert lido.erro and not lido.conferencia.decisoes and lido.pendentes == []
    assert nd.ler(None, DIA, HOJE).erro


def test_le_tudo_e_pre_marca_o_pago_no_erp():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api([{"id": "L1", "paid": True}]))
    assert lido.erro == "" and "L5" in lido.conferencia.decisoes
    (_a, sit, resp), = lido.pendentes
    assert sit.pre_marca and resp is None and lido.nomes_curtos == {"Conta Alfa - Banco": "Alfa"}
    assert lido.lista_anterior == [{"conta": "Conta Alfa - Banco", "ordinal": 1}]


def test_erp_mudo_nao_pre_marca_nada_e_avisa():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(falhar=True), registro=_registro())
    assert not lido.pendentes[0][1].pre_marca and lido.avisos
    lido = nd.ler(_Nuvem(), DIA, HOJE, registro=_registro())
    assert not lido.pendentes[0][1].pre_marca and lido.avisos


def test_retorno_ok_vira_prova_quando_o_titulo_nao_mudou():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(ABERTO_NO_ERP), registro=_registro())
    assert lido.pendentes[0][1].prova == "retorno do banco"


def test_retorno_ok_de_remessa_anterior_ao_agendamento_nao_e_prova():
    antiga = _registro(gerado_em=datetime(2026, 10, 21, 23, 59))
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(ABERTO_NO_ERP), registro=antiga)
    assert not lido.pendentes[0][1].pre_marca


def test_retorno_ok_sem_data_comparavel_nao_e_prova():
    sem_data = _registro(gerado_em=None)
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(ABERTO_NO_ERP), registro=sem_data)
    assert not lido.pendentes[0][1].pre_marca


def test_remessa_do_proprio_dia_do_agendamento_vale():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(ABERTO_NO_ERP),
                  registro=_registro(gerado_em=datetime(2026, 10, 22, 0, 0)))
    assert lido.pendentes[0][1].pre_marca


def test_registro_mudo_so_tira_a_prova_e_avisa():
    lido = nd.ler(_Nuvem(), DIA, HOJE, api=_Api(ABERTO_NO_ERP), registro=_registro(falhar=True))
    assert len(lido.pendentes) == 1 and not lido.pendentes[0][1].pre_marca and lido.avisos


def test_resposta_final_tira_dos_pendentes_e_reagendado_continua():
    pago = {"id": 9, "agendado_id": 1, "resposta": "pago"}
    assert nd.ler(_Nuvem(respostas=[pago]), DIA, HOJE, api=_Api(ABERTO_NO_ERP)).pendentes == []
    reag = {"id": 9, "agendado_id": 1, "resposta": "reagendado", "nova_data": "2026-10-25"}
    (_a, _s, resp), = nd.ler(_Nuvem(respostas=[reag]), DIA, HOJE, api=_Api(ABERTO_NO_ERP)).pendentes
    assert resp.resposta == "reagendado"
