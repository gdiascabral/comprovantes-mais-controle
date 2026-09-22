# -*- coding: utf-8 -*-
"""A varredura do calendário do portal, sem navegador.

O portal é site de terceiro e segue fora de teste de verdade; o que se prova
aqui é a REGRA: o que entra, o que fica de fora, e que guia sem PDF não vira
lançamento. Nomes e endereços INVENTADOS: o repositório é público.
"""
from pathlib import Path

from guias import calendario as mod
from guias import leitura

CAL = {
    "12": [
        {"desc": "HONORARIO CONTABIL 09/2026", "prz": "12/09/2026",
         "TemVcto": "S", "AnxID": "111", "lnk": "https://exemplo.invalido/1"},
        {"desc": "CND FEDERAL", "prz": "12/09/2026",
         "TemVcto": "S", "AnxID": "112", "lnk": "https://exemplo.invalido/2"},
    ],
    "18": [
        {"desc": "BALANCETE 08/2026", "prz": "18/09/2026",
         "TemVcto": "N", "AnxID": "113", "lnk": "https://exemplo.invalido/3"},
    ],
}


def test_so_entra_o_que_tem_vencimento_e_nao_e_certidao():
    itens = mod.itens_do_mes(CAL)

    assert [i["AnxID"] for i in itens] == ["111"]


def test_calendario_vazio_nao_quebra():
    assert mod.itens_do_mes({}) == []
    assert mod.itens_do_mes(None) == []


# ----------------------------------------------------- I7: vencimento do prz

def test_vencimento_do_prz_le_dd_mm_aaaa():
    from datetime import date
    assert mod._vencimento_do_prz("12/09/2026") == date(2026, 9, 12)


def test_vencimento_do_prz_aceita_texto_depois_da_data():
    from datetime import date
    assert mod._vencimento_do_prz("12/09/2026 - vencimento") == date(2026, 9, 12)


def test_vencimento_do_prz_ilegivel_vira_none_sem_quebrar():
    assert mod._vencimento_do_prz("") is None
    assert mod._vencimento_do_prz(None) is None
    assert mod._vencimento_do_prz("dia 12") is None
    assert mod._vencimento_do_prz("31/02/2026") is None    # 31 de fevereiro


# ------------------------------------------------------------ portal falso

class _PortalFalso:
    def __init__(self, falhar_download=()):
        self.baixados = []
        self.tentativas = []
        self.falhar = set(falhar_download)

    def empresas(self):
        return [("701", "EMPRESA UM"), ("702", "EMPRESA DOIS")]

    def calendario(self, vip_id, ano, mes):
        return CAL if vip_id == "701" else {}

    def baixar_guia(self, lnk, destino):
        self.tentativas.append(lnk)
        if lnk in self.falhar:
            raise RuntimeError("o link da guia expirou")
        self.baixados.append(destino)
        Path(destino).write_bytes(b"%PDF-1.4 fingido")
        return Path(destino)


class _MapaFalso:
    class _Empresa:
        def __init__(self, vip_id, nome):
            self.vip_id, self.nome = vip_id, nome

    empresas = [_Empresa("701", "EMPRESA UM")]


def test_varre_le_e_devolve_uma_guia_por_cobranca(tmp_path, monkeypatch):
    monkeypatch.setattr(
        mod.leitura, "ler_pdf",
        lambda _c: [leitura.ItemLido(valor=None, documento="DOC-1")])
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    # _PortalFalso.empresas() sempre traz "702" também, sem cadastro em
    # _MapaFalso: essa linha de aviso é o assunto do teste seguinte, e não
    # deste — aqui o que se prova é a empresa mapeada.
    achadas = [g for g in guias if g.vip_id == "701"]
    assert len(achadas) == 1
    assert achadas[0].documento == "DOC-1"
    assert achadas[0].pdf is not None


def test_empresa_do_portal_sem_cadastro_vira_linha_de_aviso(tmp_path):
    """O id vem do portal, mas sem empresa cadastrada não há pasta para o PDF
    nem obra para o lançamento — e some em silêncio é o que não pode."""
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    avisos = [g for g in guias if g.vip_id == "702"]
    assert len(avisos) == 1
    assert "cadastr" in avisos[0].erro.lower()
    assert avisos[0].pdf is None


def test_guia_cujo_download_falhou_fica_com_erro_e_sem_pdf(tmp_path):
    """Review Focus 3: sem PDF não se lança, por mais completo que esteja.

    E o retry tem TETO: o link do documento expira em 120 s e cada tentativa
    é um download de verdade contra o portal do escritório. Falha persistente
    tem de parar em exatamente 2 chamadas — 3 seria insistência que ninguém
    pediu, e é o que este teste passa a vigiar."""
    portal = _PortalFalso(falhar_download=["https://exemplo.invalido/1"])

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    guia = [g for g in guias if g.anx_id == "111"][0]
    assert guia.pdf is None
    assert "expirou" in guia.erro
    assert len(portal.tentativas) == 2


def test_download_e_tentado_de_novo_uma_vez(tmp_path, monkeypatch):
    """O link do iframe expira em 120 s: a segunda tentativa pede um link novo,
    e é ela que costuma funcionar. Tentar mais que isso só demora."""
    tentativas = []

    class _PortalTeimoso(_PortalFalso):
        def baixar_guia(self, lnk, destino):
            tentativas.append(lnk)
            if len(tentativas) == 1:
                raise RuntimeError("o link da guia expirou")
            Path(destino).write_bytes(b"%PDF-1.4 fingido")
            return Path(destino)

    monkeypatch.setattr(
        mod.leitura, "ler_pdf",
        lambda _c: [leitura.ItemLido(valor=None, documento="DOC-1")])

    guias = mod.varrer(_PortalTeimoso(), _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    assert len(tentativas) == 2
    assert [g for g in guias if g.vip_id == "701"][0].pdf is not None


def test_parar_interrompe_entre_empresas(tmp_path):
    portal = _PortalFalso()

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None,
                       parar=lambda: True)

    assert guias == []


def test_guia_lida_carrega_o_vencimento_do_portal_mesmo_tendo_o_do_pdf(
        tmp_path, monkeypatch):
    """I7: o `prz` do calendário viaja na Guia sempre — é o `criar` quem
    decide se usa (só na falta do vencimento do PDF)."""
    from datetime import date
    monkeypatch.setattr(
        mod.leitura, "ler_pdf",
        lambda _c: [leitura.ItemLido(valor=None, documento="DOC-1",
                                     vencimento=date(2026, 9, 20))])

    guias = mod.varrer(_PortalFalso(), _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    guia = [g for g in guias if g.vip_id == "701"][0]
    assert guia.vencimento_portal == date(2026, 9, 12)   # o "prz" da fixture CAL


def test_guia_cujo_download_falhou_ainda_carrega_o_vencimento_do_portal(
        tmp_path):
    """A ficha de arrecadação (FGTS, INSS/IRRF, contribuição) não traz
    vencimento no código de barras: sem o `prz`, uma guia com erro de
    download perderia o único dado autoritativo que tinha."""
    from datetime import date
    portal = _PortalFalso(falhar_download=["https://exemplo.invalido/1"])

    guias = mod.varrer(portal, _MapaFalso(), 2026, 9,
                       pasta_de=lambda _e: tmp_path, log=lambda _m: None)

    guia = [g for g in guias if g.anx_id == "111"][0]
    assert guia.vencimento_portal == date(2026, 9, 12)
