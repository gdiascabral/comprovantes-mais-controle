# -*- coding: utf-8 -*-
"""O bloco de guias da aba Acessórias.

Usa a fixture `raiz` do conftest (UM `Tk()` para a sessão inteira): módulo que
cria e destrói o próprio faz os seguintes pularem com "sem display".
"""
from datetime import date
from decimal import Decimal

import pytest

from guias import painel as mod
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao, Guia


def _decisao(acao, **campos):
    guia = Guia(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO",
                anx_id=campos.pop("anx_id", "111"), competencia="2026-09",
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    return Decisao(guia=guia, acao=acao, categoria="Honorários", **campos)


@pytest.fixture
def bloco(raiz):
    p = mod.GuiasPainel(raiz, aba=None, anx=None)
    yield p
    p.destroy()


def test_as_secoes_aparecem_na_ordem_do_trabalho(bloco):
    """Primeiro o que vai ser gravado, depois o que precisa de decisão, por
    último o que já está pronto."""
    assert mod.SECOES == (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)


def test_mostrar_separa_as_linhas_por_secao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3", motivo="não conheço")])

    assert bloco.quantas(ALTERAR) == 1
    assert bloco.quantas(CRIAR) == 1
    assert bloco.quantas(DECIDIR) == 1
    assert bloco.quantas(JA_LANCADO) == 0


def test_alterar_e_criar_nascem_marcados_e_decidir_nao(bloco):
    """Decidir não pode ser lançado por distração: nasce desmarcado e o botão
    nem o considera."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3"),
                   _decisao(JA_LANCADO, anx_id="4")])

    marcadas = [d.acao for d in bloco.marcadas()]
    assert sorted(marcadas) == sorted([ALTERAR, CRIAR])


def test_desmarcar_uma_linha_tira_ela_do_lancamento(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"), _decisao(ALTERAR, anx_id="2")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.alternar(iid)

    assert len(bloco.marcadas()) == 1


def test_aviso_de_divergencia_aparece_na_linha(bloco):
    """Review Focus 2: a divergência de valor tem de estar visível."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1",
                            aviso="a parcela está 620,00 e a guia diz 641,31")])
    iid = bloco.linhas_de(ALTERAR)[0]

    assert "620,00" in bloco.texto_da_linha(iid)


def test_lancar_sem_nada_marcado_nao_chama_o_executor(bloco):
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    chamadas = []
    bloco._executar = lambda *a, **k: chamadas.append(a)

    bloco.lancar()

    assert chamadas == []


def test_o_mes_padrao_e_o_ATUAL(bloco):
    """O bloco de envio de conciliações abre no mês ANTERIOR (fechamento); este
    abre no mês corrente, que é onde estão as guias a pagar."""
    hoje = date.today()

    assert bloco.periodo == (hoje.year, hoje.month)


def test_linha_com_obra_sugerida_e_marcada_para_o_dono_olhar(bloco):
    """Sugestão não é confirmação: a linha diz que aquilo é palpite."""
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    assert "?" in bloco.texto_da_linha(iid)


def test_editar_a_obra_troca_a_decisao_e_tira_a_marca_de_palpite(bloco):
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    bloco.editar(iid, "obra", "obra-7")

    assert bloco.decisoes[iid].obra_id == "obra-7"
    assert bloco.decisoes[iid].obra_sugerida is False
    assert "?" not in bloco.texto_da_linha(iid)


def test_duas_obras_de_mesmo_nome_nao_colapsam_na_escolha(bloco):
    """A obra decide a conta que paga. Duas obras homônimas guardadas num
    dicionário por nome deixariam só a última, e a escolha apontaria para a
    outra em silêncio."""
    bloco.obras = [{"id": "obra-1", "name": "CONDOMINIO IGUAL"},
                   {"id": "obra-2", "name": "CONDOMINIO IGUAL"},
                   {"id": "obra-3", "name": "CONDOMINIO UNICO"}]

    opcoes = bloco._opcoes_de("obra")

    assert sorted(opcoes.values()) == ["obra-1", "obra-2", "obra-3"]
    assert "CONDOMINIO UNICO" in opcoes


