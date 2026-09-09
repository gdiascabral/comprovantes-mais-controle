# -*- coding: utf-8 -*-
"""A sentinela do contrato do ERP, sem rede. Nenhum teste aqui baixa nada.

Ela é feita de três metades, e as três erram calado. A primeira são os
EXTRATORES: expressões regulares que leem, de dentro de um bundle minificado,
o que o front sabe do back-end. Uma expressão que deixa de casar não dá erro —
devolve lista vazia, e lista vazia comparada com lista vazia é "igual", que é
o pior desfecho possível para uma sentinela. Por isso cada extrator é testado
contra um TRECHO fictício no formato do bundle, e o formato é a coisa medida.
A segunda é a COMPARAÇÃO: o que sumiu tem de vir primeiro, porque é o que
quebra o app. A terceira é o ALERTA, que tem de nascer quando algo muda e,
principalmente, SUMIR quando a rodada seguinte não muda nada — arquivo de
alarme que fica para trás ensina a ignorar alarme.

Os trechos são inventados no formato dos bundles reais (medido em
08/09/2026), e não os bundles: nada da empresa entra aqui, e a suíte não pode
depender de o ERP estar de pé. O transporte é trocado no `baixar_` que
`rodar`, `mostrar` e `fotografar` recebem — e, para quem entra por `main()`,
no próprio `sentinela_erp.baixar`, que é resolvido na chamada.
"""
import json
import logging
import urllib.request
from datetime import datetime

import pytest

from erp.sessao import USER_AGENT
from ferramentas import sentinela_erp as sentinela


# ------------------------------------------------------------------ dublês

@pytest.fixture(autouse=True)
def _log_de_teste(monkeypatch):
    """A suíte não escreve no `diagnostico.log` de quem a roda (mesma razão
    da fixture homônima em `test_sonda.py`)."""
    monkeypatch.setattr(sentinela, "log",
                        logging.getLogger("sentinela_de_teste"))


#: O HTML do índice, com o bundle legado de "hoje". O hash é inventado.
_NOME_LEGADO = "main-0123456789abcdef.js"
_INDICE = ('<!doctype html><html><head><link rel="stylesheet" href="/x.css">'
           f'<script src="/{_NOME_LEGADO}" defer></script></head></html>')

#: Um bundle React de mentira, no formato do real: a configuração com os
#: hosts e o buildNumber, as telas do roteador, dois serviços transpilados
#: (baseUrl + métodos) e o dicionário de comandos de pré-lançamento.
_REACT = (
    'var cfg={legacyApi:"https://legado.exemplo.test/servicos",'
    'coreApiUrl:"https://api.exemplo.test",'
    'preLaunchesApiUrl:"https://pre.exemplo.test",'
    'buildNumber:Number(null!=="10018"?"10018":"0")};'
    'var rotas=[{path:"/accounts",exact:!0},{path:"/fiscal"},'
    '{path:"/work-management/works/:id"}];'
    '"baseUrl","/payable-installments";'
    'key:"list",value:function(e){return this.http.get(this.baseUrl+"/search",e)}'
    'key:"pay",value:function(e,t){return this.http.post('
    '"/payable-installments/"+e+"/paids",t)}'
    'key:"render",value:function(){return null}'
    '"baseUrl","/attachments";'
    'key:"upload",value:function(e){return this.http.post("/attachments/v2",e)}'
    'key:"remove",value:function(e){return this.http.delete("/attachments/"+e)}'
    'var comandos={"create-manual-pre-launch":{inputSchema:{}},'
    '"cancel-pre-launch":{inputSchema:{}}};'
)

#: Um bundle legado (AngularJS) de mentira: Restangular e ui-router.
_LEGADO = (
    'function(a){return a.all("purchase-order").getList()}'
    'function(a,b){return a.one("quotation",b).get()}'
    'function(a,b){return a.all("purchase-order").post(b)}'
    '$stateProvider.state("base.purchaseOrderList",{url:"/purchase-orders"})'
    '.state("base.quotationList",{url:"/quotations"});'
)


def _transporte(indice=_INDICE, react=_REACT, legado=_LEGADO,
                nome_legado=_NOME_LEGADO, erro=None):
    """Um `baixar` de mentira: responde pela URL e anota o que foi pedido.

    `erro` é levantado em toda chamada — é como uma manhã sem rede chega."""
    pedidos = []

    def baixar(url):
        pedidos.append(url)
        if erro is not None:
            raise erro
        if url == sentinela.URL_INDICE:
            return indice.encode()
        if url == sentinela.URL_REACT:
            return react.encode()
        if url.endswith("/" + nome_legado):
            return legado.encode()
        raise AssertionError(f"a sentinela pediu uma URL inesperada: {url}")

    return baixar, pedidos


