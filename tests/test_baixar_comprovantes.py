# -*- coding: utf-8 -*-
"""O motor do Inter, na parte que não depende do banco estar no ar.

O que dá para provar aqui é o que o script de terminal NÃO tinha: as recusas
que acontecem antes do QR, a regra de parada e a separação de perfis. O
caminho de navegador não tem dublê de propósito — um dublê do site do Inter
provaria só que o dublê concorda com o código, e o que precisa concordar é o
banco. A prova daquele lado é a rodada com QR de verdade.
"""

import pytest

from baixar_comprovantes import inter_baixar as inter


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


# -------------------------------------------- o layout do comprovante
# Um comprovante ja baixado (Transferencia entre Contas, 06/08/2026) saiu com
# a data, o titulo e a hora um em cima do outro, e o resto da folha vazio: o
# CSS do HTML do Sicoob e referenciado por caminho RELATIVO, e abrir o arquivo
# de fora do site (um arquivo solto em disco) nao resolve esse caminho -- o
# texto chega, o layout que o organiza nao.

def test_base_href_entra_dentro_do_head():
    from baixar_comprovantes import sicoob_baixar as sb

    html = "<html><head><title>x</title></head><body>y</body></html>"
    saida = sb._com_base_href(html, base="https://exemplo.teste/")
    assert '<base href="https://exemplo.teste/">' in saida
    assert saida.index("<base") < saida.index("<title>")


def test_base_href_cria_head_quando_falta():
    """O `detalhar` do Sicoob pode devolver so `<html><body>...`, sem head
    nenhum -- o `<base>` tem de nascer um, e ANTES do corpo."""
    from baixar_comprovantes import sicoob_baixar as sb

    html = "<html><body>y</body></html>"
    saida = sb._com_base_href(html, base="https://exemplo.teste/")
    assert '<base href="https://exemplo.teste/">' in saida
    assert saida.index("<base") < saida.index("<body>")


def test_base_href_na_frente_quando_nao_ha_moldura():
    """Sem `<html>` nem `<head>` -- so um fragmento --, o `<base>` entra na
    frente: e o unico jeito de garantir que ele vale antes de qualquer CSS
    referenciado no meio do fragmento."""
    from baixar_comprovantes import sicoob_baixar as sb

    html = "<div>fragmento sem moldura nenhuma</div>"
    saida = sb._com_base_href(html, base="https://exemplo.teste/")
    assert saida.startswith('<base href="https://exemplo.teste/">')
    assert "<div>fragmento" in saida


def test_o_padrao_aponta_para_o_site_do_sicoob():
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb.BASE_SICOOB == "https://ib.sicoob.com.br/sicoobnet/"


def test_html_para_pdf_ancora_o_html_antes_de_gravar():
    """`html_para_pdf` e "com tela" (abre aba, fala com CDP) e nao tem dublê
    de navegador de proposito -- ver o cabecalho deste arquivo. O que da para
    provar sem navegador e que ela PASSA pelo `_com_base_href` antes de
    escrever o arquivo temporario, e nao que ela imprime certo."""
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb.html_para_pdf)
    assert "_com_base_href(html)" in fonte, (
        "html_para_pdf parou de ancorar o HTML -- o comprovante volta a sair "
        "com o layout quebrado (data/titulo/hora um em cima do outro)")


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


# ------------------------------------------------ as duas telas do Sicoob
# Com o interruptor "Novo" ligado, o cabecalho escreve a conta como
# `3299 | 50.019-4 | PJ | HB2744` (no `.info-cliente-chave`); a tela antiga
# escreve `SICOOB ENGECRED 3299 CONTA 50.019-4 / PJ`. Lendo so a antiga, a
# rodada de 11/09/2026 recusou a primeira conta com "nao consegui ler".

def test_a_conta_sai_do_cabecalho_da_tela_nova():
    from extratos_sicoob import sicoob_client as sc

    assert sc.conta_do_cabecalho(" 3299 | 50.019-4 | PJ  | HB2744 ",
                                 "") == "50.019-4"


def test_a_conta_da_tela_nova_aceita_travessao():
    """A fonte do cabecalho desenha o hifen parecido com travessao; basta um
    campo vir com o caractere de verdade para a leitura voltar a dizer "nao
    consegui ler"."""
    from extratos_sicoob import sicoob_client as sc

    assert sc.conta_do_cabecalho("3299 | 50.019–4 | PJ",
                                 "") == "50.019–4"


def test_a_conta_da_tela_antiga_continua_sendo_lida():
    from extratos_sicoob import sicoob_client as sc

    corpo = "SICOOB ENGECRED 3299 CONTA 50.019-4 / PJ"
    assert sc.conta_do_cabecalho(None, corpo) == "50.019-4"


def test_o_cabecalho_novo_manda_no_corpo():
    """Na tela nova o corpo pode citar outra conta; a ABERTA e a do
    cabecalho."""
    from extratos_sicoob import sicoob_client as sc

    assert sc.conta_do_cabecalho("3299 | 50.019-4 | PJ",
                                 "CONTA 51.107-2") == "50.019-4"


def test_sem_nada_legivel_a_conta_e_vazia():
    from extratos_sicoob import sicoob_client as sc

    assert sc.conta_do_cabecalho(None, "Bem-vindo") == ""
    assert sc.conta_do_cabecalho("", "") == ""


