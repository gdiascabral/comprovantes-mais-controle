"""Leitura por IA de anexo escrito à mão (spec de 19/11/2026, parte 3).
Sem rede: o cliente da API é um dublê. Valores e nomes fictícios."""
import json
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from pagamentos_dia import leitura_ia as li


def _leitura(**k):
    base = {"tipo_papel": "pedido_de_balcao", "legivel": True, "total": "5.864,50",
            "total_por_extenso": "", "ordem_de_compra": "6803", "numero_documento": "",
            "data": "18/08/2026", "quadra": "26A", "lote": "10", "itens": [],
            "cartao_valor": "", "cartao_nome": "", "duvidas": []}
    base.update(k)
    return base


class ClienteFalso:
    def __init__(self, texto, parada="end_turn"):
        self.pedidos = []
        resposta = NS(stop_reason=parada, usage=NS(input_tokens=1500, output_tokens=400),
                      content=[NS(type="thinking", thinking=""), NS(type="text", text=texto)])
        self.beta = NS(messages=NS(create=lambda **k: self.pedidos.append(k) or resposta))


# ------------------------------------------------------------- dinheiro
@pytest.mark.parametrize("texto,valor", [
    ("1.234,56", "1234.56"), ("#4.700#", "4700.00"), ("4.700", "4700.00"),
    ("4700,00", "4700.00"), ("R$ 52,30", "52.30"), ("52.30", "52.30"), ("300", "300.00"),
    ("1.150.000,00", "1150000.00")])
def test_dinheiro(texto, valor):
    assert li.dinheiro(texto) == D(valor)


def test_dinheiro_sem_numero_e_none():
    assert li.dinheiro("") is None and li.dinheiro("ilegível") is None


@pytest.mark.parametrize("texto,valor", [
    ("quatro mil e setecentos reais", "4700.00"),
    ("Quatro mil e setecentos reais.", "4700.00"),
    ("trezentos reais", "300.00"),
    ("três mil e cem reais", "3100.00"),
    ("cinco mil oitocentos e sessenta e quatro reais e cinquenta centavos", "5864.50"),
    ("cento e vinte e três reais", "123.00"),
    ("mil reais", "1000.00"),
    ("um milhão e duzentos mil reais", "1200000.00"),
    ("cinquenta centavos", "0.50")])
def test_extenso(texto, valor):
    assert li.extenso_para_valor(texto) == D(valor)


def test_extenso_com_palavra_estranha_e_none():
    assert li.extenso_para_valor("quatro mil e sete reais pagos") is None
    assert li.extenso_para_valor("") is None


# ------------------------------------------------------------- conferência
def test_total_e_segunda_prova_batem():
    c = li.conferir(_leitura(cartao_valor="5.864,50"), 5864.50)
    assert c.estado == li.BATE and c.provas == ["comprovante do cartão"]


def test_quatro_lido_como_nove_e_desmentido_pelo_cartao():
    # O caso medido em 19/11/2026.
    c = li.conferir(_leitura(total="5.869,50", cartao_valor="5.864,50"), 5864.50)
    assert c.estado == li.DIVERGE
    assert "total lido R$ 5869.50 × lançamento R$ 5864.50" in c.motivos


def test_total_sem_segunda_prova():
    c = li.conferir(_leitura(), 5864.50)
    assert c.estado == li.SEM_SEGUNDA_PROVA
    assert c.motivos == ["valor lido por IA, sem segunda prova no papel"]


def test_soma_dos_itens_e_extenso_provam():
    itens = [{"descricao": "terra", "quantidade": "250", "unitario": "15,00", "total": "3.750,00"},
             {"descricao": "retro", "quantidade": "2,3", "unitario": "", "total": "700,00"},
             {"descricao": "caminhao", "quantidade": "2", "unitario": "", "total": "250,00"}]
    c = li.conferir(_leitura(total="4.700,00", itens=itens,
                             total_por_extenso="quatro mil e setecentos reais"), 4700)
    assert c.estado == li.BATE
    assert c.provas == ["valor por extenso", "soma dos itens"]


def test_item_ilegivel_nao_conta_como_soma():
    itens = [{"descricao": "a", "quantidade": "", "unitario": "", "total": "100,00"},
             {"descricao": "b", "quantidade": "", "unitario": "", "total": ""}]
    c = li.conferir(_leitura(total="100,00", itens=itens), 100)
    assert c.estado == li.SEM_SEGUNDA_PROVA


def test_prova_que_diz_outro_valor_e_divergencia():
    c = li.conferir(_leitura(total="300,00", total_por_extenso="trezentos e cinquenta reais"), 300)
    assert c.estado == li.DIVERGE


def _item(total):
    return {"descricao": "x", "quantidade": "1", "unitario": total, "total": total}


def test_total_bate_mas_soma_do_papel_nao_fecha_com_outra_prova():
    # Caso real (medição 25/11): itens somam 5.132,00 e o total escrito é 5.120,00.
    itens = [_item("3.000,00"), _item("2.132,00")]
    c = li.conferir(_leitura(total="5.120,00", itens=itens,
                             total_por_extenso="cinco mil cento e vinte reais"), 5120)
    assert c.estado == li.TOTAL_BATE_SOMA_NAO_FECHA
    assert c.provas == ["valor por extenso"]
    assert any("soma dos itens R$ 5132.00" in m for m in c.motivos)


