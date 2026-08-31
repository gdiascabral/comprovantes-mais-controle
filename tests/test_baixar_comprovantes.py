# -*- coding: utf-8 -*-
"""O motor do Inter, na parte que não depende do banco estar no ar.

O que dá para provar aqui é o que o script de terminal NÃO tinha: as recusas
que acontecem antes do QR, a regra de parada e a separação de perfis. O
caminho de navegador não tem dublê de propósito — um dublê do site do Inter
provaria só que o dublê concorda com o código, e o que precisa concordar é o
banco. A prova daquele lado é a rodada com QR de verdade.
"""
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from baixar_comprovantes import inter_baixar as inter  # noqa: E402


# ------------------------------------------------------------- o período

def test_periodo_de_tras_para_frente_e_recusado_antes_do_QR():
    """Recusar aqui, e não na tela: o erro só apareceria depois de a pessoa
    ter ido buscar o celular e escaneado."""
    with pytest.raises(inter.InterFalhou):
        inter.conferir_periodo("30/08/2026", "01/08/2026")


def test_periodo_maior_que_noventa_dias_e_recusado():
    """O Inter só consulta 90 dias. Pedir mais devolve tela vazia — que se lê
    como "não houve pagamento nenhum", e é a leitura errada."""
    with pytest.raises(inter.InterFalhou) as e:
        inter.conferir_periodo("01/01/2026", "30/08/2026")
    assert "90" in str(e.value)


@pytest.mark.parametrize("inicio,fim", [("", "30/08/2026"),
                                        ("30-08-2026", "31/08/2026"),
                                        ("31/02/2026", "01/03/2026")])
def test_data_que_nao_e_data_e_recusada(inicio, fim):
    with pytest.raises(inter.InterFalhou):
        inter.conferir_periodo(inicio, fim)


def test_periodo_bom_volta_normalizado():
    assert inter.conferir_periodo(" 01/08/2026 ", "30/08/2026") == (
        "01/08/2026", "30/08/2026")


def test_o_chip_da_tela_e_conferido_contra_o_que_se_pediu():
    """A única confirmação que o Inter dá é esse texto. Sem conferi-lo, dava
    para baixar o mês errado inteiro achando que se filtrou."""
    assert inter.periodo_confere("01/08/2026 - 30/08/2026",
                                 "01/08/2026", "30/08/2026")
    assert not inter.periodo_confere("01/07/2026 - 30/08/2026",
                                     "01/08/2026", "30/08/2026")
    assert not inter.periodo_confere("", "01/08/2026", "30/08/2026")


# --------------------------------------------------------- nome repetido

def test_comprovante_de_nome_repetido_nao_sobrescreve(tmp_path):
    """Dois Pix do mesmo valor, para o mesmo favorecido, no mesmo dia: o Inter
    sugere o MESMO nome para os dois. Sobrescrever apagaria o comprovante de
    um pagamento que aconteceu."""
    (tmp_path / "comprovante.pdf").write_bytes(b"o primeiro")
    segundo = inter.nome_livre(tmp_path, "comprovante.pdf")
    assert segundo.name == "comprovante_1.pdf"
    segundo.write_bytes(b"o segundo")
    assert inter.nome_livre(tmp_path, "comprovante.pdf").name == "comprovante_2.pdf"


# ----------------------------------------------------------- quando parar

def test_falhas_seguidas_param_o_lote():
    """Cinco seguidas é o site dizendo alguma coisa — bloqueio, mudança de
    tela, sessão caindo. Insistir a partir daí piora o bloqueio."""
    assert inter.deve_parar([10, 11, 12, 13, 14], 14)


def test_falha_esparsa_nao_para_nada():
    """Comprovante problemático é normal, e o lote tem de seguir."""
    assert not inter.deve_parar([1, 10, 11, 12, 14], 14)
    assert not inter.deve_parar([3], 3)
    assert not inter.deve_parar([], 0)


# ------------------------------------------------------ um perfil por conta

def test_cada_conta_tem_o_seu_perfil_de_chrome():
    """No Inter cada conta é um login. Um perfil só faria a segunda conta
    entrar como a primeira — e baixar os comprovantes da errada, sem nada na
    tela dizendo isso."""
    a = inter.pasta_do_perfil("MORAIS ENG 50022")
    b = inter.pasta_do_perfil("OUTRA EMPRESA 90011")
    assert a != b
    assert a.name.startswith(".chrome_profile_inter_")


