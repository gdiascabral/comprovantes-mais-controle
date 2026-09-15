# -*- coding: utf-8 -*-
"""A regra da janela "Confirmar o que entra" do passo 2 — sem tela.

Por que ela mudou (14/09/2026)
------------------------------
A janela abria ANTES de ler os anexos. A forma de pagar de cada linha saía
do que a busca de lançamentos trouxe, e isso mentia de dois jeitos: o título
com o boleto dentro do PDF da nota aparecia como "BOLETO sem código de
barras", e o que a apuração depois mandava para a aba NÃO ENTRARAM nem
aparecia — só se descobria abrindo a planilha, com a remessa já gerada. O
dono quase deixou pagamentos de fora por isso, e pediu que as análises do
"Gerar remessa" viessem para cá, junto com os lançamentos que não estão
aptos, para corrigir no ERP ANTES.

Então o passo 2 passou a ter duas fases. A primeira lê de verdade (baixa os
anexos, roda `montar_registros` sem filtro e a análise da remessa) e guarda
as `Entradas`; a janela mostra essa leitura; a segunda, depois do
"Confirmar", só REMONTA a partir do que foi guardado, tirando o que a pessoa
desmarcou. Não se baixa nada duas vezes, e o que a janela mostrou é o que a
planilha tem.

Por que é um módulo à parte
---------------------------
Pelo motivo de sempre da aba: o que só se testa abrindo janela não se
testa. Tudo que DECIDE o conteúdo mora aqui — as linhas de cada conta, a
situação juntando planilha e remessa, o rodapé, o que volta como não
confirmado e quais omitidos aparecem. O `pagamentos_frame` só desenha.

A análise da remessa só LÊ: `preparar` e `resolver_pagador` não reservam NSA
nem gravam nada (reservar é o `alocar_nsa` do `_gravar_remessas`, e gravar é
o `registrar`), e o teste cobra isso com um registro que anota escrita.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from . import ocr_boleto
from . import reembolso
from . import regras_pagamento as regras
from . import relatorio
from . import remessa_dia


# --------------------------------------------------------------------------
# A apuração guardada, e a remontagem sem rede
# --------------------------------------------------------------------------
@dataclass
class Entradas:
    """Tudo o que o `montar_registros` recebe, guardado depois de baixado.

    É o que permite confirmar sem voltar ao ERP: os textos dos anexos (e quais
    vieram de OCR) já estão aqui, e os cadastros locais foram lidos UMA vez —
    se alguém editar o `regras_fornecedor.json` com a janela aberta, a
    planilha continua sendo a que a janela mostrou.
    """

    selecionados: list          # os lançamentos das contas marcadas
    anexos: dict                # {tradePayableId: [anexo]}
    overviews: dict             # {id do lançamento: detalhe}
    textos: dict                # {downloadUrl: texto}
    urls_ocr: set
    cadastro_reembolso: dict | None
    regras_fornecedor: dict
    participantes: dict
    periodo: tuple              # (ini, fim) de quando a apuração rodou
    #: Anexos que deviam ser lidos e não foram (download que devolveu nada ou
    #: levantou). A forma de pagar dessas linhas foi decidida sem o documento.
    anexos_nao_lidos: set = field(default_factory=set)


def _periodo_legivel(periodo) -> str:
    ini, fim = periodo
    return f"{ini:%d/%m/%Y} a {fim:%d/%m/%Y}"


def periodo_da_planilha(periodo_da_busca, periodo_na_tela) -> tuple:
    """(período, aviso) da planilha do passo 2.

    O período é o da BUSCA, e não o da tela no clique: os lançamentos em
    memória são os que o "1. Buscar" leu, e nomear a planilha — e o
    `_periodo_do_resultado`, de que a remessa depende — pelas datas que a
    pessoa mexeu depois punha um dia no nome de uma planilha de outro. Se a
    tela mudou (ou não é uma data), o aviso diz de qual período a planilha
    sai e o que fazer para ter outro. Sem busca, `(None, "")`.
    """
    if periodo_da_busca is None:
        return None, ""
    if periodo_na_tela == periodo_da_busca:
        return periodo_da_busca, ""
    buscado = _periodo_legivel(periodo_da_busca)
    if not periodo_na_tela:
        return periodo_da_busca, (
            f"as datas na tela não são válidas: a planilha sai do período "
            f"buscado ({buscado}) — para outro período, busque de novo")
    return periodo_da_busca, (
        f"as datas na tela ({_periodo_legivel(periodo_na_tela)}) não são as "
        f"da busca ({buscado}): a planilha sai do período buscado — para "
        "outro período, busque de novo")


def aviso_de_anexos_nao_lidos(anexos) -> str:
    """O aviso da janela para os anexos que não foram lidos, ou "".

    Sem ele, o download que falhou passava calado: o boleto dentro da NF não
    lido vira o Pix do cadastro, verde, e nada na janela diz que a leitura
    daquela linha ficou pela metade."""
    quantos = len(set(anexos or ()))
    if not quantos:
        return ""
    return (f"{quantos} anexo(s) não foram lidos: a forma de pagar dessas "
            "linhas pode estar errada")


def remontar(entradas: Entradas, ids_nao_confirmados=()) -> relatorio.Resultado:
    """O `Resultado` da planilha, com o que a pessoa desmarcou de fora.

    É a MESMA chamada nas duas fases — sem filtro na apuração e com os
    desmarcados no "Confirmar" —, e por isso a janela e a planilha não têm
    como discordar sobre uma linha que ninguém tocou. Pura: não baixa nada.
    """
    return relatorio.montar_registros(
        entradas.selecionados, entradas.anexos, entradas.overviews,
        entradas.textos,
        pix_reembolso=reembolso.chaves(entradas.cadastro_reembolso),
        urls_ocr=entradas.urls_ocr,
        regras_fornecedor=entradas.regras_fornecedor,
        ids_nao_confirmados=ids_nao_confirmados,
        participantes=entradas.participantes,
        cadastro_reembolso=entradas.cadastro_reembolso,
        anexos_nao_lidos=entradas.anexos_nao_lidos)


# --------------------------------------------------------------------------
# A análise da remessa
# --------------------------------------------------------------------------
#: Os avisos que a janela mostra em cima da tabela quando a análise ficou
#: pela metade. Dizem O QUE não foi conferido, e não só que algo falhou:
#: "sem aviso de já enviado" lido como "nada foi enviado" é o pagamento em
#: dobro que a conferência existe para impedir.
#: O que a LINHA diz quando ninguém respondeu se ela já saiu numa remessa.
#: Um texto só, para o aviso de cima e a situação da linha dizerem igual.
NAO_CONFERI_ENVIO = "não conferi se já saiu em remessa"
AVISO_SEM_REGISTRO = ("não consegui falar com o registro de remessas: "
                      + NAO_CONFERI_ENVIO)
AVISO_SEM_CADASTRO = ("não li o cadastro de contas: não sei quais contas "
                      "geram remessa")
#: A análise quebrou por um motivo que NÃO é o registro (um defeito, um dado
#: que o `preparar` não esperava). O tipo do erro vai junto; culpar o registro
#: mandaria conferir a internet quando o problema é outro.
AVISO_ANALISE_FALHOU = "a análise da remessa falhou"

#: Nomes de exceção que querem dizer "o registro de remessas não respondeu".
#: Pelo NOME, e não por `isinstance`, pelo motivo do `widgets.explicar_erro`:
#: importar `nuvem.rest` aqui arrastaria a rede para dentro da regra pura.
_ERROS_DO_REGISTRO = frozenset({"RegistroMudo", "SemRede", "PrecisaEntrar",
                                "RecusadoPeloBanco", "RequestException",
                                "LoteTruncado"})


def _e_do_registro(erro: Exception) -> bool:
    """O `preparar` levantou porque o registro não respondeu (e aí vale a
    segunda passada sem ele), ou por outro motivo (e aí não vale)?"""
    if isinstance(erro, (remessa_dia.RegistroMudo, OSError)):
        return True
    return any(c.__name__ in _ERROS_DO_REGISTRO for c in type(erro).__mro__)

#: O detalhe do erro vai junto do aviso, cortado: o recado do `carregar` diz
#: qual linha do cadastro está torta, mas numa faixa de aviso cabe uma frase.
_TAMANHO_DO_ERRO = 160


def _com_erro(aviso: str, erro: Exception) -> str:
    detalhe = str(erro).strip()
    return f"{aviso} ({detalhe[:_TAMANHO_DO_ERRO]})" if detalhe else aviso


@dataclass
class AnaliseRemessa:
    """O que o "Gerar remessa" diria das contas apuradas, sem gerar nada."""

    #: `{conta: [Candidato]}` do `remessa_dia.preparar`.
    preparado: dict = field(default_factory=dict)
    #: `{conta: motivo}` das contas cujo pagador não resolveu.
    sem_remessa: dict = field(default_factory=dict)
    #: False quando o cadastro de contas não abriu — aí `sem_remessa` está
    #: vazio porque ninguém perguntou, e não porque toda conta gera.
    contas_conferidas: bool = True
    avisos: list = field(default_factory=list)
    #: Ids das linhas cuja pergunta "já saiu?" ficou SEM resposta — o
    #: registro não abriu, ou caiu antes de responder por elas. A linha diz
    #: `NAO_CONFERI_ENVIO` e fica âmbar: "não saiu" ali seria palpite.
    envios_nao_conferidos: set = field(default_factory=set)
    #: `{id: (estado da remessa, retorno do item)}` das linhas que JÁ SAÍRAM
    #: numa remessa — é o que diz se aquele envio foi rejeitado.
    envios: dict = field(default_factory=dict)

    def envio_conferido(self, ident: str) -> bool:
        return str(ident or "") not in self.envios_nao_conferidos

    def estado_do_envio(self, ident: str) -> tuple:
        return self.envios.get(str(ident or ""), ("", ""))

    def candidato(self, conta: str, ident: str):
        """O `Candidato` do lançamento, ou None. Pelo id, e não pela posição:
        a posição é um acordo com o laço do `preparar` que ninguém escreveu."""
        ident = str(ident or "")
        if not ident:
            return None
        return next((c for c in self.preparado.get(conta, ())
                     if c.id == ident), None)


def chaves_do_preparar(contas: dict) -> tuple[list, list]:
    """`(códigos de barras, referências)` que o `preparar` vai perguntar.

    Derivadas como ele deriva, linha a linha: o código de barras é
    `ocr_boleto.codigo_de_barras` da linha digitável (`dados` sem espaço nas
    pontas), só no Boleto, e a referência é o id da linha em texto
    (`remessa_dia._ja_enviado`). Aqui vão TODAS as linhas — o `preparar` não
    pergunta da linha impedida, e pré-carregar uma chave a mais custa um
    item no `in.(…)`; uma a menos custaria uma ida ao banco, e o teste que
    conta consultas pega. Sem repetição, na ordem em que aparecem.
    """
    identificadores: dict[str, None] = {}
    referencias: dict[str, None] = {}
    for registros in (contas or {}).values():
        for registro in registros:
            if registro.get("tipo") == "Boleto":
                codigo = ocr_boleto.codigo_de_barras(
                    (registro.get("dados") or "").strip())
                if codigo:
                    identificadores[codigo] = None
            referencia = str(registro.get("id") or "")
            if referencia:
                referencias[referencia] = None
    return list(identificadores), list(referencias)


class HistoricoPreCarregado:
    """O histórico de remessas com "já saiu?" respondido em LOTE — só para a
    análise da janela.

    O `preparar` pergunta `envio_de`/`envio_da_referencia` uma linha por vez,
    e contra o registro da nuvem cada pergunta é uma ida ao Supabase: com
    100–300 lançamentos, centenas de ida-e-volta dentro do worker do
    navegador, a cada "Gerar planilha". Este invólucro pergunta tudo de uma
    vez (`envios_em_lote`) ao ser criado e responde do que voltou.

    **Nunca responde "não saiu" sem ter perguntado.** Responde do cache só a
    chave que o lote DEVOLVEU — achada ou ausente —; qualquer outra (fora do
    pré-carregamento, ou que o lote não quis pôr no filtro) vai ao histórico
    de verdade, pelo caminho de sempre. Histórico sem `envios_em_lote` (o
    espelho local, um dublê) ou lote que levanta deixam o cache vazio, e aí
    tudo vai um-a-um, como antes. Qualquer outro atributo (`maior_ordem_do_dia`,
    …) passa direto.

    Fica AQUI, e não no `remessa_dia`, de propósito: o "Gerar remessa"
    continua perguntando uma por uma, na hora de gravar, ao registro vivo — é
    a pergunta que decide o arquivo, e não vale economizar nela.

    **Sem registro vivo** (`sem_registro()`, ou `historico=None`), ele não
    levanta: a ordem do dia vale 0 (o "seu número" da análise é descartado),
    a chave que já tem resposta — do lote ou de uma pergunta um-a-um que deu
    certo antes da queda — continua respondida, e a que não tem devolve "não
    saiu" ao `preparar` MAS fica anotada em `nao_respondidas`. É por essa
    anotação que a análise marca a linha como "não conferi", em vez de
    tratá-la como verde.
    """

    def __init__(self, historico, identificadores, referencias, *,
                 sem_registro: bool = False) -> None:
        self._real = historico
        self._por_identificador: dict = {}
        self._por_referencia: dict = {}
        self._sem_registro = sem_registro or historico is None
        #: `(identificadores, referencias)` que ninguém respondeu.
        self.nao_respondidas: tuple = (set(), set())
        em_lote = getattr(historico, "envios_em_lote", None)
        if em_lote is None or self._sem_registro:
            return
        try:
            por_identificador, por_referencia = em_lote(list(identificadores),
                                                        list(referencias))
        except Exception:                                    # noqa: BLE001
            # O lote é atalho: caindo, o caminho de sempre responde — e, se
            # ele também cair, é ele que levanta e vira o aviso da janela.
            return
        self._por_identificador = dict(por_identificador or {})
        self._por_referencia = dict(por_referencia or {})

    def sem_registro(self) -> "HistoricoPreCarregado":
        """O mesmo cache, sem voltar ao registro: para a segunda passada do
        `preparar` depois de o registro cair no meio da primeira."""
        outro = HistoricoPreCarregado(None, (), (), sem_registro=True)
        outro._por_identificador = self._por_identificador
        outro._por_referencia = self._por_referencia
        return outro

    def _responder(self, cache: dict, anotar: set, pergunta, chave):
        if chave in cache:
            return cache[chave]
        if self._sem_registro:
            anotar.add(chave)
            return None
        resposta = pergunta(chave)
        # Guarda o que o registro respondeu: se ele cair logo depois, a
        # segunda passada não perde esta resposta.
        cache[chave] = resposta
        return resposta

    def envio_de(self, identificador):
        return self._responder(
            self._por_identificador, self.nao_respondidas[0],
            lambda k: self._real.envio_de(k), identificador)

    def envio_da_referencia(self, referencia):
        return self._responder(
            self._por_referencia, self.nao_respondidas[1],
            lambda k: self._real.envio_da_referencia(k), referencia)

    def maior_ordem_do_dia(self, quando):
        if self._sem_registro:
            return 0
        return self._real.maior_ordem_do_dia(quando)

    def envio_respondido(self, identificador: str, referencia: str):
        """O envio que JÁ foi respondido para esta linha, sem perguntar de
        novo: primeiro pelo código de barras, depois pela referência — a
        mesma ordem do `remessa_dia._ja_enviado`."""
        for cache, chave in ((self._por_identificador, identificador),
                             (self._por_referencia, referencia)):
            if chave and cache.get(chave):
                return cache[chave]
        return None

    def __getattr__(self, nome):
        # Só chega aqui o que não é atributo do invólucro. O `_` de fora evita
        # recursão se alguém perguntar por `_real` antes do `__init__`.
        if nome.startswith("_") or self._real is None:
            raise AttributeError(nome)
        return getattr(self._real, nome)


def analisar_remessa(contas: dict, participantes: dict | None,
                     carregar_mapas, abrir_historico,
                     quando: _dt.date | None = None) -> AnaliseRemessa:
    """`remessa_dia.preparar` + `resolver_pagador` sobre as contas apuradas.

    `carregar_mapas()` devolve `(mapa_mc, empresas)`; `abrir_historico()` o
    registro de remessas. Chegam como funções porque abrir os dois é IO — a
    nuvem e dois JSON ao lado do exe — e é assim que o teste troca um e outro
    por dublês. Aqui só se decide o que fazer quando eles falham.

    **Nada aqui para a planilha.** No "Gerar remessa" a falta do registro é
    recusa, porque ali sai arquivo com NSA e "seu número" que precisam vir de
    um lugar só. Aqui não sai arquivo nenhum: sem o registro, `preparar` roda
    com `historico=None` — só deixa de dizer "já saiu na remessa nº…" — e a
    janela diz em voz alta que isso não foi conferido. A remessa de verdade,
    depois, pergunta de novo e continua recusando.
    """
    avisos: list[str] = []
    chaves = chaves_do_preparar(contas)
    try:
        real = abrir_historico()
    except Exception as e:                                   # noqa: BLE001
        avisos.append(_com_erro(AVISO_SEM_REGISTRO, e))
        real = None

    preparado = None
    if real is not None:
        # "Já saiu?" em lote: poucas consultas em vez de uma ou duas por linha.
        historico = HistoricoPreCarregado(real, *chaves)
        try:
            preparado = remessa_dia.preparar(contas, participantes,
                                             quando=quando, historico=historico)
        except Exception as e:                               # noqa: BLE001
            if not _e_do_registro(e):
                return _analise_que_falhou(contas, avisos, e)
            # `RegistroMudo` (a ordem do dia não veio) ou a rede caindo no
            # meio de um `envio_de` fora do lote. A segunda passada NÃO joga
            # fora o que já foi respondido: continua com o cache, sem voltar
            # ao registro, e o que ficou sem resposta vira "não conferi".
            avisos.append(_com_erro(AVISO_SEM_REGISTRO, e))
            historico = historico.sem_registro()
    else:
        historico = HistoricoPreCarregado(None, (), (), sem_registro=True)

    if preparado is None:
        try:
            preparado = remessa_dia.preparar(contas, participantes,
                                             quando=quando, historico=historico)
        except Exception as e:                               # noqa: BLE001
            return _analise_que_falhou(contas, avisos, e)

    nao_conferidos = _envios_sem_resposta(contas, preparado,
                                          historico.nao_respondidas)
    envios = _estados_dos_envios(contas, preparado, historico)

    sem_remessa: dict[str, str] = {}
    conferidas = True
    try:
        mapa_mc, empresas = carregar_mapas()
        for conta in preparado:
            pagador, motivo = remessa_dia.resolver_pagador(conta, mapa_mc,
                                                           empresas)
            if pagador is None:
                sem_remessa[conta] = motivo
    except Exception as e:                                   # noqa: BLE001
        conferidas, sem_remessa = False, {}
        avisos.append(_com_erro(AVISO_SEM_CADASTRO, e))
    return AnaliseRemessa(preparado=preparado, sem_remessa=sem_remessa,
                          contas_conferidas=conferidas, avisos=avisos,
                          envios_nao_conferidos=nao_conferidos, envios=envios)


def _analise_que_falhou(contas: dict, avisos: list, erro: Exception):
    """A análise que não chegou ao fim: nenhuma linha fica verde por falta de
    pergunta. Toda linha analisável entra em `envios_nao_conferidos` (âmbar,
    "não conferi se já saiu em remessa"), e o aviso diz o TIPO do erro — sem
    culpar o registro quando o motivo não foi ele."""
    ids = {str(r.get("id")) for registros in (contas or {}).values()
           for r in registros if r.get("id")}
    avisos.append(f"{AVISO_ANALISE_FALHOU}: {type(erro).__name__}")
    return AnaliseRemessa(preparado={}, sem_remessa={},
                          contas_conferidas=False, avisos=avisos,
                          envios_nao_conferidos=ids)


def _estados_dos_envios(contas: dict, preparado: dict, historico) -> dict:
    """`{id: (estado da remessa, retorno do item)}` das linhas que o
    `preparar` achou JÁ ENVIADAS. Sai da resposta que o invólucro já guardou
    — nada é perguntado de novo —, e o `remessa_dia` continua usando só o
    `nsa`/`gerado_em` de sempre."""
    envios: dict = {}
    for conta, registros in (contas or {}).items():
        for registro in registros:
            ident = str(registro.get("id") or "")
            candidato = next((c for c in preparado.get(conta, ())
                              if ident and c.id == ident), None)
            if candidato is None or not candidato.ja_enviado:
                continue
            codigo = (ocr_boleto.codigo_de_barras(
                (registro.get("dados") or "").strip())
                if registro.get("tipo") == "Boleto" else "")
            achado = historico.envio_respondido(codigo, ident)
            if not achado:
                continue
            remessa = achado[0]
            item = achado[1] if len(achado) > 1 else None
            retorno = (getattr(remessa, "retorno_estado", "")
                       or getattr(item, "retorno_estado", "") or "")
            envios[ident] = (getattr(remessa, "estado", "") or "", retorno)
    return envios


def _envios_sem_resposta(contas: dict, preparado: dict, nao_respondidas) -> set:
    """Os ids das linhas em que o `preparar` perguntou "já saiu?" e ninguém
    respondeu. Só conta a linha que ele PERGUNTOU — a que pode sair e não
    achou envio —, com as chaves derivadas como em `chaves_do_preparar`."""
    identificadores, referencias = nao_respondidas
    if not (identificadores or referencias):
        return set()
    ids: set = set()
    for conta, registros in (contas or {}).items():
        for registro in registros:
            ident = str(registro.get("id") or "")
            candidato = next((c for c in preparado.get(conta, ())
                              if ident and c.id == ident), None)
            if candidato is None or not candidato.pode or candidato.ja_enviado:
                continue
            codigo = (ocr_boleto.codigo_de_barras(
                (registro.get("dados") or "").strip())
                if registro.get("tipo") == "Boleto" else "")
            if (codigo and codigo in identificadores) or ident in referencias:
                ids.add(ident)
    return ids


# --------------------------------------------------------------------------
# SITUAÇÃO e POR ONDE
# --------------------------------------------------------------------------
VAI_NA_REMESSA = "vai na remessa"
#: A linha não tem impedimento, mas o cadastro de contas não abriu: dizer "vai
#: na remessa" seria prometer o que ninguém conferiu. O aviso de cima explica.
SEM_IMPEDIMENTO_NA_LINHA = "sem impedimento na linha para a remessa"
#: O que junta as partes da SITUAÇÃO — o mesmo separador da conferência da
#: remessa (`situacao_na_conferencia`), para as duas janelas lerem igual.
SEPARADOR = " · "
#: O que se faz com a linha de uma conta de OUTRO banco: ela não entra em
#: remessa CNAB nenhuma, e o caminho do dia para ela é o HTML dos pagamentos.
PAGUE_PELO_HTML = "pague pelo HTML"


def _conta_de_outro_banco(sem_remessa: str) -> bool:
    """A conta não gera remessa porque é de outro banco — não por cadastro
    incompleto. O motivo é o do `resolver_pagador`, comparado por inteiro."""
    return sem_remessa == remessa_dia.MOTIVO_FORA_SICOOB


def _frase_de_outro_banco() -> str:
    return f"{remessa_dia.MOTIVO_FORA_SICOOB} — {PAGUE_PELO_HTML}"


#: Os impedimentos de remessa que interessam a QUEM PAGA À MÃO — e por isso
#: pintam de âmbar mesmo na conta de outro banco, que se paga pelo HTML:
#: a observação que manda pagar outra pessoa, o boleto que não se paga pela
#: metade, a linha digitável que não fecha, o valor do boleto que diverge, o
#: reembolso sem saber quem recebe e a chave de onze dígitos sem tipo — quem a
#: digita no app do banco precisa saber que pode ser CPF ou celular. Os outros
#: motivos da remessa (sem CPF/CNPJ para o segmento B, copia-e-cola, SANESC)
#: são do ARQUIVO do banco, e numa conta que não gera arquivo não pedem nada
#: de ninguém. As
#: constantes do `remessa_dia`, e não os textos: dois textos para o mesmo
#: motivo divergem em silêncio.
MOTIVOS_DE_QUEM_PAGA_A_MAO = (
    remessa_dia.MOTIVO_MAO,
    remessa_dia.MOTIVO_PARCIAL,
    remessa_dia.MOTIVO_LINHA,
    remessa_dia.MOTIVO_VALOR_DIVERGE,
    remessa_dia.MOTIVO_REEMBOLSO,
    remessa_dia.MOTIVO_CHAVE_AMBIGUA,
)


def _importa_a_quem_paga_a_mao(registro: dict, candidato) -> str:
    """O impedimento da linha, quando ele é de interesse de quem paga à mão;
    "" quando não há impedimento ou ele é só técnico da remessa.

    O reembolso sem quem recebe tem DUAS formas: o `MOTIVO_REEMBOLSO` e o
    recado da própria identificação (`reembolso_impedimento`, com o nome do
    aviso), que o `remessa_dia._impedimento` devolve no lugar dele. A segunda
    é a mesma pergunta sem resposta — a quem pagar —, então conta igual."""
    impedimento = getattr(candidato, "impedimento", "") if candidato else ""
    if not impedimento:
        return ""
    if impedimento in MOTIVOS_DE_QUEM_PAGA_A_MAO:
        return impedimento
    if (getattr(candidato, "reembolso", False)
            and impedimento == (registro.get("reembolso_impedimento") or "")):
        return impedimento
    return ""


def rotulo_do_envio(estado: str, retorno: str) -> str:
    """O que vem depois de "já saiu na remessa nº…": o estado da remessa e,
    quando o retorno citou este pagamento e diz outra coisa, o dele."""
    if retorno and retorno != estado:
        return f"{estado} (este pagamento: {retorno})" if estado else (
            f"este pagamento: {retorno}")
    return estado or retorno


def envio_rejeitado(estado: str, retorno: str) -> bool:
    """O envio anterior foi REJEITADO, e a linha pode sair de novo?

    Decide o retorno DO ITEM quando há um: remessa "rejeitado" quer dizer que
    ALGUM item foi recusado, e este pode ter sido pago — marcá-lo seria pagar
    duas vezes. Sem retorno citando o item, vale o estado da remessa."""
    if retorno:
        return retorno == "rejeitado"
    return estado == "rejeitado"


def situacao_da_linha(registro: dict, candidato, sem_remessa: str = "",
                      contas_conferidas: bool = True,
                      envio_conferido: bool = True,
                      estado_do_envio: tuple = ("", "")) -> tuple[str, str]:
    """(texto, estado) da SITUAÇÃO de uma linha que ENTRA na planilha.

    Primeiro o veredito da planilha (`APTO`, `ATENÇÃO — …`), depois o da
    remessa. Os textos da remessa são os dela — o `impedimento` e o
    `ja_enviado` do `Candidato` já são os `MOTIVO_*` do `remessa_dia` —, só
    com o prefixo que diz de qual das duas perguntas é a resposta.

    O estado é o da linha MARCADA: `atencao` quando a planilha diz ATENÇÃO,
    quando a remessa não leva (a conta não gera, ou a linha tem impedimento)
    ou quando ela já saiu numa remessa; `ok` no resto. Desmarcar é outra
    coisa, e quem pinta de vermelho é `estado_na_tela`.

    **Conta de OUTRO banco não é pendência** (`MOTIVO_FORA_SICOOB`). Ela não
    faz remessa CNAB e nunca vai fazer: a situação diz, em tom neutro, que a
    conta não faz remessa e se paga pelo HTML, e a cor é a da planilha.
    Pintar toda linha do Inter de âmbar todo dia é ensinar a pular o âmbar —
    e é no âmbar que mora a conta Sicoob sem convênio, que essa continua
    pintando. **A exceção é quem paga à mão**: a conta de outro banco se paga
    pelo HTML, e alguns impedimentos são justamente o que essa pessoa precisa
    ver (`MOTIVOS_DE_QUEM_PAGA_A_MAO`). Com um deles a linha fica âmbar e a
    situação mostra O MOTIVO, no lugar do recado genérico; o impedimento só
    técnico da remessa continua neutro.

    **"Já saiu na remessa nº…" vem antes de tudo, em TODOS os ramos** — conta
    Sicoob, de outro banco, sem remessa —, como na conferência da remessa: o
    boleto que já saiu e aparece verde "pague pelo HTML" é pago duas vezes.
    Pelo mesmo motivo, a linha cuja pergunta ficou sem resposta
    (`envio_conferido=False`) diz `NAO_CONFERI_ENVIO` e fica âmbar. E o
    reembolso é âmbar sempre: o dinheiro vai para quem não é o favorecido.
    """
    status = (registro.get("status") or "").strip()
    partes = [status] if status else []
    atencao = (status.upper().startswith("ATEN")
               or bool(registro.get("reembolso")))

    if candidato is not None and candidato.ja_enviado:
        rotulo = rotulo_do_envio(*estado_do_envio)
        partes.append(f"{candidato.ja_enviado} — {rotulo}" if rotulo
                      else candidato.ja_enviado)
        atencao = True
    elif not envio_conferido:
        partes.append(NAO_CONFERI_ENVIO)
        atencao = True

    if _conta_de_outro_banco(sem_remessa):
        a_mao = _importa_a_quem_paga_a_mao(registro, candidato)
        if a_mao:
            partes.append(a_mao)
            atencao = True
        else:
            partes.append(_frase_de_outro_banco())
    elif sem_remessa:
        partes.append(f"conta sem remessa: {sem_remessa}")
        atencao = True
    elif candidato is not None:
        if not candidato.pode:
            partes.append(f"remessa não leva: {candidato.impedimento}")
            atencao = True
        else:
            partes.append(VAI_NA_REMESSA if contas_conferidas
                          else SEM_IMPEDIMENTO_NA_LINHA)
    return SEPARADOR.join(partes), ("atencao" if atencao else "ok")


def por_onde(tipo: str, dados: str) -> str:
    """POR ONDE o dinheiro sai, com o dado que a PLANILHA vai ter.

    Do registro, e não do `Candidato`: a chave e o código de barras do
    candidato só existem quando a remessa leva a linha, e esta coluna tem de
    mostrar o destino também da linha que ela não leva — é essa que se paga à
    mão. O boleto sai nos grupos em que se lê no papel; vazio diz o motivo da
    remessa (`MOTIVO_SEM_CHAVE`), que é o nome dessa falta no app.
    """
    dados = (dados or "").strip()
    rotulo = (tipo or "?").strip().upper()
    if tipo == "Boleto" and dados and ocr_boleto.eh_arrecadacao(dados):
        rotulo = "ARRECADAÇÃO"
    if not dados:
        return f"{rotulo}  {remessa_dia.MOTIVO_SEM_CHAVE}"
    if tipo == "Boleto":
        return f"{rotulo}  {ocr_boleto.formatar(dados)}"
    return f"{rotulo}  {dados}"


# --------------------------------------------------------------------------
# As linhas da janela
# --------------------------------------------------------------------------
ENTRA = "entra"
NAO_APTO = "nao_apto"


@dataclass
class Linha:
    """Uma linha de lançamento da janela — das que entram ou das não aptas."""

    secao: str                  # ENTRA | NAO_APTO
    id: str
    conta: str
    valor: float
    favorecido: str
    tipo: str
    dados: str
    por_onde: str
    vencimento: _dt.date | None
    oc: str
    centro_custo: str
    descricao: str
    #: Na que entra, planilha · remessa; na não apta, o MOTIVO de não entrar.
    situacao: str
    #: ok | atencao | erro — o da linha MARCADA (ver `estado_na_tela`).
    estado: str
    olhar: bool                 # o ⚠ do `confirmar_antes.json`
    obs: str = ""
    conferencia: str = ""
    candidato: object = None    # `remessa_dia.Candidato`, quando houve análise
    #: O texto de pagamento do CADASTRO do lançamento (`paidToBankAccount`: a
    #: TED escrita à mão, a chave como está lá). É o que ajuda a corrigir o
    #: não apto no ERP — o motivo diz o que falta, este diz o que ESTÁ lá.
    pagamento_no_cadastro: str = ""
    #: A linha paga um aviso "PAGAR PARA": o dinheiro vai para `reembolso_nome`
    #: (quem o `reembolso.identificar` achou), não para o `favorecido`.
    reembolso: bool = False
    reembolso_nome: str = ""
    #: A linha já saiu numa remessa e esse envio foi REJEITADO
    #: (`envio_rejeitado`): é o pagamento que tem de sair de novo.
    envio_rejeitado: bool = False

    @property
    def quem_recebe(self) -> str:
        """O que vai na coluna QUEM RECEBE. No reembolso é a PESSOA — "?"
        quando não se descobriu quem — com o fornecedor entre parênteses: a
        coluna dizia o fornecedor, e o dinheiro não vai para ele."""
        if self.reembolso:
            return (f"{self.reembolso_nome or '?'} "
                    f"(reembolso de {self.favorecido or '?'})")
        return self.favorecido

    @property
    def marcavel(self) -> bool:
        """Só a que entra. A não apta não se força pela janela: o motivo dela
        é um dado do ERP, e é lá que se corrige."""
        return self.secao == ENTRA


@dataclass
class Grupo:
    conta: str
    entram: list
    nao_aptos: list
    #: O motivo de a conta não gerar remessa, ou "" (gera, ou não se sabe).
    sem_remessa: str = ""


def omitidos_da_janela(omitidos, fornecedores=None) -> list:
    """Quais NÃO ENTRARAM aparecem na janela.

    Fora ficam dois, e os dois são decisão já tomada, não pendência: a conta
    fora do recorte (conta de ajuste, ou desmarcada na tela) e o R$ 1,00 do
    fornecedor marcado `so_marcador` no cadastro — foram três linhas dessas
    desmarcadas à mão todo dia até 20/08/2026, e vermelho repetido todo dia
    ensina a pular vermelho. O R$ 1,00 de quem NÃO está marcado continua
    aparecendo: ali o "é marcador" é suposição da regra, e pode ser taxa de
    verdade. A aba NÃO ENTRARAM da planilha continua com todos.
    """
    marcados = fornecedores or {}
    return [o for o in omitidos or ()
            if not o.get("fora_do_recorte")
            and not (o.get("motivo") == regras.MOTIVO_SIMBOLICO
                     and regras.so_marcador(o.get("favorecido") or "",
                                            marcados))]


def _ja_pago(registro: dict, item: dict) -> bool:
    return bool(item.get("paid")) or (
        registro.get("status") or "").upper().startswith("JÁ PAGO")


def grupos_da_confirmacao(resultado, analise: AnaliseRemessa | None,
                          lancamentos, destacar=(),
                          fornecedores=None) -> list:
    """`[Grupo]`: as contas em ordem alfabética, cada uma com o que ENTRA e o
    que NÃO ENTROU.

    Dentro de ENTRAM, quem o `confirmar_antes.json` manda conferir (o ⚠) vem
    na frente e o resto pelo favorecido — a ordem da janela antiga, que quem
    confere já conhece. NÃO APTOS ficam na ordem do `montar_registros` (por
    motivo), que junta os do mesmo defeito.

    Já pago não entra: não há o que decidir sobre ele, e desmarcá-lo não
    faria nada — o `montar_registros` não omite linha paga.

    `lancamentos` são os do passo 1: é de lá que sai o vencimento, que a
    linha da planilha não carrega.
    """
    por_id = {str(i.get("id")): i for i in lancamentos or () if i.get("id")}
    sem_remessa = analise.sem_remessa if analise else {}
    conferidas = analise.contas_conferidas if analise else True

    def vencimento(ident):
        item = por_id.get(str(ident or ""))
        return relatorio.data_do_item(item) if item else None

    def pagamento_no_cadastro(ident):
        item = por_id.get(str(ident or "")) or {}
        return (item.get("paidToBankAccount") or "").strip()

    entram: dict[str, list] = {}
    for conta, registros in (resultado.contas or {}).items():
        for reg in registros:
            ident = str(reg.get("id") or "")
            if _ja_pago(reg, por_id.get(ident) or {}):
                continue
            candidato = analise.candidato(conta, ident) if analise else None
            texto, estado = situacao_da_linha(
                reg, candidato, sem_remessa.get(conta, ""), conferidas,
                envio_conferido=(analise.envio_conferido(ident)
                                 if analise else True),
                estado_do_envio=(analise.estado_do_envio(ident)
                                 if analise else ("", "")))
            favorecido = reg.get("favorecido") or ""
            entram.setdefault(conta, []).append(Linha(
                secao=ENTRA, id=ident, conta=conta,
                valor=float(reg.get("valor") or 0),
                favorecido=favorecido, tipo=reg.get("tipo") or "",
                dados=reg.get("dados") or "",
                por_onde=por_onde(reg.get("tipo") or "", reg.get("dados") or ""),
                vencimento=vencimento(ident), oc=str(reg.get("oc") or ""),
                centro_custo=reg.get("centro_custo") or "",
                descricao=reg.get("descricao") or "",
                situacao=texto, estado=estado,
                olhar=regras.exige_confirmacao(favorecido, destacar),
                obs=reg.get("obs") or "",
                conferencia=reg.get("conferencia") or "",
                candidato=candidato,
                reembolso=bool(reg.get("reembolso")),
                reembolso_nome=reg.get("reembolso_nome") or "",
                envio_rejeitado=bool(analise) and envio_rejeitado(
                    *analise.estado_do_envio(ident))))

    nao_aptos: dict[str, list] = {}
    for o in omitidos_da_janela(resultado.omitidos, fornecedores):
        conta = o.get("conta") or ""
        ident = str(o.get("id") or "")
        favorecido = o.get("favorecido") or ""
        nao_aptos.setdefault(conta, []).append(Linha(
            secao=NAO_APTO, id=ident, conta=conta,
            valor=float(o.get("valor") or 0), favorecido=favorecido,
            tipo=o.get("tipo") or "", dados=o.get("dados") or "",
            por_onde=por_onde(o.get("tipo") or "", o.get("dados") or ""),
            vencimento=vencimento(ident), oc=str(o.get("oc") or ""),
            centro_custo=o.get("centro_custo") or "",
            descricao=o.get("descricao") or "",
            situacao=o.get("motivo") or "", estado="erro",
            olhar=regras.exige_confirmacao(favorecido, destacar),
            obs=o.get("obs") or "", conferencia=o.get("conferencia") or "",
            pagamento_no_cadastro=pagamento_no_cadastro(ident)))

    grupos = []
    for conta in sorted(set(entram) | set(nao_aptos)):
        linhas = entram.get(conta, [])
        linhas.sort(key=lambda ln: (not ln.olhar, relatorio.chave(ln.favorecido)))
        grupos.append(Grupo(conta=conta, entram=linhas,
                            nao_aptos=nao_aptos.get(conta, []),
                            sem_remessa=sem_remessa.get(conta, "")))
    return grupos


def resumo_da_conta(grupo: Grupo) -> str:
    """A SITUAÇÃO da linha da conta, em cima das suas: quantas entram,
    quantas não, e — quando a conta não gera remessa — por quê, com o mesmo
    tom da linha (neutro para outro banco, "conta sem remessa" para cadastro
    incompleto)."""
    texto = (f"{len(grupo.entram)} entra(m) · "
             f"{len(grupo.nao_aptos)} não apto(s)")
    if _conta_de_outro_banco(grupo.sem_remessa):
        texto += f"{SEPARADOR}{_frase_de_outro_banco()}"
    elif grupo.sem_remessa:
        texto += f"{SEPARADOR}conta sem remessa: {grupo.sem_remessa}"
    return texto


# --------------------------------------------------------------------------
# Marcas, cor e rodapé
# --------------------------------------------------------------------------
def marcada_de_inicio(linha: Linha) -> bool:
    """Se a linha nasce marcada na janela. Nasce marcada a que entra; a que
    JÁ SAIU numa remessa nasce desmarcada, como na conferência da remessa —
    marcá-la é o mesmo pagamento duas vezes, e isso pede o clique de quem leu
    o aviso. **A exceção é o envio REJEITADO** (`envio_rejeitado`): esse
    boleto não foi pago, e nascer desmarcado era deixá-lo vencer — ele nasce
    marcado, e continua âmbar com o estado escrito na situação. A não apta
    não tem marca."""
    if not linha.marcavel:
        return False
    if getattr(linha.candidato, "ja_enviado", ""):
        return linha.envio_rejeitado
    return True


def estado_na_tela(linha: Linha, marcado: bool) -> str:
    """A cor da linha, na legenda da janela: não apto e desmarcado são `erro`
    ("fica de fora"); a marcada fica com o próprio estado."""
    if not linha.marcavel or not marcado:
        return "erro"
    return linha.estado


def resumo(grupos, marcas) -> tuple[int, float, int, int]:
    """(marcados, quanto somam, desmarcados, não aptos) — o número que se
    confere antes de gerar. `marcas` é `[(Linha, marcado)]` das marcáveis."""
    marcas = list(marcas)
    vao = [ln for ln, m in marcas if m]
    return (len(vao), sum(ln.valor for ln in vao), len(marcas) - len(vao),
            sum(len(g.nao_aptos) for g in grupos))


def frase_do_rodape(marcados: int, total: float, desmarcados: int,
                    nao_aptos: int) -> str:
    """A frase do `RodapeTabela`, com os não aptos no fim: eles não somam no
    total — nada ali sai hoje —, mas quem confere precisa saber quantos são."""
    partes = [f"{marcados} marcado" + ("s" if marcados != 1 else ""),
              relatorio.brl(total)]
    if desmarcados:
        partes.append(f"{desmarcados} fica" + ("m" if desmarcados != 1 else "")
                      + " de fora")
    if nao_aptos:
        partes.append(f"{nao_aptos} não apto" + ("s" if nao_aptos != 1 else ""))
    return "  ·  ".join(partes)


def nao_confirmados(marcas) -> set:
    """Os ids DESMARCADOS — o que a remontagem tira, com
    `MOTIVO_NAO_CONFIRMADO`, da planilha e da remessa."""
    return {ln.id for ln, m in marcas if not m and ln.id}