def test_total_bate_soma_nao_fecha_cartao_concorda():
    # Caso real: itens 5.864,00 e total escrito 5.864,50 (o do lançamento).
    c = li.conferir(_leitura(total="5.864,50", itens=[_item("5.864,00")],
                             cartao_valor="5.864,50"), 5864.50)
    assert c.estado == li.TOTAL_BATE_SOMA_NAO_FECHA and c.provas == ["comprovante do cartão"]


def test_total_bate_soma_nao_fecha_sem_outra_prova_e_sem_segunda_prova():
    c = li.conferir(_leitura(total="5.120,00", itens=[_item("5.132,00")]), 5120)
    assert c.estado == li.SEM_SEGUNDA_PROVA
    assert any("soma dos itens" in m and "não fecha" in m for m in c.motivos)


def test_total_diferente_continua_diverge_mesmo_com_soma_batendo():
    c = li.conferir(_leitura(total="5.130,00", itens=[_item("5.120,00")]), 5120)
    assert c.estado == li.DIVERGE


def test_extenso_contra_o_lancamento_e_diverge_mesmo_com_total_batendo():
    c = li.conferir(_leitura(total="5.120,00", itens=[_item("5.132,00")],
                             total_por_extenso="cinco mil e duzentos reais"), 5120)
    assert c.estado == li.DIVERGE


def test_sem_total_e_so_a_soma_dizendo_outro_valor_e_diverge():
    c = li.conferir(_leitura(total="", itens=[_item("5.132,00")]), 5120)
    assert c.estado == li.DIVERGE


def test_ilegivel():
    assert li.conferir(_leitura(legivel=False), 10).estado == li.ILEGIVEL
    assert li.conferir(_leitura(total=""), 10).estado == li.ILEGIVEL


def test_sem_total_mas_com_prova_nao_e_bate():
    c = li.conferir(_leitura(total="", cartao_valor="10,00"), 10)
    assert c.estado == li.SEM_SEGUNDA_PROVA


# ------------------------------------------------------------- pedido à API
def test_pedido_leva_arquivo_esquema_e_reserva_por_recusa():
    cliente = ClienteFalso(json.dumps(_leitura()))
    leitura, uso = li.pedir_leitura(cliente, b"\xff\xd8 foto", "image/jpeg")
    (pedido,) = cliente.pedidos
    assert pedido["model"] == li.MODELO and pedido["fallbacks"] == "default"
    assert pedido["output_config"]["format"]["schema"] is li.ESQUEMA
    bloco = pedido["messages"][0]["content"][0]
    assert bloco["type"] == "image" and bloco["source"]["media_type"] == "image/jpeg"
    assert leitura["total"] == "5.864,50" and (uso.entrada, uso.saida) == (1500, 400)


def test_pdf_vai_como_documento():
    cliente = ClienteFalso(json.dumps(_leitura()))
    li.pedir_leitura(cliente, b"%PDF-1.4", "application/pdf")
    assert cliente.pedidos[0]["messages"][0]["content"][0]["type"] == "document"


@pytest.mark.parametrize("texto,parada", [
    ("{}", "end_turn"), ("não é json", "end_turn"), (json.dumps(_leitura()), "refusal"),
    (json.dumps(_leitura()), "max_tokens"), (json.dumps(_leitura(tipo_papel="foto")), "end_turn")])
def test_resposta_ruim_levanta(texto, parada):
    with pytest.raises(li.LeituraFalhou):
        li.pedir_leitura(ClienteFalso(texto, parada), b"x", "image/png")


def test_tipo_de_arquivo_nao_aceito_nao_chama_a_api():
    cliente = ClienteFalso(json.dumps(_leitura()))
    with pytest.raises(li.LeituraFalhou):
        li.pedir_leitura(cliente, b"x", li.media_type_do_nome("planilha.xlsx"))
    assert cliente.pedidos == []


def test_o_esquema_so_usa_o_que_a_api_aceita():
    def objetos(no):
        if isinstance(no, dict):
            if no.get("type") == "object":
                yield no
            for v in no.values():
                yield from objetos(v)
        elif isinstance(no, list):
            for v in no:
                yield from objetos(v)
    for o in objetos(li.ESQUEMA):
        assert o["additionalProperties"] is False
        assert sorted(o["required"]) == sorted(o["properties"])
    texto = json.dumps(li.ESQUEMA)
    for proibido in ("minimum", "maximum", "minLength", "maxLength", "pattern"):
        assert proibido not in texto


# ------------------------------------------------------------- cache
def test_cache_guarda_e_le(tmp_path):
    c = li.CacheLeituras(tmp_path / "leituras_ia.json")
    k = c.chave("a1", 300, "2026-11-01T10:00:00")
    assert c.obter(k) is None
    c.guardar(k, _leitura(), modelo=li.MODELO, quando="2026-11-20 10:00")
    assert li.CacheLeituras(tmp_path / "leituras_ia.json").obter(k)["total"] == "5.864,50"
    assert c.obter(c.chave("a1", 301, "2026-11-01T10:00:00")) is None   # anexo trocado


def test_cache_estragado_recomeca_e_guarda_o_arquivo_ruim(tmp_path):
    p = tmp_path / "leituras_ia.json"
    p.write_text("{quebrado", encoding="utf-8")
    assert li.CacheLeituras(p).obter("x") is None
    assert (tmp_path / "leituras_ia.estragado").exists()
