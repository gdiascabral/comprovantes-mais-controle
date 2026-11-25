"""A IA lê QUEM EMITIU o papel e confere "quem recebe" (25/11/2026).
Sem rede; nomes e documentos FICTÍCIOS."""
import json

import pytest

from pagamentos_dia import ia_do_dia as ia
from pagamentos_dia import leitura_ia as li
from pagamentos_dia import nivel

CNPJ = "11.222.333/0001-81"
CAMPOS = ("emitente_nome", "emitente_cnpj_cpf", "emitente_telefone")


def _leitura(**k):
    base = {"tipo_papel": "recibo", "legivel": True, "total": "410,00",
            "total_por_extenso": "quatrocentos e dez reais", "ordem_de_compra": "",
            "numero_documento": "", "data": "", "quadra": "", "lote": "", "itens": [],
            "cartao_valor": "", "cartao_nome": "", "duvidas": [],
            "emitente_nome": "Fornecedor Modelo Ltda", "emitente_cnpj_cpf": "",
            "emitente_telefone": ""}
    base.update(k)
    return base


def _item(favorecido="Fornecedor Modelo"):
    return {"id": "L1", "tradePayableId": "T1", "remainingValue": 410.0, "paidTo": favorecido,
            "plannedDate": "2026-11-25"}


F = {"downloadUrl": "https://exemplo.invalid/r.jpg", "filename": "r.jpg"}


def _do_item(leitura, favorecido="Fornecedor Modelo", doc=""):
    e = {"ok": True, "leitura": leitura, "origem": "api", "ids": {"L1"}}
    return ia.leitura_do_item(_item(favorecido), [F], {F["downloadUrl"]: e}, doc_favorecido=doc)


# ------------------------------------------------------------ esquema e cache
def test_esquema_e_instrucao_pedem_o_emitente():
    for c in CAMPOS:
        assert c in li.ESQUEMA["properties"] and c in li.ESQUEMA["required"]
    assert "emitente_nome" in li.INSTRUCAO and "SOMENTE se estiver impresso" in li.INSTRUCAO


def test_validar_aceita_leitura_antiga_sem_os_campos_novos():
    antiga = {k: v for k, v in _leitura().items() if k not in CAMPOS}
    assert li.validar(antiga) is antiga


def test_validar_recusa_campo_novo_que_nao_e_texto():
    with pytest.raises(li.LeituraFalhou):
        li.validar(_leitura(emitente_nome=["x"]))


def test_validar_ainda_exige_os_campos_de_antes():
    ruim = _leitura()
    del ruim["total"]
    with pytest.raises(li.LeituraFalhou):
        li.validar(ruim)


def test_cache_antigo_continua_valido(tmp_path):
    antiga = {k: v for k, v in _leitura().items() if k not in CAMPOS}
    caminho = tmp_path / "c.json"
    caminho.write_text(json.dumps({"k": {"leitura": antiga, "modelo": "m", "quando": "q"}}),
                       encoding="utf-8")
    assert li.CacheLeituras(caminho).obter("k") == antiga


def test_leitura_antiga_deixa_quem_recebe_nao_conferido():
    antiga = {k: v for k, v in _leitura().items() if k not in CAMPOS}
    r = _do_item(antiga)
    assert r["quem_recebe"] == "não conferido" and r["emitente"] == ""


# ------------------------------------------------------------ leitura_do_item
def test_item_traz_o_emitente_e_o_estado():
    r = _do_item(_leitura(emitente_telefone="(62) 5555-0000"))
    assert (r["emitente"], r["quem_recebe"], r["quem_recebe_por"]) == (
        "Fornecedor Modelo Ltda", "bate", "nome")
    assert r["emitente_telefone"] == "(62) 5555-0000"


def test_item_bate_forte_pelo_documento_do_cadastro():
    r = _do_item(_leitura(emitente_nome="Nome Escrito Diferente", emitente_cnpj_cpf=CNPJ),
                 doc="11222333000181")
    assert (r["quem_recebe"], r["quem_recebe_por"]) == ("bate", "cnpj/cpf")


def test_item_diverge_com_motivo():
    r = _do_item(_leitura(emitente_nome="Loja Beta"))
    assert r["quem_recebe"] == "diverge"
    assert r["quem_recebe_motivo"] == "papel emitido por Loja Beta, lançamento para Fornecedor Modelo"


@pytest.mark.parametrize("tipo", ["comprovante_de_pagamento", "comprovante_de_cartao"])
def test_emitente_de_comprovante_de_banco_ou_cartao_nao_vale(tipo):
    r = _do_item(_leitura(tipo_papel=tipo, emitente_nome="Banco Modelo"))
    assert r["quem_recebe"] == "não conferido"


# ------------------------------------------------------------ nível
def _reg(leitura_ia, **k):
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 410.0, "status": "APTO",
            "conferencia": "valor/fornecedor ? (anexo sem texto)", "id": "1",
            "fornecedor_no_anexo": False, "leitura_ia": leitura_ia}
    base.update(k)
    return base


def _ia(**k):
    base = _do_item(_leitura())
    base.update(k)
    return base


def test_valor_e_quem_recebe_provados_pela_ia_tira_de_nao_li_para_olhe():
    n = nivel.nivel_da_linha(_reg(_ia()))
    assert n.nome == nivel.OLHE
    assert dict(n.conferido)["quem recebe"] == nivel.BATE
    assert not any("não conferido" in m for m in n.motivos)