def test_nome_de_conta_com_barra_nao_vira_subpasta():
    """`/` e `\\` num nome de conta criariam pasta dentro de pasta — e o perfil
    do Chrome nasceria no lugar errado."""
    p = inter.pasta_do_perfil("MORAIS ENG / 50022 \\ PIX")
    assert "/" not in p.name and "\\" not in p.name


def test_conta_sem_nome_ainda_tem_perfil():
    assert inter.pasta_do_perfil("").name.endswith("conta")


# ------------------------------------------------------------ o desfecho

def test_sem_lancamentos_nao_e_falha():
    """Segunda-feira sem Pix é um dia normal. Era o caso que o script antigo
    lia como "login não concluído", depois de 60 s parado."""
    r = inter.Resultado(conta="X", total_na_tela=0)
    assert r.ok
    assert "sem lançamentos" in r.resumo()


def test_o_resumo_conta_o_que_deu_e_o_que_faltou(tmp_path):
    r = inter.Resultado(conta="X", total_na_tela=10,
                        baixados=[tmp_path / f"{i}.pdf" for i in range(8)],
                        falhas=[3, 7])
    assert r.ok and r.quantos == 8
    assert "8 de 10" in r.resumo() and "2 falharam" in r.resumo()


def test_motivo_preenchido_e_o_que_a_tela_mostra():
    r = inter.Resultado(conta="X", motivo="não consegui ligar o filtro 'Saída'")
    assert not r.ok
    assert r.resumo() == "não consegui ligar o filtro 'Saída'"


def test_a_marca_de_tela_e_por_conteudo_e_nao_exata():
    """Basta UMA marca: o Inter troca rótulo sem avisar, e exigir todas faria
    uma palavra nova derrubar o motor."""
    assert inter.tela_diz("Extrato de Pix — Saída", inter.MARCAS_DE_EXTRATO)
    assert not inter.tela_diz("carregando...", inter.MARCAS_DE_EXTRATO)
    assert inter.tela_diz("Acesse sua conta com o QR Code",
                          inter.MARCAS_DE_LOGIN)


# --------------------------------------------------- o segundo passe (2ª via)
# Um QR, dois passes: o Extrato Pix e depois a tela "Comprovante 2ª via", na
# MESMA sessão. O Inter pede o código a cada abertura, então tudo o que precisa
# da sessão tem de caber nela.

def test_o_resumo_separa_boleto_de_pix(tmp_path):
    """Quem lê a pill precisa saber que os dois passes rodaram — 46 e 46+3 são
    a mesma frase se o boleto não aparecer."""
    r = inter.Resultado(conta="X", total_na_tela=46, total_2via=3,
                        baixados=[tmp_path / f"{i}.pdf" for i in range(49)])
    assert "49 de 49" in r.resumo()
    assert "+3 de boleto" in r.resumo()


def test_sem_boleto_o_resumo_nao_inventa_coluna():
    r = inter.Resultado(conta="X", total_na_tela=46, total_2via=0,
                        baixados=[])
    assert "boleto" not in r.resumo()


def test_a_2via_nunca_e_a_origem_dos_pix():
    """O PDF da 2ª via vem SEM descrição, e descrição é o que faz o Anexar
    casar. Se alguém um dia trocar o filtro para "Pix" achando que simplifica,
    o casamento quebra sem quebrar teste nenhum — este teste é o aviso."""
    tipos = [t for t, _rotulo in inter.TIPOS_DA_2VIA]
    assert tipos == ["Pagamento", "DARF"]
    assert "Pix" not in tipos, (
        "Pix por esta tela vem sem descrição, e descrição é o que faz o "
        "Anexar casar sozinho")
    # O texto conferido na linha é o que a coluna Tipo mostra, em maiúsculas.
    for tipo, rotulo in inter.TIPOS_DA_2VIA:
        assert rotulo == rotulo.upper()
        assert rotulo.startswith(tipo[:4].upper())


def test_os_seletores_da_2via_nao_dependem_de_classe_gerada():
    """As classes da tela são styled-components (`sc-fgSWkL jVOOTC`) e mudam a
    cada build do banco. Ancorar nelas é escrever código com data de validade."""
    for seletor in (inter.SEL_LINHA, inter.SEL_CELULAS):
        assert "sc-" not in seletor
        assert "role=" in seletor


