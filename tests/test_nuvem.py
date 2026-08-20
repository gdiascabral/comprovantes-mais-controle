# -*- coding: utf-8 -*-
"""O pacote `nuvem` sem rede e sem tela.

O que estes testes protegem é a diferença entre os TRÊS desfechos de uma
chamada que não deu certo — "sem rede", "sua sessão venceu" e "o banco disse
não" —, porque cada um pede uma coisa diferente de quem está na frente da
tela, e confundi-los é como o app passa a mentir: um cadastro que não baixou
vira "tudo certo", e uma sessão vencida vira "erro inesperado".
"""
import json
import sys
import time
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from nuvem import cache, cadastro, rest, sessao  # noqa: E402


# --------------------------------------------------------------- dublês

class _Resposta:
    def __init__(self, status, corpo=None, texto=""):
        self.status_code = status
        self._corpo = corpo
        self.text = texto or (json.dumps(corpo) if corpo is not None else "")
        self.content = self.text.encode()

    def json(self):
        if self._corpo is None:
            raise ValueError("não é JSON")
        return self._corpo


def _responder(monkeypatch, resposta):
    def falso(*_a, **_k):
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
    monkeypatch.setattr(rest.requests, "request", falso)
    monkeypatch.setattr(rest.requests, "post", falso)


def _jwt(exp: int, email: str = "quem@exemplo.com") -> str:
    """Um JWT de mentira: só o miolo importa, ninguém verifica assinatura."""
    import base64
    corpo = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "email": email}).encode()).decode().rstrip("=")
    return f"cabecalho.{corpo}.assinatura"


# ------------------------------------------------------------------- rest

def test_sem_rede_vira_sem_rede(monkeypatch):
    _responder(monkeypatch, rest.requests.RequestException("DNS"))
    with pytest.raises(rest.SemRede):
        rest.ler("conta", "tok")


def test_401_pede_para_entrar_de_novo(monkeypatch):
    _responder(monkeypatch, _Resposta(401, {"message": "JWT expired"}))
    with pytest.raises(rest.PrecisaEntrar):
        rest.ler("conta", "tok")


def test_403_tambem_pede_para_entrar(monkeypatch):
    """RLS negando e sessão vencida chegam iguais para quem está na tela."""
    _responder(monkeypatch, _Resposta(403, {"message": "denied"}))
    with pytest.raises(rest.PrecisaEntrar):
        rest.ler("conta", "tok")


def test_erro_de_regra_nao_e_erro_de_rede(monkeypatch):
    """Trava do banco é defeito de dado ou de programa: repetir não resolve."""
    _responder(monkeypatch, _Resposta(409, {"message": "duplicate key"}))
    with pytest.raises(rest.RecusadoPeloBanco):
        rest.inserir("empresa", "tok", [{"nome_pasta": "X"}])


def test_200_que_nao_e_json_e_problema_de_rede(monkeypatch):
    """Portal de wi-fi e página de manutenção respondem 200 com HTML."""
    _responder(monkeypatch, _Resposta(200, None, "<html>entre na rede</html>"))
    with pytest.raises(rest.SemRede):
        rest.ler("conta", "tok")


def test_alterar_e_apagar_sem_filtro_sao_recusados():
    """Sem filtro o PostgREST alcança a TABELA INTEIRA, e sem erro nenhum."""
    with pytest.raises(ValueError):
        rest.alterar("conta", "tok", "", {"pasta": "X"})
    with pytest.raises(ValueError):
        rest.apagar("conta", "tok", "")


def test_a_chave_do_codigo_e_a_publica():
    """A `service_role` ignora a RLS inteira e não pode viajar no exe."""
    import base64
    miolo = rest.CHAVE_PUBLICA.split(".")[1]
    dados = json.loads(base64.urlsafe_b64decode(miolo + "==").decode())
    assert dados["role"] == "anon"


# ----------------------------------------------------------------- sessao

def test_sem_arquivo_e_precisa_entrar(tmp_path):
    with pytest.raises(rest.PrecisaEntrar):
        sessao.token(tmp_path)


def test_token_no_prazo_nao_fala_com_o_servidor(tmp_path, monkeypatch):
    bom = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": bom, "renovacao": "r", "email": "quem@exemplo.com"})
    _responder(monkeypatch, AssertionError("não devia ter chamado a rede"))
    assert sessao.token(tmp_path) == bom


