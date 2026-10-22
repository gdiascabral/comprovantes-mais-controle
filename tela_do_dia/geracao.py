# -*- coding: utf-8 -*-
"""O `Resultado` que a tela manda para planilha, HTML e remessa — sem tela.

É o da Remessa (`confirmacao.remontar`, com os MESMOS argumentos) e mais o
que o dono decidiu na nuvem: liberados (`ids_liberados`), desmarcados,
edições e pagamentos à mão. Os três geradores leem ESTE resultado
(planilha: `relatorio.gerar_excel`; HTML: `html_pagamentos.gravar`;
remessa: `para_a_remessa` → `remessa_dia.preparar`), então uma linha
editada não tem como sair com o dado antigo num e o novo noutro.

Os status novos — LIBERADO, EDITADO, À MÃO — não começam com "APTO": na
conferência da Remessa nascem DESMARCADOS (`remessa_dia.Candidato.apto`). E
não começam com "ATENÇÃO", então o HTML deixa copiar — exceto quando já
havia um alarme que a decisão não resolve: esse fica NA FRENTE do status
("ATENÇÃO — valor do boleto diverge · EDITADO — …"), e "JÁ PAGO" também.
Só cedem: à liberação, os alarmes de forma de pagar (`ATENCOES_DE_FORMA`) e o
`relatorio.STATUS_LIBERADO` que o gancho pôs; à edição da forma de pagar, só
"sem dados de pgto" (trocar a chave não traz o anexo que falta).

À mão NUNCA vai na remessa CNAB: sem lançamento do dia, não há referência
para o retorno nem para a baixa (`para_a_remessa`). No HTML, o à mão com link
tem o id "<lançamento>#mao:<n>" (o link continua o do lançamento): o mesmo
lançamento pode estar na lista do dia, e o id é a chave do "já paguei" e do
"Conferido" da página (`html_pagamentos.contas_do_html_geral`).
"""
from __future__ import annotations

import re
import unicodedata

from pagamentos_dia import confirmacao, relatorio, remessa_dia

from . import conferencia as cf
from . import pagamentos as pg

BLOQUEIO_JA_ENVIADO = "já enviado em remessa"
ATENCOES_DE_FORMA = ("ATENÇÃO — sem anexo", "ATENÇÃO — sem dados de pgto",
                     "ATENÇÃO — pagar à mão")
#: O que a liberação resolve: os alarmes de forma e o "liberado" do gancho.
_CEDE_A_LIBERACAO = (*ATENCOES_DE_FORMA, relatorio.STATUS_LIBERADO)
#: O que a edição da forma de pagar resolve: só a falta do dado de pagar.
_CEDE_A_EDICAO = ("ATENÇÃO — sem dados de pgto",)
ORDEM_A_MAO = 1_000_000
#: "pagar à mão" escrito num motivo não pode virar a ordem de pagar outra
#: pessoa: o HTML (`_motivo_do_bloqueio`, texto normalizado) e a remessa
#: (`_impedimento`, "PAGAR À MÃO" exato) leem esse texto na Obs. Procura-se
#: no texto SEM ACENTO (NFKD), como o HTML: "á", "Á", NFD, tudo cai aqui.
_GATILHO_A_MAO = re.compile(r"pagar\s+a\s+mao", re.IGNORECASE)


def ids_divididos(grupos) -> set[str]:
    """Os lançamentos divididos em N boletos (linhas com `parte`)."""
    return {ln.id for g in grupos for ln in (*g.entram, *g.nao_aptos)
            if ln.id and getattr(ln, "parte", "")}


def ids_nao_aptos(grupos) -> set[str]:
    return {ln.id for g in grupos for ln in g.nao_aptos if ln.id}