def test_sem_vencimento_do_pdf_mostra_o_do_portal_marcado_como_palpite(bloco):
    """I7: o `prz` do portal é palpite (o PDF não trouxe vencimento), e
    palpite tem de aparecer como palpite — mesma razão da obra sugerida."""
    decisao = _decisao(ALTERAR, anx_id="1")
    decisao.guia.vencimento = None
    decisao.guia.vencimento_portal = date(2026, 9, 18)
    bloco.mostrar([decisao])
    iid = bloco.linhas_de(ALTERAR)[0]

    assert "18/09" in bloco.texto_da_linha(iid)
    assert "?" in bloco.texto_da_linha(iid)


def test_editar_a_categoria_troca_a_decisao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.editar(iid, "categoria", "Outra Categoria")

    assert bloco.decisoes[iid].categoria == "Outra Categoria"
    assert "Outra Categoria" in bloco.texto_da_linha(iid)


def test_editar_campo_que_nao_se_edita_nao_muda_nada(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]
    antes = bloco.texto_da_linha(iid)

    bloco.editar(iid, "valor", "999,99")

    assert bloco.texto_da_linha(iid) == antes


def test_abrir_pdf_de_linha_sem_pdf_nao_explode(bloco):
    """Linha de "você decide" costuma ser justamente a que não tem PDF."""
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    iid = bloco.linhas_de(DECIDIR)[0]

    bloco.abrir_pdf(iid)          # não levanta


def test_parar_pede_parada_sem_derrubar_a_tela(bloco):
    bloco.parar()                 # sem rodada em pé: não faz nada e não quebra


# ------------------------------------------------------------ Tarefa 9: ERP

class _ExecutorFalso:
    """O `exec` de `AcessoriasFrame`, sem thread de verdade: só anota o que
    seria submetido, e NÃO executa — a fase 1 (portal) não pode abrir
    navegador nenhum dentro do teste."""

    def __init__(self, destino):
        self._destino = destino

    def submit(self, fn, *a):
        self._destino.append((fn, a))
        return None


class _AbaFalsa:
    def __init__(self):
        self.q = __import__("queue").Queue()
        self._parar = __import__("threading").Event()
        self.linhas = []
        self.mapa = None
        self.submetidos = []
        self.exec = _ExecutorFalso(self.submetidos)
        self.worker = None
        #: I10: o que a ABA (não o bloco de guias) está fazendo, para o teste
        #: simular o envio ao escritório rodando ao mesmo tempo.
        self._ocupada_com = None

    def _log(self, msg=""):
        self.linhas.append(msg)

    def _garantir_mapa(self):
        return False              # sem cadastro nesta falsa

    def ocupado(self):
        return self._ocupada_com


class _AnexarFalso:
    """O `AnexarFrame`, do tamanho que o painel usa."""

    def __init__(self, ocupado=False):
        self._ocupado = ocupado
        self.submetidos = []

    def avisar_se_ocupado(self, _dona):
        return self._ocupado

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.submetidos.append((rotulo, fn))
        return None          # não executa: o corpo fala com o ERP


def test_varrer_sem_o_mapa_das_contas_avisa_e_nao_abre_navegador(raiz):
    """Sem o cadastro não há vip_url nem pasta: abrir o Chrome só para
    descobrir isso custa meio minuto e assusta."""
    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert any("contas" in linha.lower() for linha in aba.linhas)


def test_lancar_anota_no_registro_mesmo_quando_o_erp_recusa(raiz, tmp_path,
                                                            monkeypatch):
    """Review Focus 5: a linha de erro fica registrada, e a rodada seguinte
    sabe que esta guia ainda não foi lançada."""
    from guias import registro as mod_registro
    from guias.modelos import ERRO, Resultado

    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    reg = mod_registro.Registro.carregar(tmp_path / "r.jsonl")
    monkeypatch.setattr(mod, "_sessao_do_erp",
                        lambda _p: (object(), object(), "user-1", object()))
    monkeypatch.setattr(mod.lancar, "alterar",
                        lambda *a, **k: Resultado(ERRO, motivo="o ERP recusou"))
    try:
        p._gravar([_decisao(ALTERAR, anx_id="1", trade_payable_id="tp-1")],
                  transporte=object(), catalogos=object(), id_usuario="user-1",
                  registro=reg, parcelas=[], regras=None, pasta_backup=tmp_path)
    finally:
        p.destroy()

    assert reg.ja_feito("701", "1", "2026-09") is None
    assert reg.linhas and reg.linhas[-1]["estado"] == ERRO