def test_token_vencido_sem_rede_mas_no_prazo_ainda_serve(tmp_path, monkeypatch):
    """O caso que impede uma queda do Supabase de parar o app com o ERP de pé.

    Dentro da folga de renovação, mas ainda válido: sem servidor para
    perguntar, vale enquanto o prazo durar."""
    quase = _jwt(int(time.time()) + 30)     # < FOLGA, porém no futuro
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": quase, "renovacao": "r", "email": "quem@exemplo.com"})
    monkeypatch.setattr(sessao.rest, "renovar",
                        lambda _r: (_ for _ in ()).throw(rest.SemRede("off")))
    assert sessao.token(tmp_path) == quase


def test_token_vencido_e_sem_rede_nao_entra(tmp_path, monkeypatch):
    velho = _jwt(int(time.time()) - 10)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": velho, "renovacao": "r", "email": "quem@exemplo.com"})
    monkeypatch.setattr(sessao.rest, "renovar",
                        lambda _r: (_ for _ in ()).throw(rest.SemRede("off")))
    with pytest.raises(rest.PrecisaEntrar):
        sessao.token(tmp_path)


def test_sessao_recusada_pelo_servidor_e_esquecida(tmp_path, monkeypatch):
    """Usuário removido ou senha trocada: não adianta insistir amanhã."""
    velho = _jwt(int(time.time()) - 10)
    apagou = {"sim": False}
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": velho, "renovacao": "r", "email": "quem@exemplo.com"})
    monkeypatch.setattr(sessao.rest, "renovar", lambda _r: (_ for _ in ()).throw(
        rest.PrecisaEntrar("não vale mais")))
    monkeypatch.setattr(sessao, "esquecer",
                        lambda _p=None: apagou.__setitem__("sim", True))
    with pytest.raises(rest.PrecisaEntrar):
        sessao.token(tmp_path)
    assert apagou["sim"]


def test_arquivo_de_sessao_corrompido_pede_a_senha(tmp_path):
    """DPAPI recusando ou arquivo truncado: pedir de novo, nunca adivinhar."""
    (tmp_path / sessao.ARQUIVO).write_bytes(b"nao sou uma sessao cifrada")
    assert sessao._ler(tmp_path) is None
    with pytest.raises(rest.PrecisaEntrar):
        sessao.token(tmp_path)


def test_jwt_ilegivel_nao_estoura():
    assert sessao._quando_vence("nem.parece.jwt") == 0
    assert sessao._quando_vence("") == 0


# ------------------------------------------------------------------ cache

def test_gravar_preserva_a_ajuda(tmp_path):
    """`_leia_me` explica o arquivo para quem o abre e não vem do banco."""
    cache.gravar_json("x.json", {"_leia_me": "como isto funciona",
                                 "nomes": ["a"]}, tmp_path)
    cache.gravar_json("x.json", {"nomes": ["b"]}, tmp_path)
    lido = json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))
    assert lido["_leia_me"] == "como isto funciona"
    assert lido["nomes"] == ["b"]


def test_gravar_e_atomico(tmp_path):
    """Não deve sobrar arquivo temporário no meio do caminho."""
    cache.gravar_json("x.json", {"a": 1}, tmp_path)
    assert not list(tmp_path.glob("*.novo"))


def test_csv_sai_com_bom_e_ponto_e_virgula(tmp_path):
    """É o que `dados.carregar_contas` lê e o que o Excel brasileiro abre."""
    cache.gravar_csv("c.csv", ["a", "b"], [{"a": "1", "b": "2"}], tmp_path)
    cru = (tmp_path / "c.csv").read_bytes()
    assert cru.startswith(b"\xef\xbb\xbf")
    assert b"a;b" in cru


# --------------------------------------------------------------- cadastro

def _banco(**tabelas):
    cheio = {t: [] for t in cadastro.TABELAS}
    cheio.update(tabelas)
    return cheio


def test_sem_rede_mantem_o_cache(tmp_path, monkeypatch):
    (tmp_path / "contas_mc.json").write_text('{"contas": [1]}', encoding="utf-8")
    monkeypatch.setattr(cadastro.rest, "ler", lambda *_a, **_k: (
        (_ for _ in ()).throw(rest.SemRede("off"))))
    r = cadastro.sincronizar("tok", tmp_path)
    assert not r.atualizou and r.usando_copia
    assert (tmp_path / "contas_mc.json").read_text(encoding="utf-8").strip()


