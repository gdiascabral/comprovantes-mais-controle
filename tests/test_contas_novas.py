# -*- coding: utf-8 -*-
"""Conta nova no ERP: a conferência que roda na abertura do app.

Sem rede e sem navegador. O que se prova aqui é que a pergunta certa é feita
(e só ela), que a resposta grava no NOSSO cadastro com os campos que o banco
exige, e que nada disso pode impedir o app de abrir.
"""
import json

import pytest

from nuvem import contas_novas as conferencia


@pytest.fixture(autouse=True)
def _cadastro_sem_rede(monkeypatch):
    """`gravar` lê as contas já cadastradas para desempatar a pasta. Nenhum
    teste daqui fala com o banco de verdade: sem outra ordem, o cadastro
    existente é vazio."""
    monkeypatch.setattr(conferencia.rest, "ler", lambda *_a, **_k: [])


def conta_erp(nome, ativa=True, id_erp="uuid-1", banco=None,
              agencia=None, agencia_dv=None, numero="58123", numero_dv="4"):
    """Uma conta CRUA, no formato exato que `listar_contas` devolve.

    Medido contra o ERP em 21/08/2026. Os testes anteriores usavam um objeto
    com `name`/`is_active` — o formato do `ErpAccount`, que a produção NÃO
    usa neste ponto — e por isso passavam enquanto o app abria sem perguntar
    nada. Teste com o formato de quem fala do outro lado, ou ele não prova.
    """
    return {"id": id_erp, "name": nome, "isActive": ativa,
            "bankCode": banco, "agency": agencia, "agencyDigit": agencia_dv,
            "account": numero, "accountDigit": numero_dv}


# ------------------------------------------------------------- comparação
def test_conta_que_o_ERP_tem_e_o_cadastro_nao_e_novidade():
    novas = conferencia.comparar([conta_erp("MORAIS ENG - SUBCONTA 58123-4")],
                                 {"OUTRA CONTA"})
    assert [c.nome for c in novas] == ["MORAIS ENG - SUBCONTA 58123-4"]
    assert novas[0].numero == "58123-4"


def test_o_numero_vem_partido_e_e_remontado():
    """O ERP manda `account` e `accountDigit` separados."""
    nova, = conferencia.comparar([conta_erp("X", numero="5969", numero_dv="3")],
                                 set())
    assert nova.numero == "5969-3"


def test_campo_nulo_do_ERP_nao_vira_a_palavra_None():
    """`bankCode` e `agency` vêm nulos na maioria das contas."""
    nova, = conferencia.comparar([conta_erp("X")], set())
    assert nova.banco == "" and nova.agencia == ""


def test_conta_ja_cadastrada_nao_pergunta():
    novas = conferencia.comparar([conta_erp("CONTA X")], {"CONTA X"})
    assert novas == []


def test_acento_e_caixa_nao_criam_novidade_falsa():
    """Sem a régua normalizada, a janela perguntaria todo dia pela mesma."""
    ja = {conferencia.util.norm_espaco("Morais Participações - SUBCONTA 1")}
    novas = conferencia.comparar(
        [conta_erp("MORAIS PARTICIPACOES - SUBCONTA 1")], ja)
    assert novas == []


def test_conta_inativa_no_ERP_fica_de_fora():
    """Perguntar sobre conta que ninguém usa mais é ruído."""
    assert conferencia.comparar([conta_erp("VELHA", ativa=False)], set()) == []


def test_a_mesma_conta_duas_vezes_pergunta_uma_vez():
    novas = conferencia.comparar([conta_erp("REPETIDA"), conta_erp("REPETIDA")],
                                 set())
    assert len(novas) == 1


def test_listas_vazias_nao_estouram():
    assert conferencia.comparar([], set()) == []
    assert conferencia.comparar(None, set()) == []


def test_o_caminho_INTEIRO_com_o_payload_do_ERP(monkeypatch, tmp_path):
    """A costura que faltava: `contas_do_erp` -> `comparar` -> lista.

    Era exatamente aqui que o defeito morava — cada metade certa, e o encontro
    das duas devolvendo vazio.
    """
    (tmp_path / "contas_mc.json").write_text(
        '{"contas": [{"erp": "CONTA VELHA"}]}', encoding="utf-8")
    monkeypatch.setattr(conferencia, "contas_do_erp",
                        lambda log=print: [conta_erp("CONTA VELHA"),
                                           conta_erp("CONTA NOVA")])
    novas = conferencia.novidades(tmp_path, log=lambda _m: None)
    assert [c.nome for c in novas] == ["CONTA NOVA"]