def test_conta_aberta_le_pela_funcao_do_cliente():
    """Um parser so, para quem troca de conta e para quem confere antes de
    baixar: duas copias divergem em silencio."""
    from baixar_comprovantes import sicoob_baixar as sb

    class PaginaNova:
        def evaluate(self, *_a):
            return {"novo": " 3299 | 50.019-4 | PJ  | HB2744 ",
                    "corpo": "Conta corrente Saldo da conta"}

    assert sb.conta_aberta(PaginaNova()) == "50.019-4"
    assert sb.mesma_conta("50.019-4", sb.conta_aberta(PaginaNova()))


def test_na_tela_nova_a_troca_de_conta_clica_no_icone_do_cabecalho():
    """O endereco `#/selecao-contas` sozinho deixou a segunda conta esperando
    45s pela lista; o icone e o que a pessoa clicou para a rodada andar."""
    import inspect

    from extratos_sicoob import sicoob_client as sc

    assert 'icone="arrow-lr"' in sc.SEL_TROCAR_CONTA_NOVO
    fonte = inspect.getsource(sc.SicoobClient.ir_para_selecao)
    assert "SEL_TROCAR_CONTA_NOVO" in fonte
    assert fonte.index("SEL_TROCAR_CONTA_NOVO") < fonte.index(
        "URL_SELECAO_CONTAS"), "o endereco e o ultimo recurso, nao o primeiro"


def test_o_login_aceita_a_home_da_tela_nova():
    """Esperar so pela lista deixava o robo parado na Home ate a pessoa
    clicar no icone de trocar conta."""
    import inspect

    from extratos_sicoob import sicoob_client as sc

    assert "div.seletor-conta" in sc.SINAIS_DE_LOGIN
    assert ".info-cliente-chave" in sc.SINAIS_DE_LOGIN
    fonte = inspect.getsource(sc.SicoobClient.aguardar_login)
    assert "SINAIS_DE_LOGIN" in fonte
    assert "ir_para_selecao" in fonte, (
        "depois de entrar pela Home, o login tem de deixar a lista na tela")


# --------------------------------------------------------------- o Pix do Sicoob
# A tela de Comprovantes nao tem Pix -- e outra tela, com API propria. O
# exemplo abaixo e o mesmo lido da Rede do navegador em 10/09/2026 (anonimizado:
# nomes, CPF e CNPJ trocados -- o repositorio e publico).

def _pix_sicoob(id_="E0000000000000000000000000000000",
               nome_pagador="EMPRESA TESTE LTDA", cnpj_pagador="11222333000181",
               nome_dest="Fulano de Tal", cpf_dest="12345678909",
               valor="1208,36", estado="FINALIZADO_SUCESSO",
               meio="CHAVE"):
    return {
        "id": id_,
        "origem": {"nome": nome_pagador, "cpfCnpj": cnpj_pagador,
                  "banco": {"NomeBanco": "COOPERATIVA DE CREDITO TESTE"}},
        "destino": {"nome": nome_dest, "cpfCnpj": cpf_dest,
                   "banco": {"NomeBanco": "BANCO DESTINO S.A."}},
        "valor": valor,
        "estado": estado,
        "tipo": "DEBITO",
        "atualizadoEm": "2026-09-08 17:57:30.37",
        "criadoEm": "2026-09-08 17:57:29.63",
        "meioIniciacaoPix": meio,
    }


def test_o_cnpj_do_pagador_sai_mascarado():
    """`**.222.333/0001-**` -- os dois primeiros e os dois últimos dígitos
    saem cobertos, como o próprio Sicoob mostra no comprovante."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb._mascarar_documento("11222333000181") == "**.222.333/0001-**"


def test_o_cpf_do_destinatario_sai_mascarado():
    """`***.456.789-**` -- os três primeiros e os dois últimos dígitos saem
    cobertos."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb._mascarar_documento("12345678909") == "***.456.789-**"


