# -*- coding: utf-8 -*-
"""O pacote `nuvem` sem rede e sem tela.

O que estes testes protegem é a diferença entre os TRÊS desfechos de uma
chamada que não deu certo — "sem rede", "sua sessão venceu" e "o banco disse
não" —, porque cada um pede uma coisa diferente de quem está na frente da
tela, e confundi-los é como o app passa a mentir: um cadastro que não baixou
vira "tudo certo", e uma sessão vencida vira "erro inesperado".
"""
import http.server
import json
import sys
import threading
import time
from pathlib import Path

import pytest
import urllib3.util.retry

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
    # `rest` fala com o transporte por UM ponto so, a sessao do modulo — nao
    # mais `requests.request`/`requests.post` soltos. Trocar a funcao do
    # modulo `requests` nao pega mais nada: e a sessao quem tem o metodo.
    monkeypatch.setattr(rest._SESSAO, "request", falso)
    monkeypatch.setattr(rest._SESSAO, "post", falso)


def _jwt(exp: int, email: str = "quem@exemplo.com",
         sub: str = "11111111-1111-1111-1111-111111111111") -> str:
    """Um JWT de mentira: só o miolo importa, ninguém verifica assinatura.

    O `sub` é o mesmo user_id que o `auth.uid()` do banco enxerga — é de lá
    que o Postgres o tira."""
    import base64
    corpo = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "email": email, "sub": sub})
        .encode()).decode().rstrip("=")
    return f"cabecalho.{corpo}.assinatura"


# ------------------------------------------------------------------- rest

class _RespostaFalsa:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self._corpo = corpo

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


def test_401_e_403_deixam_de_falar_a_mesma_coisa():
    """Uma pede login, a outra pede permissao no banco -- e o recado era igual.

    Em 24/08/2026 um cadastro recusado deixou as duas hipoteses abertas: nada
    na mensagem separava "sua sessao venceu" de "esta tabela nao aceita
    escrita", e as duas pedem coisas opostas de quem le.
    """
    import pytest
    from nuvem import rest

    with pytest.raises(rest.PrecisaEntrar) as venceu:
        rest._resposta(_RespostaFalsa(401, {"message": "JWT expired"}))
    assert "sessão venceu" in str(venceu.value) and "401" in str(venceu.value)

    with pytest.raises(rest.PrecisaEntrar) as recusou:
        rest._resposta(_RespostaFalsa(403, {"message": "violates row-level security"}))
    texto = str(recusou.value)
    assert "permissão" in texto and "403" in texto
    assert "row-level security" in texto, "o motivo do servidor se perdeu"


def test_recusa_sem_corpo_ainda_diz_o_status():
    import pytest
    from nuvem import rest

    with pytest.raises(rest.PrecisaEntrar) as e:
        rest._resposta(_RespostaFalsa(403))
    assert "403" in str(e.value)


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


# --------------------------------------------------- sessao e novas tentativas
# Estes dois não trocam a resposta por um dublê que finge a espera: sobem um
# servidor HTTP local de verdade e deixam o `Retry` de requests/urllib3
# decidir sozinho quando insistir. É a prova de que a POLÍTICA (3 tentativas,
# só GET, 502 a 504) está de fato montada no adaptador — não só escrita.

def _servidor_instavel(respostas: list, corpos: list | None = None):
    """HTTP local que responde `respostas[i]` (e `corpos[i]`) na i-ésima
    chamada, repetindo a última depois de esgotar a lista. `contador` guarda
    quantas chamadas chegaram e por qual método — é o que o teste confere."""
    contador = {"chamadas": 0, "metodos": []}
    corpos = corpos or [b""] * len(respostas)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _responder(self):
            i = min(contador["chamadas"], len(respostas) - 1)
            contador["chamadas"] += 1
            contador["metodos"].append(self.command)
            corpo = corpos[i]
            self.send_response(respostas[i])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            self._responder()

        def do_POST(self):
            self._responder()

        def log_message(self, *_a):
            pass  # silêncio: não poluir a saída do pytest com acesso HTTP

    servidor = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, contador


