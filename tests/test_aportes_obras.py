# -*- coding: utf-8 -*-
"""De onde saem as obras da aba Aportes.

Em 12/08/2026 nenhum lançamento entrava. O registro dizia `obras: 0` e depois
"Obra não encontrado no Mais Controle: ... Nada parecido no cadastro — talvez
precise ser criado lá" — mandando procurar no ERP um cadastro que estava lá,
certo, o tempo todo.

A causa não era o cadastro: as obras vinham por GraphQL, cujo host
(`execute-api`) só entra nos cabeçalhos capturados quando o ERP carrega o
FORMULÁRIO de lançamento. Esta aba passa pela tela de PAGAMENTOS, que nunca o
chama. Agora elas saem do REST `work-management/works/detailed`, a MESMA porta
que a aba Contratos usa em produção.
"""
from aportes import mc_catalogos


def catalogos():
    """Um Catalogos sem tocar em navegador: só o índice de obras interessa."""
    c = mc_catalogos.Catalogos.__new__(mc_catalogos.Catalogos)
    c.log = lambda *_a, **_k: None
    return c


REST = [
    {"id": "w1", "name": "CONTROLE DE APORTES E DISTRIBUIÇÕES",
     "status": "IN_PROGRESS"},
    {"id": "w2", "name": "TB 21 QD 51 LT 38"},
]


def test_obras_do_rest_viram_o_indice_por_nome():
    c = catalogos()
    c.definir_obras(REST)
    achada = c.obra("CONTROLE DE APORTES E DISTRIBUIÇÕES")
    assert achada is not None, "a obra do caso real não foi indexada"
    assert achada["id"] == "w1"


def test_o_nome_casa_sem_acento_e_sem_caixa():
    """O nome vem do cadastro do ERP, digitado por gente."""
    c = catalogos()
    c.definir_obras(REST)
    assert c.obra("controle de aportes e distribuicoes")["id"] == "w1"


def test_item_sem_id_ou_sem_nome_nao_entra():
    """Obra pela metade viraria um lançamento com `work.id` vazio — o ERP
    aceitaria e ninguém saberia a qual obra o dinheiro foi."""
    c = catalogos()
    c.definir_obras([{"name": "SEM ID"}, {"id": "w9"}, None, "lixo"])
    assert c.obras == {}


def test_lista_vazia_nao_derruba_e_zera_o_indice():
    """`definir_obras([])` é o caminho do erro: o resto do cadastro ainda
    serve para conferir, e o motivo aparece no registro."""
    c = catalogos()
    c.definir_obras(REST)
    c.definir_obras([])
    assert c.obras == {} and c.obra("TB 21 QD 51 LT 38") is None


def test_status_chega_ao_lancamento():
    """`mc_lancamentos` lê `work.status` — o REST traz, e quando não traz o
    padrão IN_PROGRESS continua valendo."""
    c = catalogos()
    c.definir_obras(REST)
    assert c.obra("CONTROLE DE APORTES E DISTRIBUIÇÕES")["status"] == "IN_PROGRESS"
    assert "status" not in c.obra("TB 21 QD 51 LT 38")
