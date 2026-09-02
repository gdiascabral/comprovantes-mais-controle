# -*- coding: utf-8 -*-
"""
Percorre as contas do mês, baixa OFX e PDF e arquiva cada arquivo.

A validação do OFX é a trava principal do projeto. O pior desfecho possível
aqui não é falhar — é o extrato de uma empresa ser gravado, com nome correto,
dentro da pasta de outra. Ninguém percebe isso olhando a pasta. Por isso o OFX
é baixado para um temporário, conferido contra a conta e o período esperados, e
só então movido para o destino.

A parte de validação não usa navegador: roda inteira em teste.
"""
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import sicoob_config as cfg
from .sicoob_contas import Mapa, so_digitos
from .sicoob_pastas import caminho_da_conta

RE_ACCTID = re.compile(r"<ACCTID>([^<\r\n]*)")
RE_DTSTART = re.compile(r"<DTSTART>(\d{8})")
RE_DTEND = re.compile(r"<DTEND>(\d{8})")


# ------------------------------------------------------------- validação

def ler_ofx(caminho: Path) -> str:
    """O OFX do Sicoob vem em Windows-1252 (declara CHARSET:1252), não UTF-8.
    Lido como UTF-8, acento vira erro de decodificação."""
    return caminho.read_text(encoding=cfg.CODIFICACAO_OFX, errors="replace")


def validar_ofx(texto: str, conta: str, ano: int, mes: int) -> list[str]:
    """Confere se o arquivo é mesmo o extrato daquela conta naquele mês.

    Devolve a lista de problemas; vazia significa aprovado."""
    import calendar
    problemas: list[str] = []

    achado = RE_ACCTID.search(texto)
    if not achado:
        problemas.append("o arquivo não tem ACCTID — não parece um OFX válido")
    elif so_digitos(achado.group(1)) != so_digitos(conta):
        problemas.append(
            f"o OFX é da conta {achado.group(1).strip()}, esperava {conta}")

    ini, fim = RE_DTSTART.search(texto), RE_DTEND.search(texto)
    if not ini or not fim:
        problemas.append("o arquivo não traz o período (DTSTART/DTEND)")
    else:
        esperado_ini = f"{ano}{mes:02d}01"
        esperado_fim = f"{ano}{mes:02d}{calendar.monthrange(ano, mes)[1]:02d}"
        if ini.group(1) != esperado_ini or fim.group(1) != esperado_fim:
            problemas.append(
                f"o período do OFX é {ini.group(1)}–{fim.group(1)}, "
                f"esperava {esperado_ini}–{esperado_fim}")
    return problemas


# -------------------------------------------------------------- relatório

@dataclass
class ResultadoConta:
    numero: str
    empresa: str
    ofx: bool = False
    pdf: bool = False
    problemas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ofx and self.pdf and not self.problemas


@dataclass
class Relatorio:
    resultados: list[ResultadoConta] = field(default_factory=list)

    @property
    def completos(self) -> list[ResultadoConta]:
        return [r for r in self.resultados if r.ok]

    @property
    def falhos(self) -> list[ResultadoConta]:
        return [r for r in self.resultados if not r.ok]

    def texto(self) -> str:
        linhas = [f"{len(self.completos)} de {len(self.resultados)} contas completas."]
        if self.falhos:
            linhas.append("")
            linhas.append("Pendências:")
            for r in self.falhos:
                faltando = [n for n, v in (("OFX", r.ofx), ("PDF", r.pdf)) if not v]
                detalhe = "; ".join(r.problemas) if r.problemas else "não baixou"
                linhas.append(f"  {r.numero} ({r.empresa}): "
                              f"{', '.join(faltando) or 'arquivos'} — {detalhe}")
        return "\n".join(linhas)


# ---------------------------------------------------------------- lote

def baixar_mes(cliente, mapa: Mapa, ano: int, mes: int,
               log=print, parar=lambda: False) -> Relatorio:
    """Baixa OFX e PDF de todas as contas do mapa.

    Uma conta que falha vira linha no relatório e o lote segue: interromper
    tudo por causa de uma significaria refazer as outras doze à toa."""
    rel = Relatorio()
    total = len(mapa.contas)

    with tempfile.TemporaryDirectory(prefix="sicoob_") as tmp:
        for i, conta in enumerate(mapa.contas, 1):
            if parar():
                log("Interrompido a pedido.")
                break
            res = ResultadoConta(numero=conta.numero, empresa=conta.empresa)
            rel.resultados.append(res)
            log(f"[{i}/{total}] {conta.numero} — {conta.empresa}")

            destino = caminho_da_conta(mapa, ano, mes, conta.numero)
            # O nome sai DE DENTRO do laço porque leva o `sufixo` da conta:
            # calculado uma vez para o lote, ele era o mesmo para todas, e
            # duas contas da mesma pasta gravavam uma por cima da outra.
            nome = cfg.nome_arquivo(ano, mes, conta.sufixo)
            try:
                if not cliente.acessar_conta(conta.numero):
                    res.problemas.append("conta não encontrada na lista do Sicoob")
                    log("   conta não está na lista — pulando")
                    continue

                cliente.abrir_extrato()
                cliente.definir_ordenacao()
                cliente.definir_periodo(ano, mes)

                # OFX vai para um temporário e só chega ao destino se passar.
                provisorio = Path(tmp) / f"{conta.chave}.ofx"
                cliente.exportar_ofx(provisorio)
                problemas = validar_ofx(ler_ofx(provisorio), conta.numero, ano, mes)
                if problemas:
                    # O PDF NÃO sai daqui. Ele nasce do mesmo extrato que o OFX
                    # acabou de reprovar: arquivá-lo poria o extrato de uma
                    # empresa na pasta de outra — o pior desfecho possível, e o
                    # único que nada no disco denuncia depois.
                    res.problemas.extend(problemas)
                    log("   OFX RECUSADO: " + "; ".join(problemas))
                    log("   PDF não gerado (mesmo extrato reprovado)")
                else:
                    destino.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(provisorio), str(destino / f"{nome}.ofx"))
                    res.ofx = True
                    log("   OFX conferido e arquivado")

                    # O PDF vem de um SEGUNDO download, e ninguém lê o que
                    # veio dentro dele: a trava do ACCTID cobre o OFX, e o PDF
                    # só por vizinhança (OFX reprovado, PDF não nasce). Então
                    # o mínimo é provar que o arquivo existe e não está vazio,
                    # como `contratos/pipeline.py` já faz — sem isso, zero byte
                    # no disco é relatado como "conta completa".
                    alvo_pdf = destino / f"{nome}.pdf"
                    cliente.exportar_pdf(alvo_pdf)
                    if not alvo_pdf.is_file() or alvo_pdf.stat().st_size <= 0:
                        res.problemas.append(
                            "o PDF não ficou no disco (arquivo ausente ou "
                            "de zero byte)")
                        log("   PDF RECUSADO: arquivo vazio ou ausente")
                    else:
                        res.pdf = True
                        log("   PDF gerado")

            except Exception as e:                 # noqa: BLE001 — ver docstring
                res.problemas.append(str(e))
                log(f"   falhou: {e}")
                try:
                    cliente.ir_para_selecao()      # tenta recuperar para a próxima
                except Exception:
                    log("   não consegui voltar para a lista de contas")
                    break

    log("")
    log(rel.texto())
    return rel
