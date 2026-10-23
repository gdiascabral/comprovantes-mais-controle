# -*- coding: utf-8 -*-
"""Conta RENOMEADA no ERP e conta IGNORADA para sempre (23/10/2026).

O caso real: o dono mudou o nome de uma subconta no ERP (pôs o ponto do
milhar no número). A janela de contas novas comparava só pelo nome, listou a
conta como "nova", e o "Incluir" levou um 409 do banco (`conta_numero_unico`):
a conta já estava no cadastro, com o nome antigo. Aqui o número decide que é a
MESMA conta, e o "Incluir" corrige o nome (PATCH por id), nunca insere.

Todos os nomes e números daqui são fictícios — o repositório é público.
Sem rede, sem Tk, sem ERP: dublês no lugar do `rest`.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nuvem import contas_central as cc
from nuvem import contas_novas as cn
from nuvem import contas_novas_dialogo as dialogo
from nuvem import rest

NOVO = "EMPRESA FICTICIA - SUBCONTA 12.345-6 - OBRA MODELO - SICOOB"
ANTIGO = "EMPRESA FICTICIA - SUBCONTA 12345-6 - OBRA MODELO - SICOOB"


def _cru(nome=NOVO, id_erp="u-1", numero="12.345", dv="6", banco="756",
         agencia="1234", ativa=True):
    return {"id": id_erp, "name": nome, "isActive": ativa, "bankCode": banco,
            "agency": agencia, "agencyDigit": None, "account": numero,
            "accountDigit": dv}


def _cad(id_=109, nome=ANTIGO, numero="12345-6", banco="756", agencia="1234"):
    return {"id": id_, "nome_erp": nome, "numero": numero,
            "banco_codigo": banco, "agencia": agencia}


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    def nao_pode(*_a, **_k):
        raise AssertionError("teste falou com o banco sem dublê")
    for nome in ("ler", "inserir", "alterar", "apagar"):
        monkeypatch.setattr(cn.rest, nome, nao_pode)


# ------------------------------------------------------------- renomeações
def test_mesmo_numero_com_outro_nome_e_renomeada():
    ren = cn.renomeacoes([_cru()], [_cad()])
    assert list(ren) == ["u-1"]
    assert [c["id"] for c in ren["u-1"]] == [109]


def test_numero_diferente_nao_e_renomeada():
    assert cn.renomeacoes([_cru(numero="99.999")], [_cad()]) == {}


def test_mesmo_nome_nao_e_renomeada():
    assert cn.renomeacoes([_cru(nome=ANTIGO)], [_cad()]) == {}


def test_banco_diferente_nao_e_a_mesma_conta():
    assert cn.renomeacoes([_cru(banco="1")], [_cad()]) == {}


def test_agencia_diferente_nao_e_a_mesma_conta():
    assert cn.renomeacoes([_cru(agencia="9999")], [_cad()]) == {}


def test_sem_banco_ou_agencia_de_um_lado_vale_o_numero():
    assert list(cn.renomeacoes([_cru(banco=None, agencia=None)],
                               [_cad()])) == ["u-1"]
    assert list(cn.renomeacoes([_cru()],
                               [_cad(banco="", agencia="")])) == ["u-1"]


def test_nome_antigo_ainda_ativo_no_erp_nao_e_renomeada():
    """Se a conta de nome antigo continua no ERP, não é a mesma conta com
    nome novo — é outra conta com número repetido, e não se adivinha."""
    outra = _cru(nome=ANTIGO, id_erp="u-2")
    assert cn.renomeacoes([_cru(), outra], [_cad()]) == {}


def test_numero_que_bate_com_duas_contas_devolve_as_duas():
    ren = cn.renomeacoes([_cru()], [_cad(), _cad(id_=110, nome="OUTRA")])
    assert sorted(c["id"] for c in ren["u-1"]) == [109, 110]


def test_conta_sem_numero_nunca_e_renomeada():
    assert cn.renomeacoes([_cru(numero=None, dv=None,
                                nome="SEM NUMERO - SICOOB")],
                          [_cad(numero=None)]) == {}


# ---------------------------------------------------------------- pendências
def _contas_mc(pasta, nomes):
    (pasta / "contas_mc.json").write_text(json.dumps(
        {"contas": [{"erp": n} for n in nomes]}), encoding="utf-8")


def test_pendencia_diz_que_o_nome_mudou(tmp_path):
    _contas_mc(tmp_path, [ANTIGO])
    p, = cc.pendencias([_cru()], tmp_path, tmp_path, cadastradas=[_cad()])
    assert p.falta_cadastro is True
    assert p.renomeada["id"] == 109
    assert p.falta_em == f"nome mudou no ERP: antes '{ANTIGO}'"


def test_sem_o_cadastro_da_nuvem_segue_como_nova(tmp_path):
    _contas_mc(tmp_path, [ANTIGO])
    p, = cc.pendencias([_cru()], tmp_path, tmp_path)
    assert p.renomeada is None and p.falta_em == "cadastro"


def test_duas_contas_com_o_numero_nao_adivinha(tmp_path):
    _contas_mc(tmp_path, [ANTIGO, "OUTRA"])
    p, = cc.pendencias([_cru()], tmp_path, tmp_path,
                       cadastradas=[_cad(), _cad(id_=110, nome="OUTRA")])
    assert p.renomeada is None
    assert "2 contas" in p.falta_em


# -------------------------------------------------------------- a janela
def _pend(antes):
    return SimpleNamespace(nome=NOVO, banco="756", agencia="1234",
                           numero="12.345-6", falta_cadastro=True,
                           falta_painel=False, antes=antes)


def test_escolha_da_renomeada_leva_o_id_e_nao_pede_empresa():
    linhas = [(_pend([_cad()]), True, "", "", "R", False)]
    esc, = dialogo.escolhas_marcadas(linhas, {})
    assert esc["nome_erp"] == NOVO
    assert esc["renomear"] == [{"id": 109, "nome_erp": ANTIGO,
                                "disputada": False}]


def test_escolha_comum_nao_ganha_a_chave_renomear():
    linhas = [(_pend([]), True, "E", "P", "R", False)]
    esc, = dialogo.escolhas_marcadas(linhas, {"E": 1})
    assert "renomear" not in esc


def test_sem_as_ignoradas_tira_so_as_escolhidas():
    a, b, c = (["a"], ["b"], ["c"])
    assert dialogo.sem_as_linhas([a, b, c], {0, 2}) == [b]


# ------------------------------------------------------- correção do nome
def test_corrige_o_nome_por_patch_e_nunca_insere(monkeypatch):
    chamadas = []

    def alterar(tabela, token, filtro, mud):
        chamadas.append((tabela, filtro, mud))
        return [{"id": 109}]
    monkeypatch.setattr(cn.rest, "alterar", alterar)
    avisos = cn.gravar("tok", [{"nome_erp": NOVO, "empresa_id": None,
                                "pasta": "", "renomear": [_cad()]}])
    assert avisos == []
    (tabela, filtro, mud), = chamadas
    assert tabela == "conta" and mud == {"nome_erp": NOVO}
    assert filtro == cn.filtro_da_correcao(_cad())
    assert filtro.startswith("id=eq.109&nome_erp=eq.")


def test_zero_linhas_alteradas_vira_recado_do_sql(monkeypatch):
    monkeypatch.setattr(cn.rest, "alterar", lambda *a, **k: [])
    feitas, avisos = cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                                                "renomear": [_cad()]}])
    assert feitas == 0
    assert "o banco não deixou corrigir" in avisos[0]
    assert "falta aplicar o SQL" in avisos[0]


def test_duas_candidatas_nao_chama_o_banco():
    feitas, avisos = cn.corrigir_nomes("tok", [{
        "nome_erp": NOVO, "renomear": [_cad(), _cad(id_=110, nome="OUTRA")]}])
    assert feitas == 0 and "não adivinhei" in avisos[0]


def test_nome_novo_ja_usado_vira_recado(monkeypatch):
    def recusa(*_a, **_k):
        raise rest.RecusadoPeloBanco(
            'HTTP 409: duplicate key value violates unique constraint '
            '"conta_nome_erp_unico"', status=409, codigo="23505")
    monkeypatch.setattr(cn.rest, "alterar", recusa)
    feitas, avisos = cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                                                "renomear": [_cad()]}])
    assert feitas == 0 and "outra conta com esse nome" in avisos[0]


def test_aplicar_conta_correcoes_e_cadastros_separados(monkeypatch, tmp_path):
    monkeypatch.setattr(cc.contas_novas, "gravar", lambda tok, esc: [])
    monkeypatch.setattr(cc.contas_novas, "corrigir_nomes",
                        lambda tok, esc: (len(esc), []))
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"},
                                    {"nome_erp": NOVO, "renomear": [_cad()]}])
    recado = cc.aplicar("tok", r, [], tmp_path)
    assert "1 conta(s) cadastrada(s)." in recado
    assert "1 nome(s) de conta corrigido(s) no cadastro." in recado


# ------------------------------------------- 409 que ainda escape no INSERT
def _recusa_numero(*_a, **_k):
    raise rest.RecusadoPeloBanco(
        'HTTP 409: duplicate key value violates unique constraint '
        '"conta_numero_unico"', status=409, codigo="23505")


def test_409_de_numero_vira_recado_com_o_nome_que_esta_no_cadastro(monkeypatch):
    inseridos = []

    def inserir(tabela, token, linhas, **_k):
        if any(l["numero"] == "12.345-6" for l in linhas):
            _recusa_numero()
        inseridos.extend(linhas)
    monkeypatch.setattr(cn.rest, "inserir", inserir)
    monkeypatch.setattr(cn.rest, "ler", lambda tabela, token, **k: (
        [_cad()] if "numero" in k.get("colunas", "") else []))
    avisos = cn.gravar("tok", [
        {"nome_erp": NOVO, "empresa_id": 1, "pasta": "P1",
         "numero": "12.345-6"},
        {"nome_erp": "BOA FICTICIA", "empresa_id": 1, "pasta": "P2",
         "numero": "55555-5"}])
    assert avisos == [f"{NOVO}: essa conta já está no cadastro com outro "
                      f"nome: {ANTIGO}"]
    assert [l["nome_erp"] for l in inseridos] == ["BOA FICTICIA"]


def test_409_sem_achar_quem_e_ainda_e_recado_claro(monkeypatch):
    monkeypatch.setattr(cn.rest, "inserir", _recusa_numero)
    monkeypatch.setattr(cn.rest, "ler", lambda *a, **k: [])
    avisos = cn.gravar("tok", [{"nome_erp": NOVO, "empresa_id": 1,
                                "pasta": "P1", "numero": "12.345-6"}])
    assert len(avisos) == 1
    assert "já está no cadastro com outro nome" in avisos[0]


def test_outra_recusa_continua_subindo(monkeypatch):
    def recusa(*_a, **_k):
        raise rest.RecusadoPeloBanco("HTTP 400: outra coisa", status=400)
    monkeypatch.setattr(cn.rest, "inserir", recusa)
    monkeypatch.setattr(cn.rest, "ler", lambda *a, **k: [])
    with pytest.raises(rest.RecusadoPeloBanco):
        cn.gravar("tok", [{"nome_erp": NOVO, "empresa_id": 1, "pasta": "P"}])


# ------------------------------------------------------------- ignorar
def test_ignorar_sempre_grava_e_a_conta_some(tmp_path):
    cn.ignorar_sempre(["Conta Fictícia  Ignorada - NEXT"], tmp_path)
    lidos = json.loads((tmp_path / cn.ARQUIVO_IGNORADAS).read_text("utf-8"))
    assert lidos == ["Conta Fictícia  Ignorada - NEXT"]
    ign = cn.ignorados(tmp_path)
    assert cn.comparar([_cru(nome="CONTA FICTICIA IGNORADA - NEXT")],
                       set(), ign) == []


def test_ignorada_local_casa_pelo_nome_inteiro_e_nao_por_pedaco(tmp_path):
    cn.ignorar_sempre(["CONTA FICTICIA - NEXT"], tmp_path)
    outra = _cru(nome="CONTA FICTICIA - NEXT 2", id_erp="u-9")
    novas = cn.comparar([outra], set(), cn.ignorados(tmp_path))
    assert [n.nome for n in novas] == ["CONTA FICTICIA - NEXT 2"]


def test_ignorar_de_novo_nao_duplica_e_mantem_as_outras(tmp_path):
    cn.ignorar_sempre(["A FICTICIA"], tmp_path)
    cn.ignorar_sempre(["a ficticia", "B FICTICIA"], tmp_path)
    lidos = json.loads((tmp_path / cn.ARQUIVO_IGNORADAS).read_text("utf-8"))
    assert lidos == ["A FICTICIA", "B FICTICIA"]
    assert not list(Path(tmp_path).glob("*.novo"))


def test_arquivo_estragado_nao_e_sobrescrito(tmp_path):
    (tmp_path / cn.ARQUIVO_IGNORADAS).write_text("{nao e json", "utf-8")
    with pytest.raises(ValueError):
        cn.ignorar_sempre(["A FICTICIA"], tmp_path)
    assert (tmp_path / cn.ARQUIVO_IGNORADAS).read_text("utf-8") == "{nao e json"


def test_ignorados_junta_o_mapping_e_o_arquivo_local(tmp_path):
    (tmp_path / "mapping.yaml").write_text(
        "ignored_erp_accounts:\n- PEDACO FICTICIO\n", encoding="utf-8")
    cn.ignorar_sempre(["CONTA INTEIRA FICTICIA"], tmp_path)
    ign = cn.ignorados(tmp_path)
    assert "PEDACO FICTICIO" in ign and "CONTA INTEIRA FICTICIA" in ign


def test_ignorada_local_some_tambem_da_pendencia_so_de_painel(tmp_path,
                                                             monkeypatch):
    _contas_mc(tmp_path, [NOVO])
    monkeypatch.setattr(cc, "mapa_do_painel", lambda _p=None: object())
    monkeypatch.setattr(cc, "_fora_do_painel", lambda contas, m: list(contas))
    assert len(cc.pendencias([_cru()], tmp_path, tmp_path)) == 1
    cn.ignorar_sempre([NOVO], tmp_path)
    assert cc.pendencias([_cru()], tmp_path, tmp_path) == []


def test_a_janela_tem_o_botao_ignorar_e_a_pergunta():
    fonte = Path(dialogo.__file__).read_text(encoding="utf-8")
    assert 'text="Ignorar"' in fonte
    assert "Ignorar sempre esta conta? Ela não aparece mais nesta janela." \
        in fonte
    assert 'selectmode="extended"' in fonte


def test_a_moldura_passa_o_cadastro_da_nuvem_para_as_pendencias():
    raiz = Path(__file__).resolve().parents[1]
    fonte = (raiz / "comprovantes_app.py").read_text(encoding="utf-8")
    assert fonte.count("cadastradas=contas_novas.contas_cadastradas(") == 2


# ------------------------------------------------------------- migration
def test_migration_libera_so_o_nome_e_audita():
    raiz = Path(__file__).resolve().parents[1]
    sql = (raiz / "supabase" / "migrations" /
           "20261023100000_conta_nome_erp_pode_ser_corrigido_pelo_app.sql"
           ).read_text(encoding="utf-8").lower()
    assert "grant update (nome_erp) on table public.conta to authenticated" \
        in sql
    assert "for update to authenticated" in sql
    assert sql.count("privado.e_ativo()") >= 2
    assert "drop policy if exists" in sql and "drop trigger if exists" in sql
    assert "after update on public.conta" in sql
    assert "notify pgrst, 'reload schema'" in sql
    assert "grant delete" not in sql and "for delete" not in sql
    corpo = sql.split("-- reverter")[0]
    assert "grant update on table" not in corpo    # nunca a tabela inteira
    assert "revoke update on table public.conta from authenticated" in corpo


# ===================================== revisão de dinheiro (23/10/2026)
# 1. Duas contas do ERP não podem renomear a MESMA linha do cadastro.
def test_linha_do_cadastro_disputada_por_duas_contas_nao_renomeia(tmp_path):
    outra = _cru(nome=NOVO + " B", id_erp="u-2")
    _contas_mc(tmp_path, [ANTIGO])
    pend = cc.pendencias([_cru(), outra], tmp_path, tmp_path,
                         cadastradas=[_cad()])
    assert len(pend) == 2
    for p in pend:
        assert p.renomeada is None
        assert "número igual em mais de uma conta do ERP" in p.falta_em


def test_escolha_disputada_nao_chama_o_banco():
    cand = dict(_cad(), disputada=True)
    feitas, avisos = cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                                                "renomear": [cand]}])
    assert feitas == 0
    assert "número igual em mais de uma conta do ERP" in avisos[0]


def test_patch_filtra_tambem_pelo_nome_antigo_escapado(monkeypatch):
    filtros = []
    monkeypatch.setattr(cn.rest, "alterar", lambda t, tok, filtro, mud:
                        filtros.append(filtro) or [{"id": 109}])
    antigo = "EMPRESA FICTICIA & CIA, (LOTE 1) #2"
    cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                              "renomear": [_cad(nome=antigo)]}])
    filtro, = filtros
    assert filtro.startswith("id=eq.109&nome_erp=eq.")
    from urllib.parse import unquote
    valor = filtro.split("&nome_erp=eq.", 1)[1]
    assert "&" not in valor and "#" not in valor and " " not in valor
    assert unquote(valor) == antigo          # sem aspas: eq. é literal


def test_nome_antigo_vazio_filtra_por_nulo(monkeypatch):
    filtros = []
    monkeypatch.setattr(cn.rest, "alterar", lambda t, tok, filtro, mud:
                        filtros.append(filtro) or [{"id": 109}])
    cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                              "renomear": [_cad(nome=None)]}])
    assert filtros == ["id=eq.109&nome_erp=is.null"]


def test_segundo_patch_altera_zero_e_diz_que_o_nome_ja_mudou(monkeypatch):
    monkeypatch.setattr(cn.rest, "alterar", lambda *a, **k: [])
    monkeypatch.setattr(cn.rest, "ler", lambda *a, **k: [
        {"id": 109, "nome_erp": "NOME QUE OUTRA MAQUINA GRAVOU"}])
    feitas, avisos = cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                                                "renomear": [_cad()]}])
    assert feitas == 0
    assert "o nome já tinha mudado" in avisos[0]
    assert "NOME QUE OUTRA MAQUINA GRAVOU" in avisos[0]


def test_zero_linhas_com_o_nome_antigo_intacto_e_o_sql(monkeypatch):
    monkeypatch.setattr(cn.rest, "alterar", lambda *a, **k: [])
    monkeypatch.setattr(cn.rest, "ler", lambda *a, **k: [
        {"id": 109, "nome_erp": ANTIGO}])
    _f, avisos = cn.corrigir_nomes("tok", [{"nome_erp": NOVO,
                                            "renomear": [_cad()]}])
    assert "falta aplicar o SQL" in avisos[0]


# 2. A renomeação olha TODAS as ativas, antes do filtro de ignoradas.
def test_ignorada_com_o_nome_antigo_ainda_impede_a_renomeacao(tmp_path):
    """O nome antigo continua ativo no ERP, só que ignorado na janela: a
    conta nova NÃO é a antiga renomeada."""
    _contas_mc(tmp_path, [ANTIGO])
    cn.ignorar_sempre([ANTIGO], tmp_path)
    antiga = _cru(nome=ANTIGO, id_erp="u-2")
    p, = cc.pendencias([_cru(), antiga], tmp_path, tmp_path,
                       cadastradas=[_cad()])
    assert p.nome == NOVO and p.renomeada is None


def test_disputa_conta_tambem_a_ignorada(tmp_path):
    _contas_mc(tmp_path, [ANTIGO])
    outra_nome = NOVO + " B"
    cn.ignorar_sempre([outra_nome], tmp_path)
    p, = cc.pendencias([_cru(), _cru(nome=outra_nome, id_erp="u-2")],
                       tmp_path, tmp_path, cadastradas=[_cad()])
    assert p.renomeada is None


# 3. Só nasce marcada a renomeação conferida.
def test_conferida_quando_numero_do_campo_e_banco_agencia_dos_dois_lados():
    c, = cn.renomeacoes([_cru()], [_cad()])["u-1"]
    assert c["conferida"] is True


def test_numero_so_no_nome_nao_e_conferida():
    cru = _cru(numero=None, dv=None)        # número só no nome (12.345-6)
    c, = cn.renomeacoes([cru], [_cad()])["u-1"]
    assert c["conferida"] is False


def test_banco_ou_agencia_faltando_de_um_lado_nao_e_conferida():
    c, = cn.renomeacoes([_cru(banco=None)], [_cad()])["u-1"]
    assert c["conferida"] is False
    c, = cn.renomeacoes([_cru()], [_cad(agencia="")])["u-1"]
    assert c["conferida"] is False


def test_nao_conferida_avisa_na_coluna(tmp_path):
    _contas_mc(tmp_path, [ANTIGO])
    p, = cc.pendencias([_cru(banco=None)], tmp_path, tmp_path,
                       cadastradas=[_cad()])
    assert p.renomeada is not None
    assert ("confira: o número bate, mas banco, agência ou a origem do "
            "número não foram conferidos") in p.falta_em


def test_marca_inicial_so_para_a_conferida():
    conferida = _pend([dict(_cad(), conferida=True)])
    nao = _pend([dict(_cad(), conferida=False)])
    disputada = _pend([dict(_cad(), conferida=True, disputada=True)])
    assert dialogo.nasce_marcada(conferida, "") is True
    assert dialogo.nasce_marcada(nao, "") is False
    assert dialogo.nasce_marcada(disputada, "") is False
    # A renomeada nunca nasce marcada pela empresa sugerida.
    assert dialogo.nasce_marcada(nao, "EMPRESA") is False
    assert dialogo.nasce_marcada(_pend([]), "EMPRESA") is True


# 4. 409 no lote.
def test_409_com_numero_repetido_dentro_do_lote(monkeypatch):
    inseridos = []

    def inserir(tabela, token, linhas, **_k):
        if sum(1 for l in linhas if cn.digitos(l["numero"]) == "777777") > 1:
            _recusa_numero()
        inseridos.extend(linhas)
    monkeypatch.setattr(cn.rest, "inserir", inserir)
    monkeypatch.setattr(cn.rest, "ler", lambda *a, **k: [])
    avisos = cn.gravar("tok", [
        {"nome_erp": "A FICTICIA", "empresa_id": 1, "pasta": "P1",
         "numero": "77777-7"},
        {"nome_erp": "B FICTICIA", "empresa_id": 1, "pasta": "P2",
         "numero": "77.777-7"},
        {"nome_erp": "C FICTICIA", "empresa_id": 1, "pasta": "P3",
         "numero": "55555-5"}])
    assert len(avisos) == 2
    assert all("número repetido dentro deste lote" in a for a in avisos)
    assert [l["nome_erp"] for l in inseridos] == ["C FICTICIA"]


def test_409_no_reenvio_vira_aviso_e_nao_levanta(monkeypatch):
    monkeypatch.setattr(cn.rest, "inserir", _recusa_numero)
    monkeypatch.setattr(cn.rest, "ler", lambda tabela, token, **k: (
        [_cad()] if "numero" in k.get("colunas", "") else []))
    avisos = cn.gravar("tok", [
        {"nome_erp": NOVO, "empresa_id": 1, "pasta": "P1",
         "numero": "12.345-6"},
        {"nome_erp": "BOA FICTICIA", "empresa_id": 1, "pasta": "P2",
         "numero": "55555-5"}])
    assert any(a.startswith("BOA FICTICIA:") for a in avisos)


def test_falha_nas_novas_nao_pula_a_correcao_dos_nomes(monkeypatch, tmp_path):
    def quebra(tok, esc):
        raise rest.RecusadoPeloBanco("HTTP 500: caiu", status=500)
    corrigidas = []
    monkeypatch.setattr(cc.contas_novas, "gravar", quebra)
    monkeypatch.setattr(cc.contas_novas, "corrigir_nomes",
                        lambda tok, esc: corrigidas.extend(esc)
                        or (len(esc), []))
    r = dialogo.Respostas(cadastro=[{"nome_erp": "X"},
                                    {"nome_erp": NOVO, "renomear": [_cad()]}])
    recado = cc.aplicar("tok", r, [], tmp_path)
    assert [e["nome_erp"] for e in corrigidas] == [NOVO]
    assert "1 nome(s) de conta corrigido(s) no cadastro." in recado
    assert "HTTP 500: caiu" in recado


# 5. Não se ignora a linha "nome mudou".
def test_nao_ignora_linha_de_nome_mudado():
    linhas = [[_pend([]), False, "", "", "", False],
              [_pend([_cad()]), True, "", "", "", False]]
    assert dialogo.recado_para_ignorar(linhas, [0]) == ""
    assert "nome mudou" in dialogo.recado_para_ignorar(linhas, [0, 1])