def test_documento_de_tamanho_estranho_nao_estoura():
    """Nem 11 nem 14 dígitos: devolve como veio, em vez de recortar índice
    que não existe."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb._mascarar_documento("123") == "123"
    assert sb._mascarar_documento("") == ""


def test_a_hora_sai_do_carimbo_do_banco():
    from baixar_comprovantes import sicoob_baixar as sb

    assert sb._hora_pix("2026-09-08 17:57:29.63") == "17:57:29"
    assert sb._hora_pix("") == ""
    assert sb._hora_pix("sem hora nenhuma") == ""


def test_campos_do_pix_sicoob_saem_do_json_sem_abrir_pdf():
    """Ao contrário do Sicoob comum (`do_sicoob`), aqui não há PDF para
    abrir: pagador, destinatário, valor e data já vêm estruturados."""
    from baixar_comprovantes import nome_final as nf

    campos = nf.do_sicoob_pix(_pix_sicoob())
    assert campos["valor"] == "1.208,36"
    assert campos["data"] == "08/09/2026"
    assert campos["dest"] == "Fulano de Tal"
    assert campos["desc"] is None, (
        "o JSON do Pix do Sicoob não traz descrição -- inventar uma aqui "
        "esconderia que o Anexar vai casar só por valor/data/destinatário")
    assert campos["pag"] is None


def test_valor_com_milhar_tambem_converte():
    """`"90.000,00"` (formato BR completo) -- não é só o caso sem ponto que
    o exemplo medido trouxe."""
    from baixar_comprovantes import nome_final as nf

    assert nf._numero_brl("90.000,00") == 90000.0
    assert nf._numero_brl("1208,36") == 1208.36
    assert nf._numero_brl("") is None
    assert nf._numero_brl(None) is None


def test_destinatario_ausente_nao_quebra_o_nome():
    """`destino` vazio (o Sicoob não garante o campo) não pode estourar --
    é melhor um nome incompleto do que um lote interrompido."""
    from baixar_comprovantes import nome_final as nf

    campos = nf.do_sicoob_pix({"valor": "10,00"})
    assert campos["dest"] is None


def test_nome_provisorio_do_pix_sicoob():
    from baixar_comprovantes import sicoob_baixar as sb

    nome = sb.nome_do_pix_sicoob(_pix_sicoob(id_="E04388688202609082057lGq"))
    assert nome == "SICOOB-PIX_2026-09-08_1208-36_E04388688202609082057lGq.pdf"


def test_o_comprovante_de_pix_nao_depende_de_css_externo():
    """Ao contrário do comprovante dos Comprovantes comuns (ver
    `test_html_para_pdf_ancora_o_html_antes_de_gravar`), este é montado
    inteiro aqui dentro -- não carrega nada do site do Sicoob, então não
    precisa de `<base href>` para ficar legível."""
    from baixar_comprovantes import sicoob_baixar as sb

    saida = sb.html_do_comprovante_pix(_pix_sicoob())
    assert "<base" not in saida
    assert "<link" not in saida and "<script src" not in saida


def test_o_comprovante_de_pix_mostra_os_campos_certos():
    from baixar_comprovantes import sicoob_baixar as sb

    saida = sb.html_do_comprovante_pix(_pix_sicoob())
    assert "R$ 1.208,36" in saida
    assert "Fulano de Tal" in saida
    assert "**.222.333/0001-**" in saida       # o CNPJ do pagador, mascarado
    assert "***.456.789-**" in saida           # o CPF do destinatário, mascarado
    assert "11222333000181" not in saida, "o CNPJ cru vazou sem máscara"
    assert "12345678909" not in saida, "o CPF cru vazou sem máscara"
    assert "Pix via chave" in saida
    assert "Finalizado com sucesso" in saida


def test_o_comprovante_de_pix_escapa_nome_com_caractere_especial():
    """Nome de empresa/pessoa pode trazer `&`/`<`/`>` (razão social com
    "E" comercial, por exemplo) -- sem escapar, isso quebraria o HTML em
    vez de aparecer como texto."""
    from baixar_comprovantes import sicoob_baixar as sb

    saida = sb.html_do_comprovante_pix(
        _pix_sicoob(nome_dest="A & B <Comercio> Ltda"))
    assert "A &amp; B &lt;Comercio&gt; Ltda" in saida
    assert "<Comercio>" not in saida


def test_meio_de_iniciacao_desconhecido_nao_quebra():
    """Um valor de `meioIniciacaoPix` que a tabela não conhece cai num
    rótulo genérico, em vez de estourar ou mostrar `None`."""
    from baixar_comprovantes import sicoob_baixar as sb

    saida = sb.html_do_comprovante_pix(_pix_sicoob(meio="NOVO_TIPO"))
    assert "Pix enviado" in saida


def test_a_chave_do_pix_sicoob_nao_colide_com_a_dos_comprovantes_comuns():
    """Mesmo id, mesma conta: `sicoob` e `sicoob_pix` são POPULAÇÕES
    diferentes (comprovante comum vs. Pix), e não podem compartilhar marca
    de "já baixado" -- um dos dois nunca seria baixado."""
    from baixar_comprovantes import ja_baixados as jb

    assert (jb.chave("sicoob_pix", "X", "50.019-4")
           != jb.chave("sicoob", "X", "50.019-4"))


def test_o_resumo_mostra_o_pix_junto():
    from baixar_comprovantes import sicoob_baixar as sb

    r = sb.Resultado(conta="X", no_periodo=2, pix_no_periodo=3,
                     baixados=[pathlib.Path(f"{i}.pdf") for i in range(5)])
    assert "5 de 5 comprovantes" in r.resumo()
    assert "(+3 de Pix)" in r.resumo()


def test_sem_pix_o_resumo_nao_inventa_a_coluna():
    from baixar_comprovantes import sicoob_baixar as sb

    r = sb.Resultado(conta="X", no_periodo=2,
                     baixados=[pathlib.Path("a.pdf"), pathlib.Path("b.pdf")])
    assert "Pix" not in r.resumo()


def test_pix_e_tentado_mesmo_sem_comprovantes_comuns():
    """Antes desta rodada, `if not no_periodo: return resultado` e
    `if not pendentes: return resultado` paravam a função inteira -- e
    junto com ela, o Pix, que é tela e API separadas e não deixa de existir
    só porque a de Comprovantes não teve nada no período."""
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb.baixar_conta)
    assert "if not no_periodo" not in fonte, (
        "voltou o return antecipado -- isso pula o Pix quando não há "
        "Comprovantes comuns no período")
    assert "if not pendentes" not in fonte, (
        "voltou o return antecipado -- isso pula o Pix quando os "
        "Comprovantes comuns já tinham sido baixados antes")
    assert "_baixar_pix_da_conta(" in fonte


def test_a_falha_do_pix_nunca_vira_motivo_da_conta():
    """`_baixar_pix_da_conta` não pode levantar: uma falha nela — seletor
    que mudou, filtro que não abriu — não pode apagar um resultado de
    Comprovantes que já deu certo."""
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb._baixar_pix_da_conta)
    assert "except Exception" in fonte
    assert "resultado.motivo =" not in fonte, (
        "_baixar_pix_da_conta não pode escrever em resultado.motivo -- "
        "quem decide isso é só a conta (SicoobFalhou/Exception de "
        "baixar_conta), nunca o passe de Pix")


# -------------------------------------- os seletores do formulario de Pix
# A v2.0.188 travou 45s em todas as contas procurando "Inicial" por
# `get_by_label`/`text=`: e placeholder, sem <label>, e `text=` do Playwright
# so enxerga texto renderizado. O HTML real (outerHTML copiado do console em
# 11/09/2026) tem atributos fixos -- e e deles que os seletores saem agora.

class _Localizador:
    """Grava o que foi pedido e o que foi feito, sem navegador.

    As datas "destravam" depois de `pagina.destrava_no_clique` cliques no
    rádio (de mouse ou pelo DOM) -- é o sinal que a tela real dá."""

    def __init__(self, pagina, seletor):
        self.pagina, self.seletor = pagina, seletor
        self.registro = pagina.registro
        self.first = self

    def count(self):
        return 1

    def click(self, timeout=None):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        if self.pagina.mouse_nao_alcanca:
            raise PlaywrightTimeout("element is not visible")
        self.registro.append(("click", self.seletor))
        self.pagina.cliques += 1

    def evaluate(self, _js, timeout=None):
        self.registro.append(("evaluate", self.seletor))
        self.pagina.cliques += 1

    def wait_for(self, timeout=None):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        if self.pagina.cliques < self.pagina.destrava_no_clique:
            raise PlaywrightTimeout("as datas continuam desabilitadas")

    def press(self, tecla):
        self.registro.append(("press", self.seletor, tecla))

    def type(self, texto, delay=0):
        self.registro.append(("type", self.seletor, texto))


class _PaginaDePix:
    def __init__(self, destrava_no_clique=1, mouse_nao_alcanca=False):
        self.registro = []
        self.cliques = 0
        self.destrava_no_clique = destrava_no_clique
        self.mouse_nao_alcanca = mouse_nao_alcanca

    def locator(self, seletor):
        self.registro.append(("locator", seletor))
        return _Localizador(self, seletor)

    def evaluate(self, _js):
        self.registro.append(("retrato",))
        return {"rota": "#/pix/extrato-pix", "dataInicial": "desabilitado"}

    def wait_for_timeout(self, _ms):
        pass


def test_o_periodo_e_ligado_pela_caixa_do_primeng():
    """O rádio `value="2"` é "Período"; o `value="1"` é "Selecione o mês", e
    com ele os campos de data nascem desabilitados. É um `p-radiobutton`: o
    `input` fica em `ui-helper-hidden-accessible` e quem escuta o clique é a
    `div.ui-radiobutton-box` (HTML real copiado do console em 11/09/2026)."""
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaDePix()
    sb._selecionar_periodo_pix(pagina)
    assert pagina.registro[1:2] == [("click", sb.SEL_CAIXA_PERIODO_PIX)] or (
        ("click", sb.SEL_CAIXA_PERIODO_PIX) in pagina.registro)
    assert ("click", sb.SEL_PERIODO_PIX) not in pagina.registro
    assert "ui-radiobutton-box" in sb.SEL_CAIXA_PERIODO_PIX
    assert "radioConsultaIntervalo" in sb.SEL_CAIXA_PERIODO_PIX


def test_a_caixa_nunca_mira_o_selecione_o_mes():
    """A v2.0.192 podia acertar a bolinha do rádio vizinho, que já vem
    marcado: clicar nele não muda nada e as datas continuam travadas."""
    from baixar_comprovantes import sicoob_baixar as sb

    assert 'value="1"' not in sb.SEL_CAIXA_PERIODO_PIX
    assert "radioConsultaPeriodo" not in sb.SEL_CAIXA_PERIODO_PIX


def test_caixa_fora_do_alcance_do_mouse_vai_pelo_clique_do_dom():
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaDePix(mouse_nao_alcanca=True)
    sb._selecionar_periodo_pix(pagina)
    assert ("evaluate", sb.SEL_CAIXA_PERIODO_PIX) in pagina.registro


def test_clique_que_nao_destrava_as_datas_tenta_o_proximo_jeito():
    """Clicar no lugar errado deste componente não dá erro e não marca nada:
    quem prova que marcou é a data destravar."""
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaDePix(destrava_no_clique=3)
    sb._selecionar_periodo_pix(pagina)
    assert ("evaluate", sb.SEL_CAIXA_PERIODO_PIX) in pagina.registro
    assert ("evaluate", sb.SEL_PERIODO_PIX) in pagina.registro


def test_periodo_que_nao_marca_desiste_com_motivo_e_deixa_o_retrato():
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaDePix(destrava_no_clique=99)
    with pytest.raises(sb.SicoobFalhou, match="Período"):
        sb._selecionar_periodo_pix(pagina)
    assert ("retrato",) in pagina.registro, (
        "sem o retrato no diagnostico.log, a próxima correção volta a "
        "depender de print")


@pytest.mark.parametrize("campo", ["dataInicial", "dataFinal"])
def test_as_datas_vao_pelo_name_do_campo(campo):
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaDePix()
    sb._preencher_data_pix(pagina, campo, "08/09/2026")
    seletor = f'input[name="{campo}"]'
    assert ("type", seletor, "08/09/2026") in pagina.registro
    assert ("press", seletor, "Control+a") in pagina.registro, (
        "sem limpar antes, a data digitada soma à que já estava no campo")
    assert pagina.registro[-1] == ("press", seletor, "Tab"), (
        "sem fechar o calendário, ele cobre o campo seguinte e o Consultar")


def test_nenhum_seletor_do_formulario_de_pix_depende_de_rotulo():
    """`text=`, `get_by_label` e `get_by_text` foram exatamente o que travou
    a primeira rodada real — não voltam para estas três funções."""
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    for funcao in (sb._selecionar_periodo_pix, sb._preencher_data_pix,
                   sb.listar_pix):
        codigo = inspect.getsource(funcao).split('"""')[-1]
        for proibido in ("text=", "get_by_label", "get_by_text"):
            assert proibido not in codigo, (
                f"{funcao.__name__} voltou a usar {proibido}")