def test_conta_na_lista_de_ignorados_nao_pergunta():
    """A lista `ignored_erp_accounts` do painel ja existia, e a janela nao a
    conhecia: das 15 contas que ela mostrou em 21/08/2026, sete eram decisao
    ja tomada ha meses."""
    ignorar = [conferencia.util.norm_espaco("RENATO - PAGBANK")]
    assert conferencia.comparar([conta_erp("RENATO - PAGBANK")], set(),
                                ignorar) == []


def test_o_ignorado_casa_por_PEDACO():
    """"APENAS AJUSTE DE CAIXA" cobre a conta da Morais e a da Buritis."""
    ignorar = [conferencia.util.norm_espaco("APENAS AJUSTE DE CAIXA")]
    contas = [conta_erp("MORAIS ENGENHARIA - (APENAS AJUSTE DE CAIXA)"),
              conta_erp("MORAIS EMPREENDIMENTOS BURITIS - APENAS AJUSTE DE CAIXA")]
    assert conferencia.comparar(contas, set(), ignorar) == []


def test_sem_lista_de_ignorados_nada_muda():
    nova, = conferencia.comparar([conta_erp("QUALQUER")], set(), [])
    assert nova.nome == "QUALQUER"


def test_le_os_ignorados_do_mapping(tmp_path):
    (tmp_path / "mapping.yaml").write_text(
        "model_rows: []\n"
        "ignored_erp_accounts:\n"
        "- RENATO - PAGBANK\n"
        "- Cartao de Credito\n", encoding="utf-8")
    lidos = conferencia.ignorados(tmp_path)
    assert conferencia.util.norm_espaco("RENATO - PAGBANK") in lidos
    assert conferencia.util.norm_espaco("CARTAO DE CREDITO") in lidos


def test_sem_o_mapping_nao_ignora_nada_e_nao_estoura(tmp_path):
    assert conferencia.ignorados(tmp_path) == []


# ------------------------------------------------------------ nosso lado
def test_le_os_nomes_do_cadastro_local(tmp_path):
    (tmp_path / "contas_mc.json").write_text(json.dumps(
        {"raiz": "x", "contas": [{"erp": "CONTA A"}, {"erp": "Conta B"}]}),
        encoding="utf-8")
    nomes = conferencia.nomes_cadastrados(tmp_path)
    assert conferencia.util.norm_espaco("conta a") in nomes
    assert conferencia.util.norm_espaco("CONTA B") in nomes


def test_sem_o_arquivo_o_cadastro_e_vazio_e_nao_estoura(tmp_path):
    """Máquina nova, antes da primeira sincronização."""
    assert conferencia.nomes_cadastrados(tmp_path) == set()


def test_a_pasta_nasce_sugerida_a_partir_do_nome():
    """Campo vazio custou quatro recusas de uma vez: o dono marcou as quatro
    contas, nao preencheu a pasta e o app recusou as quatro."""
    nova, = conferencia.comparar(
        [conta_erp("Morais Participações - SUBCONTA 59584-5 - LUIZ F - SICOOB")],
        set())
    assert nova.pasta_sugerida == "SUBCONTA 59584-5 - LUIZ F - SICOOB"


def test_nome_sem_prefixo_sugere_ele_mesmo():
    nova, = conferencia.comparar([conta_erp("CONTA PRINCIPAL")], set())
    assert nova.pasta_sugerida == "CONTA PRINCIPAL"


# ------------------------------------------------------------- validação
def test_marcada_sem_pasta_nao_grava():
    """`pasta` é not null: mandar vazio trocaria a pergunta por erro de SQL."""
    assert conferencia.validar({"nome_erp": "X", "empresa_id": 1, "pasta": " "})


def test_marcada_sem_empresa_nao_grava():
    assert conferencia.validar({"nome_erp": "X", "pasta": "SICOOB"})


def test_escolha_completa_passa():
    assert conferencia.validar(
        {"nome_erp": "X", "empresa_id": 1, "pasta": "SICOOB"}) == ""


