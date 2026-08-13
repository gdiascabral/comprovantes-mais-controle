"""CLI de apoio.

    python -m cnab240 validar ARQUIVO.REM
    python -m cnab240 retorno ARQUIVO.RET
    python -m cnab240 layout segmento_a
    python -m cnab240 layouts
    python -m cnab240 ocorrencia PJ
    python -m cnab240 historico remessas.json
    python -m cnab240 nsa remessas.json --convenio 123456
"""

from __future__ import annotations

import argparse
import sys

from . import spec
from .dominios import decodificar_ocorrencias
from .historico import Historico
from .retorno import ler_arquivo_retorno
from .validador import NIVEL_ARQUIVO, relatorio, validar_arquivo


def _cmd_validar(args) -> int:
    problemas = validar_arquivo(args.arquivo, encoding=args.encoding)
    print(relatorio(problemas))
    return 1 if any(p.nivel == NIVEL_ARQUIVO for p in problemas) else 0


def _cmd_retorno(args) -> int:
    arquivo = ler_arquivo_retorno(args.arquivo, encoding=args.encoding)
    resumo = arquivo.resumo()

    print(f"Empresa .......: {resumo['empresa']}")
    print(f"Convênio ......: {resumo['convenio']}")
    print(f"NSA ...........: {resumo['nsa']}   Geração: {resumo['data_geracao']}")
    print(f"Lotes .........: {resumo['lotes']}")
    print(
        f"Pagamentos ....: {resumo['pagamentos']}  "
        f"({resumo['confirmados']} confirmados / {resumo['rejeitados']} rejeitados)"
    )
    print(f"Valor confirmado: R$ {resumo['valor_confirmado']:,.2f}")
    print(f"Valor rejeitado : R$ {resumo['valor_rejeitado']:,.2f}")

    if resumo["motivos"]:
        print("\nMotivos de rejeição:")
        for motivo, quantidade in resumo["motivos"].items():
            print(f"  {quantidade:>4}x  {motivo}")

    if args.detalhes:
        print("\nPagamentos:")
        for pagamento in arquivo.pagamentos():
            print(f"  {pagamento}")

    return 1 if resumo["rejeitados"] else 0


def _cmd_layout(args) -> int:
    layout = spec.layout(args.nome)
    if layout.uso:
        print(layout.uso, end="\n\n")
    print(f"{'id':<10} {'de':>4} {'até':>4} {'tam':>4} {'dec':>3} {'tipo':<5} {'obr':<3} {'ref':<6} campo")
    print("-" * 100)
    for campo in layout.campos:
        default = f"  default={campo.default!r}" if campo.default else ""
        print(
            f"{campo.id:<10} {campo.de:>4} {campo.ate:>4} {campo.tamanho:>4} {campo.dec:>3} "
            f"{campo.tipo:<5} {campo.obrig:<3} {campo.ref or '':<6} {campo.nome}{default}"
        )
    return 0


def _cmd_layouts(args) -> int:
    for chave, layout in sorted(spec.layouts().items()):
        print(f"{chave:<60} {len(layout.campos):>3} campos")
    return 0


def _cmd_ocorrencia(args) -> int:
    codigos = decodificar_ocorrencias(args.codigo.ljust(10))
    if not codigos:
        print("nenhum código reconhecido")
        return 1
    for codigo, descricao in codigos:
        print(f"{codigo}  {descricao}")
    return 0


def _cmd_historico(args) -> int:
    historico = Historico(args.arquivo)
    remessas = historico.remessas(convenio=args.convenio)

    print(f"{'convênio':<10} {'último NSA':>10}   atualizado em")
    print("-" * 46)
    for convenio, dados in historico.contadores().items():
        if args.convenio and convenio != args.convenio.strip().upper():
            continue
        print(f"{convenio:<10} {dados['ultimo_nsa']:>10}   {dados.get('atualizado_em', '')}")

    if not remessas:
        print("\nnenhuma remessa registrada")
        return 0

    print(f"\n{'NSA':>6}  {'gerada em':<19} {'qtd':>4} {'total':>14}  {'estado':<11} arquivo")
    print("-" * 90)
    for r in remessas:
        quando = r.gerado_em.strftime("%d/%m/%Y %H:%M:%S") if r.gerado_em else ""
        print(
            f"{r.nsa:>6}  {quando:<19} {r.quantidade:>4} {r.total:>14,.2f}  "
            f"{r.estado:<11} {r.arquivo}"
        )
        if args.detalhes:
            for item in r.itens:
                origem = f"  <- {item.referencia}" if item.referencia else ""
                print(
                    f"          {item.seu_numero:<22} {item.valor:>12,.2f}  "
                    f"{item.favorecido[:28]:<28}{origem}"
                )

    ajustes = historico.ajustes(convenio=args.convenio)
    if ajustes:
        print("\nAjustes manuais do contador:")
        for a in ajustes:
            print(
                f"  {a.quando:%d/%m/%Y %H:%M}  {a.convenio}: {a.de} -> {a.para}   {a.motivo}"
            )
    return 0


def _cmd_nsa(args) -> int:
    historico = Historico(args.arquivo)
    if args.ajustar is None:
        print(f"último ..: {historico.ultimo_nsa(args.convenio)}")
        print(f"próximo .: {historico.proximo_nsa(args.convenio)}")
        return 0

    if not args.motivo:
        print(
            "ajustar o NSA exige --motivo: é o que explica o furo na sequência "
            "para quem for conferir com o banco depois.",
            file=sys.stderr,
        )
        return 2

    anterior = historico.ultimo_nsa(args.convenio)
    historico.ajustar_nsa(args.convenio, args.ajustar, motivo=args.motivo)
    print(
        f"convênio {args.convenio}: último NSA {anterior} -> {args.ajustar}   "
        f"(próximo: {historico.proximo_nsa(args.convenio)})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cnab240", description=__doc__)
    parser.add_argument("--encoding", default="latin-1")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("validar", help="valida um arquivo CNAB 240")
    p.add_argument("arquivo")
    p.set_defaults(func=_cmd_validar)

    p = sub.add_parser("retorno", help="lê e resume um arquivo de retorno")
    p.add_argument("arquivo")
    p.add_argument("-d", "--detalhes", action="store_true", help="lista pagamento a pagamento")
    p.set_defaults(func=_cmd_retorno)

    p = sub.add_parser("layout", help="imprime um layout campo a campo")
    p.add_argument("nome")
    p.set_defaults(func=_cmd_layout)

    p = sub.add_parser("layouts", help="lista os layouts disponíveis")
    p.set_defaults(func=_cmd_layouts)

    p = sub.add_parser("ocorrencia", help="descreve um código de ocorrência (G059)")
    p.add_argument("codigo")
    p.set_defaults(func=_cmd_ocorrencia)

    p = sub.add_parser("historico", help="lista as remessas geradas e os contadores")
    p.add_argument("arquivo", help="o remessas.json")
    p.add_argument("-c", "--convenio", help="filtra por convênio")
    p.add_argument("-d", "--detalhes", action="store_true", help="abre o de-para de cada remessa")
    p.set_defaults(func=_cmd_historico)

    p = sub.add_parser("nsa", help="consulta ou corrige o contador de um convênio")
    p.add_argument("arquivo", help="o remessas.json")
    p.add_argument("-c", "--convenio", required=True)
    p.add_argument("--ajustar", type=int, help="novo valor do ÚLTIMO NSA usado")
    p.add_argument("--motivo", help="obrigatório junto com --ajustar")
    p.set_defaults(func=_cmd_nsa)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
