# -*- coding: utf-8 -*-
import copy

import pytest

from leitura_manha import config as cf

BOM = {"ambiente": "producao", "nuvem_email": "robo@exemplo.com", "nuvem_senha": "SENHA-ROBO",
       "pasta": "c:/leitura",
       "empresas": [{"nome": "EMPRESA A",
                     "sicoob": {"client_id": "CID", "cert": ["c.pem", "k.pem"]},
                     "inter": {"client_id": "CI", "client_secret": "SEGREDO-INTER",
                               "cert": ["c.pem", "k.pem"]},
                     "contas": [{"banco": "sicoob", "numero": 123456, "conta_erp": "A - SICOOB"},
                                {"banco": "inter", "conta_erp": "A - INTER"}]}]}


def _com(mudar):
    d = copy.deepcopy(BOM)
    mudar(d)
    return d


def test_arquivo_bom():
    c = cf.de_dict(BOM)
    assert [x.conta_erp for x in c.contas()] == ["A - SICOOB", "A - INTER"]
    assert c.contas()[0].numero == 123456 and c.empresas[0].inter["client_secret"] == "SEGREDO-INTER"


def test_repr_nao_mostra_segredo():
    c = cf.de_dict(BOM)
    assert "SEGREDO" not in repr(c) and "SENHA-ROBO" not in repr(c)


@pytest.mark.parametrize("mudar, trecho", [
    (lambda d: d.update(ambiente="teste"), "ambiente"),
    (lambda d: d["empresas"][0]["contas"][0].update(numero="123456"), "numero"),
    (lambda d: d["empresas"][0]["contas"][0].update(numero=True), "numero"),
    (lambda d: d["empresas"][0]["contas"][1].update(conta_erp="A - SICOOB"), "repetida"),
    (lambda d: d["empresas"][0]["sicoob"].pop("cert"), "exige 'cert'"),
    (lambda d: d["empresas"][0]["inter"].pop("client_secret"), "client_secret"),
    (lambda d: d["empresas"][0]["contas"][1].update(conta_corrente="12-3"), "dígitos"),
    (lambda d: d["empresas"][0]["contas"][0].update(banco="caixa"), "banco"),
    (lambda d: d.pop("nuvem_senha"), "nuvem_senha"),
    (lambda d: d.update(empresas=[]), "sem empresas"),
])
def test_arquivo_ruim_diz_o_campo_sem_o_valor(mudar, trecho):
    with pytest.raises(cf.ConfigInvalida) as e:
        cf.de_dict(_com(mudar))
    assert trecho in str(e.value)
    assert "SEGREDO" not in str(e.value) and "SENHA-ROBO" not in str(e.value)


def test_sandbox_pede_token_fixo_e_dispensa_nuvem():
    c = cf.de_dict({"ambiente": "sandbox", "pasta": "p", "empresas": [
        {"nome": "E", "sicoob": {"client_id": "C", "token_fixo": "T"},
         "contas": [{"banco": "sicoob", "numero": 1, "conta_erp": "X"}]}]})
    assert c.empresas[0].sicoob["token_fixo"] == "T" and c.nuvem_email == ""


def test_arquivo_ilegivel(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(cf.ConfigInvalida, match="não consegui ler"):
        cf.carregar(p)