# -------------------------------------------------------------- gravação
def test_grava_no_nosso_cadastro_com_os_campos_do_banco(monkeypatch):
    gravadas = {}

    def falso_inserir(tabela, token, linhas, **_kw):
        gravadas["tabela"], gravadas["linhas"] = tabela, linhas

    monkeypatch.setattr(conferencia.rest, "inserir", falso_inserir)
    avisos = conferencia.gravar("tok", [{
        "nome_erp": "MORAIS ENG - SUBCONTA 58123-4", "empresa_id": 7,
        "pasta": "SICOOB 58123-4", "banco": "756", "agencia": "3299",
        "numero": "58123-4"}])
    assert avisos == []
    assert gravadas["tabela"] == "conta"
    linha, = gravadas["linhas"]
    assert linha["nome_erp"] == "MORAIS ENG - SUBCONTA 58123-4"
    assert linha["empresa_id"] == 7 and linha["pasta"] == "SICOOB 58123-4"


def test_a_incompleta_vira_aviso_e_a_boa_grava(monkeypatch):
    """Uma escolha pela metade não pode derrubar as outras."""
    linhas = {}
    monkeypatch.setattr(conferencia.rest, "inserir",
                        lambda t, tok, ls, **k: linhas.setdefault("ls", ls))
    avisos = conferencia.gravar("tok", [
        {"nome_erp": "SEM PASTA", "empresa_id": 1, "pasta": ""},
        {"nome_erp": "BOA", "empresa_id": 1, "pasta": "P"}])
    assert len(avisos) == 1 and "SEM PASTA" in avisos[0]
    assert [l["nome_erp"] for l in linhas["ls"]] == ["BOA"]


def test_nada_escolhido_nao_chama_o_banco(monkeypatch):
    def nao_deveria(*_a, **_k):
        raise AssertionError("chamou o banco sem ter o que gravar")

    monkeypatch.setattr(conferencia.rest, "inserir", nao_deveria)
    assert conferencia.gravar("tok", []) == []


def test_a_gravacao_nunca_apaga(monkeypatch):
    """A decisão de 14/08 muda no mínimo: insere sim, apaga nunca."""
    def nao_deveria(*_a, **_k):
        raise AssertionError("a conferência tentou APAGAR cadastro")

    monkeypatch.setattr(conferencia.rest, "apagar", nao_deveria)
    monkeypatch.setattr(conferencia.rest, "inserir", lambda *a, **k: None)
    conferencia.gravar("tok", [{"nome_erp": "X", "empresa_id": 1, "pasta": "P"}])


# ----------------------------------------------------- falha não derruba
def test_erro_ao_falar_com_o_ERP_devolve_vazio_e_nao_levanta(monkeypatch):
    """Isto roda na ABERTURA do app: nada aqui pode impedir o app de abrir.

    Sem rede, login vencido, MFA ligado ou contrato mudado — o desfecho é o
    mesmo: uma linha no log e lista vazia. É a mesma regra que já protege o
    `sincronizar`, logo acima desta chamada.
    """
    def explode():
        raise OSError("sem rede")

    recados = []
    monkeypatch.setattr(conferencia, "_ConfigMinimo", explode)
    assert conferencia.contas_do_erp(log=recados.append) == []
    assert any("ERP" in r for r in recados)


def test_sem_contas_do_ERP_nao_ha_o_que_perguntar(monkeypatch):
    monkeypatch.setattr(conferencia, "contas_do_erp", lambda log=print: [])
    assert conferencia.novidades(log=lambda _m: None) == []


# ----------------------------------------- pessoa física e empresa sugerida
def test_conta_de_pessoa_fisica_vai_para_a_pasta_unica():
    """Regra do dono (11/09/2026): NEXT, PAGBANK e NEON são de pessoa física."""
    for nome in ("FULANO DE TAL - NEXT", "BELTRANA - PAGBANK", "SICRANO - NEON"):
        nova, = conferencia.comparar([conta_erp(nome)], set())
        assert nova.pasta_sugerida == conferencia.PASTA_DE_PESSOA


def test_pessoa_fisica_sugere_a_empresa_das_pessoas_fisicas():
    """Casa sem acento e sem caixa, como todo nome aqui."""
    nova, = conferencia.comparar([conta_erp("FULANO DE TAL - PAGBANK")], set())
    assert nova.empresa_sugerida(["EMPRESA X", "Pessoas Fisicas"]) == "Pessoas Fisicas"


