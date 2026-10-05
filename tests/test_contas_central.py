import json

from nuvem import contas_central as cc


def _cru(i, ativa=True):
    return {"id": f"u-{i}", "name": f"EMPRESA MODELO - CONTA NOVA FICTICIA {i:02d}",
            "isActive": ativa, "bankCode": "756", "agency": "1234",
            "account": f"{90000 + i}", "accountDigit": "1"}


def _cadastro(pasta, nomes):
    (pasta / "contas_mc.json").write_text(json.dumps(
        {"contas": [{"erp": n} for n in nomes]}), encoding="utf-8")


def test_guarda_e_le_a_lista(tmp_path):
    assert cc.guardar_lista([_cru(2), _cru(1)], tmp_path)
    lista = cc.ler_lista(tmp_path)
    assert [c["id"] for c in lista] == ["u-1", "u-2"]
    assert lista[0] == {"id": "u-1",
                        "nome": "EMPRESA MODELO - CONTA NOVA FICTICIA 01",
                        "banco": "756", "agencia": "1234", "numero": "90001-1"}


def test_lista_vazia_nunca_apaga_a_que_estava(tmp_path):
    cc.guardar_lista([_cru(1)], tmp_path)
    assert cc.guardar_lista([], tmp_path) is False
    assert cc.guardar_lista([{"id": "", "name": ""}], tmp_path) is False
    assert [c["id"] for c in cc.ler_lista(tmp_path)] == ["u-1"]


def test_sem_arquivo_a_lista_e_vazia(tmp_path):
    assert cc.ler_lista(tmp_path) == []


def test_sem_painel_so_pergunta_pelo_cadastro(tmp_path):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    pend = cc.pendencias([_cru(1), _cru(2)], tmp_path, pasta_painel=tmp_path)
    assert [(p.nome, p.falta_cadastro, p.falta_painel) for p in pend] == [
        ("EMPRESA MODELO - CONTA NOVA FICTICIA 02", True, False)]


def test_conta_inativa_nao_e_pendencia(tmp_path):
    _cadastro(tmp_path, [])
    assert cc.pendencias([_cru(1, ativa=False)], tmp_path,
                         pasta_painel=tmp_path) == []


class _MapaDuble:
    """Casa pelo id: as contas em `no_painel` têm linha viva."""

    def __init__(self, no_painel):
        self.no_painel = set(no_painel)


def test_cadastro_e_painel_se_juntam_por_conta(tmp_path, monkeypatch):
    _cadastro(tmp_path, ["EMPRESA MODELO - CONTA NOVA FICTICIA 01"])
    mapa = _MapaDuble({"u-2"})
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: mapa)
    monkeypatch.setattr(
        cc, "_fora_do_painel",
        lambda contas, m: [c for c in contas if c.id not in m.no_painel])
    pend = {p.erp.id: p for p in cc.pendencias([_cru(1), _cru(2), _cru(3)],
                                               tmp_path, tmp_path)}
    assert (pend["u-1"].falta_cadastro, pend["u-1"].falta_painel) == (False, True)
    assert (pend["u-2"].falta_cadastro, pend["u-2"].falta_painel) == (True, False)
    assert (pend["u-3"].falta_cadastro, pend["u-3"].falta_painel) == (True, True)
    assert pend["u-3"].falta_em == "cadastro e painel"
    assert pend["u-1"].falta_em == "painel"
    assert pend["u-3"].rotulo == "EMPRESA MODELO - CONTA NOVA FICTICIA 03"


def test_ignorada_no_mapping_nao_e_pendencia_de_cadastro(tmp_path):
    _cadastro(tmp_path, [])
    (tmp_path / "mapping.yaml").write_text(
        "ignored_erp_accounts:\n  - CONTA NOVA FICTICIA 01\n", encoding="utf-8")
    pend = cc.pendencias([_cru(1)], tmp_path, pasta_painel=tmp_path)
    assert pend == []
