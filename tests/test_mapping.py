from conciliacao.models import ErpAccount


def test_mapa_tem_as_24_linhas_do_painel(mapping):
    assert len(mapping.rows) == 24
    assert [r.row for r in mapping.rows] == list(range(8, 32))


def test_tres_linhas_sem_conta_no_erp(mapping):
    assert [r.row for r in mapping.dead_rows] == [28, 30, 31]
    assert len(mapping.live_rows) == 21


def test_match_por_nome(mapping):
    row = mapping.resolve_label("MORAIS ENGENHARIA - INTER")
    assert row is not None and row.row == 8


def test_match_por_numero_vence_rotulo_divergente(mapping):
    """Linha 16: o rotulo do modelo diverge do ERP, o numero e a chave confiavel."""
    row = mapping.resolve_label("Morais Participações - SUBCONTA 55697-1 - QUALQUER OUTRO ROTULO")
    assert row is not None and row.row == 16


def test_match_por_uuid_vence_nome_trocado(mapping):
    """Com UUID preenchido, renomear a conta no ERP nao quebra o match."""
    alvo = mapping.by_row(8)
    object.__setattr__(alvo, "uuid", "uuid-linha-8")
    mapping._build_indexes()

    conta = ErpAccount(id="uuid-linha-8", name="NOME COMPLETAMENTE DIFERENTE")
    assert mapping.resolve_account(conta).row == 8

    object.__setattr__(alvo, "uuid", None)
    mapping._build_indexes()


def test_conta_fora_do_painel_nao_casa_e_e_reconhecida_como_ignorada(mapping):
    label = "PESSOA FISICA - APENAS LANÇAMENTO"
    assert mapping.resolve_label(label) is None
    assert mapping.is_ignored(label)


def test_conta_desconhecida_nao_casa_nem_e_ignorada(mapping):
    """Conta nova no ERP: precisa cair no bucket de alerta, nao ser engolida."""
    label = "EMPREENDIMENTO NOVO XPTO - SICOOB"
    assert mapping.resolve_label(label) is None
    assert not mapping.is_ignored(label)


def test_resolve_label_vazio(mapping):
    assert mapping.resolve_label(None) is None
    assert mapping.resolve_label("") is None