def test_sem_a_empresa_das_pessoas_fisicas_no_cadastro_nao_sugere():
    nova, = conferencia.comparar([conta_erp("FULANO - NEON")], set())
    assert nova.empresa_sugerida(["EMPRESA X"]) == ""


def test_banco_de_pessoa_casa_por_palavra_inteira():
    """"NEXT" dentro de outra palavra não faz a conta ser de pessoa."""
    nova, = conferencia.comparar([conta_erp("EMPRESA X - NEXTEL")], set())
    assert conferencia.banco_de_pessoa(nova.nome) == ""
    assert nova.pasta_sugerida == "NEXTEL"


def test_a_empresa_sugerida_e_a_que_abre_o_nome_da_conta():
    nova, = conferencia.comparar([conta_erp("EMPRESA CAÇULA SPE - SICOOB")], set())
    assert nova.empresa_sugerida(["EMPRESA X", "Empresa Cacula"]) == "Empresa Cacula"


def test_entre_duas_que_abrem_o_nome_fica_a_mais_comprida():
    nova, = conferencia.comparar([conta_erp("EMPRESA X SPE - SICOOB")], set())
    assert nova.empresa_sugerida(["EMPRESA", "EMPRESA X"]) == "EMPRESA X"


def test_pedaco_de_palavra_nao_abre_o_nome():
    """"EMPRESA X" não abre "EMPRESA XINGU": a comparação é por palavra."""
    nova, = conferencia.comparar([conta_erp("EMPRESA XINGU - SICOOB")], set())
    assert nova.empresa_sugerida(["EMPRESA X"]) == ""


def test_nome_sem_prefixo_nao_sugere_empresa():
    nova, = conferencia.comparar([conta_erp("CONTA PRINCIPAL")], set())
    assert nova.empresa_sugerida(["CONTA PRINCIPAL"]) == ""


# ----------------------------------------------------------- número no nome
def test_sem_numero_no_ERP_o_numero_sai_do_nome():
    """Sem número a conta fica fora do `contas_sicoob.json`, e o extrato do
    Sicoob dela nunca é baixado — sem erro nenhum."""
    nova, = conferencia.comparar(
        [conta_erp("EMPRESA X SPE - SICOOB 12.345-6", numero=None,
                   numero_dv=None)], set())
    assert nova.numero == "12.345-6"


def test_numero_sem_ponto_no_nome_tambem_serve():
    nova, = conferencia.comparar(
        [conta_erp("EMPRESA X - SUBCONTA 12345-6 - SICOOB", numero=None,
                   numero_dv=None)], set())
    assert nova.numero == "12345-6"


def test_o_numero_do_ERP_ganha_do_nome():
    nova, = conferencia.comparar(
        [conta_erp("EMPRESA X - SICOOB 12.345-6", numero="99999",
                   numero_dv="1")], set())
    assert nova.numero == "99999-1"


def test_dois_numeros_no_nome_nao_se_escolhem():
    assert conferencia.numero_no_nome("EMPRESA X - 12345-6 E 65432-1") == ""


def test_quadra_e_lote_nao_viram_numero():
    assert conferencia.numero_no_nome("SUBCONTA - TB 21 QD 51 LT 40 - SICOOB") == ""


# ------------------------------------------------ banco e sufixo na gravação
def _capturar(monkeypatch, existentes=()):
    gravadas = {}
    monkeypatch.setattr(conferencia.rest, "inserir",
                        lambda t, tok, ls, **k: gravadas.setdefault("linhas", ls))
    monkeypatch.setattr(conferencia.rest, "ler",
                        lambda *_a, **_k: list(existentes))
    return gravadas


def test_codigo_do_banco_vira_nome_e_o_codigo_vai_para_a_coluna_dele(monkeypatch):
    """"756" em `banco` fazia o extrato sair `202607 756 MAIS CONTROLE.pdf`."""
    gravadas = _capturar(monkeypatch)
    conferencia.gravar("tok", [{"nome_erp": "X", "empresa_id": 1,
                                "pasta": "SICOOB", "banco": "756"}])
    linha, = gravadas["linhas"]
    assert (linha["banco"], linha["banco_codigo"]) == ("SICOOB", "756")


