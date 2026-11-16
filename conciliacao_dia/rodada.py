# -*- coding: utf-8 -*-
"""A rodada do "Baixar e importar" (aba Conciliação), sem tela.

Na ordem: o Sicoob (um login; o outro acesso só se sobrar conta e a pessoa
disser sim), cada conta do Inter (um QR por conta), a conferência de CADA
OFX (`ofx_regras.conferir_ofx`: conta e período) e, por último, o ERP com
só os que conferem. Os três motores vêm de fora (o frame passa os de
verdade, os testes passam dublês) — é o desenho de `tela_do_dia.
nuvem_do_dia`.

Uma `Resultado` por conta pedida, na ordem da lista: nenhuma some. O Parar
corta antes da próxima etapa; o que já foi importado continua importado.

**Nunca o mesmo lançamento duas vezes** (revisão de dinheiro de 16/11/2026):
antes do ERP, o OFX perde os lançamentos que o registro (`importados`) diz
que já foram — enviados com confirmação OU sem ela —, e o que sobra vai num
arquivo PRÓPRIO desta conta do ERP (`<banco> <erp_id>.ofx`), conferido pelo
hash logo antes do envio. Dois OFX com o mesmo número de conta na mesma
rodada: só o primeiro vai. Envio sem confirmação do ERP é `NAO_VERIFICADO` e
entra no registro (o app não reenvia; a pessoa confere no extrato do ERP).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from extratos_sicoob import saldo

from . import importados as imp
from . import ofx_regras as r

PARADO = "parado pelo botão Parar antes de importar"
NAO_BAIXADO = "o OFX não foi baixado"
#: Vão depois de "nada novo: " na tabela (`ofx_regras.linha_do_resultado`).
NADA_NOVO = "todos os lançamentos deste período já foram importados"
SEM_LANCAMENTOS = "sem lançamentos no período"
MESMO_OFX = "o mesmo OFX (conta {}) já vai por outra linha da lista"
MUDOU = "o arquivo mudou depois de conferido — não importei"
#: Desfechos do motor do ERP.
ENVIO_OK, ENVIO_FALHOU, ENVIO_INCERTO = "ok", "falhou", "incerto"


def _ler(arquivo: Path) -> str:
    return Path(arquivo).read_text(encoding="cp1252", errors="replace")


def _hash(arquivo: Path) -> str:
    return hashlib.sha256(Path(arquivo).read_bytes()).hexdigest()


def rodar(contas, ini, fim, pasta, *, sicoob, inter, erp, perguntar_outro_acesso,
          ja_importados=None, registrar=lambda erp_id, chaves, incerto: None,
          avisar=lambda estado: None, parar=lambda: False, log=print) -> list:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    ja = ja_importados if ja_importados is not None else {}
    motivo: dict = {}                    # erp_id -> por que não vai ao ERP
    prontos: dict = {}                   # erp_id -> (arquivo, chaves, hash, tirados)
    sem_novos: dict = {}                 # erp_id -> lançamentos já importados
    acct_visto: dict = {}                # (banco, ACCTID) -> nome da 1ª conta
    for c in contas:
        if c.motivo:
            motivo[c.erp_id] = c.motivo

    def conferir(c, arquivo, numero):
        texto = _ler(arquivo)
        porque = r.conferir_ofx(texto, numero, ini, fim)
        if porque:
            motivo[c.erp_id] = porque
            log(f"  {c.nome}: OFX recusado — {porque}")
            return
        chave_acct = (c.banco, r._dig(numero))
        if chave_acct in acct_visto:
            motivo[c.erp_id] = MESMO_OFX.format(acct_visto[chave_acct])
            log(f"  {c.nome}: {motivo[c.erp_id]}")
            return
        acct_visto[chave_acct] = c.nome
        novo, chaves, tirados = imp.sem_os_ja_importados(texto, ja.get(c.erp_id, set()))
        if not chaves:
            sem_novos[c.erp_id] = tirados
            return
        destino = pasta / "para o ERP" / f"{c.banco.lower()} {c.erp_id}.ofx"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(novo, encoding="cp1252", errors="replace")
        prontos[c.erp_id] = (destino, chaves, _hash(destino), tirados)

    # --- Sicoob
    do_sicoob = [c for c in contas if c.banco == r.SICOOB and not c.motivo]
    if do_sicoob and not parar():
        avisar(f"Sicoob: {len(do_sicoob)} conta(s) — faça o login no Chrome do Sicoob")
        try:
            lidos = dict(sicoob(do_sicoob, pasta / "sicoob"))
            faltam = [c for c in do_sicoob
                      if lidos.get(r.ps.digitos(c.numero), (None, ""))[1]
                      == saldo.FORA_DESTE_LOGIN]
            if faltam and not parar() and perguntar_outro_acesso([c.numero for c in faltam]):
                avisar("Sicoob: entre com o OUTRO acesso (outro QR Code)")
                lidos.update(sicoob(faltam, pasta / "sicoob"))
        except Exception as e:                               # noqa: BLE001
            # O Chrome não abriu, o login esgotou: as do Sicoob levam o porquê
            # e as do Inter seguem (revisão de 16/11/2026).
            texto = (str(e).strip().splitlines() or [type(e).__name__])[0][:160]
            log(f"  Sicoob: parou — {texto}")
            lidos = {r.ps.digitos(c.numero): (None, f"o Sicoob parou: {texto}")
                     for c in do_sicoob}
        for c in do_sicoob:
            arquivo, porque = lidos.get(r.ps.digitos(c.numero), (None, NAO_BAIXADO))
            if arquivo is None:
                motivo[c.erp_id] = porque or NAO_BAIXADO
            else:
                conferir(c, arquivo, c.numero)

    # --- Inter, uma conta por QR
    for c in [c for c in contas if c.banco == r.INTER and not c.motivo]:
        if parar():
            break
        avisar(f"Leia o QR da {c.apelido} — confira a empresa no celular")
        alvo = pasta / "inter" / f"{c.erp_id}.ofx"
        alvo.parent.mkdir(parents=True, exist_ok=True)
        lido = inter(c, alvo)
        if lido.arquivo is None:
            motivo[c.erp_id] = lido.motivo or NAO_BAIXADO
        else:
            conferir(c, lido.arquivo, c.numero or lido.numero_na_tela)

    # --- ERP, só os que conferem e com o arquivo intacto
    enviados: dict = {}
    pedidos = []
    for c in contas:
        if c.erp_id not in prontos:
            continue
        arquivo, _chaves, h, _t = prontos[c.erp_id]
        if _hash(arquivo) != h:
            motivo[c.erp_id] = MUDOU
            del prontos[c.erp_id]
            continue
        pedidos.append((c.erp_id, c.nome, arquivo))
    if pedidos and not parar():
        avisar(f"Importando {len(pedidos)} OFX no Mais Controle")
        enviados = dict(erp(pedidos))
        for erp_id, (estado, _m) in enviados.items():
            if erp_id in prontos and estado in (ENVIO_OK, ENVIO_INCERTO):
                registrar(erp_id, prontos[erp_id][1], estado == ENVIO_INCERTO)

    saida = []
    for c in contas:
        if c.erp_id in prontos:
            _a, chaves, _h, tirados = prontos[c.erp_id]
            estado, porque = enviados.get(c.erp_id, (ENVIO_FALHOU, PARADO))
            extra = f" ({tirados} já importado(s) antes ficaram de fora)" if tirados else ""
            if estado == ENVIO_OK:
                saida.append(r.Resultado(c, r.IMPORTADO, len(chaves), extra.strip()))
            elif estado == ENVIO_INCERTO:
                saida.append(r.Resultado(c, r.NAO_VERIFICADO, len(chaves),
                                         f"{porque} — confira no extrato do ERP; o app "
                                         "não manda estes lançamentos de novo"))
            else:
                saida.append(r.Resultado(c, r.NAO_IMPORTADO, len(chaves), porque))
        elif c.erp_id in sem_novos:
            saida.append(r.Resultado(c, r.NADA_NOVO, 0,
                                     NADA_NOVO if sem_novos[c.erp_id] else SEM_LANCAMENTOS))
        else:
            saida.append(r.Resultado(c, r.NAO_IMPORTADO,
                                     motivo=motivo.get(c.erp_id) or PARADO))
    return saida
