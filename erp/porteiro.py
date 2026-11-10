# -*- coding: utf-8 -*-
"""O porteiro do ERP: quem mantém o Chrome central de pé e logado.

POR QUE EXISTE
--------------
O ERP aceita UMA sessão por usuário (`erp/central.py`). Quem entra pela tela é
só o porteiro; os robôs abrem a sua aba no mesmo Chrome e dividem a sessão. Se
o Chrome fecha ou a sessão cai, é o porteiro que levanta de novo — nenhum robô
precisa saber.

REGRA: robô nunca fecha o Chrome central. O porteiro também não: ao sair,
fecha só a própria aba (`MCClient` em modo central).

COMANDOS (a partir da raiz do repositório)
    python -m erp.porteiro estado                      só lê, não sobe nada
    python -m erp.porteiro guardar-login --acesso X    cifra e-mail e senha
    python -m erp.porteiro subir                       um ciclo (Chrome + login)
    python -m erp.porteiro vigiar [--intervalo 120]    ciclo para sempre

THREAD: o `MCClient` é Playwright sync e só serve na thread que o abriu. Em
`vigiar` há UM cliente por acesso, aberto entre os ciclos e usado sempre da
thread principal; se `vivo()` der False ele é fechado e recriado. Entre os
ciclos ele é PULSADO (`_dormir`): parado, prenderia as abas novas dos robôs.

CHROME TRAVADO (09/11/2026): porta aberta e calada é "mudo" (`central.
estado_chrome`), não "fechado". O porteiro não sobe outro Chrome por cima;
depois de `LIMITE_MUDO` ciclos seguidos mudo, mata o Chrome do perfil e sobe
um novo (`Socorro`). E como toda chamada do Playwright a um Chrome travado
espera para sempre, uma linha de guarda (`Guarda`) vigia o ciclo de fora:
ciclo parado com o Chrome mudo → mata o Chrome (a chamada presa cai com
erro); parado demais com o Chrome vivo → mata o driver do Playwright; ainda
parado → sai, e quem o levanta é a tarefa "MoraisEng - Vigia do porteiro"
(`erp/vigia.py`). A cada ciclo grava `porteiro-vivo.json` (sinal de vida).
"""
from __future__ import annotations

import atexit
import contextlib
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
import threading
import time

from erp import central


def montar_estado(acessos, vivo) -> dict:
    """O que `estado` imprime. Só pergunta `vivo`; não sobe nada."""
    return {"acessos": [
        {"nome": a.nome, "porta": a.porta, "chrome_vivo": bool(vivo(a))}
        for a in acessos.values()]}


def _como_estado(v) -> str:
    """`vivo(a)` pode responder bool (o jeito antigo) ou o estado."""
    if isinstance(v, str):
        return v
    return "vivo" if v else "fechado"


