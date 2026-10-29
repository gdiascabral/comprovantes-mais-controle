# -*- coding: utf-8 -*-
"""A leitura do dia da Remessa, sem tela — para a aba "Pagamentos do dia".

Quem sabe o que VAI SAIR e o que está BLOQUEADO é a apuração da Remessa:
`confirmacao.remontar` (que é quem chama `relatorio.montar_registros`, com os
mesmos argumentos da janela "Confirmar o que entra") +
`confirmacao.analisar_remessa` + `confirmacao.grupos_da_confirmacao`.
Reescrever uma delas seria a segunda régua que diverge da primeira. Aqui só se
ORQUESTRA, na mesma ordem do `PagamentosDiaFrame._t_buscar` /
`_juntar_entradas` / `_baixar_textos` / `_t_apurar`, com o ERP, a nuvem, o
disco e os leitores (QR, PDF, OCR) entrando por parâmetro.

Diferença deliberada para o frame: lá as contas são as que a pessoa MARCOU; aqui
é `conta_entra` (por padrão `relatorio.conta_entra`), que é o mesmo critério
com que o frame nasce marcando (`ignorada` desmarcada). Já pagos ficam de fora,
como no frame com "incluir pagos" desligado.

**Só leitura.** Nada reserva NSA, nada registra remessa: a análise da remessa
é a mesma da janela "Confirmar o que entra" (só pergunta "já saiu?").

**Parar no meio não monta nada** (a mesma regra do `_t_apurar`): leitura de
anexos pela metade transforma o boleto dentro da NF em Pix do cadastro. E o
"pare" visto UMA vez vale até o fim (`_Parada`): o frame pergunta ao Event de
novo depois dos downloads, e um Event limpo nesse meio-tempo deixaria passar
uma leitura pela metade com cara de inteira. Aqui, `interrompida=True` vem
sempre com `entradas`, `resultado`, `analise` = None e `grupos` vazio.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import boletos_somados, confirmacao, ocr_boleto, qr_pix, relatorio


@dataclass
class LeituraDosPagamentos:
    periodo: tuple
    lancamentos: list = field(default_factory=list)
    anexos: dict = field(default_factory=dict)
    overviews: dict = field(default_factory=dict)
    participantes: dict = field(default_factory=dict)
    entradas: "confirmacao.Entradas | None" = None
    resultado: "relatorio.Resultado | None" = None
    analise: "confirmacao.AnaliseRemessa | None" = None
    grupos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    interrompida: bool = False
    #: Ids dos lançamentos de DEPOIS do período que entraram adiantados
    #: (`separar_adiantados`); vazio sem `adiantar_ate`.
    adiantados: set = field(default_factory=set)


def separar_adiantados(lancamentos, anexos, fim) -> tuple[list, set, int]:
    """`(ficam, ids_adiantados, fora)`: os lançamentos com vencimento depois
    de `fim` só ficam quando se pagam por código de barras (dono, 29/10/2026:
    "pegar só os boletos" dos dias seguintes — guia e conta de consumo
    também). Quem decide é `relatorio.tipo_de_pagamento`, a MESMA régua da
    planilha: boleto anexado ganha; sem anexo, a forma do lançamento. Pix,
    transferência e débito automático ficam de fora (`fora` conta quantos).
    Sem data de vencimento fica, como no `filtrar_periodo`."""
    ficam, adiantados, fora = [], set(), 0
    for item in lancamentos:
        venc = relatorio.data_do_item(item)
        if venc is None or venc <= fim:
            ficam.append(item)
            continue
        files = anexos.get(str(item.get("tradePayableId")), ()) or ()
        if relatorio.tipo_de_pagamento(item, files) == "Boleto":
            ficam.append(item)
            adiantados.add(str(item.get("id") or ""))
        else:
            fora += 1
    return ficam, adiantados, fora


class _Parada:
    """O `cancelar` de quem chama, com memória: depois do primeiro True,
    devolve True para sempre. Vai também para a API (`anexos_de_titulos`,
    `listar_overviews`), que param no meio e devolvem o que leram."""

    def __init__(self, cancelar):
        self._cancelar, self.pedida = cancelar, False

    def __call__(self) -> bool:
        if not self.pedida and self._cancelar():
            self.pedida = True
        return self.pedida


# Cópia de `PagamentosDiaFrame._anexos_a_ler` / `_baixar_textos`
# (pagamentos_frame.py), sem a fila da tela: duplicação temporária e
# declarada. Quando o branch que mexe no frame entrar, o frame passa a chamar
# estas duas (e `ler_pagamentos`) em vez das cópias dele.
def anexos_a_ler(selecionados, anexos) -> list[tuple[str, bool, bool]]:
    """[(downloadUrl, é_pdf, ler_texto)] sem repetição — `_anexos_a_ler`.

    PDF sempre entra, com texto. Foto entra sempre (é dela que sai o QR do
    Pix), mas só tem o texto lido (OCR) quando é aviso "PAGAR PARA"."""
    vistos, urls = set(), []
    for item in selecionados:
        for f in anexos.get(str(item.get("tradePayableId"))) or []:
            url = f.get("downloadUrl")
            if not url or url in vistos:
                continue
            pdf = relatorio.eh_pdf(f)
            aviso = bool(relatorio._PAGAR_PARA.search(relatorio._rotulo(f)))
            if pdf or aviso or relatorio._e_imagem(f):
                vistos.add(url)
                urls.append((url, pdf, pdf or aviso))
    return urls


def baixar_textos(baixar, alvos, *, log=print, progresso=lambda f, t: None,
                  cancelar=lambda: False, ler_qr=qr_pix.ler,
                  texto_pdf=relatorio.texto_de_pdf,
                  ocr_pdf=ocr_boleto.texto_ocr_pdf,
                  ocr_imagem=ocr_boleto.texto_ocr_imagem):
    """({url: texto}, {urls por OCR}, {urls não lidas}, {url: [Pix]}) — `_baixar_textos`.

    Download que levanta ou devolve nada vira anexo NÃO LIDO (a linha sai
    "ATENÇÃO — anexo não lido"), nunca "sem texto". O QR é lido em todo anexo
    baixado; o OCR só no que veio sem camada de texto.

    `cancelar()` True para no próximo anexo e devolve o que leu até ali: quem
    chama tem de perguntar de novo (ou usar `ler_pagamentos`, que lembra).
    """
    textos, urls_ocr, nao_lidos, qrs = {}, set(), set(), {}
    sem_texto, total = 0, len(alvos)
    if alvos:
        log(f"\nBaixando e lendo {total} anexo(s) para o cruzamento...")
    for i, (url, eh_pdf, ler_texto) in enumerate(alvos, 1):
        if cancelar():
            log("Interrompido a pedido — a leitura dos anexos ficou incompleta.")
            break
        try:
            dados = baixar(url)
        except Exception as e:                               # noqa: BLE001
            log(f"  [!] não consegui baixar um anexo: {e}")
            dados = None
        if not dados:
            nao_lidos.add(url)
            progresso(i, total)
            continue
        codigos = ler_qr(dados, eh_pdf)
        if codigos:
            qrs[url] = codigos
        if not ler_texto:
            progresso(i, total)
            continue
        texto = texto_pdf(dados) if eh_pdf else ""
        if not texto.strip():
            texto = ocr_pdf(dados, log) if eh_pdf else ocr_imagem(dados)
            if texto.strip():
                urls_ocr.add(url)
        textos[url] = texto
        if not texto.strip():
            sem_texto += 1
        progresso(i, total)
    if urls_ocr:
        log(f"  {len(urls_ocr)} anexo(s) sem texto lidos por OCR.")
    if sem_texto:
        log(f"  {sem_texto} anexo(s) que nem o OCR conseguiu ler — "
            "esses não dá para cruzar.")
    if qrs:
        log(f"  {len(qrs)} anexo(s) com QR Code Pix lido.")
    return textos, urls_ocr, nao_lidos, qrs


def titulos_a_dividir(resultado, lancamentos) -> list[str]:
    """Os `tradePayableId` das linhas que o relatório marcou "vários boletos
    no título" — os ÚNICOS candidatos a dividir, e os únicos cujo título se lê
    no ERP. Sem repetição, em ordem."""
    titulo_de = {str(i.get("id")): str(i.get("tradePayableId") or "")
                 for i in lancamentos or () if i.get("id")}
    saida: dict[str, None] = {}
    for registros in (resultado.contas or {}).values():
        for reg in registros:
            if reg.get("status") == boletos_somados.STATUS_VARIOS:
                tpid = titulo_de.get(str(reg.get("id") or ""), "")
                if tpid:
                    saida[tpid] = None
    return list(saida)


def titulo_no_erp(api, tpid: str) -> dict | None:
    """O título INTEIRO no ERP (`numberOfInstallments`, `installments[]`,
    `totalValue`…), ou None. Só leitura, de dentro da página do Chrome do app
    (`_base_legacy` + `_fetch_json`, os mesmos da `mc_api`) — nunca login
    HTTP por fora.

    Endereço a confirmar na prova ao vivo: `GET <legacy>/trade-payables/<id>`,
    o mesmo que `guias/lancar.py` já lê (pelo transporte do porteiro) para
    pegar `installments`/`account` do título. Aqui ainda não foi medido pela
    sessão da `mc_api`. Resposta de erro (`__erro`), vazia ou que não é
    objeto vira None, e o título fica sem dados (não divide)."""
    url, headers = api._base_legacy(f"trade-payables/{tpid}")
    j = api._fetch_json(url, headers)
    if not isinstance(j, dict) or not j or j.get("__erro"):
        return None
    return j


def ler_titulos_no_erp(api, tpids, log=print, cancelar=lambda: False) -> dict:
    """`{tpid: título}` dos que leram. Falha fechada: o título que não leu
    (erro, vazio, exceção) fica de fora, e por isso NÃO divide — com aviso
    no log. `cancelar()` é consultado antes de cada título: o "Parar" para
    a fila ali (quem chama marca a leitura como interrompida)."""
    lidos = {}
    for tpid in tpids:
        if cancelar():
            break
        try:
            titulo = titulo_no_erp(api, tpid)
        except Exception as e:                               # noqa: BLE001
            titulo, motivo = None, str(e)
        else:
            motivo = "resposta vazia ou com erro"
        if titulo is None:
            log(f"não li o título {tpid} no ERP ({motivo}): os boletos dele "
                "não são divididos")
            continue
        lidos[tpid] = titulo
    return lidos


def ler_pagamentos(api, ini, fim, *, abrir_historico, carregar_mapas,
                   cadastro_reembolso=None, regras_fornecedor=None, destacar=(),
                   conta_entra=relatorio.conta_entra, log=print,
                   progresso=lambda f, t: None, cancelar=lambda: False,
                   adiantar_ate=None, **leitores) -> LeituraDosPagamentos:
    """Busca, lê os anexos e apura como a Remessa, de `ini` a `fim` (date).

    `adiantar_ate` (date depois de `fim`) lê também os vencimentos até ele,
    mas deles só o que se paga por código de barras (`separar_adiantados`),
    antes de ler detalhe e anexo de quem sai. `leitura.periodo` continua
    `(ini, fim)`: o dia de trabalho não muda.

    `api` é a `mc_api` da sessão do Chrome do app (`anx.garantir_sessao()`);
    `abrir_historico`/`carregar_mapas` são os do `analisar_remessa`;
    `leitores` (`ler_qr`, `texto_pdf`, `ocr_pdf`, `ocr_imagem`) vão para
    `baixar_textos`. Erro da API antes dos anexos (credenciais, lista)
    propaga; Contatos que falham viram aviso, como no frame.

    Devolve `interrompida=True` — e nada apurado — se `cancelar()` disse True
    em QUALQUER momento.
    """
    leitura = LeituraDosPagamentos(periodo=(ini, fim))
    cancelar = _Parada(cancelar)
    if not api.capturar_credenciais(log):
        raise RuntimeError("A tela de Pagamentos não carregou a lista no Chrome.")
    ate = adiantar_ate if adiantar_ate and adiantar_ate > fim else fim
    brutos = api.listar_a_pagar(f"{ini:%Y-%m-%d}", f"{ate:%Y-%m-%d}", log=log)
    leitura.lancamentos = relatorio.filtrar_periodo(brutos, ini, ate, log=log)
    if not leitura.lancamentos:
        leitura.resultado = relatorio.Resultado(contas={}, omitidos=[])
        return leitura

    titulos = sorted({str(i.get("tradePayableId")) for i in leitura.lancamentos
                      if i.get("tradePayableId")})
    if not api._req_anexos:
        api.capturar_credenciais_anexos(leitura.lancamentos[0].get("id"))
    leitura.anexos = api.anexos_de_titulos(titulos, log=log, progresso=progresso,
                                           cancelar=cancelar)
    if ate > fim:
        leitura.lancamentos, leitura.adiantados, fora = separar_adiantados(
            leitura.lancamentos, leitura.anexos, fim)
        log(f"  Adiantados: {len(leitura.adiantados)} de código de barras com vencimento "
            f"até {ate:%d/%m}; {fora} de Pix/transferência dos dias seguintes ficaram de fora.")
        if not leitura.lancamentos:
            leitura.resultado = relatorio.Resultado(contas={}, omitidos=[])
            return leitura
    ids = [str(i.get("id")) for i in leitura.lancamentos if i.get("id")]
    leitura.overviews = api.listar_overviews(ids, log=log, progresso=progresso,
                                             cancelar=cancelar)
    try:
        leitura.participantes = api.listar_participantes(log=log)
    except Exception as e:                                   # noqa: BLE001
        leitura.participantes = {}
        leitura.avisos.append(f"não li o cadastro de Contatos ({e}): o Pix por "
                              "telefone, e-mail ou chave aleatória fica de fora da remessa")
    if cancelar():
        leitura.interrompida = True
        return leitura

    selecionados = [i for i in leitura.lancamentos
                    if conta_entra(relatorio.nome_da_conta(i))]
    a_pagar, _pagos = relatorio.separar_pagos(selecionados)
    textos, urls_ocr, nao_lidos, qrs = baixar_textos(
        api.baixar_anexo, anexos_a_ler(a_pagar, leitura.anexos), log=log,
        progresso=progresso, cancelar=cancelar, **leitores)
    if cancelar():
        leitura.interrompida = True
        return leitura

    entradas = confirmacao.Entradas(
        selecionados=a_pagar, anexos=leitura.anexos, overviews=leitura.overviews,
        textos=textos, urls_ocr=urls_ocr, cadastro_reembolso=cadastro_reembolso,
        regras_fornecedor=regras_fornecedor or {}, participantes=leitura.participantes,
        periodo=(ini, fim), anexos_nao_lidos=nao_lidos, qr_pix=qrs,
        titulos_nao_lidos=set(getattr(api, "titulos_sem_leitura", ()) or ()),
        # A tela nova divide o lançamento cujos boletos somam exato
        # (`boletos_somados`); a Remessa/Retorno, lendo sozinha, não.
        dividir_boletos=True,
        adiantar_de=fim if leitura.adiantados else None)
    # Sem título lido nada divide, e as linhas candidatas continuam com o
    # status "vários boletos": é por ele que se sabe QUAIS títulos ler.
    entradas.titulos_erp = ler_titulos_no_erp(
        api, titulos_a_dividir(confirmacao.remontar(entradas), a_pagar), log=log,
        cancelar=cancelar)
    if cancelar():
        # Parou no meio dos títulos: nada apurado, nada dividido pela metade.
        leitura.interrompida = True
        return leitura
    leitura.entradas = entradas
    leitura.resultado = confirmacao.remontar(entradas)
    leitura.avisos.extend(boletos_somados.avisos(leitura.resultado))
    leitura.analise = confirmacao.analisar_remessa(
        leitura.resultado.contas, leitura.participantes,
        carregar_mapas=carregar_mapas, abrir_historico=abrir_historico)
    aviso = confirmacao.aviso_de_anexos_nao_lidos(nao_lidos)
    if aviso:
        leitura.avisos.insert(0, aviso)
    leitura.avisos.extend(leitura.analise.avisos)
    leitura.grupos = confirmacao.grupos_da_confirmacao(
        leitura.resultado, leitura.analise, a_pagar, destacar=destacar,
        fornecedores=entradas.regras_fornecedor)
    return leitura