def test_parar_no_meio_do_lote_nao_perde_a_recorrencia_ja_gravada(
        raiz, tmp_path, monkeypatch):
    """I5: `regras.gravar()` tem de rodar mesmo quando o dono aperta Parar no
    meio do lote — senão a recorrência aprendida nas linhas que JÁ saíram
    certas evapora, e o mês seguinte não a acha: nasce um SEGUNDO título
    parcelado, com as parcelas do primeiro ainda abertas."""
    from guias import registro as mod_registro
    from guias import regras as mod_regras
    from guias.modelos import ALTERADO, Resultado

    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    reg = mod_registro.Registro.carregar(tmp_path / "r.jsonl")
    caminho_regras = tmp_path / "regras.json"
    regs = mod_regras.Regras.carregar(caminho_regras)
    chamadas = []

    def alterar_dublê(*a, **k):
        chamadas.append(1)
        if len(chamadas) == 1:
            # Simula o dono clicando "Parar" logo depois da 1ª linha sair
            # certa — antes de a 2ª ser processada.
            aba._parar.set()
        return Resultado(ALTERADO, tpid=f"tp-{len(chamadas)}")

    monkeypatch.setattr(mod.lancar, "alterar", alterar_dublê)
    decisoes = [_decisao(ALTERAR, anx_id="1", tipo="honorario",
                        trade_payable_id="tp-a", obra_id="obra-1"),
               _decisao(ALTERAR, anx_id="2", tipo="honorario",
                        trade_payable_id="tp-b", obra_id="obra-1")]
    try:
        p._gravar(decisoes, transporte=object(), catalogos=object(),
                  id_usuario="user-1", registro=reg, parcelas=[], regras=regs,
                  pasta_backup=tmp_path)
    finally:
        p.destroy()

    assert chamadas == [1], "a 2ª linha não podia ter sido processada"
    relidas = mod_regras.Regras.carregar(caminho_regras)
    assert relidas.recorrencia("honorario", "701") == {
        "trade_payable_id": "tp-1", "obra": "obra-1"}


def test_gravar_nao_relanca_guia_que_o_registro_ja_tem(raiz, tmp_path,
                                                       monkeypatch):
    """C2: clicar duas vezes em "Lançar o marcado" não pode relançar tudo —
    a segunda passada tem de reconferir o registro ANTES de gravar de novo."""
    from guias import registro as mod_registro
    from guias.modelos import ALTERADO, Resultado

    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    reg = mod_registro.Registro.carregar(tmp_path / "r.jsonl")
    reg.anotar(vip_id="701", anx_id="1", competencia="2026-09",
              acao=ALTERAR, estado=ALTERADO, tpid="tp-1", motivo="",
              anexos=["guia.pdf"])
    chamadas = []
    monkeypatch.setattr(
        mod.lancar, "alterar",
        lambda *a, **k: chamadas.append(1) or Resultado(ALTERADO, tpid="tp-2"))
    try:
        p._gravar([_decisao(ALTERAR, anx_id="1", trade_payable_id="tp-1")],
                  transporte=object(), catalogos=object(), id_usuario="user-1",
                  registro=reg, parcelas=[], regras=None, pasta_backup=tmp_path)
    finally:
        p.destroy()

    assert chamadas == [], "gravou de novo uma guia que o registro já tinha"
    assert len(reg.linhas) == 1, "o segundo clique escreveu uma linha nova"


