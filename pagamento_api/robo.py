# -*- coding: utf-8 -*-
"""O robô do servidor: uma rodada por chamada (o Agendador chama a cada 1–2 min).

    python -m pagamento_api.robo --config <arquivo.json>     rodada de verdade
    python -m pagamento_api.robo --ensaio-sandbox            Sicoob do Sandbox, sem nuvem e sem ERP

O arquivo de configuração mora na pasta de chaves do servidor, NUNCA no repo:
    {"ambiente": "sandbox",
     "client_id": "...", "token_fixo": "...",          (sandbox: os do portal)
     "cert": ["c:/.../cert.pem", "c:/.../chave.pem"],   (produção)
     "nuvem_email": "...", "nuvem_senha": "...",
     "pasta_comprovantes": "c:/.../comprovantes-api",
     "contas": {"NOME DA CONTA NO ERP": {"cooperativa": 0, "numero": 0, "tipo_pessoa": 1}}}
Neste plano o ERP é o de ENSAIO (não toca no Mais Controle); o de verdade e o
token de produção entram no plano 3.
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests

from . import executor as ex
from . import lote as lt
from . import sicoob as sc


class ErpDeEnsaio:
    """Finge o ERP: todo título em aberto com o valor do item; anexo e baixa anotados."""

    def __init__(self, itens):
        self.t = {i.titulo: ex.Titulo(True, i.valor, False) for i in itens}
        self.feito = []

    def titulo(self, tid):
        return self.t.get(tid)

    def anexar(self, tid, caminho):
        self.feito.append(("anexo", tid, str(caminho)))
        return True

    def baixar(self, tid, valor, dia, conta):
        self.feito.append(("baixa", tid, str(valor)))
        self.t[tid] = ex.Titulo(False, valor, True)
        return True


class LivroNaMemoria:
    def __init__(self):
        self.lista = []

    def eventos(self):
        return list(self.lista)

    def gravar(self, e):
        self.lista.append(e)
        print(f"  item {e.ordem}: {e.estado} {e.detalhe}".rstrip())


def cliente(cfg: dict) -> sc.Sicoob:
    if cfg.get("ambiente") != "sandbox":
        raise SystemExit("produção entra no plano 3 (token OAuth e certificado)")
    tok = str(cfg["token_fixo"])
    return sc.Sicoob(requests.Session(), sc.SANDBOX, str(cfg["client_id"]), lambda: tok,
                     cert=tuple(cfg["cert"]) if cfg.get("cert") else None)


def contas(cfg: dict) -> dict[str, sc.ContaApi]:
    return {nome: sc.ContaApi(int(c["cooperativa"]), int(c["numero"]), int(c["tipo_pessoa"]))
            for nome, c in (cfg.get("contas") or {}).items()}


def ensaio_sandbox(cfg: dict, pasta: Path) -> list[ex.Evento]:
    """Três itens fictícios contra o Sandbox. Os mocks do Sandbox respondem
    sempre igual, então o que se prova é o encanamento, não a regra."""
    conta = "ENSAIO - SICOOB"
    itens = [
        lt.ItemLote(1, "E1", "E1", conta, lt.PIX_CHAVE, "ensaio@exemplo.com", Decimal("1.99"),
                    "ENSAIO", "", "ENSAIO PIX"),
        lt.ItemLote(2, "E2", "E2", conta, lt.BOLETO, "75691234500000152301234567890123456789012345"[:44],
                    Decimal("152.30"), "ENSAIO", "", "ENSAIO BOLETO"),
        lt.ItemLote(3, "E3", "E3", conta, lt.CONVENIO, "8" + "3" * 43, Decimal("1171.23"),
                    "ENSAIO", "", "ENSAIO CONVENIO"),
    ]
    livro = LivroNaMemoria()
    portas = ex.Portas(cliente(cfg), ErpDeEnsaio(itens), livro,
                       {conta: sc.ContaApi(4342, 1234569, 1)}, pasta, date.today())
    ex.Executor(itens, lt.total(itens), portas).rodar()
    return livro.lista


#: O dia do banco é o de São Paulo (`privado.hoje()`), não o do relógio do servidor.
FUSO_SP = timezone(timedelta(hours=-3))      # sem horário de verão desde 2019


def hoje_sp() -> date:
    return datetime.now(FUSO_SP).date()


def _travar(fd) -> bool:
    """Trava do SISTEMA sobre o arquivo aberto: some sozinha quando o processo
    morre, então não existe "trava velha" nem rodada apagando a trava da outra
    (revisão da Task 8, 27/11/2026)."""
    try:
        import msvcrt                         # o robô, o app e a esteira rodam no Windows
    except ImportError:
        raise SystemExit("o robô só roda no Windows (trava msvcrt)") from None
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


@contextmanager
def trava_da_rodada(pasta: Path):
    """Uma rodada por vez nesta máquina. Devolve False quando outra está rodando.
    (Entre máquinas, quem segura é o índice `lote_evento_um_iniciado` do banco.)"""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(pasta / "robo.trava"), os.O_CREAT | os.O_RDWR)
    try:
        yield _travar(fd)
    finally:
        os.close(fd)                          # fechar solta a trava; o arquivo fica


def rodada(cfg: dict) -> None:
    # Neste plano o ERP é o de ENSAIO: rodar contra a nuvem de verdade gravaria
    # "concluído" num lote real sem nada ter acontecido no ERP (e o banco nunca
    # mais libera o título pela API). Só com a chave explícita de ensaio.
    if cfg.get("nuvem_de_ensaio") is not True:
        raise SystemExit("neste plano o robô só roda com \"nuvem_de_ensaio\": true "
                         "(ERP de ensaio); o ERP real entra no plano 3")
    with trava_da_rodada(Path(cfg["pasta_comprovantes"])) as minha:
        if not minha:
            print("outra rodada está rodando; esta sai sem fazer nada")
            return
        _rodada(cfg)


def _rodada(cfg: dict) -> None:
    from . import nuvem_lote as nl
    rest = nl.rest
    s = rest.entrar(cfg["nuvem_email"], cfg["nuvem_senha"])
    token = s["access_token"]
    nl.pulso(token)
    if nl.parado(token):
        print("parado pelo botão; nada a fazer")
        return
    hoje = hoje_sp()
    for lote in nl.lotes_aprovados(token, hoje):
        print(f"lote {lote.id}: {len(lote.itens)} itens, total {lote.total}")
        livro = nl.LivroNaNuvem(token, lote.id)
        # Uma pasta por lote: o JSON cru do convênio é achado pela retomada
        # sem risco de pegar o de outro lote com o mesmo título.
        portas = ex.Portas(cliente(cfg), ErpDeEnsaio(lote.itens), livro, contas(cfg),
                           Path(cfg["pasta_comprovantes"]) / f"lote-{lote.id}", hoje,
                           parar=lambda: nl.parado(token))
        ex.Executor(lote.itens, lote.total, portas).rodar()


USO = "uso: python -m pagamento_api.robo --config <arquivo.json> [--ensaio-sandbox]"


def _argumentos(argv) -> tuple[str, bool]:
    """(caminho do --config, --ensaio-sandbox?). Sem `argparse`: ele não vem no
    exe (tests/test_imports_do_motor.py), e o robô tem de rodar onde o app roda."""
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
    config, ensaio = _argumentos(sys.argv[1:] if argv is None else argv)
    if ensaio:
        cfg = json.loads(Path(config).read_text(encoding="utf-8")) if config else {}
        cfg.setdefault("ambiente", "sandbox")
        if "client_id" not in cfg or "token_fixo" not in cfg:
            print("passe --config com client_id e token_fixo do Sandbox (portal, menu Sandbox)")
            return 2
        ensaio_sandbox(cfg, Path(cfg.get("pasta_comprovantes") or "comprovantes-ensaio"))
        return 0
    if not config:
        print(USO)
        return 2
    rodada(json.loads(Path(config).read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
