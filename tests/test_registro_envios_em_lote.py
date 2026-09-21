# -*- coding: utf-8 -*-
"""A pergunta "isto já foi mandado?" em LOTE, sem rede.

A janela "Confirmar o que entra" do passo 2 pergunta isso de CADA linha antes
de a pessoa conferir. Um por um (`envio_de`/`envio_da_referencia`) são uma ou
duas idas ao Supabase por linha, e com 100–300 lançamentos isso vira centenas
de ida-e-volta a cada "Gerar planilha". `envios_em_lote` responde a mesma
pergunta em poucas consultas `in.(…)`, e o que se prova aqui é que a resposta
é a MESMA do um-a-um, caso a caso — inclusive nos dois que custam dinheiro: a
remessa descartada (devolve o direito de reenviar) e o item mais recente da
mesma chave.

O dublê do banco APLICA os filtros que recebe (`eq`, `in`, o estado vivo no
relacionamento, `order` e `limit`), em vez de devolver uma resposta fixa: um
dublê que ignora o filtro faria o lote e o um-a-um concordarem por acidente.

Nenhum dado real: códigos de barras, ids e convênios são inventados.
"""
import pytest

from nuvem import registro


def _valores_do_in(texto: str) -> set:
    return set(texto[len("in.("):-1].split(","))


class _BancoFalso:
    """A tabela `remessa_item` com o relacionamento `remessa` embutido.

    Aplica o que o PostgREST aplica: sem `!inner`, o filtro do relacionamento
    NÃO omite a linha — devolve `remessa: null`; com `remessa!inner(...)` nas
    colunas, a linha cujo relacionamento não casa SAI do resultado, e isso
    acontece antes de `order` e `limit`."""

    def __init__(self, itens):
        self.itens = itens
        self.filtros = []
        self.colunas = []

    def ler(self, tabela, _token, *, colunas="*", filtro=""):
        assert tabela == "remessa_item"
        self.filtros.append(filtro)
        self.colunas.append(colunas)
        linhas = [dict(i, remessa=dict(i["remessa"]) if i.get("remessa") else None)
                  for i in self.itens]
        limite, ordem = None, None
        for parte in filtro.split("&"):
            chave, _, valor = parte.partition("=")
            if chave == "remessa.estado":
                vivos = _valores_do_in(valor)
                for linha in linhas:
                    if linha["remessa"] and linha["remessa"]["estado"] not in vivos:
                        linha["remessa"] = None
            elif chave == "order":
                assert valor == "id.desc"
                ordem = valor
            elif chave == "limit":
                limite = int(valor)
            elif valor.startswith("eq."):
                linhas = [l for l in linhas if str(l.get(chave)) == valor[3:]]
            elif valor.startswith("in."):
                alvo = _valores_do_in(valor)
                linhas = [l for l in linhas if str(l.get(chave)) in alvo]
            elif chave:
                raise AssertionError(f"filtro que o dublê não conhece: {parte}")
        if "remessa!inner(" in colunas:
            linhas = [l for l in linhas if l["remessa"]]
        if ordem:
            linhas.sort(key=lambda l: l["id"], reverse=True)
        return linhas[:limite] if limite else linhas


def _remessa(nsa, estado="gerado"):
    return {"nsa": nsa, "convenio": "123456", "estado": estado,
            "gerado_em": "2026-09-10T10:00:00+00:00"}


BARRAS_VIVO = "3" * 44
BARRAS_DESCARTADO = "4" * 44
BARRAS_DUAS_VEZES = "5" * 44
BARRAS_NUNCA = "6" * 44