def test_soma_do_papel_que_nao_fecha_tambem_tira_de_nao_li():
    n = nivel.nivel_da_linha(_reg(_ia(estado=li.TOTAL_BATE_SOMA_NAO_FECHA)))
    assert n.nome == nivel.OLHE


def test_nunca_chega_a_pode_pagar():
    for estado in (li.BATE, li.TOTAL_BATE_SOMA_NAO_FECHA):
        assert nivel.nivel_da_linha(_reg(_ia(estado=estado))).nome != nivel.PODE_PAGAR


def test_sem_segunda_prova_nao_prova_quem_recebe():
    n = nivel.nivel_da_linha(_reg(_ia(estado=li.SEM_SEGUNDA_PROVA)))
    assert n.nome == nivel.NAO_LI and "quem recebe não conferido" in n.motivos


def test_emitente_nao_lido_continua_nao_li():
    n = nivel.nivel_da_linha(_reg(_do_item(_leitura(emitente_nome=""))))
    assert n.nome == nivel.NAO_LI and "quem recebe não conferido" in n.motivos


def test_titulo_parcelado_a_ia_nao_melhora():
    n = nivel.nivel_da_linha(_reg(_ia(), total_parcelas=3, parcela={"numero": 1, "total": 3}))
    assert n.nome == nivel.NAO_LI


def test_emitente_diferente_e_olhe_com_o_motivo():
    n = nivel.nivel_da_linha(_reg(_do_item(_leitura(emitente_nome="Loja Beta"))))
    assert n.nome == nivel.OLHE
    assert "papel emitido por Loja Beta, lançamento para Fornecedor Modelo" in n.motivos
    assert dict(n.conferido)["quem recebe"] == nivel.DIVERGE


def test_emitente_diferente_vale_ate_em_parcelado_e_com_quem_recebe_ja_provado():
    r = _reg(_do_item(_leitura(emitente_nome="Loja Beta")), total_parcelas=2,
             parcela={"numero": 1, "total": 2}, conferencia="CNPJ ✓")
    n = nivel.nivel_da_linha(r)
    assert n.nome != nivel.PODE_PAGAR and "quem recebe diverge" in n.motivos


# ------------------------------------------------------------ etiqueta
def test_etiqueta_mostra_o_emitente_lido():
    e = nivel.etiqueta_da_ia(_reg(_do_item(_leitura(emitente_cnpj_cpf=CNPJ,
                                                    emitente_telefone="(62) 5555-0000"))))
    assert any("emitente lido: Fornecedor Modelo Ltda · CNPJ/CPF 11.222.333/0001-81 · "
               "tel. (62) 5555-0000 — quem recebe bate (nome)" in x for x in e["linhas"])


def test_etiqueta_da_divergencia_traz_o_motivo():
    e = nivel.etiqueta_da_ia(_reg(_do_item(_leitura(emitente_nome="Loja Beta"))))
    assert any("quem recebe diverge" in x for x in e["linhas"])
    assert "papel emitido por Loja Beta, lançamento para Fornecedor Modelo" in e["linhas"]


def test_etiqueta_de_leitura_antiga_nao_inventa_emitente():
    antiga = {k: v for k, v in _leitura().items() if k not in CAMPOS}
    e = nivel.etiqueta_da_ia(_reg(_do_item(antiga)))
    assert not any("emitente" in x for x in e["linhas"])


# ------------------------------------------------------------ revisão de dinheiro
def _pix(valor):
    v = f"{valor:.2f}"
    return ("00020126330014br.gov.bcb.pix0111fulano@x.br52040000530398654"
            f"{len(v):02d}{v}5802BR5905MODEL6007GOIANIA6304ABCD")


def test_valor_provado_pelo_pix_e_quem_recebe_so_pela_ia_nao_chega_a_pode_pagar():
    r = _reg(_do_item(_leitura()), dados=_pix(410.0),
             conferencia="valor/fornecedor ? (anexo sem texto)")
    assert nivel.conferido(r, com_ia=False)["valor"] == nivel.BATE
    n = nivel.nivel_da_linha(r)
    assert n.nome == nivel.OLHE
    assert "quem recebe lido por IA: Fornecedor Modelo Ltda" in n.motivos


def test_quem_recebe_ja_provado_por_outro_caminho_nao_ganha_motivo_da_ia():
    r = _reg(_do_item(_leitura()), dados=_pix(410.0), conferencia="CNPJ ✓")
    n = nivel.nivel_da_linha(r)
    assert not any(m.startswith("quem recebe lido por IA") for m in n.motivos)


def test_escolher_leva_a_divergencia_de_quem_recebe_de_outro_anexo():
    f2 = {"downloadUrl": "https://exemplo.invalid/b.jpg", "filename": "b.jpg"}
    ok = {"ok": True, "leitura": _leitura(), "origem": "api", "ids": {"L1"}}
    ruim = {"ok": True, "leitura": _leitura(emitente_nome="Loja Beta", total_por_extenso=""),
            "origem": "api", "ids": {"L1"}}
    r = ia.leitura_do_item(_item(), [F, f2], {F["downloadUrl"]: ok, f2["downloadUrl"]: ruim})
    assert r["quem_recebe"] == "diverge" and r["emitente"] == "Loja Beta"
    assert "Loja Beta" in r["quem_recebe_motivo"]
