# -*- coding: utf-8 -*-
"""
Árvore de pastas do fechamento mensal.

    <raiz>/<ANO>/<MÊS>/<MÊS ANO - EMPRESA>/<SUBPASTA>/

O planejamento é separado da criação de propósito: quem chama mostra o que
seria criado, destaca o que é novo e só então confirma. Criar pasta no lugar
errado é fácil de fazer e chato de desfazer.

Sem navegador e sem tkinter: roda inteiro em teste.
"""
from dataclasses import dataclass
from pathlib import Path

from . import sicoob_config as cfg
from .sicoob_contas import Mapa


@dataclass
class Pasta:
    caminho: Path
    nova: bool                  # ainda não existe no disco
    empresa: str
    subpasta: str = ""          # vazio = a própria pasta da empresa
    recebe_download: bool = False


def caminho_do_mes(mapa: Mapa, ano: int, mes: int) -> Path:
    return mapa.raiz / str(ano) / cfg.nome_do_mes(mes)


def caminho_da_conta(mapa: Mapa, ano: int, mes: int, numero: str) -> Path | None:
    """Onde os arquivos de uma conta devem ser gravados."""
    conta = mapa.conta_por_numero(numero)
    if conta is None:
        return None
    return (caminho_do_mes(mapa, ano, mes)
            / cfg.nome_pasta_empresa(ano, mes, conta.empresa)
            / conta.pasta)


def planejar(mapa: Mapa, ano: int, mes: int) -> list[Pasta]:
    """Toda a árvore do mês, marcando o que ainda não existe."""
    base = caminho_do_mes(mapa, ano, mes)
    plano: list[Pasta] = []
    for emp in mapa.empresas:
        pasta_emp = base / cfg.nome_pasta_empresa(ano, mes, emp.nome)
        plano.append(Pasta(caminho=pasta_emp, nova=not pasta_emp.is_dir(),
                           empresa=emp.nome))
        com_download = {c.pasta for c in emp.contas}
        for sub in emp.subpastas:
            alvo = pasta_emp / sub
            plano.append(Pasta(caminho=alvo, nova=not alvo.is_dir(),
                               empresa=emp.nome, subpasta=sub,
                               recebe_download=sub in com_download))
    return plano


def criar(plano: list[Pasta]) -> list[Pasta]:
    """Cria as pastas que faltam. Devolve as que foram efetivamente criadas."""
    criadas = []
    for p in plano:
        if p.nova:
            p.caminho.mkdir(parents=True, exist_ok=True)
            criadas.append(p)
    return criadas


def comparar_com_mes_anterior(mapa: Mapa, ano: int, mes: int) -> list[str]:
    """Empresas que existem no mês anterior mas não estão no mapa.

    Serve de alarme para empresa nova que entrou no fluxo sem ninguém avisar:
    o silêncio vira aviso agora, em vez de arquivo faltando descoberto meses
    depois. Mês anterior ausente (primeiro uso) não é problema."""
    ano_ant, mes_ant = cfg.mes_anterior(ano, mes)
    base = mapa.raiz / str(ano_ant) / cfg.nome_do_mes(mes_ant)
    if not base.is_dir():
        return []

    prefixo = f"{cfg.nome_do_mes(mes_ant)} {ano_ant} - "
    conhecidas = {e.nome.upper() for e in mapa.empresas}
    orfas = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not d.name.startswith(prefixo):
            continue
        nome = d.name[len(prefixo):].strip()
        if nome.upper() not in conhecidas:
            orfas.append(nome)
    return orfas


def resumo(plano: list[Pasta]) -> str:
    """Texto para a confirmação, agrupado por empresa. As pastas novas levam
    'NOVA' na frente porque são exatamente as que merecem um segundo olhar."""
    linhas: list[str] = []
    atual = None
    for p in plano:
        if p.empresa != atual:
            atual = p.empresa
            linhas.append("")
        marca = "NOVA  " if p.nova else "      "
        if not p.subpasta:
            linhas.append(f"{marca}{p.caminho.name}")
        else:
            alvo = "  <- extratos" if p.recebe_download else ""
            linhas.append(f"{marca}    {p.subpasta}{alvo}")
    novas = sum(1 for p in plano if p.nova)
    linhas.append("")
    linhas.append(f"{len(plano)} pastas no total, {novas} a criar.")
    return "\n".join(linhas).strip()