def _sessao_local(monkeypatch, servidor):
    """Uma sessão com a MESMA política de retry da produção (`_montar_sessao`
    de verdade, não uma cópia à mão), só que também válida para `http://` —
    o módulo só usa `https://`, e o servidor de teste não tem TLS."""
    sessao_teste = rest._montar_sessao()
    sessao_teste.mount("http://", sessao_teste.get_adapter("https://x"))
    monkeypatch.setattr(rest, "_SESSAO", sessao_teste)
    monkeypatch.setattr(rest, "URL", f"http://127.0.0.1:{servidor.server_port}")
    # Sem isto o teste esperaria de verdade o backoff (uns 2s) a cada rodada.
    # O que importa aqui é QUANTAS vezes e COM QUE MÉTODO, não a espera real.
    monkeypatch.setattr(urllib3.util.retry.time, "sleep", lambda *_a, **_k: None)


def test_get_repete_5xx_ate_o_sucesso(monkeypatch):
    """Um 504 passageiro do gateway (como o que ficou no diagnostico.log de
    produção) não pode virar rodada perdida: GET insiste, até 3 vezes, e
    devolve o que veio na terceira."""
    servidor, contador = _servidor_instavel(
        [504, 504, 200], [b"", b"", b'[{"id": 1}]'])
    try:
        _sessao_local(monkeypatch, servidor)
        assert rest.ler("conta", "tok") == [{"id": 1}]
        assert contador["chamadas"] == 3
        assert contador["metodos"] == ["GET", "GET", "GET"]
    finally:
        servidor.shutdown()


def test_post_nao_repete_5xx(monkeypatch):
    """Reenviar um POST que criou algo e perdeu a resposta duplicaria o que
    foi criado (cadastro em dobro) — por isso só GET tem novas tentativas, e
    o 504 único vira a mesma exceção nomeada de sempre, sem insistir."""
    servidor, contador = _servidor_instavel([504])
    try:
        _sessao_local(monkeypatch, servidor)
        with pytest.raises(rest.RecusadoPeloBanco):
            rest.inserir("empresa", "tok", [{"nome_pasta": "X"}])
        assert contador["chamadas"] == 1
        assert contador["metodos"] == ["POST"]
    finally:
        servidor.shutdown()


# ----------------------------------------------------------------- sessao

def test_sem_arquivo_e_precisa_entrar(tmp_path):
    with pytest.raises(rest.PrecisaEntrar):
        sessao.token(tmp_path)


def test_token_no_prazo_nao_fala_com_o_servidor(tmp_path, monkeypatch):
    """Toda chamada à nuvem passa por aqui: uma viagem de rede neste caminho
    seria uma viagem por chamada.

    A sessão do teste vem COMPLETA, com papel e situação, porque é assim que
    ela fica desde o primeiro login. A única exceção — a sessão gravada por
    versão anterior a esta, que não tem papel — busca o perfil uma vez por
    execução, e quem prova o freio é
    `test_a_busca_do_papel_perdido_nao_se_repete_a_cada_chamada`."""
    bom = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": bom, "renovacao": "r", "email": "quem@exemplo.com",
        "papel": "operador", "situacao": "ativo"})
    _responder(monkeypatch, AssertionError("nao devia ter chamado a rede"))
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
    assert sessao._sub("nem.parece.jwt") == ""
    assert sessao._email("") == ""


# ------------------------------------------------------------------ perfil
# O papel de cada um viaja junto da sessão desde 30/08/2026. O que estes
# testes seguram é a diferença entre "o servidor disse que esta conta ainda
# não foi liberada" e "não deu para perguntar": a primeira é uma resposta, a
# segunda é a ausência dela, e tratá-las igual é como uma oscilação de rede
# vira gente sem aba nenhuma.

@pytest.fixture(autouse=True)
def _perfil_do_zero():
    """A busca de recuperação é uma por execução — e cada teste é uma."""
    sessao._ja_procurei_o_perfil = False
    yield
    sessao._ja_procurei_o_perfil = False


def _caminhos_pedidos(monkeypatch) -> list:
    """Guarda os caminhos que o `rest` pediu, sem falar com rede nenhuma."""
    pedidos = []

    def falso(_metodo, url, **_kw):
        pedidos.append(url)
        return _Resposta(200, [])
    monkeypatch.setattr(rest._SESSAO, "request", falso)
    return pedidos