_AGORA = datetime(2026, 9, 8, 7, 5, 0)
_AMANHA = datetime(2026, 9, 9, 7, 5, 0)


# ------------------------------------------------------------ os extratores

def test_o_nome_do_legado_sai_do_indice():
    """É o único lugar onde o hash de hoje está escrito."""
    assert sentinela.nome_do_legado(_INDICE) == _NOME_LEGADO
    assert sentinela.nome_do_legado("<html>sem bundle</html>") == ""


def test_recursos_do_react():
    assert sentinela.recursos_do_react(_REACT) == [
        "/attachments", "/payable-installments"]


def test_metodos_por_recurso_com_verbos_e_rotas():
    """Cada método fica com o recurso ANTERIOR a ele, e `render` fica de fora.

    O `render` está entre dois serviços e não chama HTTP nenhum: é componente
    de tela, e listá-lo seria inventariar o que não é contrato."""
    assert sentinela.metodos_do_react(_REACT) == [
        "/attachments remove [delete] /attachments/",
        "/attachments upload [post] /attachments/v2",
        "/payable-installments list [get] /search",
        "/payable-installments pay [post] /payable-installments/ /paids",
    ]


def test_metodo_sem_baseurl_antes_dele_nao_entra():
    """Método escrito ANTES do primeiro `baseUrl` não é de recurso nenhum."""
    solto = 'key:"x",value:function(){return this.http.get("/solto")}' + _REACT
    assert "/solto" not in " ".join(sentinela.metodos_do_react(solto))


def test_telas_do_react():
    assert sentinela.telas_do_react(_REACT) == [
        "/accounts", "/fiscal", "/work-management/works/:id"]


def test_hosts_da_configuracao():
    assert sentinela.hosts_do_react(_REACT) == [
        "coreApiUrl=https://api.exemplo.test",
        "legacyApi=https://legado.exemplo.test/servicos",
        "preLaunchesApiUrl=https://pre.exemplo.test",
    ]


def test_comandos_de_pre_lancamento():
    assert sentinela.comandos_do_react(_REACT) == [
        "cancel-pre-launch", "create-manual-pre-launch"]


def test_build_number_do_react():
    assert sentinela.build_do_react(_REACT) == "10018"
    assert sentinela.build_do_react("sem build") == ""


def test_recursos_do_legado_sem_repeticao():
    """`purchase-order` aparece duas vezes no bundle e uma no inventário."""
    assert sentinela.recursos_do_legado(_LEGADO) == [
        "purchase-order", "quotation"]


def test_telas_do_legado():
    assert sentinela.telas_do_legado(_LEGADO) == [
        "base.purchaseOrderList", "base.quotationList"]


def test_extrator_que_nao_casa_devolve_lista_vazia_e_nao_estoura():
    """Bundle irreconhecível é lista vazia — e a comparação é que vai gritar,
    porque tudo o que havia ontem terá "sumido"."""
    for extrator in (sentinela.recursos_do_react, sentinela.metodos_do_react,
                     sentinela.telas_do_react, sentinela.hosts_do_react,
                     sentinela.comandos_do_react, sentinela.recursos_do_legado,
                     sentinela.telas_do_legado):
        assert extrator("") == []


# ------------------------------------------------------------- o inventário

def test_o_inventario_e_ordenado_e_serializavel():
    """Dicionário com ordem fixa, que vai e volta do JSON sem perder nada."""
    inv = sentinela.inventariar(_REACT.encode(), _LEGADO.encode(),
                                _NOME_LEGADO, _AGORA)

    assert list(inv) == ["quando", "react", "legado", "categorias"]
    assert list(inv["categorias"]) == list(sentinela.CATEGORIAS)
    assert inv["quando"] == "2026-09-08T07:05:00"
    assert inv["react"]["build"] == "10018"
    assert inv["react"]["bytes"] == len(_REACT.encode())
    assert inv["legado"]["arquivo"] == _NOME_LEGADO
    assert len(inv["react"]["sha256"]) == 64
    assert json.loads(json.dumps(inv)) == inv


