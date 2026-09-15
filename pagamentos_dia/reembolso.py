# -*- coding: utf-8 -*-
"""
Quem recebe o reembolso.

O aviso anexado `PAGAR PARA <pessoa>` manda o dinheiro para quem **não** é o
favorecido do lançamento. O segmento B do CNAB 240 carrega UM par
nome/documento (07.3B e 08.3B, obrigatórios), e os dois lados vinham de
origens diferentes: nome e CPF/CNPJ do FORNECEDOR (do cadastro de Contatos,
casado pelo `paidTo`) com a chave Pix DA PESSOA. O arquivo contradizia a si
mesmo — ou o banco recusa o registro, ou paga sob documento de terceiro —, e
por isso todo reembolso era barrado.

Este módulo existe para desfazer o empate: ele descobre **nome e documento da
mesma pessoa**, da mesma fonte, e é isso que o segmento B passa a declarar.
Não achando com certeza, devolve o impedimento — que continua sendo o
desfecho normal, não uma falha.

DEPENDÊNCIA DE MÃO ÚNICA
------------------------
`relatorio` importa daqui; daqui não se importa `relatorio`. É o que permite
testar esta decisão sem Excel, sem tkinter e sem rede. O preço é que a leitura
da CHAVE Pix fica lá (é ela que carrega os padrões de chave) e chega aqui como
argumento — o que também é o desenho certo: a chave não decide quem recebe,
ela só CONFERE (ver `identificar`).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import util
from . import regras_pagamento as regras

#: Cadastro local de quem recebe reembolso. Fica ao lado do exe, FORA do
#: repositório: é nome e CPF de gente.
ARQ_REEMBOLSO = "pix_reembolso.json"

PAGAR_PARA = re.compile(r"pagar\s*_?\s*para", re.I)

#: Tudo que o aviso escreve depois do "PAGAR PARA" e ainda diz respeito à
#: pessoa. O documento de reembolso costuma trazer também o CNPJ da empresa e
#: o valor; varrer o texto inteiro pegaria o primeiro número parecido, não o
#: certo. É a mesma janela que o `relatorio` usa para achar a chave Pix.
TAMANHO_DA_JANELA = 300

#: O rótulo do aviso que é só `PIX: <chave>`, com o "PAGAR PARA" morando
#: apenas no nome do arquivo (o caso de 14/09/2026). Exige os dois-pontos e a
#: palavra PIX: "CHAVE DE ACESSO" (a DANFE) e "via PIX" (o recibo) não são
#: rótulo de chave. O tipo declarado é aceito menos CNPJ — reembolso é para
#: PESSOA, e "PIX CNPJ:" num papel sem a frase é a chave da loja.
#: O grupo pega a linha do rótulo ou, vazia, a linha de baixo.
ROTULO_DA_CHAVE = re.compile(
    r"(?<!\w)(?:chave\s+)?pix(?:\s+(?:cpf|celular|telefone|e-?mail|aleat\w*))?"
    r"\s*:[ \t]*(?:\r?\n[ \t]*)?([^\r\n]*)", re.I)

#: O papel sem a frase que NÃO é aviso, mesmo renomeado "PAGAR PARA": o
#: comprovante (a chave nele é de quem RECEBEU o pagamento), a nota fiscal e a
#: DANFE (a chave de acesso tem 44 dígitos com pedaços de cara de celular), o
#: recibo e o cupom. Um aviso que é só a chave não escreve nenhuma destas.
_OUTRO_DOCUMENTO = re.compile(
    r"comprovante|transfer[eê]ncia|transa[cç][aã]o|recebedor|\bdanfe\b|"
    r"chave\s+de\s+acesso|nota\s+fiscal|\bnfc?-?e\b|\brecibo\b|\bcupom\b", re.I)

#: O PRIMEIRO item depois do rótulo, casado no começo e fechado por espaço ou
#: fim de linha — nunca uma janela varrida por padrão. Varrer uma janela de
#: 300 caracteres com o padrão de CNPJ antes do de CPF foi o que fez a revisão
#: achar o CNPJ da loja declarado como chave E como documento da pessoa. CNPJ
#: não está na lista, e onze dígitos crus passam por aqui para o `relatorio`
#: decidir (`_chave_confiavel`), como qualquer outra chave de aviso.
_ITENS_DE_CHAVE = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
    re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}"),
    re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\s?\d{4}"),
)
_TIPOS_DE_PESSOA = frozenset((regras.CHAVE_CPF, regras.CHAVE_TELEFONE,
                              regras.CHAVE_EMAIL, regras.CHAVE_ALEATORIA))

# --------------------------------------------------------------------------
# Impedimentos — o texto vai para a tela e para o "ficou de fora"
# --------------------------------------------------------------------------
MOTIVO_SEM_NOME = ("reembolso: o aviso não diz para quem pagar — renomeie o "
                   "anexo como 'PAGAR PARA <nome>' ou pague à mão")
MOTIVO_SEM_DOCUMENTO = ("reembolso para '{nome}': o CPF de quem recebe não foi "
                        "encontrado — cadastre no {arquivo} ou pague à mão")
MOTIVO_DOCUMENTO_DIVERGENTE = ("reembolso para '{nome}': {origens} dão documentos "
                               "DIFERENTES — confira antes de pagar")
#: A chave não é fonte do documento (decisão do dono: fonte que se confirma
#: sozinha não confere nada). Mas ela é CONFERENTE, e este é o caso em que ela
#: contradiz o resto: o dinheiro iria para o dono da chave enquanto o arquivo
#: declara outra pessoa — exatamente o defeito que fechou o reembolso inteiro.
MOTIVO_CHAVE_DE_OUTRO = ("reembolso para '{nome}': a chave Pix do aviso é o "
                         "documento de OUTRA pessoa, e o arquivo declararia "
                         "esta — pague à mão")

ORIGEM_CADASTRO_LOCAL = f"cadastro local ({ARQ_REEMBOLSO})"
ORIGEM_ERP = "Contatos do ERP"
ORIGEM_AVISO = "lido no próprio aviso"


@dataclass
class Pessoa:
    """Quem o segmento B vai declarar — ou por que não dá para declarar.

    `nome` e `documento` só vêm preenchidos juntos, e sempre da MESMA fonte:
    é essa amarra que impede o par de se contradizer.
    """

    nome: str = ""
    documento: str = ""
    origem: str = ""
    impedimento: str = ""

    @property
    def resolvida(self) -> bool:
        return bool(self.nome and self.documento and not self.impedimento)


# --------------------------------------------------------------------------
# Leitura do aviso
# --------------------------------------------------------------------------
def _rotulo(f: dict) -> str:
    return f"{f.get('filename') or ''} {f.get('tagName') or ''}"


def _comparavel(s) -> str:
    return util.sem_acento(s or "").casefold().strip()


def eh_aviso(f: dict) -> bool:
    return bool(PAGAR_PARA.search(_rotulo(f)))


def nome_do_aviso(files) -> str:
    """O nome escrito no RÓTULO: `PAGAR PARA <nome>.pdf` → `<nome>`.

    Só o nome do arquivo, e não a tag: quem renomeia o anexo é quem sabe para
    quem é o reembolso, e a tag costuma vir de uma lista fixa.
    """
    for f in files or ():
        m = re.search(r"pagar\s*_?\s*para\s*[-:_ ]*(.+)", _comparavel(f.get("filename")))
        if m:
            return re.sub(r"\.(pdf|jpe?g|png|docx?)$", "", m.group(1)).strip()
    return ""


def pessoa_e_o_favorecido(files, favorecido: str,
                          participantes: dict | None = None) -> bool:
    """O favorecido do LANÇAMENTO é a própria pessoa do aviso?

    O reembolso nasceu para o caso em que não é — o título é da loja, e o
    aviso manda o dinheiro para quem pagou a loja do próprio bolso. Mas há
    lançamento feito direto no nome da pessoa, com a chave DELA no
    `paidToBankAccount`, e o aviso anexado assim mesmo. Ali duas coisas que o
    ramo do reembolso recusa por desenho passam a ser a resposta certa: o nome
    completo do favorecido é o nome da pessoa (desempata os homônimos que o
    primeiro nome do aviso não desempata), e a chave do lançamento é a dela.

    **Igual, ou começo em fronteira de palavra**: "FULANA" é o começo de
    "FULANA DE TAL SOUZA", e não de "FULANARIA COMERCIO".

    **Falha FECHADA: só é a pessoa quem está nos Contatos com CPF que fecha.**
    "PAGAR PARA FULANA" num título da "Fulana Materiais Ltda" bate pelo nome,
    e pagar a chave dela seria pagar o fornecedor de novo em vez de devolver o
    dinheiro a quem comprou. Cadastro que não carregou (`{}`) ou nome ambíguo
    que saiu do mapa não provam nada — e, sem prova, empresa passaria por
    pessoa. E mesmo sendo pessoa, pode ser a HOMÔNIMA do aviso: por isso isto
    só abre a porta, e quem confirma é o aviso (ver `identificar` e o ramo do
    reembolso no `relatorio`).
    """
    nome = util.norm_espaco(nome_do_aviso(files))
    alvo = util.norm_espaco(favorecido)
    if not nome or not alvo:
        return False
    if alvo != nome and not alvo.startswith(nome + " "):
        return False
    return len(regras.documento_valido((participantes or {}).get(alvo) or "")) == 11


def _item_da_chave(texto: str) -> str:
    """A chave do aviso que NÃO escreve a frase — ou "" quando não há certeza.

    Exatamente um rótulo (`ROTULO_DA_CHAVE`), e dele só o primeiro item, que
    tem de ser chave de PESSOA pelo `regras.tipo_de_chave_pix` — a mesma régua
    que classifica a chave no resto do app. Papel com cara de outro documento
    é recusado inteiro antes de qualquer leitura.
    """
    if regras.PROVA_DE_PAGAMENTO.search(texto) or _OUTRO_DOCUMENTO.search(texto):
        return ""
    rotulos = ROTULO_DA_CHAVE.findall(texto)
    if len(rotulos) != 1:
        return ""
    linha = rotulos[0].strip()
    for padrao in _ITENS_DE_CHAVE:
        m = padrao.match(linha)
        if m and (m.end() == len(linha) or linha[m.end()] in " \t,;"):
            item = m.group(0)
            return item if regras.tipo_de_chave_pix(item) in _TIPOS_DE_PESSOA else ""
    return ""


def janelas_do_aviso(files, textos: dict, urls_ocr=()):
    """O trecho de cada aviso logo depois do "PAGAR PARA".

    Existe como função própria porque DOIS leitores dependem da mesma janela —
    a chave Pix (no `relatorio`) e o documento (aqui). Fossem duas janelas,
    bastaria uma mudar de tamanho para os dois passarem a falar de pedaços
    diferentes do mesmo papel.

    **O aviso nem sempre escreve a frase.** Há aviso cujo texto é só
    `PIX: <cpf>`, e a frase está no nome do arquivo. Exigir a frase no texto
    deixava os dois leitores sem janela — e a linha saía "chave não
    cadastrada; abrir o aviso" com a chave escrita no próprio aviso.

    Sem a frase, a "janela" é só a CHAVE (`_item_da_chave`), e só em anexo
    cujo NOME DO ARQUIVO diz "pagar para": é de lá que sai o nome da pessoa
    (`nome_do_aviso`), e a etiqueta, que vem de lista fixa, pode estar em
    qualquer anexo do título, a nota fiscal inclusive. Não é uma janela de
    300 caracteres depois de um "pix" qualquer: renomeado "PAGAR PARA", o
    recibo, o comprovante e a DANFE entregavam o CNPJ da loja, a chave de
    quem recebeu ou dígitos da chave de acesso — e os dois leitores os
    declaravam como chave e como documento da pessoa.

    **E só com camada de texto.** O caminho sem a frase separa o aviso do
    comprovante renomeado por PALAVRA ("comprovante", "valor pago"...), e o
    OCR de uma foto escreve "Comprovamte" e "Valor pagu" — não há lista de
    erros de OCR que feche isso. `urls_ocr` são os anexos cujo texto veio de
    OCR (o mesmo conjunto que o `montar_registros` já recebe); para eles, só
    vale a janela depois da frase escrita no papel, como sempre valeu.

    Com a frase no texto, nada muda — vale o que vem depois dela.
    """
    for f in files or ():
        if not eh_aviso(f):
            continue
        url = f.get("downloadUrl") or ""
        texto = (textos or {}).get(url) or ""
        m = PAGAR_PARA.search(texto)
        if m:
            yield texto[m.end():m.end() + TAMANHO_DA_JANELA]
        elif url not in (urls_ocr or ()) and PAGAR_PARA.search(f.get("filename") or ""):
            item = _item_da_chave(texto)
            if item:
                yield item


_CPF_CNPJ_ROTULADO = re.compile(r"\bCP\s*F\b|\bCNPJ\b", re.I)
#: Corridos ou formatados, um padrão para cada. Um regex frouxo do tipo
#: `\d[\d.\-/\s]+\d` seria mais curto e estaria errado: ele é GANANCIOSO, e
#: dois documentos vizinhos ("<cpf> <cnpj>") entrariam numa captura só, que
#: não fecha DV nenhum — os dois se perderiam calados. As bordas `(?<!\d)` e
#: `(?!\d)` também impedem o padrão de CPF de casar dentro de um CNPJ.
_CPF = re.compile(r"(?<!\d)\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}(?!\d)")
_CNPJ = re.compile(r"(?<!\d)\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-.\s]?\d{2}(?!\d)")


def _documentos_em(texto: str) -> list[str]:
    """Todo CPF/CNPJ que FECHA o dígito verificador, na ordem em que aparece.

    O DV não é preciosismo: sem ele todo telefone de onze dígitos viraria
    "CPF encontrado" — e aqui o texto costuma vir de OCR de uma foto, onde um
    dígito trocado é o erro mais provável que existe.

    A ordem é a do TEXTO, e não a dos padrões: quem lê isto depois de um
    rótulo ("CPF: …") quer o primeiro documento escrito ali, e ordenar por
    padrão devolveria o CPF do fim antes do CNPJ do começo.
    """
    achados = []
    for padrao in (_CPF, _CNPJ):
        for m in padrao.finditer(texto or ""):
            doc = regras.documento_valido(m.group(0))
            if doc:
                achados.append((m.start(), doc))
    vistos, ordenados = set(), []
    for _, doc in sorted(achados):
        if doc not in vistos:
            vistos.add(doc)
            ordenados.append(doc)
    return ordenados


def documento_do_aviso(files, textos: dict, urls_ocr=()) -> str:
    """O CPF/CNPJ de quem recebe, escrito DENTRO do aviso.

    Quem monta o aviso já escreve ali o documento; o que faltava era lê-lo.
    Duas defesas, porque este é o caminho que lê uma FOTO por OCR:

    - o dígito verificador. Sem ele todo telefone de onze dígitos viraria
      "CPF encontrado", e o erro de OCR de um dígito passaria batido;
    - **ambiguidade não se resolve por chute.** Achando mais de um documento
      válido na janela — o da pessoa e o CNPJ da empresa, por exemplo —, o
      rótulo `CPF:`/`CNPJ:` desempata; não havendo rótulo, devolve "" e o
      pagamento cai no impedimento. Escolher um dos dois é escolher para quem
      o dinheiro vai.
    """
    for janela in janelas_do_aviso(files, textos, urls_ocr):
        achados = _documentos_em(janela)
        if len(achados) == 1:
            return achados[0]
        if len(achados) > 1:
            # O rótulo desempata pelo TIPO que ele nomeia, e não por
            # proximidade: "CPF: <cpf> <cnpj>" tem os dois a poucos caracteres
            # dele, e pegar "o mais perto" devolveria os dois de novo.
            rotulados = []
            for m in _CPF_CNPJ_ROTULADO.finditer(janela):
                tamanho = 11 if m.group(0).upper().replace(" ", "") == "CPF" else 14
                for doc in _documentos_em(janela[m.end():m.end() + 30]):
                    if len(doc) == tamanho:
                        rotulados.append(doc)
                        break
            unicos = list(dict.fromkeys(rotulados))
            if len(unicos) == 1:
                return unicos[0]
    return ""


# --------------------------------------------------------------------------
# Cadastro local
# --------------------------------------------------------------------------
def carregar(base: Path | None = None) -> dict:
    """`{nome comparável: {"nome", "documento", "chave"}}` do arquivo local.

    Dois formatos são aceitos, porque o antigo já está em uso na máquina de
    quem trabalha e trocar o arquivo por baixo dele apagaria os cadastros:

    - antigo, `{"NOME": "chave pix"}` — vira uma entrada só com a chave;
    - novo, `{"NOME": {"nome": …, "documento": …, "chave": …}}`.

    Cadastro ausente ou ilegível devolve `{}`: ele é uma das três fontes, não
    a única, e não pode derrubar o dia.
    """
    try:
        caminho = (base or util.pasta_base()) / ARQ_REEMBOLSO
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(dados, dict):
        return {}

    cadastro = {}
    for nome, valor in dados.items():
        alvo = _comparavel(nome)
        if not alvo:
            continue
        if isinstance(valor, dict):
            cadastro[alvo] = {
                "nome": util.norm_espaco(valor.get("nome") or nome),
                "documento": regras.documento_valido(valor.get("documento") or ""),
                "chave": str(valor.get("chave") or "").strip(),
            }
        else:
            cadastro[alvo] = {"nome": util.norm_espaco(nome), "documento": "",
                              "chave": str(valor).strip()}
    return cadastro


def chaves(cadastro: dict) -> dict:
    """`{nome: chave}` — o formato que o `relatorio.pix_do_reembolso` espera."""
    return {nome: dado["chave"] for nome, dado in (cadastro or {}).items()
            if dado.get("chave")}


def _do_cadastro_local(nome: str, cadastro: dict) -> tuple[str, str]:
    """(nome oficial, documento) do cadastro local, casando por PEDAÇO.

    Casa como o resto do app casa nome digitado por gente, e o cadastrado
    MAIS LONGO ganha — quem cadastrou o nome inteiro quis ser específico.
    """
    alvo = _comparavel(nome)
    achadas = [(k, v) for k, v in (cadastro or {}).items()
               if k and k in alvo and v.get("documento")]
    if not achadas:
        return "", ""
    _, melhor = max(achadas, key=lambda kv: len(kv[0]))
    return melhor["nome"], melhor["documento"]


def _do_erp(nome: str, participantes: dict) -> tuple[str, str]:
    """(nome oficial, documento) do cadastro de Contatos do ERP.

    O papel EMPLOYEE já entra em `listar_participantes`, e reembolso costuma
    ser para funcionário: é daqui que a maioria dos casos deve sair, sem
    ninguém cadastrar nada à mão.

    **Casa por igualdade, ou por começo ÚNICO.** Nome de gente não aceita o
    "casa por pedaço" que o app usa para nome de empresa: "FULANO SOUZA" está
    dentro de "FULANO SOUZA LIMA" e de "FULANO SOUZA COSTA", que são duas
    pessoas com dois CPFs. Havendo mais de um começo possível, some — e a
    linha cai no impedimento, que é o desfecho certo quando não se sabe.
    """
    alvo = util.norm_espaco(nome)
    if not alvo or not participantes:
        return "", ""
    if alvo in participantes:
        return alvo, participantes[alvo]
    comecam = [k for k in participantes if k.startswith(alvo + " ")]
    if len(comecam) == 1:
        return comecam[0], participantes[comecam[0]]
    return "", ""


# --------------------------------------------------------------------------
# A decisão
# --------------------------------------------------------------------------
def identificar(files, textos: dict, participantes: dict | None = None,
                cadastro: dict | None = None, chave: str = "",
                favorecido: str = "", urls_ocr=()) -> Pessoa:
    """Quem recebe este reembolso — ou por que não dá para dizer.

    A ordem das fontes vai da mais DECLARADA para a menos: cadastro local
    (alguém digitou nome e CPF de propósito), Contatos do ERP (alguém digitou
    no sistema), e por último o texto do aviso, que numa foto é OCR.

    `chave` é a chave Pix já lida do aviso. Ela **não** é fonte de documento:
    fosse, uma chave que é um CPF válido confirmaria a si mesma. Ela é
    CONFERENTE — sendo um documento e não sendo o que resolvemos, o dinheiro
    e o arquivo apontariam para pessoas diferentes, e aí ninguém paga nada.

    `favorecido` é o `paidTo` do lançamento. Quando ele pode ser a pessoa do
    aviso (`pessoa_e_o_favorecido`: começa com o nome dela e está nos Contatos
    com CPF), o nome COMPLETO dele desempata dois cadastros que começam igual
    — **mas só se o aviso confirmar**: o documento lido no aviso, o do
    cadastro local ou a `chave` (que vem de um dos dois) tem de ser o MESMO
    CPF que os Contatos têm para o favorecido. Sem isso, "PAGAR PARA FULANA"
    num título da HOMÔNIMA a declararia com o CPF dela, e o começo do nome não
    decide para quem vai. Não confirmando, vale a busca de sempre, pelo
    primeiro nome.

    `urls_ocr` vai para a leitura do documento no aviso: texto de OCR só
    conta pela janela depois da frase (ver `janelas_do_aviso`).
    """
    nome = nome_do_aviso(files)
    if not nome:
        return Pessoa(impedimento=MOTIVO_SEM_NOME)

    local = _do_cadastro_local(nome, cadastro or {})
    erp = _do_erp(nome, participantes or {})
    do_aviso = documento_do_aviso(files, textos, urls_ocr)
    if pessoa_e_o_favorecido(files, favorecido, participantes):
        completo = util.norm_espaco(favorecido)
        do_favorecido = regras.documento_valido(participantes[completo])
        if do_favorecido in {local[1], do_aviso, regras.documento_valido(chave)}:
            erp = (completo, do_favorecido)

    achados = []                       # [(documento, nome oficial, origem)]
    for oficial, doc, origem in (
        (*local, ORIGEM_CADASTRO_LOCAL),
        (*erp, ORIGEM_ERP),
        (util.norm_espaco(nome), do_aviso, ORIGEM_AVISO),
    ):
        if oficial and doc:
            achados.append((doc, oficial, origem))

    if not achados:
        return Pessoa(impedimento=MOTIVO_SEM_DOCUMENTO.format(
            nome=util.norm_espaco(nome), arquivo=ARQ_REEMBOLSO))

    if len({doc for doc, _, _ in achados}) > 1:
        return Pessoa(impedimento=MOTIVO_DOCUMENTO_DIVERGENTE.format(
            nome=util.norm_espaco(nome),
            origens=" e ".join(origem for _, _, origem in achados)))

    documento, oficial, origem = achados[0]

    da_chave = regras.documento_valido(chave)
    if da_chave and da_chave != documento:
        return Pessoa(impedimento=MOTIVO_CHAVE_DE_OUTRO.format(
            nome=util.norm_espaco(nome)))

    return Pessoa(nome=oficial, documento=documento, origem=origem)