def test_o_perfil_pedido_e_o_do_proprio_usuario(monkeypatch):
    """Para o ADMIN a RLS não filtra nada: ele lê a tabela inteira.

    Sem o `user_id=eq.` no pedido, o app do admin receberia a fila de
    aprovação toda e leria o papel da primeira linha que viesse."""
    pedidos = _caminhos_pedidos(monkeypatch)
    rest.perfil("tok", "22222222-2222-2222-2222-222222222222")
    assert len(pedidos) == 1
    assert "user_id=eq.22222222-2222-2222-2222-222222222222" in pedidos[0]
    assert "limit=1" in pedidos[0]


def test_perfil_sem_user_id_nao_chega_a_perguntar(monkeypatch):
    """Token ilegível não pode virar uma leitura sem filtro."""
    pedidos = _caminhos_pedidos(monkeypatch)
    assert rest.perfil("tok", "") is None
    assert pedidos == []


def test_conta_sem_linha_de_perfil_responde_None(monkeypatch):
    _responder(monkeypatch, _Resposta(200, []))
    assert rest.perfil("tok", "abc") is None


def _entrando(monkeypatch, perfil):
    """Login que dá certo. `perfil` é o que o banco responde — ou o que ele
    levanta, quando é uma exceção."""
    gravado = {}
    acesso = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao.rest, "entrar", lambda _e, _s: {
        "access_token": acesso, "refresh_token": "r"})
    monkeypatch.setattr(sessao, "_gravar",
                        lambda s, _p=None: gravado.update(s))

    def responder(_tok, _uid):
        if isinstance(perfil, Exception):
            raise perfil
        return perfil
    monkeypatch.setattr(sessao.rest, "perfil", responder)
    return gravado, acesso


def test_login_guarda_o_papel_junto_do_token(tmp_path, monkeypatch):
    gravado, acesso = _entrando(monkeypatch, {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "nome": "Quem Usa", "email": "quem@exemplo.com",
        "papel": "aprovador", "situacao": "ativo"})
    assert sessao.entrar("quem@exemplo.com", "senha", tmp_path) == acesso
    assert gravado["papel"] == "aprovador"
    assert gravado["situacao"] == "ativo"
    assert gravado["nome"] == "Quem Usa"
    assert gravado["user_id"] == "11111111-1111-1111-1111-111111111111"


def test_conta_sem_perfil_no_banco_entra_como_pendente(tmp_path, monkeypatch):
    """O critério de pronto da fase: conta nova cai em pendente, e entra."""
    gravado, acesso = _entrando(monkeypatch, None)
    assert sessao.entrar("nova@exemplo.com", "senha", tmp_path) == acesso
    assert gravado["situacao"] == "pendente"
    assert gravado["papel"] == "operador"


def test_perfil_mudo_nao_impede_o_login(tmp_path, monkeypatch):
    """A senha estava certa e o token está na mão: derrubar aqui seria trocar
    uma oscilação de rede por "não consigo entrar"."""
    gravado, acesso = _entrando(monkeypatch, rest.SemRede("caiu"))
    assert sessao.entrar("quem@exemplo.com", "senha", tmp_path) == acesso
    assert gravado["acesso"] == acesso


def test_perfil_mudo_nao_apaga_o_papel_que_ja_se_sabia(tmp_path, monkeypatch):
    """Senão a pessoa perderia as abas por causa do wi-fi."""
    gravado, _acesso = _entrando(monkeypatch, rest.SemRede("caiu"))
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "email": "chefe@exemplo.com", "nome": "Nome Do Chefe",
        "papel": "admin", "situacao": "ativo"})
    sessao.entrar("chefe@exemplo.com", "senha", tmp_path)
    assert gravado["papel"] == "admin"
    assert gravado["situacao"] == "ativo"
    assert gravado["nome"] == "Nome Do Chefe"


