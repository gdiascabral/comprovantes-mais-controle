# -*- coding: utf-8 -*-
"""O vigia do porteiro: confere, de fora, se o porteiro está vivo e ok.

POR QUE EXISTE
--------------
Em 09/11/2026 o Chrome central travou às 14:04 e o porteiro ficou preso numa
chamada do Playwright até 14:33. Para a tarefa do Agendador ele seguia "Em
execução" (e com "não iniciar outra" ninguém subia outro), e ninguém foi
avisado: só se descobriu olhando. O porteiro agora tem uma guarda interna
(`erp.porteiro.Guarda`); este vigia é o cinto de segurança dela, e o aviso.

Roda de 5 em 5 min pela tarefa "MoraisEng - Vigia do porteiro", uma passada
por vez, e sai. Só lê arquivo e mexe em processo/tarefa: nunca fala com o
ERP, nunca abre aba, nunca faz login.

    python -m erp.vigia            uma passada
    python -m erp.vigia --sem-email

O QUE FAZ EM CADA PASSADA
-------------------------
1. Porteiro não está rodando → inicia a tarefa "MoraisEng - Porteiro do ERP".
2. Rodando, mas sem sinal de vida (`porteiro-vivo.json`) há mais de
   `MORTO_MIN` → mata o processo e inicia a tarefa de novo.
3. Fora do "ok" (travado, SEM LOGIN, ERRO ou sem sinal) há `AVISAR_MIN` ou
   mais → UM e-mail "PORTEIRO FORA". Quando volta ao ok → UM e-mail
   "PORTEIRO VOLTOU". Nada de e-mail a cada passada.

Por que não passa pelo `rodar_e_relatar.py`: ele manda e-mail a cada rodada,
e o vigia roda 288 vezes por dia. Aqui o e-mail sai só na mudança.

Código de saída: 0 quando a passada rodou (mesmo achando o porteiro fora —
isso vai no e-mail), 1 quando o próprio vigia falhou. Última linha: resumo.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from erp import central

TAREFA_PORTEIRO = "MoraisEng - Porteiro do ERP"
ARQUIVO_VIVO = "porteiro-vivo.json"          # o mesmo de `erp.porteiro`
ARQUIVO_ESTADO = "vigia-porteiro.json"
ARQUIVO_LOG = "vigia-porteiro.log"
ARQUIVO_EMAIL = "relatorio-robos.json"       # destinatários e caixa dos robôs

#: Sem sinal de vida há tanto tempo, o porteiro não está só lento: ciclo de
#: 2 min, guarda interna que sai sozinha aos 20 min. Passou de 25, o
#: processo não consegue nem sair — o vigia o mata.
MORTO_MIN = 25
#: Sem ciclo novo há tanto tempo, conta como "fora" (não ok).
SEM_SINAL_MIN = 8
#: Fora do ok há tanto tempo → e-mail. Abaixo disso a guarda e o socorro
#: costumam resolver sozinhos (Chrome travado é reiniciado em ~6 min).
AVISAR_MIN = 10

_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _agora() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _ler_json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _gravar_json(caminho: Path, dados: dict) -> None:
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, caminho)


def pids_do_porteiro(*, rodar=subprocess.run) -> list[int]:
    """Os processos python que rodam `erp.porteiro vigiar`."""
    script = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
              "? { $_.CommandLine -match 'erp\\.porteiro\\s+vigiar' } | % { $_.ProcessId }")
    r = rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
              capture_output=True, text=True, timeout=60, creationflags=_SEM_JANELA)
    return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]


def matar(pid: int, *, rodar=subprocess.run) -> None:
    rodar(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
          timeout=30, creationflags=_SEM_JANELA)


def iniciar_tarefa(*, rodar=subprocess.run) -> str:
    r = rodar(["schtasks", "/Run", "/TN", TAREFA_PORTEIRO], capture_output=True,
              text=True, timeout=60, creationflags=_SEM_JANELA)
    return "tarefa iniciada" if r.returncode == 0 else (
        f"a tarefa não iniciou (código {r.returncode}): {(r.stderr or r.stdout or '').strip()[:150]}")


def _minutos(desde: dt.datetime | None, agora: dt.datetime) -> float | None:
    if desde is None:
        return None
    return (agora - desde).total_seconds() / 60


def _data(texto) -> dt.datetime | None:
    try:
        d = dt.datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.astimezone()


def passada(pasta: Path, *, agora=None, pids=None, matar_pid=None, iniciar=None,
            avisar=None, log=print) -> str:
    """Uma passada do vigia. Devolve a linha de resumo. Tudo de fora (tempo,
    processos, tarefa, e-mail) entra por parâmetro, para os testes."""
    agora = agora or _agora()
    pids = (pids or pids_do_porteiro)()
    matar_pid = matar_pid or matar
    iniciar = iniciar or iniciar_tarefa
    vivo = _ler_json(pasta / ARQUIVO_VIVO)
    estado = _ler_json(pasta / ARQUIVO_ESTADO)

    ultimo = _data(vivo.get("em"))
    idade = _minutos(ultimo, agora)
    linhas = list(vivo.get("linhas") or [])
    feito = []

    if not pids:
        feito.append(f"porteiro não estava rodando: {iniciar()}")
    elif idade is not None and idade >= MORTO_MIN and int(vivo.get("pid") or 0) in pids:
        for pid in pids:
            with contextlib.suppress(Exception):
                matar_pid(pid)
        feito.append(f"porteiro preso há {idade:.0f} min (pid "
                     f"{', '.join(map(str, pids))}): processo morto e {iniciar()}")

    ok = (bool(pids) and not feito and idade is not None and idade < SEM_SINAL_MIN
          and bool(vivo.get("ok")))
    if ok:
        situacao = "ok"
    elif idade is None:
        situacao = "sem sinal de vida (porteiro-vivo.json não existe)"
    elif idade >= SEM_SINAL_MIN:
        situacao = f"sem ciclo novo há {idade:.0f} min"
    else:
        situacao = "; ".join(linhas) or "fora"

    for f in feito:
        log(f)

    fora_desde = _data(estado.get("fora_desde"))
    avisado = bool(estado.get("avisado"))
    if ok:
        if avisado and avisar is not None:
            minutos = _minutos(fora_desde, agora) or 0
            if not avisar("PORTEIRO VOLTOU — Mais Controle",
                          texto_voltou(minutos, linhas, agora)):
                return "porteiro ok de novo; o e-mail \"VOLTOU\" falhou, tento na próxima"
        _gravar_json(pasta / ARQUIVO_ESTADO, {"fora_desde": None, "avisado": False,
                                              "ultima": agora.isoformat(timespec="seconds")})
        return f"porteiro ok (último ciclo há {idade:.0f} min)"

    fora_desde = fora_desde or agora
    minutos = _minutos(fora_desde, agora) or 0
    if not avisado and minutos >= AVISAR_MIN and avisar is not None:
        # Só conta como avisado se o e-mail saiu: senão tenta na próxima.
        avisado = bool(avisar("PORTEIRO FORA — robôs do Mais Controle parados",
                              texto_fora(minutos, situacao, linhas, feito, agora)))
    _gravar_json(pasta / ARQUIVO_ESTADO, {
        "fora_desde": fora_desde.isoformat(timespec="seconds"), "avisado": avisado,
        "ultima": agora.isoformat(timespec="seconds"), "situacao": situacao})
    return (f"porteiro FORA há {minutos:.0f} min: {situacao}"
            + (" — e-mail enviado" if avisado else ""))


def _o_que_fazer(situacao: str) -> str:
    s = situacao.upper()
    if "SEM LOGIN" in s:
        return ("O Mais Controle pediu login de novo. Entre na janela do Chrome "
                "central (no servidor) com o usuário do robô; o porteiro segue sozinho.")
    if "TRAVADO" in s:
        return ("O Chrome central está travado. O porteiro o reinicia sozinho em "
                "~6 min; se este e-mail não for seguido de \"PORTEIRO VOLTOU\" em "
                "15 min, reinicie o servidor.")
    return ("O vigia já tentou levantar o porteiro. Se não chegar o e-mail "
            "\"PORTEIRO VOLTOU\" em 15 min, rode no servidor: "
            "python _portal\\servidor\\robo_fila.py --verificar, e veja "
            "_central\\porteiro.log.")


def texto_fora(minutos, situacao, linhas, feito, agora) -> str:
    partes = [f"O porteiro do Mais Controle está fora há {minutos:.0f} min "
              f"({agora:%d/%m/%Y %H:%M}). Enquanto isso, os robôs que usam o ERP param.",
              "", f"Situação: {situacao}"]
    if feito:
        partes += ["", "O vigia fez:"] + [f"- {f}" for f in feito]
    if linhas:
        partes += ["", "Último ciclo do porteiro:"] + [f"- {x}" for x in linhas]
    partes += ["", "O que fazer: " + _o_que_fazer(situacao)]
    return "\n".join(partes)


def texto_voltou(minutos, linhas, agora) -> str:
    return "\n".join([f"O porteiro voltou ao normal às {agora:%H:%M} "
                      f"(ficou fora uns {minutos:.0f} min).", "",
                      *[f"- {x}" for x in linhas],
                      "", "Nada a fazer. Robôs que falharam nesse tempo repetem "
                      "sozinhos na próxima rodada."])


def enviar_email(pasta: Path, assunto: str, texto: str) -> None:
    """Pela mesma caixa dos relatórios (`relatorio-robos.json`); a senha vem
    do cofre do Windows (keyring), nunca de arquivo. Imports aqui dentro: o
    `erp/` vai no codigo.zip do app, cujo exe não embute smtplib/ssl/email."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    cfg = _ler_json(pasta / ARQUIVO_EMAIL)
    if not cfg or not cfg.get("ativo", True):
        raise RuntimeError(f"e-mail desligado ou sem {ARQUIVO_EMAIL}")
    import keyring
    senha = keyring.get_password(cfg["keyring_servico"], cfg["de"]) or ""
    if not senha:
        raise RuntimeError(f"senha do e-mail não está no cofre ({cfg['keyring_servico']})")
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = assunto, cfg["de"], ", ".join(cfg["para"])
    msg.set_content(texto)
    porta = int(cfg.get("porta", 465))
    if porta == 465:
        s = smtplib.SMTP_SSL(cfg["smtp"], 465, context=ctx, timeout=60)
    else:
        s = smtplib.SMTP(cfg["smtp"], porta, timeout=60)
        s.starttls(context=ctx)
    with s:
        s.login(cfg["de"], senha)
        s.send_message(msg)