def test_gravar_nao_recria_titulo_que_o_erp_ja_tem(raiz, tmp_path, monkeypatch):
    """C2, o lado do CRIAR: mesmo sem linha no registro local, se o ERP já tem
    título com este documento no mês, recriar duplicaria a conta a pagar."""
    from guias import registro as mod_registro
    from guias.modelos import CRIADO, Resultado

    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    reg = mod_registro.Registro.carregar(tmp_path / "r.jsonl")
    chamadas = []
    monkeypatch.setattr(
        mod.lancar, "criar",
        lambda *a, **k: chamadas.append(1) or Resultado(CRIADO, tpid="tp-novo"))
    parcelas = [{"documentNumber": "DOC-1", "tradePayableId": "tp-existente"}]
    try:
        p._gravar([_decisao(CRIAR, anx_id="1", obra_id="obra-1")],
                  transporte=object(), catalogos=object(), id_usuario="user-1",
                  registro=reg, parcelas=parcelas, regras=None,
                  pasta_backup=tmp_path)
    finally:
        p.destroy()

    assert chamadas == [], "criou um segundo título para um documento que já existe"


def test_obra_com_cadastro_incompleto_fica_fora_da_lista_e_avisa(raiz):
    """Item extra da revisão da Tarefa 8: obra sem nome ou sem id sumia da
    lista sem dizer nada, e é a obra que decide a conta que paga."""
    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    p.obras = [{"id": "obra-1", "name": "OBRA COMPLETA"},
               {"id": "", "name": "SEM ID"},
               {"id": "obra-3", "name": ""}]
    try:
        opcoes = p._opcoes_de("obra")
    finally:
        p.destroy()

    assert sorted(opcoes.values()) == ["obra-1"]
    assert any("2 obra" in linha for linha in aba.linhas)


# --------------------------------------------- Tarefa 9, rodada de conserto 1

def test_varrer_usa_o_executor_da_aba_e_nao_o_do_navegador(raiz):
    """A fase do PORTAL é do Chrome da aba Acessórias, que tem thread própria."""
    aba, anx = _AbaFalsa(), _AnexarFalso()
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    try:
        p.varrer()
    finally:
        p.destroy()

    assert aba.submetidos and not anx.submetidos


def test_casar_e_lancar_passam_pelo_executor_do_navegador(raiz):
    """Os objetos do Playwright pertencem à thread que os criou: tocá-los de
    outra dá erro de greenlet, e isso só apareceria no primeiro clique real."""
    aba, anx = _AbaFalsa(), _AnexarFalso()
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    try:
        p.casar([], 2026, 9)
        # `anx.submeter` aqui é dublê e de propósito NÃO executa `_t_casar`
        # (rodar o corpo chamaria o ERP de verdade). Em produção é `_t_casar`
        # — na thread do Anexar — quem grava a decisão na fila E zera
        # `_tarefa` no MESMO `finally`, os dois antes de o `_drain` (thread da
        # tela) sequer processar a mensagem e chamar `mostrar()`. Sem o dublê
        # rodar esse corpo, `_tarefa` nunca voltaria a "" sozinho — a linha
        # abaixo simula o ponto em que a fase 2 de verdade já teria terminado.
        p._tarefa = ""
        p.mostrar([_decisao(ALTERAR, anx_id="1")])
        p.lancar()
    finally:
        p.destroy()

    rotulos = [r for r, _fn in anx.submetidos]
    assert any("casar" in r for r in rotulos)
    assert any("lançar" in r for r in rotulos)
    assert aba.submetidos == []


def test_navegador_ocupado_recusa_casar_e_lancar(raiz):
    """Recusar ANTES de mexer em fila ou botão: quem sai por aqui não passa
    mais pelo _drain, e a aba ficaria travada."""
    aba, anx = _AbaFalsa(), _AnexarFalso(ocupado=True)
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    try:
        p.casar([], 2026, 9)
        p.mostrar([_decisao(ALTERAR, anx_id="1")])
        p.lancar()
    finally:
        p.destroy()

    assert anx.submetidos == []
    assert p.ocupado() is None