# ------------------------------------------ o período, lido da própria linha
# Três tentativas de preencher o filtro de data da tela falharam, e a terceira
# falhou CALADA: o site ignorou o que foi digitado e a busca saiu com os três
# meses padrão — 71 comprovantes onde se pediu 13, sem um erro na tela. A data
# passou a sair da linha, que é o que o banco afirma ter acontecido.

def test_a_data_vem_da_linha():
    assert inter.data_da_linha("PAGAMENTO 28/08/2026 R$ 108,39")
    assert inter.data_da_linha("PAGAMENTO 28/08/2026 R$ 108,39").day == 28


def test_linha_sem_data_nao_tem_data():
    assert inter.data_da_linha("PAGAMENTO R$ 108,39") is None
    assert inter.data_da_linha("") is None


@pytest.mark.parametrize("linha,dentro", [
    ("PAGAMENTO 24/08/2026 R$ 1,00", True),    # o primeiro dia entra
    ("PAGAMENTO 31/08/2026 R$ 1,00", True),    # o último também
    ("PAGAMENTO 28/08/2026 R$ 1,00", True),
    ("PAGAMENTO 23/08/2026 R$ 1,00", False),   # um dia antes
    ("PAGAMENTO 01/09/2026 R$ 1,00", False),   # um dia depois
    ("PAGAMENTO 15/06/2026 R$ 1,00", False),   # o padrão de três meses da tela
])
def test_o_periodo_e_fechado_dos_dois_lados(linha, dentro):
    assert inter.dentro_do_periodo(linha, "24/08/2026", "31/08/2026") is dentro


def test_linha_sem_data_legivel_fica_de_fora():
    """De fora, e não dentro. Pular um comprovante vira "sem anexo" na
    conferência, que alguém vê; baixar o que não se sabe datar é três meses
    virarem "a semana passada" sem ninguém notar."""
    assert not inter.dentro_do_periodo("PAGAMENTO R$ 108,39",
                                       "24/08/2026", "31/08/2026")


def test_periodo_invalido_nao_deixa_tudo_passar():
    """O contrário seria o pior desfecho: período quebrado virando "baixe
    tudo"."""
    assert not inter.dentro_do_periodo("PAGAMENTO 28/08/2026 R$ 1,00",
                                       "", "31/08/2026")


def test_o_tipo_procurado_sobrevive_ao_laco_que_le_as_datas():
    """O laço que lê as datas chamava a sua variável de `texto` — o mesmo nome
    do PARÂMETRO com o tipo procurado. Ele pisava no parâmetro, e o download
    passava a procurar linhas contendo o conteúdo inteiro da última linha
    lida: nenhuma casava, e cada uma vinha vazia, sem td e sem HTML.

    Custou quatro leituras de QR procurando na tela um defeito que era uma
    variável reaproveitada. O teste lê o código porque o defeito só aparece
    com o banco na frente — e aí é tarde."""
    import inspect

    fonte = inspect.getsource(inter._baixar_um_tipo)
    corpo = fonte.split("escolhidas, fora = [], []")[1]
    assert "texto =" not in corpo, (
        "o laço voltou a atribuir `texto`, que é o parâmetro com o tipo")
    assert "_linhas_do_tipo(page, texto)" in corpo, (
        "o download tem de filtrar pelo TIPO, não pelo texto de uma linha")


# ----------------------------------------------------- a 2ª via pela API
# A tela é uma casca sobre duas chamadas. Falar com elas resolve o que a casca
# cobrou caro: o filtro de data existia o tempo todo em `dataInicio`/`dataFim`,
# a lista não pagina, e o histórico é de 24 meses.

def _operacao(codigo="554362970", tipo="PAGAMENTO"):
    return {
        "dataEfetivacao": "28/08/2026",
        "valor": "R$ 108,39",
        "classificacao": {"tipo": tipo, "operacao": "PAGAMENTO_BOLETO_COBRANCA"},
        "pagamento": {"codigoLancamento": codigo},
    }