def _logger(pasta: Path):
    caminho = pasta / ARQUIVO_LOG

    def log(texto: str) -> None:
        with contextlib.suppress(OSError):
            if caminho.exists() and caminho.stat().st_size > 1_000_000:
                os.replace(caminho, caminho.with_name(caminho.name + ".1"))
            with open(caminho, "a", encoding="utf-8") as f:
                f.write(f"{_agora():%Y-%m-%d %H:%M:%S} {texto}\n")
        print(texto, flush=True)
    return log


def main(argv=None) -> int:
    import argparse   # tarde: o exe não embute argparse
    p = argparse.ArgumentParser(prog="python -m erp.vigia")
    p.add_argument("--sem-email", action="store_true")
    args = p.parse_args(argv)
    pasta = central.pasta_central()
    if pasta is None:
        print("central desligado (MC_CENTRAL=off)")
        return 1
    log = _logger(pasta)

    def avisar(assunto, texto):
        if args.sem_email:
            log(f"(sem e-mail) {assunto}")
            return True
        try:
            enviar_email(pasta, assunto, texto)
            log(f"e-mail enviado: {assunto}")
            return True
        except Exception as e:
            log(f"e-mail FALHOU ({type(e).__name__}: {str(e)[:150]}): {assunto}")
            return False
    try:
        resumo = passada(pasta, avisar=avisar, log=log)
    except Exception as e:
        log(f"o vigia falhou: {type(e).__name__}: {str(e)[:200]}")
        return 1
    log(resumo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