def um_ciclo(acessos, *, vivo, subir_chrome, checar_login, log,
             faxinar=None, socorro=None) -> list[str]:
    """Um passo de vigia: por acesso, sobe o Chrome se estiver fechado e
    confere o login. Devolve o que fez, uma linha por acesso. Erro num acesso
    vira linha "ERRO" e não impede os outros.

    `vivo(a)` responde bool ou "vivo"/"fechado"/"mudo" (`central.
    estado_chrome`). Chrome MUDO não ganha outro Chrome por cima nem conversa
    de Playwright (que esperaria para sempre): vira linha "CHROME TRAVADO", e
    `socorro` (opcional, `Socorro`) decide se já é hora de matá-lo — se
    matou, o ciclo segue como se estivesse fechado e sobe um novo.

    `faxinar(a, logado)` (opcional) fecha as abas esquecidas e devolve uma
    linha por aba fechada (`erp/faxina.py`). Roda depois do login, e o erro
    dela vira linha de log: nunca muda o "ok"/"SEM LOGIN" do acesso. Com o
    Chrome mudo ela não roda."""
    saida = []
    for a in acessos.values():
        logado = False
        mudo = False
        try:
            partes = []
            estado = _como_estado(vivo(a))
            if estado == "mudo" and socorro is not None:
                feito = socorro.travado(a)
                if feito:
                    partes.append(feito)
                    estado = "fechado"
            elif socorro is not None:
                socorro.respondeu(a)
            if estado == "mudo":
                mudo = True
                vezes = socorro.vezes(a) if socorro is not None else 0
                linha = (f"{a.nome}: CHROME TRAVADO — a porta {a.porta} aceita "
                         f"conexão e não responde"
                         + (f" ({vezes}ª vez seguida)" if vezes else ""))
            else:
                if estado != "vivo":
                    subir_chrome(a)
                    partes.append("chrome subiu")
                if checar_login(a):
                    logado = True
                    partes.append("ok")
                    linha = f"{a.nome}: " + "; ".join(partes)
                else:
                    linha = (f"{a.nome}: " + "".join(x + "; " for x in partes)
                             + "SEM LOGIN — entre na janela do Chrome central")
        except Exception as e:
            linha = f"{a.nome}: ERRO {e!r}"
        log(linha)
        saida.append(linha)
        if faxinar is not None and not mudo:
            try:
                for f in faxinar(a, logado):
                    log(f"{a.nome}: faxina — {f}")
            except Exception as e:
                log(f"{a.nome}: faxina não rodou ({e!r})")
    return saida


#: Ciclos seguidos com o Chrome mudo antes de matá-lo. Com o intervalo de
#: 120 s são uns 6 min: um Chrome só lento (10 s de prazo na 2ª pergunta)
#: não chega a três seguidas; o de 09/11/2026 ficou mudo 25 min até alguém
#: fechá-lo à mão.
LIMITE_MUDO = 3


class Socorro:
    """Conta os ciclos seguidos com o Chrome mudo, por acesso, e no
    `LIMITE_MUDO`º mata o Chrome do perfil (`central.matar_chrome`) e solta
    o cliente do porteiro (`ao_matar(nome)`), que apontava para o morto."""

    def __init__(self, *, matar=None, ao_matar=None, limite=LIMITE_MUDO,
                 esperar_fechar=None):
        self._matar = matar
        self._ao_matar = ao_matar
        self._limite = limite
        self._esperar_fechar = esperar_fechar
        self._contas: dict = {}

    def vezes(self, a) -> int:
        return self._contas.get(a.nome, 0)

    def respondeu(self, a) -> None:
        self._contas.pop(a.nome, None)

    def travado(self, a) -> str | None:
        n = self._contas.get(a.nome, 0) + 1
        self._contas[a.nome] = n
        if n < self._limite:
            return None
        pids = (self._matar or central.matar_chrome)(a)
        self._contas.pop(a.nome, None)
        if self._ao_matar is not None:
            with contextlib.suppress(Exception):
                self._ao_matar(a.nome)
        if self._esperar_fechar is not None:
            self._esperar_fechar(a)
        return (f"Chrome travado há {n} ciclos: reiniciado "
                f"(processos {', '.join(map(str, pids)) or 'nenhum achado'})")


def _esperar_porta_fechar(a, *, prazo=20.0, dormir=time.sleep):
    """Depois do `taskkill`, a porta leva um instante para soltar; subir o
    Chrome novo antes disso daria "mudo" de novo."""
    fim = time.monotonic() + prazo
    while time.monotonic() < fim and central.porta_ouvindo(a):
        dormir(0.5)