ITENS = [
    {"id": 1, "identificador": BARRAS_VIVO, "referencia": "L1",
     "seu_numero": "260910-0001", "remessa": _remessa(7),
     "retorno_estado": "rejeitado"},
    {"id": 2, "identificador": BARRAS_DESCARTADO, "referencia": "L2",
     "seu_numero": "260910-0002", "remessa": _remessa(8, "descartado")},
    # A mesma chave em duas remessas: a antiga descartada e a nova viva...
    {"id": 3, "identificador": BARRAS_DUAS_VEZES, "referencia": "L3",
     "seu_numero": "260910-0003", "remessa": _remessa(9, "descartado")},
    {"id": 4, "identificador": BARRAS_DUAS_VEZES, "referencia": "L3",
     "seu_numero": "260911-0001", "remessa": _remessa(10, "enviado")},
    # ...e o contrário: a antiga VIVA e a mais recente DESCARTADA. O envio
    # que vale é o da viva: descartar a nova não desfaz a antiga, que saiu.
    {"id": 5, "identificador": "7" * 44, "referencia": "L5",
     "seu_numero": "260910-0005", "remessa": _remessa(11)},
    {"id": 6, "identificador": "7" * 44, "referencia": "L5",
     "seu_numero": "260911-0002", "remessa": _remessa(12, "descartado")},
    # Item sem remessa nenhuma (relacionamento vazio).
    {"id": 7, "identificador": "8" * 44, "referencia": "L7",
     "seu_numero": "260910-0007", "remessa": None},
]


@pytest.fixture
def banco(monkeypatch):
    b = _BancoFalso(ITENS)
    monkeypatch.setattr(registro.rest, "ler", b.ler)
    return b


def _resumo(resposta):
    """(nsa, estado) do que a pergunta achou, ou None."""
    if not resposta:
        return None
    envio = resposta[0]
    return envio.nsa, envio.estado


def test_o_lote_responde_o_mesmo_que_o_um_a_um(banco):
    reg = registro.Registro("tok")
    barras = [BARRAS_VIVO, BARRAS_DESCARTADO, BARRAS_DUAS_VEZES, "7" * 44,
              "8" * 44, BARRAS_NUNCA]
    refs = ["L1", "L2", "L3", "L5", "L7", "L-NUNCA"]

    um_a_um_barras = {b: _resumo(reg.envio_de(b)) for b in barras}
    um_a_um_refs = {r: _resumo(reg.envio_da_referencia(r)) for r in refs}
    por_barras, por_ref = reg.envios_em_lote(barras, refs)

    assert {b: _resumo(v) for b, v in por_barras.items()} == um_a_um_barras
    assert {r: _resumo(v) for r, v in por_ref.items()} == um_a_um_refs
    # E o que isso quer dizer, escrito à mão — sem isto os dois lados
    # poderiam concordar num erro comum.
    assert um_a_um_barras == {
        BARRAS_VIVO: (7, "gerado"),
        BARRAS_DESCARTADO: None,
        BARRAS_DUAS_VEZES: (10, "enviado"),
        "7" * 44: (11, "gerado"),
        "8" * 44: None,
        BARRAS_NUNCA: None,
    }


def test_envio_novo_descartado_nao_esconde_o_antigo_vivo(banco):
    """O item de maior id era escolhido ANTES de descartar `remessa: null`: um
    envio mais novo numa remessa DESCARTADA escondia o mais antigo numa VIVA,
    e o pagamento voltava marcável — em dobro na geração seguinte, inclusive
    no "Gerar remessa". Com `remessa!inner` o filtro de estado vale na LINHA."""
    reg = registro.Registro("tok")
    assert _resumo(reg.envio_de("7" * 44)) == (11, "gerado")
    assert _resumo(reg.envio_da_referencia("L5")) == (11, "gerado")
    por_barras, por_ref = reg.envios_em_lote(["7" * 44], ["L5"])
    assert _resumo(por_barras["7" * 44]) == (11, "gerado")
    assert _resumo(por_ref["L5"]) == (11, "gerado")


def test_as_duas_consultas_pedem_o_relacionamento_inner(banco):
    reg = registro.Registro("tok")
    reg.envio_de(BARRAS_VIVO)
    reg.envios_em_lote([BARRAS_VIVO], ["L1"])
    assert banco.colunas and all("remessa!inner(" in c for c in banco.colunas)
    assert "order=id.desc&limit=1" in banco.filtros[0], \
        "o um-a-um continua pegando só o mais recente (vivo)"