def test_codigo_desconhecido_fica_como_veio(monkeypatch):
    gravadas = _capturar(monkeypatch)
    conferencia.gravar("tok", [{"nome_erp": "X", "empresa_id": 1,
                                "pasta": "P", "banco": "999"}])
    linha, = gravadas["linhas"]
    assert (linha["banco"], linha["banco_codigo"]) == ("999", "999")


def test_conta_de_pessoa_sem_banco_leva_o_banco_do_nome(monkeypatch):
    gravadas = _capturar(monkeypatch)
    conferencia.gravar("tok", [{"nome_erp": "FULANO - PAGBANK", "empresa_id": 1,
                                "pasta": "PESSOA FÍSICA", "banco": ""}])
    linha, = gravadas["linhas"]
    assert (linha["banco"], linha["banco_codigo"]) == ("PAGBANK", "")


LOTE_MISTO = [
    {"nome_erp": "FULANO - NEXT", "empresa_id": 9, "pasta": "PESSOA FÍSICA"},
    {"nome_erp": "BELTRANA - PAGBANK", "empresa_id": 9, "pasta": "pessoa fisica "},
    {"nome_erp": "EMPRESA X - SICOOB", "empresa_id": 1, "pasta": "SICOOB"},
]


def test_varias_na_mesma_pasta_ganham_sufixo(monkeypatch):
    """Sem o sufixo o banco recusava o lote INTEIRO (`conta_destino_unico`),
    e com ele os arquivos das contas não passam um por cima do outro."""
    gravadas = _capturar(monkeypatch)
    assert conferencia.gravar("tok", [dict(e) for e in LOTE_MISTO]) == []
    sufixos = {l["nome_erp"]: l["sufixo"] for l in gravadas["linhas"]}
    assert sufixos == {"FULANO - NEXT": "FULANO - NEXT",
                       "BELTRANA - PAGBANK": "BELTRANA - PAGBANK",
                       "EMPRESA X - SICOOB": ""}


def test_toda_linha_do_lote_leva_as_mesmas_chaves(monkeypatch):
    """O PostgREST recusa INSERT em massa com objetos de chaves diferentes."""
    gravadas = _capturar(monkeypatch)
    conferencia.gravar("tok", [dict(e) for e in LOTE_MISTO])
    assert len({tuple(sorted(l)) for l in gravadas["linhas"]}) == 1


def test_pasta_que_ja_tem_conta_sem_sufixo_desempata(monkeypatch):
    gravadas = _capturar(monkeypatch, existentes=[
        {"empresa_id": 1, "pasta": "SICOOB", "sufixo": ""}])
    conferencia.gravar("tok", [{"nome_erp": "EMPRESA X - SICOOB 2",
                                "empresa_id": 1, "pasta": "Sicoob"}])
    assert gravadas["linhas"][0]["sufixo"] == "EMPRESA X - SICOOB 2"


def test_a_mesma_pasta_em_outra_empresa_nao_desempata(monkeypatch):
    gravadas = _capturar(monkeypatch, existentes=[
        {"empresa_id": 2, "pasta": "SICOOB", "sufixo": ""}])
    conferencia.gravar("tok", [{"nome_erp": "EMPRESA X - SICOOB",
                                "empresa_id": 1, "pasta": "SICOOB"}])
    assert gravadas["linhas"][0]["sufixo"] == ""


def test_sem_ler_o_cadastro_o_lote_ainda_se_desempata(monkeypatch):
    """Falhar a leitura não pode derrubar a gravação: o desempate do lote
    continua valendo, e o banco segue sendo quem recusa o resto."""
    gravadas = _capturar(monkeypatch)

    def explode(*_a, **_k):
        raise OSError("sem rede")

    monkeypatch.setattr(conferencia.rest, "ler", explode)
    conferencia.gravar("tok", [dict(e) for e in LOTE_MISTO])
    assert all(l["sufixo"] for l in gravadas["linhas"] if l["empresa_id"] == 9)


def test_sufixo_nao_leva_caractere_que_o_windows_recusa():
    assert (conferencia.sufixo_do_nome('EMPRESA X - Conta corrente: 12.345-6 / "A"')
            == "EMPRESA X - Conta corrente 12.345-6 A")