# ---------------------------------------------- o aviso de periodo sem Pix
# Rodada de 11/09/2026 (v2.0.194): sem Pix no periodo a tela abre um aviso
# modal com "Ok", e a rodada so seguia depois que a pessoa clicava.

class _BotaoOk:
    def __init__(self, pagina):
        self.pagina = pagina
        self.first = self

    def wait_for(self, state=None, timeout=None):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        if not self.pagina.tem_ok:
            raise PlaywrightTimeout("nenhum Ok visivel")

    def click(self, timeout=None):
        self.pagina.registro.append(("click", "Ok"))


class _PaginaComAviso:
    def __init__(self, tem_ok=True):
        self.registro = []
        self.tem_ok = tem_ok
        self.keyboard = self

    def get_by_role(self, papel, name=None):
        self.registro.append(("papel", papel))
        return _BotaoOk(self)

    def press(self, tecla):
        self.registro.append(("tecla", tecla))


def test_o_aviso_de_periodo_sem_pix_fecha_pelo_ok():
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaComAviso()
    assert sb._fechar_aviso_pix(pagina) is True
    assert ("papel", "button") in pagina.registro
    assert ("click", "Ok") in pagina.registro
    assert ("tecla", "Escape") not in pagina.registro


def test_o_ok_e_so_o_ok():
    from baixar_comprovantes import sicoob_baixar as sb

    for nome in ("Ok", "OK", " ok "):
        assert sb._RE_BOTAO_OK.match(nome), nome
    for nome in ("Okay", "Bloquear", "Consultar", "Ok, exportar"):
        assert not sb._RE_BOTAO_OK.match(nome), nome


