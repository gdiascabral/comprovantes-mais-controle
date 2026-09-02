# -*- coding: utf-8 -*-
"""
Empacota cada empresa do mês num .zip, ao lado da própria pasta:

    EXTRATOS/2026/JULHO/JULHO 2026 - BURITIS.zip

É comando separado do download de propósito. O zip só faz sentido com o mês
completo, e o mês só fica completo depois que os outros bancos (Caixa, Inter,
Bradesco) entrarem — o que não é feito por esta automação. Zipar junto com o
download empacotaria mês pela metade.

Sem navegador e sem tkinter: roda inteiro em teste.
"""
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import sicoob_config as cfg
from .sicoob_contas import Mapa


@dataclass
class ResultadoZip:
    empresa: str
    caminho: Path | None
    arquivos: int
    pastas_vazias: list[str]


def pastas_vazias_da_empresa(pasta: Path) -> list[str]:
    """Subpastas sem nenhum arquivo — o sinal de que o mês ainda não fechou."""
    return sorted(sub.name for sub in pasta.iterdir()
                  if sub.is_dir() and not any(sub.rglob("*")))


def zipar_mes(mapa: Mapa, ano: int, mes: int, log=print) -> list[ResultadoZip]:
    """Gera um zip por empresa. Avisa quais pastas estão vazias antes de
    empacotar, mas não impede: às vezes a empresa não tem mesmo o banco."""
    base = mapa.raiz / str(ano) / cfg.nome_do_mes(mes)
    if not base.is_dir():
        raise FileNotFoundError(
            f"O mês não existe: {str(base).replace(chr(92), '/')}")

    resultados = []
    for empresa in mapa.empresas:
        pasta = base / cfg.nome_pasta_empresa(ano, mes, empresa.nome)
        if not pasta.is_dir():
            log(f"{empresa.nome}: pasta do mês não existe — pulando")
            resultados.append(ResultadoZip(empresa.nome, None, 0, []))
            continue

        vazias = pastas_vazias_da_empresa(pasta)
        # with_suffix() troca o que vem depois do ULTIMO ponto: razao social
        # com ponto ("MORAIS EMPREEND. BURITIS") viraria "MORAIS EMPREEND.zip"
        # e o mes inteiro de uma empresa iria para o arquivo errado.
        alvo = pasta.parent / (pasta.name + ".zip")
        arquivos = [p for p in sorted(pasta.rglob("*")) if p.is_file()]
        # Grava ao lado e só então troca. Abrir o alvo em "w" TRUNCA o zip
        # anterior no próprio open: quem ziparia de novo para incluir o
        # extrato que faltava ficava, a uma queda de distância, sem o zip
        # velho e sem o novo — e o zip é o que a aba Acessórias envia ao
        # escritório. `os.replace` é atômico no Windows, a mesma decisão de
        # `sicoob_contas.adicionar_cliente_erp`.
        temporario = alvo.with_name(alvo.name + ".tmp")
        try:
            with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as z:
                for arq in arquivos:
                    z.write(arq, arq.relative_to(pasta.parent))
            os.replace(temporario, alvo)
        except BaseException:
            # BaseException, e não Exception, porque KeyboardInterrupt é
            # justamente a interrupção que este arranjo veio proteger: sem a
            # limpeza sobraria um ".zip.tmp" pela metade ao lado dos zips
            # bons, na pasta que a pessoa abre para conferir o mês.
            try:
                temporario.unlink()
            except OSError:
                pass
            raise

        resultados.append(ResultadoZip(empresa.nome, alvo, len(arquivos), vazias))
        aviso = f"  (vazias: {', '.join(vazias)})" if vazias else ""
        log(f"{empresa.nome}: {len(arquivos)} arquivos{aviso}")

    total_vazias = sum(1 for r in resultados if r.pastas_vazias)
    if total_vazias:
        log("")
        log(f"Atenção: {total_vazias} empresa(s) com pasta de banco vazia. "
            "Se o mês ainda não fechou, vale zipar de novo depois.")
    return resultados