def _ja_enviados(grupos) -> dict[str, str]:
    """{id: "já saiu na remessa nº …"} dos `pg.ids_que_nao_saem` — os MESMOS
    ids que a entrega 1 tira de planilha, HTML e remessa."""
    ids = pg.ids_que_nao_saem(grupos)
    return {ln.id: str(getattr(ln.candidato, "ja_enviado", "") or BLOQUEIO_JA_ENVIADO)
            for g in grupos for ln in g.entram if ln.id in ids}


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c))


def _texto_do_dono(texto) -> str:
    """O texto livre do dono, sem o gatilho "pagar à mão" (em qualquer
    grafia). Só quando o gatilho existe o texto perde os acentos — é o preço
    de trocar o trecho no texto que o HTML e a remessa leem."""
    t = str(texto or "")
    sem = _sem_acento(t)
    if not _GATILHO_A_MAO.search(sem):
        return t
    return _GATILHO_A_MAO.sub("pagar (a mao)", sem)


def _status(antes: str, rotulos: list[str], cede: tuple) -> str:
    novo = " · ".join(rotulos)
    if not antes or antes.startswith("APTO") or antes in cede:
        return novo
    return f"{antes} · {novo}"           # ATENÇÃO que fica, JÁ PAGO…


def aplicar_decisao(reg: dict, d, *, liberavel: bool, bloqueio: str = "",
                    participantes: dict | None = None) -> dict:
    """O registro com a decisão do dono aplicada (o mesmo dicionário).

    `liberavel`: a linha estava bloqueada (não apta ou já enviada) quando a
    tela a mostrou; liberação de linha que já sai não muda nada. `bloqueio`:
    o que a prendia, quando o registro não traz `bloqueio_liberado` (o já
    enviado: "já saiu na remessa nº …"). `participantes`: o cadastro de
    Contatos (`Entradas.participantes`), para a chave Pix editada dizer se o
    CPF/CNPJ dela é o do favorecido do ERP."""
    if d is None:
        return reg
    antes, notas, rotulos = str(reg.get("status") or ""), [], []
    cede: tuple = ()
    # Parte de lançamento dividido (entrega 5): a edição é por id e a forma
    # de pagar (ou o reembolso) iria igual às N partes — o mesmo boleto N
    # vezes. Só a descrição vale para elas; a tela já recusa o resto.
    dividido = bool(reg.get("parte"))
    valor_diverge = False
    if d.edicoes:
        campos = []
        if dividido and d.edicoes.keys() & {"tipo", "dados", "reembolso_nome",
                                             "reembolso_documento"}:
            notas.append("forma de pagar editada não vale aqui: lançamento dividido "
                         "em boletos — corrija no ERP")
        if "tipo" in d.edicoes and not dividido:
            tipo = d.edicoes["tipo"]
            reg["tipo"], reg["dados"] = tipo, d.edicoes.get("dados", "")
            # O que era da cobrança antiga não acompanha a forma nova: o Pix do
            # QR e a linha da guia (o "Copiar" e a checagem de repetição do
            # HTML) e o "boleto parcial", que a remessa só lê no boleto e o
            # HTML lê sempre — sem isto os dois discordariam.
            reg["pix_qr"], reg["linha_da_guia"] = "", ""
            # A conferência do documento (cruzamento NF × boleto) era da
            # cobrança antiga: não vale para a forma nova.
            reg["conferencia"] = ""
            reg["parcial"] = bool(reg.get("parcial")) and tipo == "Boleto"
            campos.append("forma de pagar")
            cede = _CEDE_A_EDICAO
        if "reembolso_nome" in d.edicoes and not dividido:
            nome = d.edicoes["reembolso_nome"]
            reg.update(reembolso=True, reembolso_nome=nome, reembolso_para=nome,
                       reembolso_documento=d.edicoes.get("reembolso_documento", ""),
                       reembolso_origem="tela", reembolso_impedimento="")
            campos.append("reembolso")
        if "descricao" in d.edicoes:
            reg["descricao"] = reg["descricao_editada"] = d.edicoes["descricao"]
        if "tipo" in d.edicoes and not dividido and reg["tipo"] == "Pix":
            # A chave editada vai como foi digitada, com observação (dono,
            # 22/10/2026). A marca faz a remessa declarar o titular da chave
            # quando ela é CPF/CNPJ (`remessa_dia.preparar`); a comparação é
            # com o documento que a remessa usaria sem a edição.
            reg[remessa_dia.CHAVE_EDITADA] = True
            notas.append(cf.nota_da_chave_editada(
                reg["dados"], remessa_dia.documento_sem_edicao(reg, participantes)))
        if "tipo" in d.edicoes and not dividido and reg["tipo"] == "Boleto":
            # A linha editada × o valor do pagamento (dono, 22/10/2026). A tela
            # já perguntou antes de gravar a que diverge; aqui ela fica em
            # ATENÇÃO (Copiar do HTML bloqueado, desmarcada na Remessa).
            conferido = cf.conferir_valor_da_linha(reg["dados"], reg.get("valor"))
            if conferido.nota:
                notas.append(conferido.nota)
            valor_diverge = conferido.estado == cf.VALOR_DIVERGE
        era = "; ".join(f"{k}={v}" for k, v in d.antes.items())
        notas.append(f"editado na tela por {d.quem_nome or '?'} "
                     f"({_texto_do_dono(d.motivo_edicao)})"
                     + (f": era {_texto_do_dono(era)}" if era else ""))
        if d.corrigir_no_erp:
            notas.append(f"corrigir no ERP: lançamento {reg.get('id') or '?'}")
        if campos:                         # só a descrição: o status não muda
            rotulos.append("EDITADO — " + ", ".join(campos))
    if d.liberado and liberavel and not dividido:
        bloqueio = reg.get("bloqueio_liberado") or bloqueio or BLOQUEIO_JA_ENVIADO
        rotulos.insert(0, f"LIBERADO — {bloqueio} · {_texto_do_dono(d.motivo_liberacao)}")
        notas.append(f"liberado na tela por {d.quem_nome or '?'} em {d.quando[:16]}")
        cede = _CEDE_A_LIBERACAO
    if rotulos:
        reg["status"] = _status(antes, rotulos, cede)
    if valor_diverge and not reg["status"].startswith(("ATENÇÃO", "JÁ PAGO")):
        # Na FRENTE: é o "ATENÇÃO" que bloqueia o Copiar do HTML e faz a
        # Remessa não marcar. Um ATENÇÃO ou JÁ PAGO que já estava fica na frente.
        reg["status"] = f"{cf.STATUS_VALOR_DIVERGE} · {reg['status']}"
    if reg.get("status") != antes and antes:
        notas.append(f"status antes: {antes}")
    if notas:
        reg["obs"] = " · ".join(filter(None, [*notas, reg.get("obs") or ""]))
    return reg


