# -*- coding: utf-8 -*-
"""Pedidos do dono de 27/11/2026 no HTML das PF. Nomes fictícios.

(1) "PAGAMENTO AUTORIZADO — autorizado por X" sozinho vira "Pode pagar
(autorizado por X)"; com outro anexo ao lado, o outro papel decide.
(2) Pix copia-e-cola escrito na observação vira QR (escondido atrás do
"conferi"), só quando é deste lançamento.
(3) Os cartões do topo filtram e cada linha tem "Excluir da lista".
"""
from datetime import date

from pagamentos_dia import html_pf, nivel, qr_pix, relatorio
from pagamentos_dia.relatorio import Resultado

CPF_OK = "52998224725"          # CPF de exemplo, DV válido

AUT = {"filename": "PAGAMENTO AUTORIZADO - FULANA", "extension": ".pdf",
       "downloadUrl": "http://x/aut.pdf"}
TEXTO_AUT = ("A T E N Ç Ã O\nPAGAMENTO\nAUTORIZADO\nautorizado por Beltrano Silva\n"
             "autorizado por FULANA")
RECIBO = {"filename": "recibo", "extension": ".pdf", "downloadUrl": "http://x/rec.pdf"}


def reg(**k):
    base = {"id": "L1", "tipo": "Pix", "dados": f"PIX CPF: {CPF_OK}", "valor": 150.0,
            "favorecido": "LOJA MODELO", "status": "APTO (autorizado)",
            "conferencia": "valor ? · fornecedor ?", "centro_custo": "OBRA X QD 1 LT 2",
            "oc": "", "nf": "", "nf_anexada": False, "oc_da_descricao": "",
            "descricao_lancamento": "MATERIAL", "utilidade": False,
            "vencimento": "2026-11-27", "reembolso": False, "reembolso_nome": "",
            "reembolso_para": "", "pix_qr": "",
            "autorizado_por": ["Beltrano Silva", "FULANA"], "so_autorizacao": True,
            "pago_pela_autorizacao": True}
    base.update(k)
    return base


# ---------------------------------------------------------------- relatorio
def test_quem_autorizou_le_o_texto_e_o_nome_do_arquivo_sem_repetir():
    nomes = relatorio.quem_autorizou([AUT], {AUT["downloadUrl"]: TEXTO_AUT})
    assert nomes == ["Beltrano Silva", "FULANA"]


def test_quem_autorizou_so_pelo_nome_do_arquivo():
    assert relatorio.quem_autorizou([AUT], {}) == ["FULANA"]


def test_so_autorizacao_com_recibo_ao_lado_e_falso():
    textos = {AUT["downloadUrl"]: TEXTO_AUT, RECIBO["downloadUrl"]: "RECIBO R$ 150,00"}
    assert relatorio.so_autorizacao([AUT], textos)
    assert not relatorio.so_autorizacao([AUT, RECIBO], textos)
    assert not relatorio.so_autorizacao([], textos)


def test_oc_autorizada_nao_e_autorizacao_de_pagamento():
    oc = {"filename": "OC 5909 AUTORIZADA", "extension": ".pdf", "downloadUrl": "http://x/oc"}
    assert relatorio.quem_autorizou([oc], {"http://x/oc": "autorizado por FULANA"}) == []


# ---------------------------------------------------------------- nivel
def test_autorizacao_sozinha_pode_pagar_com_quem_autorizou():
    n = nivel.nivel_da_linha(reg())
    assert n.nome == nivel.PODE_PAGAR and n.motivos == []
    assert nivel.rotulo(n) == "PODE PAGAR (autorizado por Beltrano Silva e FULANA)"


def test_autorizacao_com_outro_anexo_o_outro_papel_decide():
    n = nivel.nivel_da_linha(reg(so_autorizacao=False))
    assert n.nome == nivel.NAO_LI
    assert any("confira o outro anexo" in m for m in n.motivos)
    assert nivel.rotulo(n) == "NÃO LI"


def test_autorizacao_com_outro_anexo_que_confere_pode_pagar():
    n = nivel.nivel_da_linha(reg(so_autorizacao=False, conferencia="valor ✓ · fornecedor ✓",
                                 fornecedor_no_anexo=True))
    assert n.nome == nivel.PODE_PAGAR and not n.autorizado_por


def test_autorizacao_nao_passa_por_cima_de_alarme():
    for st in ("ATENÇÃO — valor do boleto diverge", "ATENÇÃO — sem dados de pgto"):
        n = nivel.nivel_da_linha(reg(status=st))
        assert n.nome != nivel.PODE_PAGAR