class Mantenedor:
    """Um cliente do ERP por acesso, aberto entre os ciclos (mesma thread)."""

    def __init__(self, abrir, fechar):
        self._abrir, self._fechar = abrir, fechar
        self._clientes: dict = {}
        self._ids: list = []       # (aba, targetId): perguntado UMA vez por aba

    def checar(self, a) -> bool:
        c = self._clientes.get(a.nome)
        if c is not None and not c.vivo():
            self._soltar(a.nome)
            c = None
        if c is None:
            c = self._abrir(a)
            self._clientes[a.nome] = c
        if c.esta_logado():
            return True
        return bool(c.garantir_login())

    def soltar(self, nome):
        """Esquece o cliente deste acesso (o próximo `checar` abre outro)."""
        self._soltar(nome)

    def _soltar(self, nome):
        c = self._clientes.pop(nome, None)
        if c is not None:
            with contextlib.suppress(Exception):
                self._fechar(c)

    def fechar_tudo(self):
        for nome in list(self._clientes):
            self._soltar(nome)

    def ids_das_abas(self, nome) -> set:
        """Os targetIds das abas do porteiro neste acesso (a faxina nunca as
        fecha). Pergunta ao CDP (`Target.getTargetInfo`) UMA vez por aba e
        guarda: até 09/11/2026 perguntava a cada ciclo, e com o Chrome
        travado essa pergunta — sem prazo, como toda chamada do Playwright —
        prendeu o porteiro das 14:06 às 14:33. Não roda JS em aba nenhuma."""
        c = self._clientes.get(nome)
        abas = list(getattr(c, "_minhas", ()) or ())
        todas = [x for cl in self._clientes.values()
                 for x in (getattr(cl, "_minhas", ()) or ())]
        self._ids = [(x, t) for x, t in self._ids if any(x is y for y in todas)]
        ids = set()
        for aba in abas:
            tid = next((t for x, t in self._ids if x is aba), None)
            if tid is None:
                with contextlib.suppress(Exception):
                    sess = aba.context.new_cdp_session(aba)
                    try:
                        tid = sess.send("Target.getTargetInfo")["targetInfo"]["targetId"]
                    finally:
                        sess.detach()
                    self._ids.append((aba, tid))
            if tid is not None:
                ids.add(tid)
        return ids

    def respirar(self):
        """Uma ida curta ao navegador por cliente (`MCClient.pulsar`), para os
        eventos pendentes chegarem — ver `_dormir`."""
        for c in list(self._clientes.values()):
            c.pulsar()


#: Maior sono seguido entre os ciclos. É o máximo que a aba nova de OUTRO
#: programa espera pelo porteiro para começar a carregar.
PASSO_RESPIRO = 0.5


def _dormir(segundos, respirar, *, relogio=time.monotonic, dormir=time.sleep):
    """O sono entre os ciclos, em passos de `PASSO_RESPIRO`, pulsando o
    navegador a cada um.

    Com `time.sleep(intervalo)` inteiro, a aba nova que um robô abria no Chrome
    central ficava PARADA, sem nem pedir a página, até o ciclo seguinte do
    porteiro (medido em 29/10/2026: o pedido saía no mesmo instante do ciclo,
    até 2 min depois) — o Playwright sync do porteiro só trata o que chega do
    navegador durante uma chamada. Pulso que falha não para o sono: navegador
    fechado é assunto do próximo ciclo."""
    fim = relogio() + segundos
    while (falta := fim - relogio()) > 0:
        with contextlib.suppress(Exception):
            respirar()
        dormir(min(PASSO_RESPIRO, falta))


# ------------------------------------------------- a guarda e o sinal de vida

