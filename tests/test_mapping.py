from conciliacao.models import ErpAccount


def test_mapa_cobre_todas_as_linhas_do_painel(mapping, planilha):
    # Uma linha de mapa por linha de conta do painel: sobrar significa
    # mapa apontando para linha que nao existe, e faltar significa conta
    # que nunca recebe saldo.
    assert len(mapping.rows) == len(planilha.linhas)
    assert ([r.row for r in mapping.rows]
            == list(range(planilha.primeira_linha,
                          planilha.ultima_linha + 1)))


def test_as_linhas_sem_conta_no_erp_sao_as_duas_do_inter(mapping):
    # Ipanema e Terra Bela do Inter: as contas foram encerradas, mas a
    # linha fica no painel para o historico do mes nao mudar de forma.
    mortas = [r.row for r in mapping.dead_rows]
    assert mortas == [30, 31]
    assert len(mapping.live_rows) == len(mapping.rows) - len(mortas)


def test_match_por_nome(mapping):
    row = mapping.resolve_label("MORAIS ENGENHARIA - INTER")
    assert row is not None and row.row == 8


def test_match_por_numero_vence_rotulo_divergente(mapping):
    """Linha 16: o rotulo do modelo diverge do ERP, o numero e a chave confiavel."""
    row = mapping.resolve_label("Morais Participações - SUBCONTA 55697-1 - QUALQUER OUTRO ROTULO")
    assert row is not None and row.row == 16


def test_match_por_uuid_vence_nome_trocado(mapping):
    """Com UUID preenchido, renomear a conta no ERP nao quebra o match.

    A fixture `mapping` e de escopo SESSION: sem desfazer a mudanca no
    teardown, um assert falhando aqui deixaria o uuid plantado e derrubaria os
    testes seguintes com erro sem relacao nenhuma com a causa."""
    alvo = mapping.by_row(8)
    anterior = alvo.uuid
    object.__setattr__(alvo, "uuid", "uuid-linha-8")
    mapping._build_indexes()
    try:
        conta = ErpAccount(id="uuid-linha-8", name="NOME COMPLETAMENTE DIFERENTE")
        assert mapping.resolve_account(conta).row == 8
    finally:
        object.__setattr__(alvo, "uuid", anterior)
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
