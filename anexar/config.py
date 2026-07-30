# -*- coding: utf-8 -*-
"""
Ajustes do app de anexar. Os caminhos são relativos à pasta deste arquivo
(ou à pasta do executável, quando empacotado como .exe),
então funciona em qualquer computador sem editar nada.
"""
import sys
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
# compatibilidade com versões antigas
IGNORAR_PADRAO = IGNORAR_TARIFAS + IGNORAR_APORTES