def test_autorizacao_que_nao_pagou_pela_chave_dos_dados_bancarios_nao_libera():
    """Revisão de dinheiro: o status "APTO (autorizado)" vem só do rótulo; sem a
    chave dos Dados Bancários passar pelas travas de 22/10, não é "Pode pagar"."""
    assert nivel.nivel_da_linha(reg(pago_pela_autorizacao=False)).nome == nivel.NAO_LI


def test_autorizacao_em_titulo_parcelado_nao_libera():
    n = nivel.nivel_da_linha(reg(total_parcelas=3, parcela={"numero": 1, "total": 3}))
    assert n.nome != nivel.PODE_PAGAR


def test_autorizacao_sem_nome_nao_libera():
    assert nivel.nivel_da_linha(reg(autorizado_por=[])).nome == nivel.NAO_LI


def test_autorizacao_vencida_fica_em_olhe_com_quem_autorizou():
    n = nivel.nivel_da_linha(reg(), vencido=True)
    assert n.nome == nivel.OLHE
    assert "autorizado por Beltrano Silva e FULANA" in n.motivos


def test_valor_divergente_continua_divergente_com_autorizacao():
    n = nivel.nivel_da_linha(reg(conferencia="VALOR DIVERGE: anexo R$ 1 × lançamento R$ 2"))
    assert n.nome == nivel.OLHE and "valor diverge" in n.motivos


def test_o_cartao_mostra_o_rotulo_da_autorizacao():
    it = html_pf.item_do_registro("PF", reg())
    html = html_pf._cartao(1, it, date(2026, 11, 27))
    assert "PODE PAGAR (autorizado por Beltrano Silva e FULANA)" in html


# ---------------------------------------------------------------- QR da observação
def _br(nome="CARTORIO MODELO", valor=139.93):
    return html_pf.pix_estatico("fulano@exemplo.com", valor, nome)


def _a_mao(br, **k):
    obs = ("Chave/copia-e-cola veio da observação do lançamento. · PAGAR À MÃO — a "
           f"observação manda pagar outra pessoa. · Observação do lançamento: {br}")
    base = dict(dados=br, valor=139.93, favorecido="CARTORIO MODELO", status="APTO",
                obs=obs, autorizado_por=[], so_autorizacao=False, pix_da_observacao=br)
    base.update(k)
    return reg(**base)


def test_copia_e_cola_da_observacao_vira_qr_escondido():
    br = _br()
    assert qr_pix.valido(br)
    it = html_pf.item_do_registro("PF", _a_mao(br))
    assert [c[1] for c in it.codigos] == [br] and it.codigos[0][2] == "qr"
    assert it.escondido
    assert any("veio da observação" in a for a in it.alertas)
    assert not any("NÃO PAGAR POR AQUI" in a for a in it.alertas)


def test_qr_de_anexo_nunca_vira_o_codigo_da_observacao():
    """Revisão de dinheiro: o "pague à mão" de "PAGAR 8.000,00 PARA FULANO" com
    o QR da NF anexada em `dados` continua sem código."""
    it = html_pf.item_do_registro("PF", _a_mao(_br(), pix_da_observacao=""))
    assert not it.codigos and any("NÃO PAGAR POR AQUI" in a for a in it.alertas)


def test_codigos_no_texto_acha_codigo_com_espaco_no_nome():
    br = _br()
    assert qr_pix.codigos_no_texto(f"guia do cartório: {br} pagar hoje") == [br]
    assert qr_pix.codigos_no_texto("PIX CPF 111.444.777-35") == []


def _linha_relatorio(obs, chave_cadastro="", qr_anexo=None):
    item = {"id": "L1", "tradePayableId": "T-L1", "paidTo": "CARTORIO MODELO",
            "remainingValue": 139.93, "plannedDate": "2026-11-27",
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": chave_cadastro,
            "documentNumber": "", "costCentreDetails": [{"workName": "OBRA MODELO"}],
            "paid": False}
    url = "https://exemplo.invalid/guia"
    anexos = {"T-L1": [{"filename": "guia", "tagName": None, "extension": ".pdf",
                        "downloadUrl": url}]}
    res = relatorio.montar_registros([item], anexos, {"L1": {"comment": obs}},
                                     {url: "guia cartorio modelo 139,93"},
                                     qr_pix={url: [qr_anexo]} if qr_anexo else None)
    return [x for regs in res.contas.values() for x in regs]


def test_relatorio_grava_o_codigo_da_observacao():
    br = _br()
    linha, = _linha_relatorio(br)
    assert linha["pix_da_observacao"] == br