def test_o_pedido_do_pdf_sai_dos_campos_certos():
    """O de-para foi lido da chamada que a própria tela faz."""
    assert inter.pedido_de_pdf(_operacao()) == {
        "tipo": "PAGAMENTO",
        "operacao": "PAGAMENTO_BOLETO_COBRANCA",
        "codigo": "554362970",
        "dataEfetivacao": "28/08/2026",
    }


@pytest.mark.parametrize("faltando", ["codigo", "tipo", "data"])
def test_operacao_incompleta_nao_vira_pedido(faltando):
    """Pedir com campo vazio volta um HTTP 400 genérico, e o motivo — QUAL
    item estava quebrado — se perde dentro dele."""
    op = _operacao()
    if faltando == "codigo":
        op["pagamento"] = {}
    elif faltando == "tipo":
        op["classificacao"] = {"operacao": "X"}
    else:
        op["dataEfetivacao"] = ""
    assert inter.pedido_de_pdf(op) is None


def test_o_nome_do_arquivo_carrega_o_pagamento():
    """O nome que a API sugere é um carimbo de hora: inútil na pasta e inútil
    para o Anexar. Data, valor e código identificam sem ambiguidade."""
    assert inter.nome_do_comprovante(_operacao()) ==         "PAGAMENTO_2026-08-28_108-39_554362970.pdf"


def test_o_nome_sobrevive_a_operacao_capenga():
    """Sem data e sem valor o nome fica feio, mas não estoura no meio do
    lote — e um arquivo com nome feio é achável; um lote interrompido, não."""
    nome = inter.nome_do_comprovante({})
    assert nome.endswith(".pdf") and "/" not in nome


def test_os_dois_tipos_da_api_sao_os_que_o_dono_pediu():
    assert inter.TIPOS_DA_API == ("PAGAMENTO", "DARF")


# ------------------------------------------------------------- o token
# Prometido a quem usa: o cabeçalho de sessão não é gravado, não é impresso e
# não sai da execução. Promessa que não vira teste é promessa que se esquece —
# esta lê o código e cobra.

def test_o_token_nunca_vai_para_o_log():
    import inspect

    fonte = inspect.getsource(inter)
    suspeitas = []
    for n, linha in enumerate(fonte.splitlines(), start=1):
        chama_log = "log(" in linha or "print(" in linha
        tem_token = "cabecalho" in linha or "autorizacao" in linha
        # A linha que ATRIBUI não imprime; o que se proíbe é o par.
        if chama_log and tem_token and "não vou mostrá-lo" not in linha:
            suspeitas.append(f"{n}: {linha.strip()[:70]}")
    assert not suspeitas, (
        "o cabeçalho de sessão apareceu junto de um log: "
        + " · ".join(suspeitas))


def test_o_token_nao_e_gravado_em_arquivo():
    """Nem em disco, nem devolvido para quem chamou guardar sem querer."""
    import inspect

    fonte = inspect.getsource(inter.escutar_autorizacao)
    for proibido in ("write_text", "write_bytes", "open(", "json.dump"):
        assert proibido not in fonte, (
            f"`escutar_autorizacao` usa {proibido}: o cabeçalho tem de viver "
            "só em memória")


# --------------------------------------------------------- o Pix pela API

def _movimentacao(valor=116.56, nome="Pex", descricao="", origem="CHAVE",
                  tipo="D", data="28/08/2026", e2e="E0041696820260828"):
    return {"data": data, "valor": valor, "nome": nome, "tipoExtrato": "PIX",
            "tipo": tipo, "descricao": descricao,
            "detalhePix": {"endToEnd": e2e, "origemMovimento": origem,
                           "descricaoPagamento": "", "campoLivre": ""}}


def test_so_pix_de_saida_entra():
    """`tipo == D` é o que a tela chamava de filtro "Saída". Comprovante de
    Pix RECEBIDO na pasta de pagamento é o erro que a validação da fase 3
    existe para pegar."""
    assert inter.e_pix_enviado(_movimentacao(tipo="D"))
    assert not inter.e_pix_enviado(_movimentacao(tipo="C"))


def test_o_codigo_do_pix_e_o_endToEnd():
    """De graça no JSON, e é o mesmo identificador que a fase 3 do plano ia
    extrair de dentro do PDF para não baixar em dobro."""
    pedido = inter.pedido_de_pdf_pix(_movimentacao(), "362674043")
    assert pedido["codigo"] == "E0041696820260828"
    assert pedido["contaCorrente"] == "362674043"
    assert pedido["tipo"] == "PIX" and pedido["operacao"] == "PAGAMENTO_PIX"