def test_fotografar_pede_o_indice_o_react_e_o_legado_de_hoje():
    """Três GETs, e o do legado com o nome que o índice acabou de dizer."""
    baixar, pedidos = _transporte()

    inv = sentinela.fotografar(baixar, _AGORA)

    assert pedidos == [sentinela.URL_INDICE, sentinela.URL_REACT,
                       f"{sentinela.hosts.ACESSAR}/{_NOME_LEGADO}"]
    assert inv["legado"]["arquivo"] == _NOME_LEGADO


def test_indice_sem_bundle_legado_e_falha_de_download():
    """Sem o nome não há o que baixar — e a tela mudou de forma, o que já é
    notícia."""
    baixar, _ = _transporte(indice="<html>nada aqui</html>")
    with pytest.raises(sentinela.NaoBaixou, match="main-<hash>"):
        sentinela.fotografar(baixar, _AGORA)


# ------------------------------------------------------------- a comparação

def _foto(react=_REACT, legado=_LEGADO, nome=_NOME_LEGADO, quando=_AGORA):
    return sentinela.inventariar(react.encode(), legado.encode(), nome, quando)


def test_comparar_igual_ignora_a_hora():
    dif = sentinela.comparar(_foto(quando=_AGORA), _foto(quando=_AMANHA))
    assert not dif.mudou
    assert dif.resumo() == "igual"


def test_comparar_ve_o_que_sumiu_e_o_que_apareceu():
    """Recurso trocado: um some, outro aparece — nas duas listas, com a
    categoria certa. E o hash muda junto, porque o bundle é outro."""
    outro = _REACT.replace('"baseUrl","/attachments"',
                           '"baseUrl","/attachments-v2"')
    dif = sentinela.comparar(_foto(), _foto(react=outro))

    assert dif.contrato_mudou and dif.mudou
    assert dif.removidos["react/recursos"] == ["/attachments"]
    assert dif.adicionados["react/recursos"] == ["/attachments-v2"]
    assert dif.removidos["react/metodos"] == [
        "/attachments remove [delete] /attachments/",
        "/attachments upload [post] /attachments/v2"]
    assert any(b.startswith("react: bytes diferentes") for b in dif.bundles)
    assert dif.resumo().startswith("contrato mudou: -3 +3")


def test_comparar_build_novo_sem_mudar_o_contrato():
    """Bytes diferentes com o mesmo inventário: mudou, mas o contrato não."""
    novo = _REACT.replace('"10018"?"10018"', '"10019"?"10019"')
    dif = sentinela.comparar(_foto(), _foto(react=novo, nome="main-ffff.js"))

    assert dif.mudou and not dif.contrato_mudou
    assert not dif.removidos and not dif.adicionados
    assert "buildNumber 10018 -> 10019" in dif.bundles
    assert f"legado {_NOME_LEGADO} -> main-ffff.js" in dif.bundles
    assert "contrato mudou" not in dif.resumo()


def test_o_alerta_poe_o_que_sumiu_antes_do_que_apareceu():
    """Rota que sumiu é o que quebra o app; vem primeiro, e vem nomeada."""
    outro = _REACT.replace('{path:"/fiscal"},', '{path:"/fiscal-novo"},')
    dif = sentinela.comparar(_foto(), _foto(react=outro))

    texto = sentinela.texto_do_alerta(dif, _foto(react=outro), _AGORA)

    assert texto.index("SUMIU") < texto.index("APARECEU") < texto.index("BUNDLES")
    assert "  - react/telas: /fiscal\n" in texto
    assert "  - react/telas: /fiscal-novo\n" in texto
    assert "O CONTRATO do front do ERP mudou" in texto
    assert "python -m ferramentas.sonda" in texto      # sugere; não roda
    assert "08/09/2026 07:05:00" in texto


def test_o_alerta_de_build_novo_diz_que_o_contrato_nao_mudou():
    novo = _REACT + "/* build novo, mesmas rotas */"
    dif = sentinela.comparar(_foto(), _foto(react=novo))

    texto = sentinela.texto_do_alerta(dif, _foto(react=novo), _AGORA)

    assert "SEM mudança no inventário" in texto
    assert "SUMIU" not in texto and "APARECEU" not in texto


# ---------------------------------------------------------------- a rodada

def _saida():
    linhas = []
    return linhas, linhas.append


