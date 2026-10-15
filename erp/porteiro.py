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
thread principal; se `vivo()` der False ele é fechado e recriado.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import logging
import sys
import time

from erp import central


def montar_estado(acessos, vivo) -> dict:
    """O que `estado` imprime. Só pergunta `vivo`; não sobe nada."""
    return {"acessos": [
        {"nome": a.nome, "porta": a.porta, "chrome_vivo": bool(vivo(a))}
        for a in acessos.values()]}


def um_ciclo(acessos, *, vivo, subir_chrome, checar_login, log) -> list[str]:
    """Um passo de vigia: por acesso, sobe o Chrome se estiver fechado e
    confere o login. Devolve o que fez, uma linha por acesso. Erro num acesso
    vira linha "ERRO" e não impede os outros."""
    saida = []
    for a in acessos.values():
        try:
            partes = []
            if not vivo(a):
                subir_chrome(a)
                partes.append("chrome subiu")
            if checar_login(a):
                partes.append("ok")
                linha = f"{a.nome}: " + "; ".join(partes)
            else:
                linha = f"{a.nome}: SEM LOGIN — entre na janela do Chrome central"
        except Exception as e:
            linha = f"{a.nome}: ERRO {e!r}"
        log(linha)
        saida.append(linha)
    return saida


class Mantenedor:
    """Um cliente do ERP por acesso, aberto entre os ciclos (mesma thread)."""

    def __init__(self, abrir, fechar):
        self._abrir, self._fechar = abrir, fechar
        self._clientes: dict = {}

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

    def _soltar(self, nome):
        c = self._clientes.pop(nome, None)
        if c is not None:
            with contextlib.suppress(Exception):
                self._fechar(c)

    def fechar_tudo(self):
        for nome in list(self._clientes):
            self._soltar(nome)


def _mantenedor_real(log) -> Mantenedor:
    from anexar.mc_client import MCClient   # tarde: puxa Playwright

    def abrir(a):
        mc = MCClient(acesso=a, log=log)
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


def vigiar(acessos, pasta, intervalo=120, *, ciclos=None):
    """Ciclo a cada `intervalo` segundos. Sai fechando as abas do porteiro por
    três portas: Ctrl+C, SIGTERM/SIGBREAK (viram KeyboardInterrupt e caem no
    `finally`) e `atexit` (fim do interpretador por outro caminho).

    Fica de fora o que nenhum código vê: TerminateProcess ("Finalizar
    tarefa" do Agendador, Gerenciador de Tarefas). Aí a aba fica no Chrome
    central até alguém fechá-la."""
    lg = _logger(pasta)
    m = _mantenedor_real(lg.info)
    atexit.register(m.fechar_tudo)          # idempotente: o finally já esvazia
    anteriores = _instalar_sinais()
    lg.info(f"porteiro de pé: {', '.join(acessos)}; intervalo {intervalo} s")
    n = 0
    try:
        while ciclos is None or n < ciclos:
            um_ciclo(acessos, vivo=central.chrome_vivo, subir_chrome=_subir_chrome,
                     checar_login=m.checar, log=lg.info)
            n += 1
            if ciclos is None or n < ciclos:
                time.sleep(intervalo)
    except KeyboardInterrupt:
        lg.info("porteiro parado")
    finally:
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
            um_ciclo(todos, vivo=central.chrome_vivo, subir_chrome=_subir_chrome,
                     checar_login=m.checar, log=print)
        finally:
            m.fechar_tudo()
    else:
        vigiar(todos, pasta, args.intervalo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