def test_varrer_recusa_quando_a_aba_ja_esta_ocupada(raiz):
    """I10: o `_parar` é da ABA, compartilhado com o envio de conciliações.
    Limpar aqui com o envio rodando desfaz a parada que o dono pediu para
    ele, e o envio volta a subir solicitações sozinho."""
    aba, anx = _AbaFalsa(), _AnexarFalso()
    aba._parar.set()                 # o dono pediu Parar no envio em curso
    aba._ocupada_com = "enviando ao escritório"
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    try:
        p.varrer()
    finally:
        p.destroy()

    assert aba.submetidos == []
    assert aba._parar.is_set(), "o clear() desfez a parada do envio em curso"
    assert any("enviando ao escritório" in linha for linha in aba.linhas)


def test_lancar_recusa_quando_a_aba_ja_esta_ocupada(raiz):
    """I10, o outro botão: mesma guarda para "Lançar o marcado"."""
    aba, anx = _AbaFalsa(), _AnexarFalso()
    aba._parar.set()
    aba._ocupada_com = "enviando ao escritório"
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    p.mostrar([_decisao(ALTERAR, anx_id="1")])
    try:
        p.lancar()
    finally:
        p.destroy()

    assert anx.submetidos == []
    assert aba._parar.is_set()


def test_obra_do_erp_falha_fechado_quando_nao_esta_no_catalogo(raiz):
    """I8a: obra fora do catálogo tem de devolver `{}`, e NUNCA
    `{"id": obra_id}` — mandar só o id cria o título sem centro de custo."""
    aba = _AbaFalsa()
    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    catalogos = type("C", (), {"obras": {"o1": {"id": "obra-1",
                                                "name": "OBRA UM"}}})()
    try:
        obra = p._obra_do_erp(catalogos, "obra-desconhecida")
    finally:
        p.destroy()

    assert obra == {}


def test_parar_na_fase_do_portal_nao_abre_o_erp(raiz):
    """I6: `calendario.varrer` só observa o `parar` ENTRE empresas e devolve
    o que já baixou; quem apertou Parar normalmente quer o ERP LIVRE — e o
    ERP aceita uma sessão por usuário. `casar()` não pode abrir a sessão do
    Mais Controle nesse caso."""
    aba, anx = _AbaFalsa(), _AnexarFalso()
    aba._parar.set()
    p = mod.GuiasPainel(raiz, aba=aba, anx=anx)
    try:
        p.casar([], 2026, 9)
    finally:
        p.destroy()

    assert anx.submetidos == []
    assert p.ocupado() is None
    assert any("não vou abrir" in linha for linha in aba.linhas)


# ------------------------------------- UM navegador do portal por aba (v2.0.209)
class _MapaFalso:
    raiz = "C:/nao/existe"
    vip_url = "https://exemplo.invalido/escritorio"
    empresas = []


class _PortalFalso:
    """O `PortalClient`, do tamanho que o `_t_varrer` usa."""

    abertos = []

    def __init__(self, vip_url, log=None, **kw):
        self.kw = kw
        self.fechado = False
        _PortalFalso.abertos.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechado = True

    def aguardar_login(self):
        pass


class _AbaComMapa(_AbaFalsa):
    def __init__(self):
        super().__init__()
        self.mapa = _MapaFalso()
        self.portal = None

    def _garantir_mapa(self):
        return True

    def _sicoob_mods(self):
        class _Cfg:
            @staticmethod
            def nome_do_mes(m):
                return "MES"

            @staticmethod
            def nome_pasta_empresa(a, m, nome):
                return "PASTA"
        return _Cfg(), None


def _preparar_portal(monkeypatch):
    _PortalFalso.abertos = []
    monkeypatch.setattr(mod, "PortalClient", _PortalFalso)
    monkeypatch.setattr(mod.calendario, "varrer",
                        lambda *a, **k: [])
    return _AbaComMapa()


def test_varrer_nao_abre_um_segundo_navegador_do_portal(raiz, monkeypatch):
    """A aba já mantém UM cliente do portal em `self.portal`.

    Abrir outro põe um segundo Chrome no MESMO `--user-data-dir`, que morre no
    berço ("Target page, context or browser has been closed"), e um segundo
    Playwright síncrono na mesma thread reclama de laço asyncio. Foi o que a
    primeira rodada real da v2.0.209 mostrou.
    """
    aba = _preparar_portal(monkeypatch)
    ja_aberto = _PortalFalso("url")
    _PortalFalso.abertos = []          # o de fora não conta para a medição
    aba.portal = ja_aberto

    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert _PortalFalso.abertos == [], "abriu um segundo navegador do portal"
    assert not ja_aberto.fechado, "fechou o navegador que era do envio"
    assert aba.portal is ja_aberto


