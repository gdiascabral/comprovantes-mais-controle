"""Linha de comando.

Uso normal (pelos atalhos .bat, sem terminal):
    conciliacao configurar-acesso   # uma vez: login manual, guarda a sessao
    conciliacao rodar               # o dia a dia: coleta + planilha + resumo

Uteis para diagnostico:
    conciliacao coletar --visivel   # so coleta, com janela aberta
    conciliacao analisar --snapshot snapshots/2026-07-30.json
    conciliacao montar   --snapshot snapshots/2026-07-30.json
    conciliacao descobrir-contas --aplicar
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from . import snapshot as snapshot_io
from .config import load_config
from .errors import ErpError, SessaoExpirada
from .mapping import AccountMapping
from .models import Periodo, sugerir_periodo
from .pipeline import analyze, run_offline
from .validate import ValidationError, erros
from .workbook import WorkbookError

RAIZ_PADRAO = Path(__file__).resolve().parents[2]

_DIAS_SEMANA = (
    "segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sabado", "domingo",
)


def _configurar_saida() -> None:
    """O console do Windows abre em cp1252 e engasga com acento/emoji."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _base(args) -> tuple:
    return load_config(args.config), AccountMapping.load(args.mapping)


def _data(args) -> date:
    return date.fromisoformat(args.data) if getattr(args, "data", None) else date.today()


def _ler_data_solta(texto: str, hoje: date) -> date | None:
    """Aceita DD/MM, DD/MM/AAAA, DD-MM-AAAA ou AAAA-MM-DD."""
    limpo = texto.strip().replace("-", "/")
    if not limpo:
        return None
    partes = [p for p in limpo.split("/") if p]
    try:
        if len(partes) == 2:  # DD/MM -> assume o ano de hoje
            return date(hoje.year, int(partes[1]), int(partes[0]))
        if len(partes) == 3:
            if len(partes[0]) == 4:  # AAAA/MM/DD
                return date(int(partes[0]), int(partes[1]), int(partes[2]))
            ano = int(partes[2])
            if ano < 100:
                ano += 2000
            return date(ano, int(partes[1]), int(partes[0]))
    except ValueError:
        return None
    return None


def resolver_periodo(args, *, interativo: bool = True) -> Periodo:
    """Decide o intervalo de vencimentos que entra no painel.

    Prioridade: --de/--ate > --data > pergunta ao usuario > sugestao automatica.
    A sugestao inclui os dias nao-uteis anteriores: numa segunda ela cobre
    sabado, domingo e segunda, que e como o Gustavo fecha o dia.
    """
    hoje = date.today()

    de = _ler_data_solta(args.de, hoje) if getattr(args, "de", None) else None
    ate = _ler_data_solta(args.ate, hoje) if getattr(args, "ate", None) else None
    if de or ate:
        inicio, fim = de or ate, ate or de
        if inicio > fim:
            inicio, fim = fim, inicio
        return Periodo(inicio=inicio, fim=fim)

    if getattr(args, "data", None):
        return Periodo.de_um_dia(date.fromisoformat(args.data))

    sugerido = sugerir_periodo(hoje)

    if not interativo or getattr(args, "sem_perguntar", False):
        return sugerido

    print("=" * 58)
    print(f"  Hoje e {_DIAS_SEMANA[hoje.weekday()]}, {hoje:%d/%m/%Y}")
    print("=" * 58)
    print()
    print("  Quais vencimentos devem entrar no painel?")
    print()
    if sugerido.um_dia_so:
        print(f"    [Enter]  somente hoje ({hoje:%d/%m})")
    else:
        print(
            f"    [Enter]  {sugerido.descrever()}  "
            f"({len(sugerido.dias)} dias, inclui o fim de semana)"
        )
    print("    ou digite as datas, ex.:  25/07 a 27/07")
    print("    ou uma data so, ex.:      28/07")
    print()

    try:
        resposta = input("  Periodo [Enter para aceitar]: ").strip()
    except (EOFError, KeyboardInterrupt):
        resposta = ""

    if not resposta:
        print(f"\n  -> usando {sugerido.descrever()}\n")
        return sugerido

    # Aceita "25/07 a 27/07", "25/07 - 27/07", "25/07 27/07"
    bruto = resposta.lower().replace(" a ", " ").replace(" ate ", " ")
    bruto = bruto.replace(" até ", " ").replace(" - ", " ")
    pedacos = [p for p in bruto.split() if p]

    datas = [d for d in (_ler_data_solta(p, hoje) for p in pedacos) if d]
    if not datas:
        print(f"\n  nao entendi {resposta!r}; usando {sugerido.descrever()}\n")
        return sugerido

    periodo = Periodo(inicio=min(datas), fim=max(datas))
    print(f"\n  -> usando {periodo.descrever()}\n")
    return periodo