def registro_a_mao(p, ordem: int) -> dict:
    """O registro de planilha/HTML de um pagamento à mão. Com link, a
    descrição sai das peças do lançamento (CC na frente, documento no fim),
    como uma linha do ERP: o Anexar casa o comprovante quando a baixa vier."""
    reg = {"tipo": p.tipo or "-", "dados": p.dados, "valor": float(p.valor),
           "descricao": p.descricao, "favorecido": p.favorecido, "pix_qr": "",
           "linha_da_guia": "", "status": f"À MÃO — {p.motivo}", "conferencia": "",
           "obs": " · ".join(filter(None, [
               f"pagamento à mão por {p.quem_nome or '?'}",
               (f"parcial: {p.valor} de {p.valor_em_aberto} em aberto"
                if p.valor_em_aberto is not None and p.valor < p.valor_em_aberto else ""),
               "" if p.lancamento_id else "sem lançamento no ERP: o Anexar não tem o que casar"])),
           "oc": p.oc, "centro_custo": p.centro_custo, "nf": p.nf, "nf_anexada": False,
           "oc_da_descricao": p.oc, "descricao_lancamento": p.descricao if p.lancamento_id else "",
           "utilidade": False, "ordem": ordem, "id": p.lancamento_id, "parcial": False,
           "reembolso": False, "valor_diverge": False, "reembolso_nome": "",
           "reembolso_documento": "", "reembolso_origem": "", "reembolso_impedimento": "",
           "reembolso_para": "", "a_mao": p.alvo}
    if not p.lancamento_id:
        reg["descricao_editada"] = p.descricao
    return reg