def test_renovar_o_token_atualiza_o_papel(tmp_path, monkeypatch):
    """Liberado às 9h: às 10h, na renovação, as abas aparecem sozinhas."""
    gravado = {}
    velho = _jwt(int(time.time()) - 10)
    novo = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": velho, "renovacao": "r", "email": "quem@exemplo.com",
        "papel": "operador", "situacao": "pendente"})
    monkeypatch.setattr(sessao, "_gravar", lambda s, _p=None: gravado.update(s))
    monkeypatch.setattr(sessao.rest, "renovar", lambda _r: {
        "access_token": novo, "refresh_token": "r2"})
    monkeypatch.setattr(sessao.rest, "perfil", lambda _t, _u: {
        "nome": "Quem Usa", "papel": "operador", "situacao": "ativo"})
    assert sessao.token(tmp_path) == novo
    assert gravado["situacao"] == "ativo"


def test_sessao_de_versao_anterior_ganha_o_papel_sem_pedir_senha(
        tmp_path, monkeypatch):
    """No dia da atualização o token guardado ainda vale por até uma hora.

    Sem esta busca o app abriria sem renovar e, portanto, sem nunca perguntar
    quem é a pessoa — numa manhã em que o menu se monta pelo papel, é a equipe
    inteira sem abas."""
    gravado = {}
    bom = _jwt(int(time.time()) + 3600)
    antiga = {"acesso": bom, "renovacao": "r", "email": "quem@exemplo.com"}
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: antiga)
    monkeypatch.setattr(sessao, "_gravar", lambda s, _p=None: gravado.update(s))
    monkeypatch.setattr(
        sessao.rest, "renovar",
        lambda _r: pytest.fail("não devia renovar: o token ainda vale"))
    monkeypatch.setattr(sessao.rest, "perfil", lambda _t, _u: {
        "nome": "Quem Usa", "papel": "admin", "situacao": "ativo"})
    assert sessao.token(tmp_path) == bom
    assert gravado["papel"] == "admin"


def test_a_busca_do_papel_perdido_nao_se_repete_a_cada_chamada(
        tmp_path, monkeypatch):
    """Sem freio, um app aberto sem internet pagaria a espera do `rest` em
    cada chamada — por uma informação que só serve para desenhar o menu."""
    tentativas = []
    bom = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": bom, "renovacao": "r", "email": "quem@exemplo.com"})
    monkeypatch.setattr(sessao, "_gravar", lambda _s, _p=None: None)

    def caiu(_t, _u):
        tentativas.append(1)
        raise rest.SemRede("caiu")
    monkeypatch.setattr(sessao.rest, "perfil", caiu)
    for _ in range(5):
        assert sessao.token(tmp_path) == bom
    assert len(tentativas) == 1


def test_quem_devolve_o_email_e_o_papel(tmp_path, monkeypatch):
    """O critério de pronto da fase, do lado de quem lê."""
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": _jwt(int(time.time()) + 60,
                       sub="33333333-3333-3333-3333-333333333333"),
        "email": "chefe@exemplo.com", "nome": "Nome Do Chefe",
        "papel": "aprovador", "situacao": "ativo"})
    eu = sessao.quem(tmp_path)
    assert eu.email == "chefe@exemplo.com"
    assert eu.papel == "aprovador"
    assert eu.aprovador and eu.ativo and eu.conhecido
    assert not eu.admin and not eu.pendente
    assert eu.primeiro_nome == "Nome"
    assert eu.user_id == "33333333-3333-3333-3333-333333333333"


def test_quem_sem_ninguem_entrado_nao_estoura(tmp_path):
    eu = sessao.quem(tmp_path)
    assert not eu
    assert eu.email == "" and eu.papel == ""
    assert not eu.conhecido and not eu.admin


def test_situacao_vazia_nao_e_pendente(tmp_path, monkeypatch):
    """Ainda-nao-perguntei e espera-aprovacao sao coisas diferentes.

    Esconder tudo de quem ficou sem internet e o app sumindo sozinho."""
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "email": "quem@exemplo.com", "papel": "", "situacao": ""})
    eu = sessao.quem(tmp_path)
    assert not eu.conhecido
    assert not eu.pendente and not eu.ativo


# ------------------------------------------------------------- criar conta
# A pessoa cria a própria conta desde 30/08/2026, e a senha nunca passa pelo
# app: vai do campo para o servidor. O que estes testes seguram é a diferença
# entre criar conta e ENTRAR — são coisas separadas de propósito, e a segunda
# só acontece depois que um administrador libera.

