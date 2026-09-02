# -*- coding: utf-8 -*-
"""A janela da suíte nasce com handles que a captura do pytest não fecha.

Ver `tcl_com_handles_proprios` no conftest: o Tcl embrulha os handles padrão
do processo, a captura do pytest os fecha por fora a cada fase de teste, e o
valor reaproveitado pelo Windows faz o `open` seguinte do Tcl falhar em
silêncio — no meio da varredura que ensina ao autoload onde mora o
`tk_focusNext`. Reencenado num processo à parte, porque a suíte tem UM `Tk()`
e ele já nasce protegido: um `Tk()` com ou sem a proteção, um `dup2` sobre os
fds 0, 1 e 2 (a captura em miniatura) e o autoload do Tk em seguida. Sem a
proteção o `tk_focusNext` não aparece; com ela, aparece. As duas metades
importam: a segunda é a garantia, a primeira prova que a encenação reproduz o
defeito nesta máquina — sem ela, a garantia poderia estar passando à toa.

**A primeira metade é um dado viciado, não uma certeza.** O defeito depende
de o Windows devolver ao `CreateFile` do Tcl exatamente o valor de handle que
o `dup2` acabou de fechar. Ele devolve o último fechado quase sempre, mas
qualquer alocação de handle que outra thread do processo faça nesse
intervalo (o notifier do Tcl, o próprio Windows) leva o valor antes. Medido
com três suítes rodando ao mesmo tempo: 13 reproduções em 20 sem esperar a
janela assentar, 19 em 20 esperando — e é por isso que o filho dá um
`update` e 200 ms antes do `dup2`, e a metade "sem proteção" tenta até
quatro vezes, cada uma num processo novo. A metade "com proteção" não tem
dado nenhum: sem handle morto na lista do Tcl, não há o que colidir.

Só no Windows: é uma peculiaridade do Tcl sobre handles do Windows, e nos
outros sistemas o `dup2` troca o arquivo por trás do MESMO descritor, sem
invalidar o que o Tcl segura."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="peculiaridade do Tcl sobre handles do Windows")

_TESTES = Path(__file__).resolve().parent

# O filho. Os três NUL são abertos ANTES dos `dup2`, para que os três valores
# de handle originais fiquem livres ao mesmo tempo, com o do fd 1 no topo da
# lista — é ele que o `open` do `tclIndex` recebe, e `stdout` é canal só de
# escrita: permissão diferente da leitura pedida, e o Tcl recusa. O `catch`
# existe porque o desfecho pode ser o outro: o valor do fd 0 tem a MESMA
# permissão, e aí o Tcl devolve o canal `stdin` morto e a varredura estoura
# lendo dele. Nos dois casos o `tk_focusNext` não aparece, e é isso que se
# confere.
_ROTEIRO = r'''
import contextlib, os, sys, time, tkinter as tk
sys.path.insert(0, sys.argv[1])
from conftest import tcl_com_handles_proprios
protegido = sys.argv[2] == "sim"
relato = os.dup(1)                    # o fd 1 vai para NUL logo abaixo
with (tcl_com_handles_proprios() if protegido else contextlib.nullcontext()):
    root = tk.Tk()
root.update(); time.sleep(0.2); root.update()   # a janela assenta
novos = {fd: os.open(os.devnull, modo)
         for fd, modo in ((2, os.O_WRONLY), (0, os.O_RDONLY), (1, os.O_WRONLY))}
for fd in (2, 0, 1):
    os.dup2(novos[fd], fd)            # a captura do pytest, em miniatura
carregou = root.tk.eval("catch {auto_load tk_focusNext} r; set r")
existe = root.tk.eval("info commands tk_focusNext")
os.write(relato, f"{carregou}|{existe}".encode())
root.destroy()
'''


def _reencenar(protegido: bool, pasta: Path) -> tuple[str, str]:
    """(o que `auto_load tk_focusNext` devolveu, o que `info commands` vê).

    Os três fds padrão do filho são ARQUIVOS em disco, como os temporários da
    captura do pytest — e não os pipes que `capture_output` daria. A
    diferença decide o teste: pipe vira canal de outro tipo no Tcl, fora da
    lista em que o `TclWinOpenFileChannel` procura handle repetido, e a
    encenação deixaria de reproduzir o defeito."""
    pasta.mkdir(parents=True, exist_ok=True)
    entrada, saida, erros = (pasta / n for n in ("entrada", "saida", "erros"))
    entrada.write_bytes(b"")
    with open(entrada, "rb") as fi, open(saida, "wb") as fo, \
            open(erros, "wb") as fe:
        r = subprocess.run(
            [sys.executable, "-c", _ROTEIRO, str(_TESTES),
             "sim" if protegido else "nao"],
            stdin=fi, stdout=fo, stderr=fe, timeout=120)
    assert r.returncode == 0, erros.read_text(errors="replace")
    carregou, existe = saida.read_text().strip().split("|")
    return carregou, existe


def test_sem_a_protecao_a_captura_mata_o_autoload_do_tk(raiz, tmp_path):
    tentativas = []
    for n in range(4):
        carregou, existe = _reencenar(protegido=False, pasta=tmp_path / str(n))
        tentativas.append((carregou, existe))
        if existe == "":
            return                    # reproduziu: o Tk ficou sem o proc
    pytest.fail(
        "a encenação não reproduziu o defeito nesta máquina em quatro "
        "tentativas: o Windows não devolveu ao Tcl nenhum handle que o dup2 "
        f"fechou — o teste seguinte pode estar passando à toa: {tentativas}")


def test_com_a_protecao_o_autoload_do_tk_sobrevive_a_captura(raiz, tmp_path):
    carregou, existe = _reencenar(protegido=True, pasta=tmp_path)
    assert (carregou, existe) == ("1", "tk_focusNext"), (
        "o Tcl perdeu o índice do Tk mesmo com handles próprios "
        f"(auto_load={carregou!r}, commands={existe!r})")
