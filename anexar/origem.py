# -*- coding: utf-8 -*-
"""De onde saiu cada comprovante, e de que conta é cada lançamento.

Regra do dono (14/09/2026): quando a OC não casa, olhar o nº do documento, DE
ONDE SAIU o pagamento e QUAL A CONTA cadastrada no sistema. O `matcher` só
sabe comparar (banco, conta); quem descobre os dois lados é este módulo:

- o PDF, pelo registro da baixa (`.ja-baixados.json`), que desde 14/09/2026
  guarda `origem` e `recebedor` de cada arquivo -- e, nos registros de antes,
  pelo que a própria CHAVE já dizia (`sicoob:<conta>:<id>`, `pix:<id>`);
- o lançamento, pelo MESMO cadastro de contas que a remessa usa
  (`contas_mc.json` + `contas_sicoob.json`), escolhendo a conta do Sicoob por
  `remessa_dia._escolher_conta`. Um terceiro mapa seria uma divergência a
  mais esperando acontecer.

Não saber é permitido e é neutro: arquivo posto à mão, conta fora do cadastro
ou cadastro que não abriu deixam `origem` em None, e aí a conta não tira
ninguém da disputa. Nada aqui levanta para quem chama `preencher`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import util

_REGISTRO = ".ja-baixados.json"
_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")


def _digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _banco(texto) -> str:
    """"756"/"0756"/"Sicoob" -> "SICOOB"; "077"/"Inter" -> "INTER"."""
    t = util.norm_espaco(texto or "")
    if "SICOOB" in t or t.lstrip("0") == "756":
        return "SICOOB"
    if "INTER" in t or t.lstrip("0") == "77":
        return "INTER"
    return t


# ------------------------------------------------------------ o lado do PDF
def _origem_da_linha(chave: str, linha: dict) -> tuple | None:
    bruta = str(linha.get("origem") or "")
    if ":" in bruta:
        banco, conta = bruta.split(":", 1)
    else:
        partes = chave.split(":")
        fonte = partes[0].lower()
        if fonte in ("sicoob", "sicoob_pix") and len(partes) >= 3:
            banco, conta = "SICOOB", partes[1]
        elif fonte in ("pix", "inter2via"):
            banco, conta = "INTER", ""
        else:
            return None
    banco = _banco(banco)
    if banco == "SICOOB":
        return (banco, _digitos(conta))
    # No Inter a conta é o LOGIN (apelido), e não a empresa: duas contas da
    # mesma empresa são contas diferentes (revisão do PR #94).
    return (banco, util.norm_espaco(conta))


def origens_dos_pdfs(pasta) -> dict[str, dict]:
    """{nome do arquivo: {"origem": (banco, conta), "recebedor": str|None}}.

    O registro mora na raiz dos comprovantes, e a pasta escolhida no Anexar
    costuma ser a do DIA; por isso procura na pasta e na mãe. Numa pasta com
    nome de dia só valem as linhas baixadas naquele dia -- o mesmo nome de
    arquivo pode existir em outro dia, vindo de outra conta. Nome que aparece
    com duas origens diferentes fica de fora (não se sabe qual é qual)."""
    pasta = Path(pasta)
    dados = {}
    for onde in (pasta, pasta.parent):
        try:
            dados = json.loads((onde / _REGISTRO).read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            continue
    if not isinstance(dados, dict):
        return {}
    dia = pasta.name if _DIA.fullmatch(pasta.name) else ""

    achado: dict[str, dict] = {}
    duvidosos: set[str] = set()
    for chave, linha in dados.items():
        if not isinstance(linha, dict) or not linha.get("arquivo"):
            continue
        if dia and not str(linha.get("quando") or "").startswith(dia):
            continue
        org = _origem_da_linha(str(chave), linha)
        if org is None:
            continue
        nome = linha["arquivo"]
        novo = {"origem": org, "recebedor": linha.get("recebedor") or None,
                "doc_recebedor": linha.get("doc_recebedor") or None}
        if nome in achado and achado[nome]["origem"] != org:
            duvidosos.add(nome)
        achado[nome] = novo
    for nome in duvidosos:
        achado.pop(nome, None)
    return achado


# ------------------------------------------------------ o lado do lançamento
def origem_da_conta_erp(nome_erp: str, mapa_mc, empresas,
                        contas_inter=None) -> tuple | None:
    """(banco, conta) da conta do ERP, ou None quando o cadastro não diz.

    Sicoob: o número da conta. Inter: o apelido do login -- só quando a
    empresa tem UM login; com dois, não se sabe qual, e fica só o banco."""
    # Import tardio: o Anexar só paga por isto quando casa.
    from pagamentos_dia.remessa_dia import _escolher_conta

    destino = mapa_mc.de(nome_erp) if mapa_mc else None
    if destino is None or not (destino.banco or "").strip():
        return None
    banco = _banco(destino.banco)
    if banco == "SICOOB":
        _empresa, conta, _falta = _escolher_conta(destino, empresas or [])
        return (banco, _digitos(conta.numero) if conta else "")
    if banco == "INTER":
        empresa = util.norm_espaco(destino.empresa)
        logins = [c.apelido for c in (contas_inter or [])
                  if util.norm_espaco(c.empresa) == empresa]
        return (banco, util.norm_espaco(logins[0]) if len(logins) == 1 else "")
    return (banco, util.norm_espaco(destino.empresa))


def ocs_do_overview(overview) -> set[str]:
    """{"1234"} do `purchaseOrder.number` do overview; vazio sem OC."""
    oc = ((overview or {}).get("purchaseOrder") or {}).get("number")
    return {str(oc).strip()} if oc not in (None, "") else set()


def documentos_do_grupo(empresas) -> dict[str, str]:
    """{nome normalizado: CNPJ} das empresas do próprio cadastro.

    O favorecido de um APORTE é uma empresa do grupo, que nem sempre está no
    cadastro de Contatos do ERP; o `contas_sicoob.json` já tem o CNPJ dela,
    com os nomes pelos quais ela aparece (pasta, razão social e os clientes do
    ERP). Nome que cai em dois CNPJs sai do mapa."""
    vistos: dict[str, set] = {}
    for e in empresas or []:
        cnpj = _digitos(getattr(e, "cnpj", ""))
        if len(cnpj) != 14:
            continue
        nomes = [e.nome, getattr(e, "razao_social", "")] + list(
            getattr(e, "clientes_erp", []) or [])
        for nome in nomes:
            chave = util.norm_espaco(nome or "")
            if chave:
                vistos.setdefault(chave, set()).add(cnpj)
    return {n: docs.pop() for n, docs in vistos.items() if len(docs) == 1}


# --------------------------------------------------------------- juntando
def preencher(pendentes, pdfs, pasta, *, mapa_mc=None, empresas=None,
              contas_inter=None, documentos=None) -> dict:
    """Põe `origem`/`recebedor` nos PDFs e `origem` nos lançamentos.

    Os cadastros podem vir por argumento (teste) ou são lidos aqui; um que não
    abrir só deixa aquele lado sem origem. Devolve as contagens para o
    Registro da aba dizer quanto da regra de conta valeu nesta rodada."""
    if contas_inter is None:
        try:
            from baixar_comprovantes import contas_inter as _ci
            contas_inter = _ci.carregar()
        except Exception:                                    # noqa: BLE001
            contas_inter = []                                # ver o docstring
    if mapa_mc is None:
        try:
            from relatorios import contas_mc
            mapa_mc = contas_mc.carregar()
        except Exception:                                    # noqa: BLE001
            mapa_mc = None
    if empresas is None:
        try:
            from extratos_sicoob import sicoob_contas
            empresas = sicoob_contas.carregar().empresas
        except Exception:                                    # noqa: BLE001
            empresas = []

    origens = origens_dos_pdfs(pasta)
    for pd in pdfs:
        info = origens.get(pd["fn"]) or {}
        pd["origem"] = info.get("origem")
        pd["recebedor"] = info.get("recebedor")
        pd["doc_recebedor"] = info.get("doc_recebedor")
    # O cadastro de Contatos (quem chamou leu do ERP) manda; as empresas do
    # grupo completam o que ele não tem.
    docs = dict(documentos_do_grupo(empresas))
    docs.update({util.norm_espaco(k): _digitos(v)
                 for k, v in (documentos or {}).items() if _digitos(v)})
    for pe in pendentes:
        pe["doc_favorecido"] = docs.get(util.norm_espaco(pe.get("favorecido") or ""))
    for pe in pendentes:
        try:
            pe["origem"] = origem_da_conta_erp(pe.get("conta") or "", mapa_mc,
                                               empresas, contas_inter)
        except Exception:                                    # noqa: BLE001
            pe["origem"] = None
    return {"pdfs": len(pdfs),
            "pdfs_com_origem": sum(1 for p in pdfs if p.get("origem")),
            "lancamentos": len(pendentes),
            "lancamentos_com_conta": sum(1 for p in pendentes if p.get("origem"))}
