# -*- coding: utf-8 -*-
"""
Ajustes do app de anexar. Os caminhos são relativos à pasta deste arquivo
(ou à pasta do executável, quando empacotado como .exe),
então funciona em qualquer computador sem editar nada.
"""
import sys
import time
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

if getattr(sys, "frozen", False):
    # Rodando como executável (PyInstaller): usa a pasta onde o .exe está,
    # para o log persistir entre execuções.
    _AQUI = Path(sys.executable).resolve().parent
else:
    _AQUI = Path(__file__).resolve().parent

# Perfil do Chrome (mantém o login do Mais Controle salvo entre execuções).
# Sai de `util.pasta_do_perfil()`, e não de `_AQUI`: rodando como SCRIPT,
# `_AQUI` é a pasta DESTE módulo (`anexar/`), e um segundo conjunto de
# perfis nascia ali dentro — a mesma família do defeito que o cache do
# cadastro já teve (CLAUDE.md, "quem lê o cache tem de usar
# util.pasta_base()"). Congelado o lugar não muda: `_AQUI` já era a pasta
# do exe, igual a `util.pasta_base()`.
PASTA_PERFIL_CHROME = util.pasta_do_perfil()

# Log (CSV) com o resultado de cada anexo.
ARQUIVO_LOG = _AQUI / "log_anexos.csv"

# Log de diagnóstico para erros normalmente silenciosos (ex.: captura de
# credenciais na tela de Pagamentos).
ARQUIVO_DIAG = _AQUI / "diagnostico.log"

# Login salvo (e-mail + senha) cifrado com a DPAPI do Windows, para o login
# automático. Fica atrelado ao usuário do Windows; nunca em texto puro.
ARQUIVO_LOGIN = _AQUI / "login.dat"


def diag(msg: str):
    """Registra no diagnostico.log um erro que de outro modo seria silencioso.

    Vários pontos do app precisam degradar sem quebrar (o ERP muda um seletor,
    a DPAPI recusa o login salvo, um anexo não baixa). Engolir o erro esconde
    a causa e a falha reaparece como comportamento estranho — então engole,
    mas deixa registrado aqui."""
    try:
        with open(ARQUIVO_DIAG, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%d/%m/%Y %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass                      # sem disco/permissão: não há o que fazer


# Tag aplicada ao arquivo anexado no Mais Controle.
TAG_COMPROVANTE = "Comprovante"

# URL do sistema.
MC_URL_BASE = "https://acessar.maiscontroleerp.com.br"
MC_URL_PAGAMENTOS = MC_URL_BASE + "/#/payable-installments"
#: A porta de entrada, usada quando a sessão NÃO está de pé.
#:
#: Existe porque cair numa rota interna com o token vencido é o que produz a
#: tela de "sessão encerrada" e o vaivém de entra-sai-entra: o single-spa
#: repinta a casca, descobre que não pode, e volta — às vezes duas vezes. Indo
#: direto para o login, a tela que aparece é a de login, que é o que a pessoa
#: precisa ver.
MC_URL_LOGIN = MC_URL_BASE + "/#/login"
# Prefixo do link de um lançamento (basta concatenar o launchId).
MC_URL_LANCAMENTO = MC_URL_BASE + "/#/payable-installments/"

# Descrições/categorias ignoradas pelas opções da janela
# (comparação sem acento, maiúsculas).
IGNORAR_TARIFAS = [
    "IOF",
    "TARIFA PIX",
    "TARIFA BANC",
    "CESTA",
    "DEBITO PACOTE",
]
IGNORAR_APORTES = [
    "APORTE CAPITAL",
    "DISTRIBUICAO DE LUCRO",
]