def test_sem_endToEnd_ou_sem_conta_nao_vira_pedido():
    assert inter.pedido_de_pdf_pix(_movimentacao(e2e=""), "362674043") is None
    assert inter.pedido_de_pdf_pix(_movimentacao(), "") is None


def test_o_valor_no_nome_nao_perde_os_centavos():
    """Ele chega como número (116.56); tirar a pontuação dava `11656`, que se
    lê como onze mil. Saiu assim em 46 arquivos antes de alguém reparar."""
    assert "116-56" in inter.nome_do_pix(_movimentacao(valor=116.56))
    assert "3523-72" in inter.nome_do_pix(_movimentacao(valor=3523.72))
    assert "5-00" in inter.nome_do_pix(_movimentacao(valor=5))


def test_a_descricao_entra_no_nome_quando_existe():
    """44 de 46 Pix por chave trazem descrição (medido em 31/08/2026), e é por
    ela que o Anexar casa. No nome, dispensa abrir o PDF."""
    nome = inter.nome_do_pix(_movimentacao(descricao="NF 4521 obra RPB"))
    assert "NF 4521 obra RPB" in nome


def test_sem_descricao_o_nome_nao_fica_com_sobra():
    """QR Code não traz descrição — 0 de 7 no mesmo extrato."""
    nome = inter.nome_do_pix(_movimentacao(origem="QR_CODE"))
    assert nome.endswith("_Pex.pdf")


def test_a_descricao_e_procurada_nos_tres_lugares():
    m = _movimentacao()
    m["detalhePix"]["campoLivre"] = "veio do campo livre"
    assert inter.descricao_do_pix(m) == "veio do campo livre"


def test_a_conta_de_descricoes_separa_por_origem():
    """A pergunta "Pix traz descrição?" foi respondida por AMOSTRA e a amostra
    era um QR Code — o único caso onde ela nunca vem. Contar por origem é o
    que troca opinião por medida."""
    contas = inter.contar_descricoes([
        _movimentacao(descricao="tem", origem="CHAVE"),
        _movimentacao(descricao="", origem="CHAVE"),
        _movimentacao(descricao="", origem="QR_CODE"),
    ])
    assert contas["CHAVE"] == {"total": 2, "com_descricao": 1}
    assert contas["QR_CODE"] == {"total": 1, "com_descricao": 0}


# ------------------------------------------------- as contas do Inter
# O Sicoob enumera as contas sozinho: basta entrar e perguntar. No Inter cada
# conta e um login separado, entao alguem tem de declarar quais sao.