def test_sem_ok_na_tela_tenta_o_esc_e_nao_levanta():
    from baixar_comprovantes import sicoob_baixar as sb

    pagina = _PaginaComAviso(tem_ok=False)
    assert sb._fechar_aviso_pix(pagina) is False
    assert ("tecla", "Escape") in pagina.registro


def test_listar_pix_fecha_o_aviso_quando_o_periodo_vem_vazio():
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb.listar_pix)
    assert "_fechar_aviso_pix(page)" in fonte
    assert fonte.index("if not itens") < fonte.index("_fechar_aviso_pix(page)")


def test_listar_pix_usa_os_names_reais_e_o_botao_pelo_atributo():
    import inspect

    from baixar_comprovantes import sicoob_baixar as sb

    fonte = inspect.getsource(sb.listar_pix)
    assert '"dataInicial"' in fonte and '"dataFinal"' in fonte
    assert 'data-content-label="Consultar"' in fonte


import pathlib


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


# ------------------------------------------- o nome no padrao do Renomear
# `2.980,00 - RPB 24 QD 26A LT 08 OC 6974 - 24-08.pdf`. Renomear na BAIXA
# economiza uma passada e evita o erro de esquecer a passada.

def linhas(*partes):
    """Um comprovante de mentira, montado linha a linha."""
    return chr(10).join(partes)


def test_o_nome_sai_da_funcao_do_renomear_e_nao_de_uma_copia():
    """Reproduzir o padrao aqui criaria duas verdades que divergem no dia em
    que alguem mudar a regra num lado so -- e divergem em SILENCIO, porque
    nada quebra: os arquivos so passam a sair diferentes."""
    import inspect

    from baixar_comprovantes import nome_final as nf

    assert "nome_arquivo" in inspect.getsource(nf.nomear)


def test_o_pix_e_nomeado_sem_abrir_o_pdf():
    """O Inter entrega valor, data, descricao e favorecido no JSON. Ler o PDF
    para descobrir o que ja se tem seria trabalho e risco de graca."""
    from baixar_comprovantes import nome_final as nf

    campos = nf.do_pix({"data": "24/08/2026", "valor": 2980.0,
                        "nome": "Ar Pre Moldados",
                        "descricao": "RPB 24 QD 26A LT 08 OC 6974",
                        "detalhePix": {}})
    assert campos["valor"] == "2.980,00"
    assert nf.nomear(campos) == "2980,00 - RPB 24 QD 26A LT 08 OC 6974 - 24-08"


def test_o_valor_vira_o_formato_que_o_renomear_espera():
    from baixar_comprovantes import nome_final as nf

    assert nf.brl(2980.0) == "2.980,00"
    assert nf.brl(108.39) == "108,39"
    assert nf.brl(90000) == "90.000,00"
    assert nf.brl(None) == ""