def _cadastrando(monkeypatch, resposta):
    """Guarda o que foi enviado ao /signup e responde o que o teste mandar."""
    enviado = {}

    def falso(url, headers=None, json=None, timeout=None):
        enviado["url"] = url
        enviado["corpo"] = json
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
    monkeypatch.setattr(rest._SESSAO, "post", falso)
    return enviado


def test_criar_conta_manda_o_nome_no_metadata(monkeypatch):
    """O gatilho do banco copia o nome de `raw_user_meta_data` para o perfil.

    Sem ele, o admin veria uma fila de e-mails sem gente para aprovar."""
    enviado = _cadastrando(monkeypatch, _Resposta(200, {"id": "abc"}))
    assert rest.criar_conta("Fulano De Tal", " novo@exemplo.com ",
                            "uma-senha-boa") is True
    assert enviado["url"].endswith("/auth/v1/signup")
    assert enviado["corpo"]["email"] == "novo@exemplo.com"
    assert enviado["corpo"]["password"] == "uma-senha-boa"
    assert enviado["corpo"]["data"]["nome"] == "Fulano De Tal"


def test_criar_conta_nao_entra(tmp_path, monkeypatch):
    """Criar e entrar são coisas diferentes: a sessão só nasce depois que a
    pessoa clica no link que chegou no endereço que ela digitou — é isso que
    prova que o endereço é dela."""
    _cadastrando(monkeypatch, _Resposta(200, {"id": "abc"}))
    rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "uma-senha-boa")
    assert not sessao.tem_sessao(tmp_path)


def test_conta_que_ja_nasce_confirmada_avisa_que_nao_precisa_confirmar(
        monkeypatch):
    """Se vier token, a confirmação de e-mail está DESLIGADA no projeto — e
    quem está na tela precisa ouvir outra frase."""
    _cadastrando(monkeypatch, _Resposta(200, {"access_token": "t",
                                              "user": {"id": "abc"}}))
    assert rest.criar_conta("Fulano De Tal", "novo@exemplo.com",
                            "uma-senha-boa") is False


def test_cadastro_desligado_diz_onde_ligar(monkeypatch):
    """A recusa mais provável na estreia — e a única que quem lê não resolve
    sozinho. Sem dizer ONDE se liga, vira telefonema."""
    _cadastrando(monkeypatch, _Resposta(
        422, {"msg": "Signups not allowed for this instance"}))
    with pytest.raises(rest.RecusadoPeloBanco) as e:
        rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "uma-senha-boa")
    assert "Authentication" in str(e.value)


def test_email_ja_cadastrado_manda_para_a_outra_aba(monkeypatch):
    _cadastrando(monkeypatch, _Resposta(
        422, {"msg": "User already registered"}))
    with pytest.raises(rest.RecusadoPeloBanco) as e:
        rest.criar_conta("Fulano De Tal", "velho@exemplo.com", "uma-senha-boa")
    assert "Entrar" in str(e.value)


def test_limite_de_tentativas_nao_e_culpa_de_quem_digitou(monkeypatch):
    _cadastrando(monkeypatch, _Resposta(
        429, {"msg": "email rate limit exceeded"}))
    with pytest.raises(rest.RecusadoPeloBanco) as e:
        rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "uma-senha-boa")
    assert "servidor" in str(e.value)


def test_as_tres_recusas_de_senha_dizem_coisas_diferentes(monkeypatch):
    """Curta, sem os tipos exigidos, e conhecida por vazada são problemas
    diferentes. Com a mesma frase para as três, a pessoa mexe no lugar errado
    — alonga uma senha que já é longa, ou embaralha uma que o servidor nem
    pede embaralhada."""
    curta = "Password should be at least 12 characters."
    tipos = ("Password should contain at least one character of each: "
             "abcdefghijklmnopqrstuvwxyz, ABCDEFGHIJKLMNOPQRSTUVWXYZ, "
             "0123456789.")
    vazada = ("Password is known to be weak and easy to guess, please choose "
              "a different one.")
    frases = {}
    for rotulo, msg in (("curta", curta), ("tipos", tipos),
                        ("vazada", vazada)):
        _cadastrando(monkeypatch, _Resposta(422, {"msg": msg}))
        with pytest.raises(rest.RecusadoPeloBanco) as e:
            rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "abc")
        frases[rotulo] = str(e.value)

    assert len(set(frases.values())) == 3, "as três saíram com a mesma frase"
    assert "curta demais" in frases["curta"]
    # O número que o painel configurou vem junto: sem ele a frase manda tentar
    # de novo sem dizer até onde.
    assert "12" in frases["curta"]
    assert "tipos de caractere" in frases["tipos"]
    assert "vazadas" in frases["vazada"]