def resultado_da_tela(entradas, grupos, conferencia) -> relatorio.Resultado:
    """O `Resultado` de planilha, HTML e (por `para_a_remessa`) remessa.

    Sem decisão nenhuma é EXATAMENTE o da entrega 1:
    `remontar(entradas, ids_que_nao_saem(grupos))`. Desmarcado ganha de tudo
    (vai para os omitidos com `MOTIVO_NAO_CONFIRMADO`)."""
    decisoes = conferencia.decisoes
    # Liberar é por id: num lançamento dividido devolveria também a parte já
    # enviada (pagar em dobro). A tela recusa; a liberação que chegue pela
    # nuvem não vale para ele (`pagamentos.por_conta` diz o mesmo).
    divididos = ids_divididos(grupos)
    liberados = {a for a, d in decisoes.items() if d.liberado and a not in divididos}
    desmarcados = {a for a, d in decisoes.items() if d.desmarcado}
    ja_enviados = _ja_enviados(grupos)
    nao_aptos = ids_nao_aptos(grupos)
    participantes = getattr(entradas, "participantes", None)
    r = confirmacao.remontar(entradas, (set(ja_enviados) - liberados) | desmarcados,
                             ids_liberados=nao_aptos & liberados)
    bloqueados = nao_aptos | set(ja_enviados)
    contas = {}
    for conta, regs in r.contas.items():
        saem = []
        for reg in regs:
            ident = str(reg.get("id") or "")
            saem.append(aplicar_decisao(dict(reg), decisoes.get(ident),
                                        liberavel=ident in bloqueados,
                                        bloqueio=ja_enviados.get(ident, ""),
                                        participantes=participantes))
        contas[conta] = saem
    for i, p in enumerate(conferencia.a_mao):
        contas.setdefault(p.conta, []).append(registro_a_mao(p, ORDEM_A_MAO + i))
    return relatorio.Resultado(dict(sorted(contas.items())), r.omitidos)


def para_a_remessa(resultado) -> relatorio.Resultado:
    """O mesmo resultado sem os pagamentos à mão (que nunca vão no CNAB)."""
    contas = {c: [r for r in regs if not r.get("a_mao")] for c, regs in resultado.contas.items()}
    return relatorio.Resultado({c: regs for c, regs in contas.items() if regs}, resultado.omitidos)


def chaves_que_saem(resultado) -> set[str]:
    """O id do lançamento, ou "mao:<n>" do à mão — o que a tela soma."""
    return {r.get("a_mao") or str(r.get("id") or "")
            for regs in resultado.contas.values() for r in regs}


def registro_atual(resultado, ident: str, parte_linha: str = "") -> dict | None:
    """O registro do LANÇAMENTO `ident` (nunca um à mão com o mesmo link), ou
    o omitido dele. Com `parte_linha` (lançamento dividido), o da parte
    daquela linha digitável; sem ela, o primeiro do id (o de sempre)."""
    achados = [r for regs in resultado.contas.values() for r in regs
               if not r.get("a_mao") and str(r.get("id") or "") == ident]
    if parte_linha:
        da_parte = next((r for r in achados if r.get("parte_linha") == parte_linha), None)
        if da_parte is not None:
            return da_parte
    if achados:
        return achados[0]
    return next((o for o in resultado.omitidos if str(o.get("id") or "") == ident), None)