def test_varrer_guarda_o_cliente_na_aba_e_o_deixa_aberto(raiz, monkeypatch):
    """Nunca um `with` local: navegador que só a própria thread enxerga não
    pode ser fechado por quem está saindo do app, e o Chrome fica aberto
    segurando o perfil — o defeito que o envio já teve e corrigiu.

    E ele FICA aberto quando a varredura acaba: quem fecha é o `fechar()` da
    aba, ao sair do app. Fechar aqui e reabrir na rodada seguinte corre com o
    Chrome que ainda está saindo, e a segunda varredura da v2.0.211 morreu
    assim — depois de já ter listado as doze empresas.
    """
    aba = _preparar_portal(monkeypatch)
    vistos = []
    monkeypatch.setattr(mod.calendario, "varrer",
                        lambda *a, **k: vistos.append(aba.portal) or [])

    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert len(_PortalFalso.abertos) == 1
    criado = _PortalFalso.abertos[0]
    assert vistos == [criado], "o cliente não estava em `aba.portal` durante o trabalho"
    assert not criado.fechado, "fechou ao fim da varredura; quem fecha é a aba"
    assert aba.portal is criado, "soltou a referência, e aí `fechar()` não o alcança"


def test_duas_varreduras_seguidas_usam_o_mesmo_navegador(raiz, monkeypatch):
    """A segunda rodada da v2.0.211 abriu um Chrome sobre o perfil que o
    primeiro ainda segurava, e morreu com "browser has been closed"."""
    aba = _preparar_portal(monkeypatch)

    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert len(_PortalFalso.abertos) == 1, "abriu um segundo navegador na 2a rodada"


def test_varrer_nao_abre_o_portal_escondido(raiz, monkeypatch):
    """O login do portal é manual. Em headless, sessão caída vira dez minutos
    de espera por um login que ninguém consegue fazer."""
    aba = _preparar_portal(monkeypatch)

    p = mod.GuiasPainel(raiz, aba=aba, anx=None)
    try:
        p._t_varrer(2026, 9)
    finally:
        p.destroy()

    assert _PortalFalso.abertos[0].kw.get("headless") is not True


# ---------------------------- o contexto da pagina que morre com a navegacao
def test_leitura_das_parcelas_refaz_quando_o_contexto_morre(monkeypatch):
    monkeypatch.setattr(mod, "ESPERA_ANTES_DE_REFAZER", 0)
    """`garantir_credenciais_anexos` ABRE a tela de um lançamento para ouvir a
    chamada de anexos — é navegação. Um `page.evaluate` disparado em cima dela
    morre com "Execution context was destroyed", e foi assim que a primeira
    rodada real da v2.0.211 parou, logo depois de "obras: 204".
    """
    tentativas = []

    def transporte_instavel(_url):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise RuntimeError(
                "Execution context was destroyed, most likely because of a "
                "navigation.")
        return {"content": [{"id": "par-1"}]}

    resposta = mod._com_contexto(transporte_instavel, "qualquer/url")

    assert len(tentativas) == 2, "não refez a leitura"
    assert resposta["content"] == [{"id": "par-1"}]


def test_erro_que_nao_e_de_contexto_sobe_na_hora():
    """Refazer qualquer erro esconderia defeito de verdade atrás de repetição."""
    tentativas = []

    def sempre_recusa(_url):
        tentativas.append(1)
        raise RuntimeError("o ERP recusou (HTTP 401)")

    with pytest.raises(RuntimeError, match="401"):
        mod._com_contexto(sempre_recusa, "qualquer/url")

    assert len(tentativas) == 1, "tentou de novo um erro que não é de corrida"