def _matar_driver(*, rodar=subprocess.run, pid=None) -> list[int]:
    """Mata o driver do Playwright DESTE processo (o node.exe filho). A
    chamada presa nele cai com erro na linha principal, e o `Mantenedor`
    abre um cliente novo no ciclo seguinte. Não toca no Chrome."""
    pid = pid or os.getpid()
    script = (f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={int(pid)} "
              "and Name='node.exe'\" | % { $_.ProcessId }")
    r = rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
              capture_output=True, text=True, timeout=60,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    pids = [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]
    for filho in pids:
        with contextlib.suppress(Exception):
            rodar(["taskkill", "/PID", str(filho), "/T", "/F"], capture_output=True,
                  timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return pids


class Guarda:
    """Vigia o ciclo do porteiro DE FORA da linha do Playwright.

    Toda chamada do Playwright sync a um Chrome travado espera para sempre (em
    09/11/2026 o porteiro ficou preso das 14:06 às 14:33, e só voltou quando
    alguém o matou). A guarda roda numa linha à parte e só usa HTTP e
    processos — nunca o Playwright. Se o ciclo não `marcar` há mais de
    `parado` segundos:
      1. Chrome MUDO em `LIMITE_MUDO` olhadas seguidas → mata o Chrome do
         perfil; a chamada presa cai com erro e o ciclo segue;
      2. parado há `limite_driver` s com o Chrome respondendo → mata o driver
         do Playwright deste processo (uma vez);
      3. parado há `limite_sair` s → sai com código 3; a tarefa "MoraisEng -
         Vigia do porteiro" (`erp/vigia.py`) o levanta de novo.
    `limite_driver` passa dos 10 min que o login pode esperar pela trava do
    login (`MCClient.garantir_login`): login demorado não é porteiro preso."""

    def __init__(self, acessos, *, log, estado=None, matar=None, matar_driver=None,
                 sair=os._exit, relogio=time.monotonic, passo=30.0, parado=300.0,
                 limite_driver=900.0, limite_sair=1200.0, limite_mudo=LIMITE_MUDO):
        self._acessos = acessos
        self._log = log
        self._estado = estado
        self._matar = matar
        self._matar_driver = matar_driver or _matar_driver
        self._sair = sair
        self._relogio = relogio
        self._passo = passo
        self._parado, self._limite_driver = parado, limite_driver
        self._limite_sair, self._limite_mudo = limite_sair, limite_mudo
        self._ultima = relogio()
        self._mudos: dict = {}
        self._driver_morto = False
        self._fim = threading.Event()
        self._linha = None

    def marcar(self) -> None:
        self._ultima = self._relogio()
        self._mudos.clear()
        self._driver_morto = False

    def verificar(self) -> str | None:
        """Uma olhada. Devolve o que fez (ou None)."""
        idade = self._relogio() - self._ultima
        if idade < self._parado:
            return None
        estado = self._estado or central.estado_chrome
        for a in self._acessos.values():
            try:
                mudo = estado(a) == "mudo"
            except Exception:
                mudo = False
            if not mudo:
                self._mudos.pop(a.nome, None)
                continue
            n = self._mudos.get(a.nome, 0) + 1
            self._mudos[a.nome] = n
            if n >= self._limite_mudo:
                self._mudos.pop(a.nome, None)
                pids = (self._matar or central.matar_chrome)(a)
                feito = (f"{a.nome}: GUARDA — porteiro parado há {idade / 60:.0f} min "
                         f"com o Chrome travado: Chrome reiniciado (processos "
                         f"{', '.join(map(str, pids)) or 'nenhum achado'})")
                self._log(feito)
                return feito
        if idade >= self._limite_sair:
            self._log(f"GUARDA — porteiro parado há {idade / 60:.0f} min: saindo "
                      f"para a tarefa do vigia levantar de novo")
            self._sair(3)
            return "saiu"
        if idade >= self._limite_driver and not self._driver_morto:
            self._driver_morto = True
            pids = self._matar_driver()
            feito = (f"GUARDA — porteiro parado há {idade / 60:.0f} min com o Chrome "
                     f"respondendo: driver do Playwright reiniciado (processos "
                     f"{', '.join(map(str, pids)) or 'nenhum achado'})")
            self._log(feito)
            return feito
        return None

    def comecar(self) -> None:
        def laco():
            while not self._fim.wait(self._passo):
                with contextlib.suppress(Exception):
                    self.verificar()
        self._linha = threading.Thread(target=laco, name="guarda-do-porteiro", daemon=True)
        self._linha.start()

    def parar(self) -> None:
        self._fim.set()


#: O sinal de vida que `erp/vigia.py` lê, na pasta central.
ARQUIVO_VIVO = "porteiro-vivo.json"


def gravar_vivo(pasta, linhas, *, agora=None) -> None:
    """Grava `porteiro-vivo.json`: quando foi o último ciclo, o pid e se
    todos os acessos ficaram "ok". Escreve num temporário e troca, para o
    vigia nunca ler meio arquivo. Falha aqui nunca para o porteiro."""
    if pasta is None:
        return
    with contextlib.suppress(Exception):
        agora = agora or _dt.datetime.now().astimezone()
        dados = {"em": agora.isoformat(timespec="seconds"), "pid": os.getpid(),
                 "ok": bool(linhas) and all(x.endswith("ok") for x in linhas),
                 "linhas": list(linhas)}
        tmp = pasta / (ARQUIVO_VIVO + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, pasta / ARQUIVO_VIVO)


def _mantenedor_real(log) -> Mantenedor:
    from anexar.mc_client import MCClient   # tarde: puxa Playwright

    def abrir(a):
        mc = MCClient(acesso=a, log=log)
        # O porteiro É quem entra: não pede o login principal (28/10/2026),
        # e o comportamento dele fica o de sempre.
        mc.login_principal = False
        mc.__enter__()
        return mc
    return Mantenedor(abrir, lambda mc: mc.__exit__(None, None, None))


def _subir_chrome(a):
    """Sobe o Chrome do acesso. O histórico de downloads é apagado DENTRO de
    `central.garantir_chrome`, sob a trava e com o Chrome confirmado fechado —
    vale para quem subir, robô ou porteiro. Limpar aqui também seria limpar
    fora da trava, com outro robô podendo estar subindo o mesmo perfil."""
    central.garantir_chrome(a)


def guardar_login(a, *, pedir_email=input, pedir_senha=None,
                  proteger=None):
    """Cifra (DPAPI) e grava o login do acesso, no formato de
    `anexar/credenciais.py`. A senha nunca é impressa."""
    if a.credencial is None:
        sys.exit(f"o acesso '{a.nome}' não tem 'credencial' no acessos.json")
    if pedir_senha is None:
        import getpass   # tarde: o exe não embute getpass
        pedir_senha = getpass.getpass
    if proteger is None:
        import util
        proteger = util.proteger_bytes
    email = pedir_email("E-mail do ERP: ").strip()
    senha = pedir_senha("Senha (não aparece): ")
    dados = json.dumps({"email": email, "senha": senha}).encode("utf-8")
    a.credencial.parent.mkdir(parents=True, exist_ok=True)
    a.credencial.write_bytes(proteger(dados))
    print(f"login do acesso '{a.nome}' guardado em {a.credencial}")


def _logger(pasta):
    # Importado AQUI e não no topo: `logging.handlers` é submódulo à parte e já
    # derrubou uma release (v2.0.159) por faltar no exe. O `erp/` vai no
    # codigo.zip; assim importar `erp.porteiro` nunca depende dele.
    from logging.handlers import RotatingFileHandler
    pasta.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger("porteiro")
    lg.setLevel(logging.INFO)
    if not lg.handlers:
        h = RotatingFileHandler(pasta / "porteiro.log", maxBytes=1_000_000,
                                backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        lg.addHandler(h)
        lg.addHandler(logging.StreamHandler())
    return lg


def _ao_sinal(signum, frame):
    """Tratador de SIGTERM/SIGBREAK: SÓ levanta. Roda na thread principal, que
    é a do Playwright — tocar no navegador aqui seria reentrar nele no meio de
    uma chamada. Quem fecha é o `finally` de `vigiar`."""
    raise KeyboardInterrupt(f"sinal {signum}")


def _sinais_de_parar() -> list:
    """SIGTERM sempre; SIGBREAK onde existir (Windows: Ctrl+Break e o fechar
    do console chegam como ele)."""
    import signal
    return [getattr(signal, n) for n in ("SIGTERM", "SIGBREAK") if hasattr(signal, n)]


def _instalar_sinais() -> dict:
    import signal
    anteriores = {}
    for s in _sinais_de_parar():
        with contextlib.suppress(ValueError, OSError):   # fora da thread principal
            anteriores[s] = signal.signal(s, _ao_sinal)
    return anteriores


def _restaurar_sinais(anteriores: dict) -> None:
    import signal
    for s, h in anteriores.items():
        with contextlib.suppress(ValueError, OSError, TypeError):
            signal.signal(s, h)


def vigiar(acessos, pasta, intervalo=120, *, ciclos=None, guarda=None):
    """Ciclo a cada `intervalo` segundos. Sai fechando as abas do porteiro por
    três portas: Ctrl+C, SIGTERM/SIGBREAK (viram KeyboardInterrupt e caem no
    `finally`) e `atexit` (fim do interpretador por outro caminho).

    Fica de fora o que nenhum código vê: TerminateProcess ("Finalizar
    tarefa" do Agendador, Gerenciador de Tarefas). Aí a aba fica no Chrome
    central até alguém fechá-la."""
    from erp.faxina import Faxina
    lg = _logger(pasta)
    m = _mantenedor_real(lg.info)
    fx = Faxina(pasta_reg=None if pasta is None else pasta / "abas-robos")

    def faxinar(a, logado):
        return fx.passar(a, minhas=m.ids_das_abas(a.nome), logado=logado)

    socorro = Socorro(ao_matar=m.soltar, esperar_fechar=_esperar_porta_fechar)
    guarda = (guarda or Guarda)(acessos, log=lg.info)
    atexit.register(m.fechar_tudo)          # idempotente: o finally já esvazia
    anteriores = _instalar_sinais()
    lg.info(f"porteiro de pé: {', '.join(acessos)}; intervalo {intervalo} s")
    guarda.comecar()
    n = 0
    try:
        while ciclos is None or n < ciclos:
            guarda.marcar()
            linhas = um_ciclo(acessos, vivo=central.estado_chrome,
                              subir_chrome=_subir_chrome, checar_login=m.checar,
                              log=lg.info, faxinar=faxinar, socorro=socorro)
            guarda.marcar()
            gravar_vivo(pasta, linhas)
            n += 1
            if ciclos is None or n < ciclos:
                _dormir(intervalo, m.respirar)
    except KeyboardInterrupt:
        lg.info("porteiro parado")
    finally:
        guarda.parar()
        try:
            m.fechar_tudo()    # só as abas do porteiro; o Chrome central fica
        finally:
            _restaurar_sinais(anteriores)
            atexit.unregister(m.fechar_tudo)


def main(argv=None) -> int:
    import argparse   # tarde: o exe não embute argparse (ver tests/test_imports_do_motor.py)
    p = argparse.ArgumentParser(prog="python -m erp.porteiro")
    p.add_argument("comando", choices=["estado", "guardar-login", "subir", "vigiar"])
    p.add_argument("--acesso", help="só este acesso (padrão: todos)")
    p.add_argument("--intervalo", type=int, default=120)
    args = p.parse_args(argv)

    pasta = central.pasta_central()
    todos = central.carregar_acessos(pasta)
    if not todos:
        onde = "MC_CENTRAL=off" if pasta is None else pasta
        print(f"central desligado ou sem acessos.json ({onde})", file=sys.stderr)
        return 2
    if args.acesso:
        if args.acesso not in todos:
            print(f"acesso '{args.acesso}' não existe: {', '.join(todos)}",
                  file=sys.stderr)
            return 2
        todos = {args.acesso: todos[args.acesso]}

    if args.comando == "estado":
        print(json.dumps(montar_estado(todos, central.chrome_vivo),
                         ensure_ascii=False, indent=2))
    elif args.comando == "guardar-login":
        if not args.acesso:
            print("use --acesso NOME", file=sys.stderr)
            return 2
        guardar_login(todos[args.acesso])
    elif args.comando == "subir":
        m = _mantenedor_real(print)
        try:
            um_ciclo(todos, vivo=central.estado_chrome, subir_chrome=_subir_chrome,
                     checar_login=m.checar, log=print)
        finally:
            m.fechar_tudo()
    else:
        vigiar(todos, pasta, args.intervalo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
