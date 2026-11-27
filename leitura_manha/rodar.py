# -*- coding: utf-8 -*-
"""A leitura das 07:30, uma rodada por chamada (o Agendador chama uma vez por dia).

    python -m leitura_manha.rodar --config <arquivo.json>                    rodada de verdade
    python -m leitura_manha.rodar --config <ensaio.json> --ensaio-sandbox    Sandbox do Sicoob
                                                                              e/ou do Inter, sem
                                                                              nuvem e sem ERP

O arquivo mora na pasta de chaves do servidor (formato em `config.py`). O
ensaio aceita o JSON do plano 1 ({"client_id", "token_fixo"}) e/ou
{"inter_chaves": "<pasta com client_id.txt, client_secret.txt, .crt e .key>"},
e não grava nada.
O ERP só é lido pelo porteiro (Chrome central ligado): nunca login HTTP.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from pagamento_api.robo import trava_da_rodada

from . import bancos as bc
from . import config as cf
from . import leitura as lt
from . import nuvem_leitura as nl
from .transporte import Ritmo


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Fabrica:
    """Os clientes reais. Um Ritmo por banco, compartilhado entre as empresas."""

    def __init__(self, cfg: cf.Config, sessao=None):
        self._cfg = cfg
        self._s = sessao or requests.Session()
        self.ritmo_sicoob = Ritmo(bc.INTERVALO_SICOOB)
        self.ritmo_inter = Ritmo(bc.INTERVALO_INTER)
        self.ritmo_token_inter = Ritmo(bc.INTERVALO_TOKEN_INTER)
        self._tokens_inter = {}

    def sicoob(self, empresa: cf.Empresa) -> bc.ContaCorrenteSicoob:
        cred = empresa.sicoob
        cert = tuple(cred["cert"]) if cred.get("cert") else None
        if self._cfg.ambiente == "sandbox":
            fixo = cred["token_fixo"]
            return bc.ContaCorrenteSicoob(self._s, bc.SICOOB_SANDBOX, cred["client_id"],
                                          lambda: fixo, ritmo=self.ritmo_sicoob, cert=cert)
        token = bc.token_sicoob(self._s, cred["client_id"], cert)
        return bc.ContaCorrenteSicoob(self._s, bc.SICOOB_PRODUCAO, cred["client_id"], token,
                                      ritmo=self.ritmo_sicoob, cert=cert)

    def inter(self, empresa: cf.Empresa, conta: cf.ContaBanco) -> bc.BankingInter:
        cred = empresa.inter
        cert = tuple(cred["cert"])
        base = bc.INTER_SANDBOX if self._cfg.ambiente == "sandbox" else bc.INTER_PRODUCAO
        if empresa.nome not in self._tokens_inter:   # um token por empresa, não por conta
            self._tokens_inter[empresa.nome] = bc.token_inter(
                self._s, base, cred["client_id"], cred["client_secret"], cert,
                self.ritmo_token_inter)
        return bc.BankingInter(self._s, base, self._tokens_inter[empresa.nome],
                               ritmo=self.ritmo_inter, cert=cert,
                               conta_corrente=conta.conta_corrente)


class _ConfigDoErp:
    """O bastante do `config` da Conciliação para o `SessaoApi` (mesmo recurso de
    `ferramentas/sonda.py:_ConfigDoErp`, sem importar a sonda inteira)."""

    def __init__(self):
        from nuvem.contas_novas import API_BASE, LEGACY_BASE
        self.erp = {"api_base": API_BASE, "legacy_api_base": LEGACY_BASE}


def ler_erp_pelo_porteiro(*, central=None, ler_saldos=None, log=print) -> list:
    """Saldos do ERP SÓ com o porteiro ligado. Desligado: levanta antes de tocar
    no ERP — `ler_saldos` com o central desligado iria para a aba do app (que o
    servidor não tem) e o login HTTP derruba a sessão do Chrome central."""
    from conciliacao.errors import ErpError
    if central is None:
        from erp.sessao import central_ligado as central
    if ler_saldos is None:
        from tela_do_dia.erp_do_dia import ler_saldos

    def so_com_porteiro() -> bool:
        if not central():
            raise ErpError("porteiro do ERP desligado (Chrome central): o ERP não é lido sem ele")
        return True

    so_com_porteiro()
    return ler_saldos(_ConfigDoErp(), None, central_ligado=so_com_porteiro, log=log)


def _registro(pasta: Path):
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "leitura_manha.log"

    def log(msg: str) -> None:
        print(msg)
        try:
            with arquivo.open("a", encoding="utf-8") as f:
                f.write(f"{agora_utc().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass
    return log


def resumo(le: lt.LeituraDosBancos, erp: list, marcas: list, log) -> None:
    for s in le.saldos + erp:
        log(f"  saldo {s.fonte:6} {s.conta}: " + (f"{s.valor}" if s.valor is not None
                                                 else f"NÃO LIDO — {s.motivo}"))
    for x in le.extratos:
        log(f"  extrato {x.fonte:6} {x.conta} {x.dia:%d/%m}: {x.saidas} saída(s), "
            f"{x.entradas} entrada(s), {x.ilegiveis} ilegível(is), {x.fora_do_dia} fora do dia"
            + (f" — {x.motivo}" if x.motivo else ""))
    log(f"  pré-marcados: {sum(1 for m in marcas if m.prova)} de {len(marcas)} agendado(s) olhados")


def rodada(cfg: cf.Config, *, fabrica=None, entrar=None, nuvem=nl, ler_erp=None,
           agora=agora_utc, log=print) -> int:
    """0 = gravou tudo; 1 = não gravou, ou gravou sem as pré-marcas (em_aberto não lido). Banco ou ERP fora não é 1: vira 'não lido'."""
    if cfg.ambiente != "producao":
        raise SystemExit("rodada de verdade só com ambiente 'producao'; Sandbox é --ensaio-sandbox")
    from nuvem import rest
    entrar = entrar or rest.entrar
    ler_erp = ler_erp or (lambda: ler_erp_pelo_porteiro(log=log))
    hoje, ontem = lt.dias_sp(agora())
    rodada_id = str(uuid.uuid4())
    log(f"leitura das 07:30 de {hoje:%d/%m/%Y} (extrato de {ontem:%d/%m}), rodada {rodada_id}")
    le = lt.ler_bancos(cfg, fabrica or Fabrica(cfg), ontem, agora)
    erp = lt.ler_erp(ler_erp, [c.conta_erp for c in cfg.contas()], agora)
    falhou = False
    try:
        token = entrar(cfg.nuvem_email, cfg.nuvem_senha)["access_token"]
        try:
            marcas = lt.pre_marcas(nuvem.em_aberto(token), le, hoje, log=log)
        except Exception as e:  # noqa: BLE001 — sem em_aberto não há pré-marca, mas os saldos entram
            marcas, falhou = [], True
            log(f"pré-marcas puladas: não li os agendados em aberto ({type(e).__name__})")
        resumo(le, erp, marcas, log)
        gravadas = nuvem.gravar(token, rodada_id, ontem, le.saldos + erp, le.extratos, marcas)
    except Exception as e:  # noqa: BLE001 — o Agendador vê o código 1; o log diz o tipo
        resumo(le, erp, [], log)
        log(f"NÃO GRAVOU na nuvem: {type(e).__name__}: {str(e)[:200]}")
        return 1
    log("gravado: " + ", ".join(f"{t} {n}" for t, n in gravadas.items()))
    return 1 if falhou else 0


def credencial_inter_da_pasta(pasta) -> dict:
    """As credenciais do Sandbox do Inter como o portal as entrega (4 arquivos).
    O conteúdo nunca é impresso: só vai para o bloco `inter` da config."""
    p = Path(pasta)
    return {"client_id": (p / "client_id.txt").read_text(encoding="utf-8-sig").strip(),
            "client_secret": (p / "client_secret.txt").read_text(encoding="utf-8-sig").strip(),
            "cert": [str(p / "Sandbox_InterAPI_Certificado.crt"),
                     str(p / "Sandbox_InterAPI_Chave.key")]}


def ensaio_sandbox(dados: dict, *, sessao=None, agora=agora_utc, log=print) -> lt.LeituraDosBancos:
    """Saldo e extrato de ontem de UMA conta do Sandbox do Sicoob (com `client_id`
    e `token_fixo`) e/ou do Inter (com `inter_chaves`: a pasta dos 4 arquivos).
    Só leitura: sem nuvem, sem ERP."""
    empresa = {"nome": "ENSAIO", "contas": []}
    if dados.get("client_id") or dados.get("token_fixo"):
        empresa["sicoob"] = {"client_id": dados.get("client_id"),
                             "token_fixo": dados.get("token_fixo")}
        empresa["contas"].append({"banco": "sicoob", "numero": int(dados.get("numero_ensaio") or 1),
                                  "conta_erp": "ENSAIO - SICOOB"})
    if dados.get("inter_chaves"):
        try:
            empresa["inter"] = credencial_inter_da_pasta(dados["inter_chaves"])
        except OSError as e:
            raise cf.ConfigInvalida(f"pasta do Inter ilegível ({type(e).__name__})") from None
        empresa["contas"].append({"banco": "inter", "conta_erp": "ENSAIO - INTER"})
    cfg = cf.de_dict({"ambiente": "sandbox", "pasta": str(dados.get("pasta") or "leitura-ensaio"),
                      "empresas": [empresa]})
    _hoje, ontem = lt.dias_sp(agora())
    le = lt.ler_bancos(cfg, Fabrica(cfg, sessao), ontem, agora)
    resumo(le, [], [], log)
    return le


USO = "uso: python -m leitura_manha.rodar --config <arquivo.json> [--ensaio-sandbox]"


def _argumentos(argv) -> tuple[str, bool]:
    """(caminho do --config, --ensaio-sandbox?). Sem `argparse`, como o robô."""
    config, ensaio, resto = "", False, list(argv)
    while resto:
        a = resto.pop(0)
        if a == "--ensaio-sandbox":
            ensaio = True
        elif a == "--config" and resto:
            config = resto.pop(0)
        elif a.startswith("--config="):
            config = a.split("=", 1)[1]
        else:
            raise SystemExit(f"argumento desconhecido: {a}\n{USO}")
    return config, ensaio


def main(argv=None) -> int:
    try:  # console do Agendador em cp1252: caractere fora dela não derruba a rodada
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    config, ensaio = _argumentos(sys.argv[1:] if argv is None else argv)
    if not config:
        print(USO)
        return 2
    if ensaio:
        import json
        try:
            dados = json.loads(Path(config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"não consegui ler {config} ({type(e).__name__})")
            return 2
        try:
            ensaio_sandbox(dados)
        except cf.ConfigInvalida as e:
            print(f"arquivo de ensaio: {e}")
            return 2
        return 0
    try:
        cfg = cf.carregar(config)
    except cf.ConfigInvalida as e:
        print(f"arquivo do servidor: {e}")
        return 2
    pasta = Path(cfg.pasta)
    log = _registro(pasta)
    with trava_da_rodada(pasta) as minha:
        if not minha:
            log("outra leitura está rodando; esta sai sem fazer nada")
            return 0
        return rodada(cfg, log=log)


if __name__ == "__main__":
    sys.exit(main())