def test_o_minimo_local_e_copia_do_servidor_e_nao_regra(monkeypatch):
    """Trava local mais dura que a do servidor recusa senha que o servidor
    aceitaria — e quem lê não tem como saber que foi o app quem disse não."""
    from nuvem import login_dialogo
    _cadastrando(monkeypatch, _Resposta(
        422, {"msg": "Password should be at least 6 characters."}))
    with pytest.raises(rest.RecusadoPeloBanco):
        rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "abc")
    assert login_dialogo.MINIMO_DA_SENHA == 6


def test_recusa_desconhecida_mostra_o_que_o_servidor_disse(monkeypatch):
    """Frase genérica em cima de causa nova esconde justamente a causa nova."""
    _cadastrando(monkeypatch, _Resposta(
        400, {"msg": "something we have never seen"}))
    with pytest.raises(rest.RecusadoPeloBanco) as e:
        rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "uma-senha-boa")
    assert "something we have never seen" in str(e.value)


def test_criar_conta_sem_rede_e_sem_rede(monkeypatch):
    _cadastrando(monkeypatch, rest.requests.RequestException("DNS"))
    with pytest.raises(rest.SemRede):
        rest.criar_conta("Fulano De Tal", "novo@exemplo.com", "uma-senha-boa")


# ------------------------------------------------------- liberado agora?

def test_reconferir_traz_a_liberacao_sem_fechar_o_app(tmp_path, monkeypatch):
    """O admin liberou agora. Ter de fechar e abrir o app para descobrir isso
    é o tipo de coisa que vira telefonema."""
    guardado = {"acesso": _jwt(int(time.time()) + 3600),
                "renovacao": "r", "email": "novo@exemplo.com",
                "papel": "operador", "situacao": "pendente"}
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: dict(guardado))
    monkeypatch.setattr(sessao, "_gravar",
                        lambda s, _p=None: guardado.update(s))
    monkeypatch.setattr(sessao.rest, "perfil", lambda _t, _u: {
        "nome": "Fulano De Tal", "papel": "operador", "situacao": "ativo"})
    agora = sessao.reconferir(tmp_path)
    assert agora.ativo
    assert guardado["situacao"] == "ativo"


def test_reconferir_sem_sessao_nao_estoura(tmp_path):
    """Quem chama está desenhando uma tela, não gravando nada."""
    assert not sessao.reconferir(tmp_path)


def test_papel_de_admin_desativado_nao_vale(tmp_path, monkeypatch):
    """Desligar alguém é `situacao`, não `papel` — a linha fica de pé para a
    auditoria saber quem era. Quem conferisse só o papel deixaria o desligado
    com os poderes dele."""
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "email": "exchefe@exemplo.com", "papel": "admin",
        "situacao": "desativado"})
    assert not sessao.quem(tmp_path).admin


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


# ----------------------------------- as contas do Inter descem com o cadastro
# No Inter cada conta e um LOGIN separado: ninguem as enumera, alguem precisa
# declarar quais sao. Enquanto essa declaracao era um arquivo escrito a mao,
# ela existia numa maquina so -- a aba mostrava 3 contas do Inter aqui e
# nenhuma no computador de outra pessoa, sem erro na tela.