def test_o_favorecido_do_boleto_sai_do_bloco_beneficiario():
    """`Nome/Razao social` aparece DUAS vezes no comprovante de boleto, e a
    primeira ocorrencia pode ser a do PAGADOR -- que e justamente quem nao
    interessa. A ancora e o BLOCO, nao o rotulo."""
    from baixar_comprovantes import nome_final as nf

    texto = linhas("Tipo documento Titulo",
                   "Beneficiario",
                   "Nome/Razao Social ALLSEG SEGURADORA S A",
                   "CPF/CNPJ 67.865.360/0001-27",
                   "Pagador",
                   "Nome/Razao social MORAIS EMPREENDIMENTOS BURITIS")
    assert nf.favorecido_do_comprovante(texto) == "ALLSEG SEGURADORA S A"


def test_o_favorecido_da_transferencia_sai_do_bloco_credito():
    from baixar_comprovantes import nome_final as nf

    texto = linhas("Debito",
                   "Conta 50.019-4 / MORAIS EMPREENDIMENTOS BURITIS SPE LTDA",
                   "Credito",
                   "Conta 6.135-2 / ROCHA SANTIAGO ENGENHARIA LTDA")
    assert nf.favorecido_do_comprovante(texto) == "ROCHA SANTIAGO ENGENHARIA LTDA"


def test_a_data_e_a_do_pagamento_e_nao_a_da_impressao():
    """O topo do comprovante traz o carimbo de quando o ARQUIVO foi gerado. O
    parser do Renomear pegou esse, e os 23 sairam com a data de hoje."""
    from baixar_comprovantes import nome_final as nf

    texto = linhas("COMPROVANTE DE", "31/08/2026 12:04:52",
                   "PAGAMENTO DE BOLETO",
                   "Datas", "Realizado 03/08/2026 as 17:57:03",
                   "Pagamento 03/08/2026")
    assert nf.data_do_comprovante(texto) == "03/08/2026"


def test_o_sicoob_junta_o_json_com_o_documento():
    """Valor e data do JSON (certos); favorecido do PDF (so la existe)."""
    from baixar_comprovantes import nome_final as nf

    item = {"valorLancamento": 1244.91, "dataLancamento": "2026-08-03 00:00:00.0"}
    texto = linhas("Beneficiario", "Nome/Razao Social ALLSEG SEGURADORA S A",
                   "Pagamento 03/08/2026")
    campos = nf.do_sicoob(item, texto)
    assert nf.nomear(campos) == "1244,91 - ALLSEG SEGURADORA S A - 03-08"


# ------------------------------------ a Observação do Sicoob vira a descrição
# Em 10 e 11/09/2026, 121 dos 144 comprovantes comuns do Sicoob saíram com o
# nome de quem recebeu, com a descrição escrita no PDF: `do_sicoob` punha
# `desc` = None fixo. O dono exige VALOR - DESCRIÇÃO - DATA.

def test_a_observacao_na_mesma_linha_e_a_descricao():
    from baixar_comprovantes import nome_final as nf

    texto = linhas("Situação Efetivado",
                   "Observação OBRA TESTE QD 99 LT 01 NF 123 OC 456",
                   "Autenticação 0a1b2c3d-0000-0000-0000-000000000000",
                   "OUVIDORIA SICOOB: 0000000000")
    assert nf.descricao_do_comprovante(texto) == \
        "OBRA TESTE QD 99 LT 01 NF 123 OC 456"


def test_descricao_com_ou_sem_dois_pontos_e_espacos_normalizados():
    from baixar_comprovantes import nome_final as nf

    assert nf.descricao_do_comprovante(
        linhas("Descrição: OBRA TESTE   QD 99  LT 01")) == "OBRA TESTE QD 99 LT 01"
    assert nf.descricao_do_comprovante(
        linhas("Observacao: NF 123 OC 456")) == "NF 123 OC 456"
    assert nf.descricao_do_comprovante(
        linhas("Descricao OBRA TESTE")) == "OBRA TESTE"


def test_rotulo_sozinho_com_o_valor_na_linha_de_baixo():
    from baixar_comprovantes import nome_final as nf

    texto = linhas("Situação Efetivado",
                   "Observação",
                   "OBRA TESTE QD 99 LT 01",
                   "Autenticação 0a1b2c3d-0000-0000-0000-000000000000")
    assert nf.descricao_do_comprovante(texto) == "OBRA TESTE QD 99 LT 01"


def test_observacao_quebrada_em_volta_do_rotulo_se_emenda():
    """No comprovante de convênio o Sicoob corta o texto em 48 caracteres,
    no meio da palavra, e o pdfplumber poe o rotulo SOZINHO entre as duas
    metades. Ler so a de baixo daria "IS ITBI CASA 1" -- foram os 7 casos que
    pareciam "Observacao vazia" em 10 e 11/09."""
    from baixar_comprovantes import nome_final as nf

    completo = "OBRA TESTE QD 99 LT 01 DEVOLUCAO DE VALORES A MAIS ITBI CASA 1"
    acima, abaixo = completo[:48], completo[48:]
    assert not acima.endswith(" ") and not abaixo.startswith(" ")
    texto = linhas("Autenticação 0A1B2C3D-0000-0000-0000-000000000000",
                   acima,
                   "Observação",
                   abaixo,
                   "OUVIDORIA SICOOB: 0000000000")
    assert nf.descricao_do_comprovante(texto) == completo

    # metade de cima que NAO enche a coluna: o corte foi em espaco
    texto = linhas("Autenticação 0A1B2C3D", "OBRA TESTE QD 99", "Observação",
                   "LT 01 NF 123", "OUVIDORIA SICOOB: 0000000000")
    assert nf.descricao_do_comprovante(texto) == "OBRA TESTE QD 99 LT 01 NF 123"