def _arquivo(tmp_path, dados):
    import json
    (tmp_path / "contas_inter.json").write_text(
        json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_le_as_contas_declaradas(tmp_path):
    from baixar_comprovantes import contas_inter

    pasta = _arquivo(tmp_path, {"contas": [
        {"apelido": "MORAIS ENG", "empresa": "MORAIS ENG", "pasta": "INTER"},
        {"apelido": "VXZ", "empresa": "VXZ"}]})
    contas = contas_inter.carregar(pasta)
    assert [c.apelido for c in contas] == ["MORAIS ENG", "VXZ"]
    assert contas[1].pasta == "INTER", "sem pasta declarada, o padrão é INTER"


def test_sem_arquivo_nao_e_erro(tmp_path):
    """Quem só usa Sicoob nunca precisa dele, e a aba tem de abrir assim
    mesmo — mostrando as contas do Sicoob e dizendo que o Inter não foi
    declarado."""
    from baixar_comprovantes import contas_inter

    assert contas_inter.carregar(tmp_path) == []


def test_arquivo_torto_nao_derruba_a_aba(tmp_path):
    """Um JSON quebrado não pode impedir o resto do trabalho."""
    from baixar_comprovantes import contas_inter

    (tmp_path / "contas_inter.json").write_text("{isso não é json",
                                                encoding="utf-8")
    assert contas_inter.carregar(tmp_path) == []


def test_linha_sem_apelido_ou_sem_empresa_e_ignorada(tmp_path):
    """O apelido dá nome à pasta de perfil do Chrome, e a empresa diz onde
    arquivar. Sem um dos dois, a conta não tem como ser percorrida — entrar na
    fila só para falhar na vez dela seria pior."""
    from baixar_comprovantes import contas_inter

    pasta = _arquivo(tmp_path, {"contas": [
        {"apelido": "", "empresa": "X"},
        {"apelido": "Y", "empresa": ""},
        {"apelido": "BOM", "empresa": "BOM"}]})
    assert [c.apelido for c in contas_inter.carregar(pasta)] == ["BOM"]


# ------------------------------------------------------------ onde cai
# Uma pasta `Comprovantes`, e dentro dela uma por data. TUDO junto: sem
# separar por conta nem por empresa, porque e assim que o Anexar precisa --
# ele varre uma pasta e casa cada comprovante pelo conteudo do nome.

def test_uma_subpasta_por_dia_de_download():
    import datetime

    from baixar_comprovantes import comprovantes_frame as cf

    alvo = cf.pasta_da_rodada("D:/x", datetime.date(2026, 8, 31))
    assert alvo.name == "2026-08-31"
    assert alvo.parent.name == "x"


def test_a_data_e_a_do_download_e_nao_a_do_pagamento():
    """Ela responde "o que eu baixei hoje?", que é a pergunta de quem está com
    a pasta aberta. A data do pagamento já está no nome de cada arquivo."""
    import datetime

    from baixar_comprovantes import comprovantes_frame as cf

    hoje = datetime.date.today()
    assert cf.pasta_da_rodada("D:/x").name == hoje.strftime("%Y-%m-%d")


def test_o_padrao_fica_ao_lado_do_app():
    """Para ninguém ser obrigado a escolher pasta antes de baixar o primeiro
    comprovante."""
    from baixar_comprovantes import comprovantes_frame as cf

    assert cf.pasta_padrao().name == "Comprovantes"


# -------------------------------------------- o 400 do Sicoob, separado
# Na primeira rodada de verdade, 6 das 13 contas responderam HTTP 400 -- e as
# tres que funcionaram tinham exatamente UM comprovante cada. O Sicoob diz
# "nao ha nada aqui" com 400, em vez de lista vazia.

def test_400_de_conta_parada_nao_e_falha():
    """Conta sem movimento virando pill vermelha faz alguem procurar defeito
    onde nao ha -- e num dia normal a maioria das 13 contas esta parada."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb.e_conta_sem_movimento(
        {"status": 400, "corpo": "Nenhum registro encontrado"})
    assert sb.e_conta_sem_movimento(
        {"status": 400, "corpo": "NAO FORAM ENCONTRADOS COMPROVANTES"})


def test_400_de_outra_coisa_continua_sendo_falha():
    """Sessao caida tambem responde 400, e essa precisa aparecer em vermelho.
    Tratar as duas igual esconde uma ou assusta com a outra."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert not sb.e_conta_sem_movimento(
        {"status": 400, "corpo": "periodo invalido"})
    assert not sb.e_conta_sem_movimento({"status": 401, "corpo": "nenhum registro"})
    assert not sb.e_conta_sem_movimento({"status": 400, "corpo": ""})


def test_a_falha_carrega_o_que_o_servidor_disse(monkeypatch):
    """"HTTP 400" sozinho nao separa conta parada de sessao caida."""
    from baixar_comprovantes import sicoob_baixar as sb

    class PaginaFalsa:
        def evaluate(self, *_a):
            return {"status": 400, "erro": "HTTP 400",
                    "corpo": "periodo fora do limite de 6 meses"}

    with pytest.raises(sb.SicoobFalhou) as e:
        sb.listar(PaginaFalsa(), "01/01/2020", "31/01/2020")
    assert "6 meses" in str(e.value)


def test_conta_parada_devolve_lista_vazia():
    from baixar_comprovantes import sicoob_baixar as sb

    class PaginaFalsa:
        def evaluate(self, *_a):
            return {"status": 400, "erro": "HTTP 400",
                    "corpo": "Nenhum registro encontrado"}

    assert sb.listar(PaginaFalsa(), "01/08/2026", "31/08/2026") == []