def _abrir_arquivo(caminho: Path) -> None:
    try:
        os.startfile(str(caminho))  # type: ignore[attr-defined]
    except Exception:
        pass


# --------------------------------------------------------------------- comandos


def cmd_salvar_senha(args) -> int:
    """Guarda e-mail/senha no cofre do Windows e valida entrando no ERP."""
    import getpass

    from .erp.auth import salvar_credenciais
    from .erp.collect import testar_login

    config, _ = _base(args)

    print("As credenciais vao para o Gerenciador de Credenciais do Windows,")
    print("criptografadas pela sua conta. Nao ficam em arquivo nem no codigo.\n")

    email = args.email or input("E-mail do Mais Controle: ").strip()
    if not email:
        print("E-mail vazio, nada foi salvo.", file=sys.stderr)
        return 1

    senha = getpass.getpass("Senha (nao aparece na tela): ")
    if not senha:
        print("Senha vazia, nada foi salvo.", file=sys.stderr)
        return 1

    salvar_credenciais(email, senha)
    print("\nSalvo. Testando o login de verdade...\n")
    testar_login(config)
    print("\nPronto: a conciliacao diaria agora entra sozinha.")
    return 0


def cmd_testar_login(args) -> int:
    from .erp.collect import testar_login

    config, _ = _base(args)
    testar_login(config)
    return 0


def cmd_coletar(args) -> int:
    from .erp.collect import coletar

    config, _ = _base(args)
    snap = coletar(config, periodo=resolver_periodo(args), visivel=not args.oculto)
    caminho = snapshot_io.save(snap, config.caminho("snapshots"))
    print(f"\nSnapshot salvo: {caminho}")
    print(f"  {len(snap.accounts)} contas | {len(snap.payments)} linhas de pagamento")
    return 0


def cmd_rodar(args) -> int:
    """Coleta no ERP e gera a planilha do dia. E o comando do dia a dia."""
    from .erp.collect import coletar

    config, mapping = _base(args)

    snap = coletar(config, periodo=resolver_periodo(args), visivel=not args.oculto)
    caminho_snapshot = snapshot_io.save(snap, config.caminho("snapshots"))
    print(f"Snapshot: {caminho_snapshot}\n")

    try:
        resultado = run_offline(snap, config, mapping, forcar=args.forcar)
    except ValidationError as exc:
        print("A planilha NAO foi gerada porque os dados nao passaram na conferencia:\n")
        print(exc)
        print("\nO snapshot esta salvo. Se quiser gerar mesmo assim, use --forcar.")
        return 1
    except WorkbookError as exc:
        print(f"Falha ao montar a planilha:\n{exc}", file=sys.stderr)
        return 2

    print(resultado.resumo)
    if resultado.log_fora_do_painel:
        print(f"Log fora do painel: {resultado.log_fora_do_painel}")

    if args.abrir and resultado.arquivo:
        _abrir_arquivo(resultado.arquivo)
    return 0


def cmd_analisar(args) -> int:
    config, mapping = _base(args)
    resultado = analyze(snapshot_io.load(args.snapshot), config, mapping)
    print(resultado.resumo)
    return 1 if erros(resultado.issues) else 0