def test_banco_vazio_nao_apaga_o_cadastro(tmp_path, monkeypatch):
    """Projeto novo ou migração não rodada não pode zerar quem tem os dados."""
    (tmp_path / "contas_mc.json").write_text('{"contas": [1]}', encoding="utf-8")
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: [])
    r = cadastro.sincronizar("tok", tmp_path)
    assert not r.atualizou
    assert "sem empresas" in r.motivo
    assert json.loads((tmp_path / "contas_mc.json").read_text())["contas"] == [1]


def test_tabela_vazia_nao_apaga_o_arquivo_que_tinha_coisa(tmp_path, monkeypatch):
    """O caso fino, que a checagem de banco-vazio não pega.

    Alguém apaga as entidades pelo painel sem querer. O banco continua com
    empresas e contas, então a sincronização segue — e zeraria o `contas.csv`
    de todas as máquinas na próxima abertura."""
    cache.gravar_csv("contas.csv",
                     ["nome_exibicao", "nome_oficial", "conta", "nome_descricao"],
                     [{"nome_exibicao": "FULANO", "nome_oficial": "FULANO LTDA",
                       "conta": "1", "nome_descricao": ""}], tmp_path)
    cache.gravar_json("subcontas.json", {"00000-0": {"obras": ["OBRA"],
                                                     "investidores": ["X"]}},
                      tmp_path)
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "E", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "1-1", "agencia": "",
                "nome_erp": "E", "pasta": "P", "banco": "B",
                "banco_codigo": "756", "sufixo": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    assert cadastro.sincronizar("tok", tmp_path).atualizou
    csv_texto = (tmp_path / "contas.csv").read_text(encoding="utf-8-sig")
    assert "FULANO" in csv_texto
    sub = json.loads((tmp_path / "subcontas.json").read_text(encoding="utf-8"))
    assert "00000-0" in sub


def test_arquivo_ausente_pode_nascer_vazio(tmp_path, monkeypatch):
    """A regra é "não troque cheio por vazio", não "nunca escreva vazio":
    máquina nova precisa receber os arquivos, mesmo os sem conteúdo."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "E", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "1-1", "agencia": "",
                "nome_erp": "E", "pasta": "P", "banco": "B",
                "banco_codigo": "756", "sufixo": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    assert (tmp_path / "contas.csv").exists()
    assert (tmp_path / "subcontas.json").exists()


def test_os_dois_mapas_saem_da_mesma_conta(tmp_path, monkeypatch):
    """A razão de tudo isto existir: uma conta, uma pasta, dois arquivos.

    Enquanto eram dois cadastros, bastava um divergir para o mês ficar
    partido — o PDF do ERP numa pasta e o OFX na outra."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "EMPRESA A", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "00.000-0",
                "agencia": "0000-0", "nome_erp": "EMPRESA A 00.000-0",
                "pasta": "BANCO", "banco": "NOME DO BANCO",
                "banco_codigo": "756", "sufixo": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    assert cadastro.sincronizar("tok", tmp_path).atualizou
    sic = json.loads((tmp_path / "contas_sicoob.json").read_text(encoding="utf-8"))
    mc = json.loads((tmp_path / "contas_mc.json").read_text(encoding="utf-8"))
    assert sic["empresas"][0]["contas"][0]["pasta"] == "BANCO"
    assert mc["contas"][0]["pasta"] == "BANCO"
    # E `banco` quer dizer coisas diferentes nos dois: nome de um lado,
    # código do outro. Uma coluna só arquivaria o extrato como "202607 756".
    assert sic["empresas"][0]["contas"][0]["banco"] == "756"
    assert mc["contas"][0]["banco"] == "NOME DO BANCO"