def test_primeira_fotografia_grava_e_nao_alarma(tmp_path):
    """Sem `ultimo.json` não há com o que comparar: grava, avisa, sai com 0."""
    baixar, _ = _transporte()
    linhas, escrever = _saida()

    codigo = sentinela.rodar(tmp_path, baixar, _AGORA, escrever)

    assert codigo == 0
    fotos = tmp_path / sentinela.PASTA_FOTOS
    assert (fotos / "ultimo.json").is_file()
    assert (fotos / "2026-09-08.json").is_file()
    assert json.loads((fotos / "ultimo.json").read_text(encoding="utf-8")) \
        == json.loads((fotos / "2026-09-08.json").read_text(encoding="utf-8"))
    assert not (tmp_path / sentinela.ARQUIVO_ALERTA).exists()
    registro = (tmp_path / sentinela.ARQUIVO_LOG).read_text(encoding="utf-8")
    assert registro.endswith("primeira fotografia\n")
    assert "08/09/2026 07:05:00" in registro and _NOME_LEGADO in registro
    assert any("Primeira fotografia" in l for l in linhas)


def test_mudanca_cria_o_alerta_e_sai_com_1(tmp_path):
    """Ontem `/attachments` existia; hoje não. ALERTA com o nome, código 1,
    e o `ultimo.json` passa a ser o de hoje — amanhã compara com hoje."""
    ontem, _ = _transporte()
    sentinela.rodar(tmp_path, ontem, _AGORA, lambda *_: None)
    hoje, _ = _transporte(react=_REACT.replace(
        '"baseUrl","/attachments";', '"baseUrl","/anexos";'))
    linhas, escrever = _saida()

    codigo = sentinela.rodar(tmp_path, hoje, _AMANHA, escrever)

    assert codigo == 1
    alerta = (tmp_path / sentinela.ARQUIVO_ALERTA).read_text(encoding="utf-8")
    assert "  - react/recursos: /attachments\n" in alerta
    assert "  - react/recursos: /anexos\n" in alerta
    assert alerta.index("/attachments\n") < alerta.index("/anexos\n")
    registro = (tmp_path / sentinela.ARQUIVO_LOG).read_text(encoding="utf-8")
    assert registro.count("\n") == 2
    assert "contrato mudou: -3 +3" in registro.splitlines()[-1]
    ultimo = json.loads((tmp_path / sentinela.PASTA_FOTOS / "ultimo.json")
                        .read_text(encoding="utf-8"))
    assert "/anexos" in ultimo["categorias"]["react/recursos"]
    assert (tmp_path / sentinela.PASTA_FOTOS / "2026-09-09.json").is_file()
    assert any("Mudou" in l for l in linhas)


def test_rodada_igual_apaga_o_alerta_e_sai_com_0(tmp_path):
    """A metade que ninguém percebe estar quebrada: o ALERTA tem de SUMIR."""
    ontem, _ = _transporte()
    sentinela.rodar(tmp_path, ontem, _AGORA, lambda *_: None)
    mudou, _ = _transporte(react=_REACT + "/* build novo */")
    assert sentinela.rodar(tmp_path, mudou, _AMANHA, lambda *_: None) == 1
    assert (tmp_path / sentinela.ARQUIVO_ALERTA).is_file()

    codigo = sentinela.rodar(tmp_path, mudou, datetime(2026, 9, 10, 7, 5),
                             lambda *_: None)

    assert codigo == 0
    assert not (tmp_path / sentinela.ARQUIVO_ALERTA).exists()
    registro = (tmp_path / sentinela.ARQUIVO_LOG).read_text(encoding="utf-8")
    assert registro.splitlines()[-1].endswith("|  igual")


def test_build_novo_sem_mudanca_no_contrato_tambem_alarma(tmp_path):
    """Bundle diferente é build novo do ERP — vale saber, mesmo que nenhuma
    rota tenha mudado. O ALERTA diz isso com essas palavras."""
    ontem, _ = _transporte()
    sentinela.rodar(tmp_path, ontem, _AGORA, lambda *_: None)
    hoje, _ = _transporte(react=_REACT.replace('"10018"?"10018"',
                                               '"10019"?"10019"'))

    codigo = sentinela.rodar(tmp_path, hoje, _AMANHA, lambda *_: None)

    assert codigo == 1
    alerta = (tmp_path / sentinela.ARQUIVO_ALERTA).read_text(encoding="utf-8")
    assert "SEM mudança no inventário" in alerta
    assert "buildNumber 10018 -> 10019" in alerta