def _com_inter(**extra):
    return _banco(
        empresa=[{"id": 1, "nome_pasta": "EMPRESA A", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""},
                 {"id": 2, "nome_pasta": "EMPRESA B", "cnpj": "", "vip_id": "",
                  "razao_social": "", "convenio": ""}],
        conta=[{"id": 9, "empresa_id": 1, "numero": "00.000-0", "agencia": "1",
                "nome_erp": "A", "pasta": "SICOOB", "banco": "SICOOB",
                "banco_codigo": "756", "sufixo": "", "ativa": True},
               # Conta do Inter: sem numero, porque o cadastro guarda numero
               # de Sicoob. Por isso ela nao entra no contas_sicoob.json.
               {"id": 10, "empresa_id": 2, "numero": None, "agencia": "",
                "nome_erp": "B", "pasta": "INTER", "banco": "INTER",
                "banco_codigo": "", "sufixo": "", "ativa": True}],
        configuracao=[{"chave": "raiz", "valor": "C:/x"}], **extra)


def _inter_gerado(tmp_path):
    return json.loads(
        (tmp_path / "contas_inter.json").read_text(encoding="utf-8"))["contas"]


def test_a_conta_do_inter_desce_para_o_arquivo_da_aba(tmp_path, monkeypatch):
    dados = _com_inter()
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    assert cadastro.sincronizar("tok", tmp_path).atualizou
    assert _inter_gerado(tmp_path) == [
        {"apelido": "EMPRESA B", "empresa": "EMPRESA B", "pasta": "INTER"}]


def test_a_conta_do_sicoob_nao_vai_parar_na_fila_do_inter(tmp_path, monkeypatch):
    """Uma conta do Sicoob na lista do Inter pediria um QR que nao existe."""
    dados = _com_inter()
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    assert [c["empresa"] for c in _inter_gerado(tmp_path)] == ["EMPRESA B"]


def test_o_inter_e_reconhecido_pelo_codigo_tambem(tmp_path, monkeypatch):
    """O cadastro tem os dois jeitos: umas linhas trazem `banco_codigo`,
    outras so o nome. Casar por um so deixaria metade das contas de fora."""
    dados = _com_inter()
    dados["conta"][1]["banco"] = ""
    dados["conta"][1]["banco_codigo"] = "077"
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    assert len(_inter_gerado(tmp_path)) == 1


def test_duas_contas_do_inter_na_mesma_empresa_nao_dividem_o_perfil(
        tmp_path, monkeypatch):
    """O apelido da nome a pasta de perfil do Chrome. Dois apelidos iguais =
    um perfil so: a segunda conta entraria logada na primeira, e baixaria os
    comprovantes dela."""
    dados = _com_inter()
    dados["conta"][1]["sufixo"] = "MATRIZ"
    dados["conta"].append(dict(dados["conta"][1], id=11, sufixo="FILIAL"))
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    apelidos = [c["apelido"] for c in _inter_gerado(tmp_path)]
    assert apelidos == ["EMPRESA B FILIAL", "EMPRESA B MATRIZ"]


def test_cadastro_sem_inter_nao_apaga_a_lista_que_existe(tmp_path, monkeypatch):
    """Mesma regra dos outros arquivos: nao troque cheio por vazio. Apagar a
    lista custaria tres leituras de QR para reconstrui-la."""
    cache.gravar_json("contas_inter.json",
                      {"contas": [{"apelido": "EMPRESA B",
                                   "empresa": "EMPRESA B",
                                   "pasta": "INTER"}]}, tmp_path)
    dados = _com_inter()
    dados["conta"] = dados["conta"][:1]          # so a do Sicoob
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])

    cadastro.sincronizar("tok", tmp_path)
    assert _inter_gerado(tmp_path)[0]["apelido"] == "EMPRESA B"


def test_o_leitor_da_aba_le_o_que_a_sincronizacao_escreve(tmp_path, monkeypatch):
    """As duas pontas do mesmo arquivo, no mesmo teste: quem escreve e quem
    le. Separadas, cada uma passa sozinha com um formato que a outra nao
    entende."""
    from baixar_comprovantes import contas_inter

    dados = _com_inter()
    monkeypatch.setattr(cadastro.rest, "ler", lambda t, *_a, **_k: dados[t])
    cadastro.sincronizar("tok", tmp_path)

    lidas = contas_inter.carregar(tmp_path)
    assert [(c.apelido, c.empresa, c.pasta) for c in lidas] == [
        ("EMPRESA B", "EMPRESA B", "INTER")]