def test_o_sufixo_sobrevive_a_ida_e_volta_pelo_cache(tmp_path, monkeypatch):
    """Duas contas dividindo a pasta só não gravam uma por cima da outra
    porque o desempate chega aos DOIS arquivos.

    Ele descia só para o `contas_mc.json`: o PDF do ERP saía desempatado e o
    OFX do banco não, e a segunda conta apagava o extrato da primeira sem
    erro na tela — cada OFX passa pela trava do ACCTID, porque cada um é
    mesmo da sua conta. O nome da chave é o mesmo dos dois lados de
    propósito: `sicoob_contas` e `contas_mc` leem "sufixo"."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "EMPRESA A", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "11.111-1",
                "agencia": "0000-0", "nome_erp": "EMPRESA A 11.111-1",
                "pasta": "SICOOB", "banco": "SICOOB",
                "banco_codigo": "756", "sufixo": "11111-1"},
               {"id": 10, "empresa_id": 1, "numero": "22.222-2",
                "agencia": "0000-0", "nome_erp": "EMPRESA A 22.222-2",
                "pasta": "SICOOB", "banco": "SICOOB",
                "banco_codigo": "756", "sufixo": "22222-2"}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    assert cadastro.sincronizar("tok", tmp_path).atualizou
    sic = json.loads((tmp_path / "contas_sicoob.json").read_text(encoding="utf-8"))
    mc = json.loads((tmp_path / "contas_mc.json").read_text(encoding="utf-8"))
    assert [c["sufixo"] for c in sic["empresas"][0]["contas"]] == ["11111-1",
                                                                  "22222-2"]
    assert [c["sufixo"] for c in mc["contas"]] == ["11111-1", "22222-2"]

    # E, relido pelo módulo que de fato o usa, dá dois nomes de arquivo — que
    # é a única coisa que importa no fim.
    import sicoob_config
    import sicoob_contas
    mapa = sicoob_contas.carregar(tmp_path / "contas_sicoob.json")
    nomes = {sicoob_config.nome_arquivo(2026, 7, c.sufixo) for c in mapa.contas}
    assert nomes == {"202607 SICOOB 11111-1", "202607 SICOOB 22222-2"}
    assert sicoob_contas.impedimentos(mapa) == []


def test_conta_sem_sufixo_nao_ganha_a_chave(tmp_path, monkeypatch):
    """Como em `_contas_mc`: o desempate só existe onde alguém o cadastrou.
    Escrevê-lo vazio em toda conta sugeriria um campo a preencher sempre."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "E", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "1-1", "agencia": "",
                "nome_erp": "E", "pasta": "P", "banco": "B",
                "banco_codigo": "756", "sufixo": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    sic = json.loads((tmp_path / "contas_sicoob.json").read_text(encoding="utf-8"))
    mc = json.loads((tmp_path / "contas_mc.json").read_text(encoding="utf-8"))
    assert "sufixo" not in sic["empresas"][0]["contas"][0]
    assert "sufixo" not in mc["contas"][0]


def test_conta_sem_numero_fica_fora_do_mapa_do_sicoob(tmp_path, monkeypatch):
    """Conta de outro banco não é buscável no SicoobNet."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "EMPRESA A", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": None, "agencia": "",
                "nome_erp": "EMPRESA A OUTRO BANCO", "pasta": "OUTRO",
                "banco": "OUTRO", "banco_codigo": "", "sufixo": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    sic = json.loads((tmp_path / "contas_sicoob.json").read_text(encoding="utf-8"))
    mc = json.loads((tmp_path / "contas_mc.json").read_text(encoding="utf-8"))
    assert sic["empresas"][0]["contas"] == []
    assert len(mc["contas"]) == 1


def test_pagar_a_mao_volta_com_o_nome_que_o_app_le(tmp_path, monkeypatch):
    """No banco é `pagar_a_mao`; no arquivo tem de ser `confirmar_sempre`,
    que é o que `regras_pagamento.py` procura hoje."""
    dados = _banco(
        empresa=[{"id": 1, "nome_pasta": "E", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "1-1", "agencia": "",
                "nome_erp": "E", "pasta": "P", "banco": "B",
                "banco_codigo": "756", "sufixo": ""}],
        regra_fornecedor=[
            {"id": 1, "tipo": "pagar_a_mao", "nome": "FORNECEDOR X", "valor": ""},
            {"id": 2, "tipo": "so_reembolso", "nome": "FORNECEDOR Y", "valor": ""},
            {"id": 3, "tipo": "confirmar_antes", "nome": "PESSOA Z", "valor": ""},
            {"id": 4, "tipo": "so_marcador", "nome": "CONCESSIONARIA W",
             "valor": ""}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}])
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    regras = json.loads((tmp_path / "regras_fornecedor.json").read_text(
        encoding="utf-8"))
    assert regras["FORNECEDOR X"]["confirmar_sempre"] is True
    assert regras["FORNECEDOR Y"]["so_com_reembolso"] is True
    # Precisa vir da nuvem: o arquivo é reescrito a cada abertura, e uma marca
    # posta à mão no JSON sumiria na sincronização seguinte.
    assert regras["CONCESSIONARIA W"]["so_marcador"] is True
    # `confirmar_antes` é OUTRA coisa, e mora em outro arquivo: ela abre a
    # janela de confirmação, enquanto `pagar_a_mao` tira da remessa.
    assert "PESSOA Z" not in regras
    confirmar = json.loads((tmp_path / "confirmar_antes.json").read_text(
        encoding="utf-8"))
    assert confirmar["nomes"] == ["PESSOA Z"]