def test_observacao_vazia_nao_vira_descricao():
    """Nem a linha de baixo nem a de cima podem ser outro campo: sem essa
    conferencia, "Autenticacao 0a1b..." viraria o nome do arquivo."""
    from baixar_comprovantes import nome_final as nf

    assert nf.descricao_do_comprovante(linhas(
        "Situação Efetivado", "Observação",
        "Autenticação 0a1b2c3d-0000-0000-0000-000000000000")) == ""
    assert nf.descricao_do_comprovante(linhas(
        "Autenticação 0A1B2C3D", "Observação:",
        "OUVIDORIA SICOOB: 0000000000")) == ""
    assert nf.descricao_do_comprovante(linhas("Observação")) == ""


def test_transferencia_sem_observacao_fica_no_favorecido():
    from baixar_comprovantes import nome_final as nf

    item = {"valorLancamento": 500.0, "dataLancamento": "2026-08-03 00:00:00.0"}
    texto = linhas("Natureza TRANSF.INTERC",
                   "Débito",
                   "Conta 00.000-0 / EMPRESA PAGADORA EXEMPLO",
                   "Crédito",
                   "Conta 0.000-0 / FORNECEDOR EXEMPLO",
                   "Data do lançamento 03/08/2026")
    assert nf.descricao_do_comprovante(texto) == ""
    campos = nf.do_sicoob(item, texto)
    assert campos["desc"] is None
    assert nf.nomear(campos) == "500,00 - FORNECEDOR EXEMPLO - 03-08"


def test_o_nome_do_sicoob_sai_valor_descricao_data():
    """O caso dos 121: favorecido E Observacao no mesmo comprovante. Vale a
    descricao, e o favorecido so entra quando ela falta."""
    from baixar_comprovantes import nome_final as nf

    item = {"valorLancamento": 1244.91, "dataLancamento": "2026-08-03 00:00:00.0"}
    texto = linhas("Beneficiário",
                   "Nome/Razão Social FORNECEDOR EXEMPLO",
                   "Pagamento 03/08/2026",
                   "Situação Efetivado",
                   "Observação OBRA TESTE QD 99 LT 01 NF 123 OC 456",
                   "Autenticação 0a1b2c3d-0000-0000-0000-000000000000")
    campos = nf.do_sicoob(item, texto)
    assert campos["dest"] == "FORNECEDOR EXEMPLO"
    assert nf.nomear(campos) == \
        "1244,91 - OBRA TESTE QD 99 LT 01 NF 123 OC 456 - 03-08"


def test_sem_nome_montavel_o_arquivo_fica_onde_esta(tmp_path):
    """Falhar no nome nunca pode perder comprovante: com o nome de origem ele
    e achavel; sumido, nao."""
    from baixar_comprovantes import nome_final as nf

    arquivo = tmp_path / "SICOOB_original.pdf"
    arquivo.write_bytes(b"%PDF-")
    assert nf.renomear(arquivo, {}).exists()


def test_o_desempate_segue_o_do_renomear(tmp_path):
    """` (2)`, e nao o `_1` do downloader: dois arquivos com o mesmo nome
    final vem do mesmo padrao, e quem os ve na pasta espera a numeracao de
    la."""
    from baixar_comprovantes import nome_final as nf

    campos = {"valor": "100,00", "data": "24/08/2026", "desc": "TESTE",
              "dest": None, "pag": None}
    for n in range(2):
        origem = tmp_path / ("origem%d.pdf" % n)
        origem.write_bytes(b"%PDF-")
        nf.renomear(origem, campos)
    nomes = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert any("(2)" in nome for nome in nomes), nomes


# ------------------------------------- o cabecalho da coluna marca e desmarca
# E onde a pessoa procura esse botao numa tabela de selecao, antes de procurar
# no rodape.

@pytest.fixture
def abrir_aba(raiz):
    """Abre a aba de verdade na janela compartilhada, e a FECHA no fim.

    Os dois cuidados aqui nasceram de estragos medidos, nao de zelo:

    Sem ESPACO, o Treeview nao chega a desenhar o cabecalho, e
    `identify_region` responde "nothing" onde ele esta -- o teste do cabecalho
    PULOU em vez de falhar, que e o jeito de sumir sem nada em vermelho.

    Sem FECHAR, a aba fica empacotada (`fill both, expand`) na janela, que e
    de sessao (a conftest explica por que): ela cobre tudo e espreme os
    widgets dos testes seguintes. Cinco testes de foco e de calendario, em
    outros tres arquivos, passaram a falhar por causa disto.
    """
    import tkinter as tk

    import widgets
    from baixar_comprovantes import comprovantes_frame as cf

    criadas = []
    geometria = raiz.geometry()

    def criar(contas):
        try:
            widgets.aplicar_estilos(raiz)
        except Exception:                                    # noqa: BLE001
            pass
        aba = cf.ComprovantesFrame(raiz)
        raiz.geometry("900x600+0+0")
        aba.pack(fill="both", expand=True)
        raiz.update()
        criadas.append(aba)

        aba.tabela.delete(*aba.tabela.get_children())
        aba.linhas.clear()
        for c in contas:
            chave = f"{c['banco']}:{c['conta']}"
            aba.linhas[chave] = dict(c, situacao="espera", marcada=True)
            aba.tabela.insert("", "end", iid=chave,
                              values=(cf.MARCADA, c["banco"], c["conta"],
                                      c["empresa"], "na fila"))
        aba._contar()
        return aba

    yield criar

    for aba in criadas:
        try:
            aba.destroy()
        except tk.TclError:
            pass
    raiz.geometry(geometria)
    raiz.update()