# ------------------------------------ a conta pedida e a conta que valeu
# Numa rodada com 13 contas, tres trouxeram o comprovante de OUTRA conta e
# seis deram HTTP 400 -- e as contas que falharam TINHAM movimento (Terra
# Bela, 17 pagamentos). A causa: `page.goto` numa URL com `#` recarrega a SPA
# inteira, e ela reinicia na conta PADRAO. Eu trocava de conta e em seguida
# desfazia a troca.

def test_a_conta_e_comparada_so_pelos_digitos():
    """`50.019-4` e `500194` sao a mesma conta; a tela escreve de um jeito e
    o cadastro de outro."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb.mesma_conta("50.019-4", "50.019-4")
    assert sb.mesma_conta("50.019-4", "500194")
    assert not sb.mesma_conta("50.019-4", "50.021-6")


def test_sem_conta_na_tela_nao_e_a_mesma():
    """Nao conseguir LER a conta e diferente de ler e bater. Na duvida, nao
    baixa -- comprovante de outra conta com o nome desta e pior que nenhum."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert not sb.mesma_conta("50.019-4", "")
    assert not sb.mesma_conta("", "50.019-4")


def test_a_navegacao_nao_recarrega_a_pagina():
    """`goto` recarrega e joga fora a conta escolhida. O caminho e mexer no
    `location.hash`, que dispara a rota sem recarregar."""
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb.ir_para_comprovantes)
    assert "location.hash" in sb.JS_IR_PARA
    assert ".goto(" not in fonte, (
        "voltou a usar goto: a SPA recarrega e a conta volta para a padrao")
import pathlib  # noqa: E402


# --------------------------------------------- nao baixar o mesmo duas vezes
# Rodar o mesmo periodo duas vezes trazia tudo de novo: o desempate de nome
# (`_1`, `_2`) impedia a sobrescrita, entao nada se perdia -- mas a pasta
# enchia de copias e o Anexar via dois comprovantes onde houve um pagamento.

def test_a_chave_separa_bancos_e_contas():
    """O idAgendamento do Sicoob e o codigoLancamento do Inter sao numeradores
    de bancos diferentes: um acerto por acaso silenciaria um comprovante de
    verdade. E o Sicoob numera POR CONTA, entao a conta tambem entra."""
    from baixar_comprovantes import ja_baixados as jb

    assert jb.chave("sicoob", "15057364", "50.019-4") !=         jb.chave("sicoob", "15057364", "50.021-6")
    assert jb.chave("inter2via", "15057364") != jb.chave("sicoob", "15057364")


def test_o_registro_lembra_entre_rodadas(tmp_path):
    from baixar_comprovantes import ja_baixados as jb

    r = jb.Registro(tmp_path)
    marca = jb.chave("pix", "E0041696820260828")
    assert not r.tem(marca)
    r.anotar(marca, tmp_path / "PIX_x.pdf")
    r.gravar()

    outro = jb.Registro(tmp_path)          # como na rodada seguinte
    assert outro.tem(marca)
    assert len(outro) == 1


def test_registro_ilegivel_nao_para_o_lote(tmp_path):
    """O pior caso de um registro corrompido e baixar de novo o que ja se
    tinha -- chato e reversivel. O contrario, deixar de baixar, perderia
    comprovante sem ninguem notar."""
    from baixar_comprovantes import ja_baixados as jb

    (tmp_path / jb.ARQUIVO).write_text("{isso nao e json", encoding="utf-8")
    r = jb.Registro(tmp_path)
    assert len(r) == 0
    assert not r.tem(jb.chave("pix", "qualquer"))


def test_pasta_somente_leitura_nao_derruba(tmp_path, monkeypatch):
    from baixar_comprovantes import ja_baixados as jb

    r = jb.Registro(tmp_path)
    r.anotar(jb.chave("pix", "x"), tmp_path / "a.pdf")
    monkeypatch.setattr(pathlib.Path, "write_text",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("ro")))
    r.gravar()                             # não levanta


def test_chave_vazia_nunca_conta_como_baixado(tmp_path):
    """Comprovante sem identificador tem de ser baixado, e nao pulado: pular
    o que nao se sabe identificar perderia comprovante em silencio."""
    from baixar_comprovantes import ja_baixados as jb

    r = jb.Registro(tmp_path)
    assert not r.tem("")
    r.anotar("", tmp_path / "a.pdf")
    assert len(r) == 0