def test_bloco_que_bate_no_teto_do_banco_levanta(monkeypatch):
    """O PostgREST corta a resposta em `max_rows` (1000) sem dizer nada: um
    bloco que volta com 1000 linhas pode ter perdido a que importa. Levantar
    faz quem chama cair no um-a-um, em vez de responder "não saiu"."""
    muitas = [{"id": i, "identificador": "3" * 44, "referencia": "L1",
               "seu_numero": f"260910-{i:04d}", "remessa": _remessa(7)}
              for i in range(registro.LINHAS_MAXIMAS_POR_CONSULTA)]
    monkeypatch.setattr(registro.rest, "ler", _BancoFalso(muitas).ler)
    with pytest.raises(registro.LoteTruncado):
        registro.Registro("tok").envios_em_lote(["3" * 44], [])


def test_o_envio_traz_o_estado_da_remessa_e_o_retorno_do_item(banco):
    """Quem confere precisa saber se o que "já saiu" foi REJEITADO: é esse o
    pagamento que tem de sair de novo. A mesma consulta traz os dois."""
    reg = registro.Registro("tok")
    envio, _ = reg.envio_da_referencia("L1")
    assert (envio.estado, envio.retorno_estado) == ("gerado", "rejeitado")
    por_barras, _por_ref = reg.envios_em_lote([BARRAS_VIVO], [])
    envio, _ = por_barras[BARRAS_VIVO]
    assert (envio.estado, envio.retorno_estado) == ("gerado", "rejeitado")
    assert all("retorno_estado" in c for c in banco.colunas)


def test_o_lote_devolve_o_envio_no_formato_do_um_a_um(banco):
    por_barras, _por_ref = registro.Registro("tok").envios_em_lote(
        [BARRAS_VIVO], [])
    envio, item = por_barras[BARRAS_VIVO]
    assert item is None
    assert (envio.nsa, envio.convenio, envio.seu_numero) \
        == (7, "123456", "260910-0001")
    assert envio.gerado_em.year == 2026


def test_o_lote_pede_so_estado_vivo_e_do_mais_recente(banco):
    registro.Registro("tok").envios_em_lote([BARRAS_VIVO], ["L1"])
    assert banco.filtros, "tinha de ter perguntado"
    for filtro in banco.filtros:
        assert "=in.(" in filtro
        assert "order=id.desc" in filtro
        for estado in registro.ESTADOS_VIVOS:
            assert estado in filtro.split("remessa.estado=in.(")[1]


def test_cem_linhas_custam_poucas_consultas(banco):
    barras = [f"{i:044d}" for i in range(100)]
    refs = [f"L{i:06d}" for i in range(100)]
    por_barras, por_ref = registro.Registro("tok").envios_em_lote(barras, refs)
    assert len(por_barras) == 100 and len(por_ref) == 100, \
        "toda chave perguntada volta respondida, achada ou não"
    assert len(banco.filtros) <= 6, banco.filtros
    for filtro in banco.filtros:
        assert len(filtro) <= registro.TAMANHO_DO_FILTRO_EM_LOTE + 200, \
            "URL comprida demais é recusada por proxy antes de chegar ao banco"


def test_chave_que_nao_cabe_no_filtro_nao_e_respondida(banco):
    """Vírgula, parêntese, espaço ou `&` dentro de um `in.(…)` não seriam uma
    chave não achada: seriam OUTRO filtro. Essas ficam de fora da resposta —
    e quem chama pergunta uma por uma, em vez de ouvir "não saiu"."""
    estranhas = ["12,34", "(9)", "a b", "x&y=1", ""]
    por_barras, por_ref = registro.Registro("tok").envios_em_lote(
        estranhas, estranhas)
    assert por_barras == {} and por_ref == {}
    assert banco.filtros == []


def test_lista_vazia_nao_pergunta_nada(banco):
    assert registro.Registro("tok").envios_em_lote([], []) == ({}, {})
    assert banco.filtros == []


def test_o_espelhado_pergunta_a_nuvem():
    pedidos = []

    class Nuvem:
        def envios_em_lote(self, identificadores, referencias):
            pedidos.append((list(identificadores), list(referencias)))
            return {"b": None}, {"r": None}

    class LocalSemLote:
        def __getattr__(self, nome):
            raise AssertionError(f"o espelho local não responde isto ({nome})")

    esp = registro.Espelhado(Nuvem(), LocalSemLote())
    assert esp.envios_em_lote(["b"], ["r"]) == ({"b": None}, {"r": None})
    assert pedidos == [(["b"], ["r"])]