def test_relatorio_nao_grava_quando_a_observacao_manda_pagar_outro():
    br = _br()
    linha, = _linha_relatorio(f"{br} PAGAR 8.000,00 PARA FULANO PIX CPF 111.444.777-35")
    assert linha["pix_da_observacao"] == ""


def test_copia_e_cola_de_outra_pessoa_continua_bloqueado_e_diz_quem():
    it = html_pf.item_do_registro("PF", _a_mao(_br(nome="OUTRA PESSOA")))
    assert not it.codigos
    assert any("NÃO PAGAR POR AQUI" in a and "OUTRA PESSOA" in a for a in it.alertas)


def test_copia_e_cola_de_outro_valor_continua_bloqueado():
    it = html_pf.item_do_registro("PF", _a_mao(_br(valor=200.0)))
    assert not it.codigos
    assert any("R$ 200,00" in a for a in it.alertas)


def test_copia_e_cola_nao_desfaz_outro_bloqueio():
    it = html_pf.item_do_registro("PF", _a_mao(_br(), parcial=True))
    assert not it.codigos


def test_observacao_sem_codigo_continua_a_mao():
    obs = "PAGAR À MÃO — a observação manda pagar outra pessoa."
    it = html_pf.item_do_registro("PF", reg(obs=obs, autorizado_por=[], so_autorizacao=False))
    assert not it.codigos and any("NÃO PAGAR POR AQUI" in a for a in it.alertas)


# ---------------------------------------------------------------- página
def test_pagina_tem_filtros_e_excluir(tmp_path):
    res = Resultado(contas={"PESSOA FISICA - APENAS LANÇAMENTO": [reg()]}, omitidos=[])
    g = html_pf.gravar(res, [], tmp_path, date(2026, 11, 1), date(2026, 11, 27),
                       regras_pf=html_pf.RegrasPF(), hoje=date(2026, 11, 27))
    html = g.caminho.read_text(encoding="utf-8")
    for f in ('data-filtro="atencao"', 'data-filtro="boleto"', 'data-filtro="pix"',
              'data-filtro="pagos"', 'class="excl"', 'id="excluidos"',
              "NÃO exclui no Mais Controle"):
        assert f in html, f


def test_script_da_pagina_e_javascript_valido(tmp_path):
    """Revisão de dinheiro (27/11/2026): uma quebra de linha crua dentro de uma
    string JS do `MODELO` matava o script inteiro — sem "já paguei", sem lista
    de baixas, sem Copiar. Sem node na máquina, confere só a quebra crua."""
    import re
    import shutil
    import subprocess
    res = Resultado(contas={"PESSOA FISICA - APENAS LANÇAMENTO": [reg()]}, omitidos=[])
    g = html_pf.gravar(res, [], tmp_path, date(2026, 11, 1), date(2026, 11, 27),
                       regras_pf=html_pf.RegrasPF(), hoje=date(2026, 11, 27))
    js = re.search(r"<script>(.*?)</script>", g.caminho.read_text(encoding="utf-8"), re.S).group(1)
    for linha in js.splitlines():
        assert linha.count('"') % 2 == 0 or "\\\"" in linha, linha
    node = shutil.which("node")
    if node:
        arq = tmp_path / "pagina.js"
        arq.write_text(js, encoding="utf-8")
        r = subprocess.run([node, "--check", str(arq)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_nome_do_arquivo_com_sublinhado_nao_repete_quem_autorizou():
    aut = {"filename": "PAGAMENTO_AUTORIZADO_BELTRANO_SILVA", "extension": ".pdf",
           "downloadUrl": "http://x/a2"}
    nomes = relatorio.quem_autorizou([aut], {"http://x/a2": "autorizado por Beltrano Silva"})
    assert nomes == ["Beltrano Silva"]


def test_celular_declarado_nos_dados_bancarios_e_chave_inequivoca():
    assert relatorio.chave_dos_dados_bancarios("PIX CELULAR: 62900000001") == "62900000001"


def test_onze_digitos_sem_tipo_ou_sem_forma_de_celular_continuam_recusados():
    assert relatorio.chave_dos_dados_bancarios("PIX: 62900000001") == ""
    assert relatorio.chave_dos_dados_bancarios("PIX CELULAR: 62800000001") == ""


def test_autorizacao_com_chave_nao_inequivoca_diz_o_motivo():
    n = nivel.nivel_da_linha(reg(pago_pela_autorizacao=False))
    assert any("chave Pix dos dados bancários" in m for m in n.motivos)