DUAS = [{"banco": "Sicoob", "conta": "00.000-0", "empresa": "EMPRESA A",
         "pasta": "SICOOB"},
        {"banco": "Inter", "conta": "—", "empresa": "EMPRESA B",
         "pasta": "INTER"}]


def _mensagens(aba):
    import queue

    saida = []
    while True:
        try:
            saida.append(aba.q.get_nowait())
        except queue.Empty:
            return saida


def test_parar_termina_a_conta_da_vez_e_nao_comeca_as_outras(abrir_aba,
                                                             monkeypatch,
                                                             tmp_path):
    """O botao Parar nasceu da rodada de 11/09/2026: cada conta com erro
    esperava 45s e nao havia como sair sem fechar o app."""
    from baixar_comprovantes import inter_baixar
    from baixar_comprovantes import sicoob_baixar as sb
    from extratos_sicoob import sicoob_client

    contas = [{"banco": "Sicoob", "conta": "11.111-1", "empresa": "EMPRESA A",
               "pasta": "SICOOB"},
              {"banco": "Sicoob", "conta": "22.222-2", "empresa": "EMPRESA B",
               "pasta": "SICOOB"},
              {"banco": "Inter", "conta": "—", "empresa": "EMPRESA C",
               "pasta": "INTER"}]
    aba = abrir_aba(contas)

    class ClienteFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def aguardar_login(self):
            pass

    feitas = []

    def baixar_conta(cli, conta, *a, **k):
        feitas.append(conta)
        aba._parar.set()          # a pessoa aperta Parar no meio da 1a conta
        return sb.Resultado(conta=conta)

    inter_chamado = []
    monkeypatch.setattr(sicoob_client, "SicoobClient", ClienteFalso)
    monkeypatch.setattr(sb, "baixar_conta", baixar_conta)
    monkeypatch.setattr(inter_baixar, "baixar",
                        lambda *a, **k: inter_chamado.append(a))

    aba._trabalhar("01/09/2026", "02/09/2026", tmp_path / "2026-09-02")

    assert feitas == ["11.111-1"]
    assert inter_chamado == []
    msgs = _mensagens(aba)
    assert ("situacao", ("Sicoob:22.222-2", "parado", {})) in msgs
    assert ("situacao", ("Inter:—", "parado", {})) in msgs
    assert msgs[-1] == ("fim", None)


def test_o_botao_parar_so_vale_durante_a_rodada(abrir_aba):
    aba = abrir_aba(DUAS)
    assert str(aba.b_parar.cget("state")) == "disabled"
    aba._pedir_parada()           # sem rodada: nao arma nada
    assert not aba._parar.is_set()


def test_o_cabecalho_desmarca_todas_e_marca_de_novo(abrir_aba):
    aba = abrir_aba(DUAS)
    assert all(c["marcada"] for c in aba.linhas.values())

    aba._alternar_todas()
    assert not any(c["marcada"] for c in aba.linhas.values())

    aba._alternar_todas()
    assert all(c["marcada"] for c in aba.linhas.values())


def test_com_algumas_marcadas_o_cabecalho_marca_todas(abrir_aba):
    """Sem terceiro estado: o clique responde ao que esta na tela."""
    aba = abrir_aba(DUAS)
    aba._marcar_conta("Inter:—", False)

    aba._alternar_todas()
    assert all(c["marcada"] for c in aba.linhas.values())


def test_o_simbolo_do_cabecalho_segue_as_linhas(abrir_aba):
    from baixar_comprovantes import comprovantes_frame as cf

    aba = abrir_aba(DUAS)
    assert aba.tabela.heading("marca", "text") == cf.MARCADA

    aba._marcar_conta("Inter:—", False)
    assert aba.tabela.heading("marca", "text") == cf.DESMARCADA


def test_o_clique_na_linha_nao_engole_o_comando_do_cabecalho(abrir_aba):
    """`_clicou` devolvia "break" para toda a coluna #1, cabecalho incluido --
    e a ligacao do widget corre ANTES da ligacao de classe que dispara o
    comando do cabecalho. A marca de todas simplesmente nao responderia."""

    aba = abrir_aba(DUAS)
    tabela = aba.tabela
    # A altura do cabecalho muda com o tema e com o DPI; procura-la e mais
    # honesto que fixar um y que funciona nesta maquina.
    alturas = [y for y in range(0, 60)
               if tabela.identify_region(30, y) == "heading"]
    if not alturas:
        pytest.skip("o Tk desta maquina nao desenhou o cabecalho")

    class Evento:
        x, y = 30, alturas[len(alturas) // 2]

    assert tabela.identify_column(Evento.x) == "#1"
    assert aba._clicou(Evento()) is None, (
        "devolver 'break' no cabecalho mata o comando da coluna")