def cmd_montar(args) -> int:
    config, mapping = _base(args)
    snap = snapshot_io.load(args.snapshot)
    try:
        resultado = run_offline(snap, config, mapping, forcar=args.forcar)
    except ValidationError as exc:
        print("A planilha NAO foi gerada:\n", file=sys.stderr)
        print(exc, file=sys.stderr)
        print("\nUse --forcar para gerar mesmo assim.", file=sys.stderr)
        return 1

    print(resultado.resumo)
    if resultado.log_fora_do_painel:
        print(f"Log fora do painel: {resultado.log_fora_do_painel}")
    if args.abrir and resultado.arquivo:
        _abrir_arquivo(resultado.arquivo)
    return 0


def cmd_descobrir_contas(args) -> int:
    """Casa contas do ERP com linhas do painel e grava os uuids.

    Desde que os saldos passaram a vir da API, isto nao abre mais navegador.
    """
    from .erp.accounts import coletar_contas
    from .erp.discover import aplicar_uuids, descobrir, relatorio

    config, mapping = _base(args)
    contas = coletar_contas(config)

    resultado = descobrir(contas, mapping)
    print(relatorio(resultado, mapping))

    if args.aplicar:
        alteradas = aplicar_uuids(args.mapping, resultado.uuids)
        print(f"\n{alteradas} uuid(s) gravado(s) em {args.mapping}")
    else:
        print("\n(nada foi alterado — use --aplicar para gravar os uuids)")
    return 0


# ----------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conciliacao",
        description="Conciliacao financeira diaria — Painel de Controle",
    )
    parser.add_argument("--config", type=Path, default=RAIZ_PADRAO / "config.yaml")
    parser.add_argument("--mapping", type=Path, default=RAIZ_PADRAO / "mapping.yaml")

    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("salvar-senha", help="guarda a senha no cofre do Windows")
    p.add_argument("--email", help="evita a pergunta interativa")
    p.set_defaults(func=cmd_salvar_senha)

    p = sub.add_parser("testar-login", help="confirma que consegue entrar no ERP")
    p.set_defaults(func=cmd_testar_login)

    def argumentos_de_periodo(parser_alvo) -> None:
        parser_alvo.add_argument("--data", help="um dia so, AAAA-MM-DD")
        parser_alvo.add_argument("--de", help="inicio do periodo, ex. 25/07")
        parser_alvo.add_argument("--ate", help="fim do periodo, ex. 27/07")
        parser_alvo.add_argument(
            "--sem-perguntar",
            dest="sem_perguntar",
            action="store_true",
            help="usa o periodo sugerido sem perguntar (para agendamento)",
        )

    p = sub.add_parser("rodar", help="coleta no ERP e gera a planilha do periodo")
    argumentos_de_periodo(p)
    p.add_argument(
        "--oculto",
        action="store_true",
        help="NAO FUNCIONA neste ERP: o WAF recusa navegador sem janela (so p/ teste)",
    )
    p.add_argument("--forcar", action="store_true", help="gera mesmo com erros")
    p.add_argument("--abrir", action="store_true", help="abre a planilha no fim")
    p.set_defaults(func=cmd_rodar)

    p = sub.add_parser("coletar", help="so coleta e salva o snapshot")
    argumentos_de_periodo(p)
    p.add_argument("--oculto", action="store_true")
    p.set_defaults(func=cmd_coletar)

    p = sub.add_parser("analisar", help="valida um snapshot e mostra o resumo")
    p.add_argument("--snapshot", type=Path, required=True)
    p.set_defaults(func=cmd_analisar)

    p = sub.add_parser("montar", help="gera a planilha a partir de um snapshot")
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--forcar", action="store_true")
    p.add_argument("--abrir", action="store_true")
    p.set_defaults(func=cmd_montar)

    p = sub.add_parser("descobrir-contas", help="propoe/grava os uuids no mapping.yaml")
    p.add_argument("--aplicar", action="store_true", help="grava os uuids")
    p.add_argument("--oculto", action="store_true")
    p.set_defaults(func=cmd_descobrir_contas)

    return parser


def main(argv: list[str] | None = None) -> int:
    _configurar_saida()
    args = build_parser().parse_args(argv)

    try:
        return args.func(args)
    except SessaoExpirada as exc:
        # Caso mais comum no dia a dia: nao merece traceback.
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except ErpError as exc:
        print(f"\nNao consegui ler o ERP:\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