def test_sem_rede_sai_com_1_e_nao_toca_na_fotografia_nem_no_alerta(tmp_path):
    """Uma manhã sem rede não pode virar a fotografia de referência, nem
    apagar um alarme de ontem que ninguém viu ainda."""
    ontem, _ = _transporte()
    sentinela.rodar(tmp_path, ontem, _AGORA, lambda *_: None)
    ultimo = tmp_path / sentinela.PASTA_FOTOS / "ultimo.json"
    antes = ultimo.read_text(encoding="utf-8")
    alerta = tmp_path / sentinela.ARQUIVO_ALERTA
    alerta.write_text("alarme de ontem\n", encoding="utf-8")
    sem_rede, _ = _transporte(erro=OSError("sem DNS"))
    linhas, escrever = _saida()

    codigo = sentinela.rodar(tmp_path, sem_rede, _AMANHA, escrever)

    assert codigo == 1
    assert ultimo.read_text(encoding="utf-8") == antes
    assert alerta.read_text(encoding="utf-8") == "alarme de ontem\n"
    assert not (tmp_path / sentinela.PASTA_FOTOS / "2026-09-09.json").exists()
    ultima = (tmp_path / sentinela.ARQUIVO_LOG).read_text(
        encoding="utf-8").splitlines()[-1]
    assert "falhou" in ultima and "sem DNS" in ultima
    assert any("Não deu para fotografar" in l for l in linhas)


def test_ultimo_json_corrompido_vira_primeira_fotografia(tmp_path):
    """Arquivo quebrado conta como "não há": grava por cima em vez de morrer
    todo dia no mesmo JSON."""
    fotos = tmp_path / sentinela.PASTA_FOTOS
    fotos.mkdir()
    (fotos / "ultimo.json").write_text("{isto não é json", encoding="utf-8")
    baixar, _ = _transporte()

    codigo = sentinela.rodar(tmp_path, baixar, _AGORA, lambda *_: None)

    assert codigo == 0
    assert json.loads((fotos / "ultimo.json").read_text(encoding="utf-8"))
    registro = (tmp_path / sentinela.ARQUIVO_LOG).read_text(encoding="utf-8")
    assert "primeira fotografia" in registro


def test_mostrar_imprime_o_inventario_e_nao_grava(monkeypatch):
    """`--mostrar` é olhar, não fotografar: nada no disco, nada comparado."""
    baixar, _ = _transporte()
    monkeypatch.setattr(sentinela, "gravar",
                        lambda *_a, **_k: pytest.fail("gravou com --mostrar"))
    monkeypatch.setattr(sentinela, "comparar",
                        lambda *_a, **_k: pytest.fail("comparou com --mostrar"))
    linhas, escrever = _saida()

    codigo = sentinela.mostrar(baixar, escrever)

    assert codigo == 0
    texto = "\n".join(linhas)
    assert "build 10018" in texto and _NOME_LEGADO in texto
    assert "react/recursos (2)" in texto
    assert "  /payable-installments pay [post] /payable-installments/ /paids" in texto
    assert "legado/telas (2)" in texto


def test_main_com_pasta_usa_o_baixar_do_modulo(tmp_path, monkeypatch):
    """Quem entra por `main()` também é dublável: o transporte é resolvido
    na chamada, não congelado como valor padrão do parâmetro."""
    baixar, pedidos = _transporte()
    monkeypatch.setattr(sentinela, "baixar", baixar)
    monkeypatch.setattr(sentinela, "print", lambda *_a, **_k: None,
                        raising=False)

    codigo = sentinela.main(["--pasta", str(tmp_path)])

    assert codigo == 0
    assert len(pedidos) == 3
    assert (tmp_path / sentinela.PASTA_FOTOS / "ultimo.json").is_file()


def test_o_get_leva_user_agent_de_chrome(monkeypatch):
    """Sem ele o WAF devolve 403 — e a sentinela viraria alarme diário."""
    visto = {}

    class _Resposta:
        def read(self):
            return b"conteudo"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def urlopen(req, timeout=None):
        visto["ua"] = req.get_header("User-agent")
        visto["timeout"] = timeout
        visto["metodo"] = req.get_method()
        return _Resposta()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert sentinela.baixar("https://exemplo.test/x.js") == b"conteudo"
    assert visto == {"ua": USER_AGENT, "timeout": sentinela.TIMEOUT_S,
                     "metodo": "GET"}


def test_a_sentinela_nunca_loga():
    """Ela só conhece o índice e o React por URL; o login do ERP não aparece
    no módulo — nem `URL_LOGIN`, nem `Sessao`, nem `credenciais`."""
    fonte = sentinela.__file__
    with open(fonte, encoding="utf-8") as f:
        texto = f.read()
    corpo = texto.split('"""', 2)[2]          # tira o docstring do módulo
    for proibido in ("URL_LOGIN", "Sessao(", "credenciais", "users/login",
                     "jwtToken", "accessToken"):
        assert proibido not in corpo, proibido
