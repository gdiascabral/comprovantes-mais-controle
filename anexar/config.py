# -*- coding: utf-8 -*-
"""
Ajustes do app de anexar. Os caminhos são relativos à pasta deste arquivo
(ou à pasta do executável, quando empacotado como .exe),
então funciona em qualquer computador sem editar nada.
"""
import sys
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    # Rodando como executável (PyInstaller): usa a pasta onde o .exe está,
    # para o perfil do Chrome e o log persistirem entre execuções.
    _AQUI = Path(sys.executable).resolve().parent
else:
    _AQUI = Path(__file__).resolve().parent

# Perfil do Chrome (mantém o login do Mais Controle salvo entre execuções).
PASTA_PERFIL_CHROME = _AQUI / ".chrome_profile"

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