def test_contexto_que_morre_duas_vezes_nao_vira_laco(monkeypatch):
    monkeypatch.setattr(mod, "ESPERA_ANTES_DE_REFAZER", 0)
    tentativas = []

    def sempre_morre(_url):
        tentativas.append(1)
        raise RuntimeError("Execution context was destroyed")

    with pytest.raises(RuntimeError, match="Execution context"):
        mod._com_contexto(sempre_morre, "qualquer/url")

    assert len(tentativas) == 2, "insistiu mais que uma vez"


def test_a_leitura_das_parcelas_PASSA_pelo_refazer(raiz, monkeypatch):
    monkeypatch.setattr(mod, "ESPERA_ANTES_DE_REFAZER", 0)
    """Não basta o ajudante existir e ser testado sozinho: o que importa é a
    leitura das parcelas usá-lo. Testar a peça isolada e não o caminho que a
    contém foi o que deixou o bloco inteiro sair invisível na v2.0.208."""
    tentativas = []

    class _ApiInstavel:
        """Só tem `listar_a_pagar`.

        É de propósito: se alguém voltar a montar a URL à mão e chamar
        `buscar`/`page.evaluate`, este dublê estoura em AttributeError em vez
        de concordar com o engano. Foi essa URL escrita de memória que matou as
        quatro rodadas reais da v2.0.211/212.
        """

        def listar_a_pagar(self, inicio, fim, log=None):
            tentativas.append((inicio, fim))
            if len(tentativas) == 1:
                raise RuntimeError("Execution context was destroyed, most "
                                   "likely because of a navigation.")
            return [{"id": "par-1"}]

    p = mod.GuiasPainel(raiz, aba=None, anx=None)
    try:
        parcelas = p._parcelas_da_janela(_ApiInstavel(), 2026, 9)
    finally:
        p.destroy()

    assert len(tentativas) == 2, "a leitura não passa pelo refazer"
    assert parcelas == [{"id": "par-1"}]
    # Do dia 1 do mês ao último do MÊS SEGUINTE: outubro tem 31, e um
    # `monthrange` trocado por número fixo pediria uma data que o ERP recusa.
    assert tentativas[0] == ("2026-09-01", "2026-10-31")


def test_a_janela_de_dezembro_atravessa_o_ANO(raiz):
    """Mês + 1 em dezembro é janeiro do ano seguinte. Somar 1 ao mês daria
    2026-13-31, e aí a leitura inteira falha em dezembro — uma vez por ano,
    justamente na virada, quando ninguém está olhando."""
    pedidos = []

    class _Api:
        def listar_a_pagar(self, inicio, fim, log=None):
            pedidos.append((inicio, fim))
            return []

    p = mod.GuiasPainel(raiz, aba=None, anx=None)
    try:
        p._parcelas_da_janela(_Api(), 2026, 12)
    finally:
        p.destroy()

    assert pedidos == [("2026-12-01", "2027-01-31")]


@pytest.mark.parametrize("texto", [
    "Execution context was destroyed, most likely because of a navigation.",
    "TypeError: Failed to fetch\n    at https://exemplo.invalido/main.js:2:34",
])
def test_os_tres_textos_da_MESMA_corrida_sao_refeitos(texto, monkeypatch):
    """As três rodadas reais da v2.0.211 falharam no mesmo pedido, com textos
    diferentes: o contexto do `evaluate` morre, ou o `fetch` de dentro da
    página é abortado. É a mesma navegação no meio do caminho."""
    monkeypatch.setattr(mod, "ESPERA_ANTES_DE_REFAZER", 0)
    tentativas = []

    def instavel(_url):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise RuntimeError(texto)
        return {"ok": True}

    assert mod._com_contexto(instavel, "url") == {"ok": True}
    assert len(tentativas) == 2


def test_navegador_morto_NAO_e_refeito(monkeypatch):
    """"browser has been closed" não é corrida: é navegador morto, e repetir
    sobre ele não tem o que dar certo."""
    monkeypatch.setattr(mod, "ESPERA_ANTES_DE_REFAZER", 0)
    tentativas = []

    def morto(_url):
        tentativas.append(1)
        raise RuntimeError("Target page, context or browser has been closed")

    with pytest.raises(RuntimeError, match="has been closed"):
        mod._com_contexto(morto, "url")

    assert len(tentativas) == 1
