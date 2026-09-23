import asyncio
from datetime import date
from decimal import Decimal
import json

import pytest

from app.domain import ConsultaMercado, DadosInvalidosError
from app.services.bcb_mercado_service import BCBMercadoService, normalizar_agregado, periodos_candidatos
from app.services.mensagem_service import _decimal_br, _moeda_br, gerar_mensagem
from app.services.ports import RespostaBCB


# Recorte da resposta oficial de 202606, preservando nomes, IDs e unidades.
REGISTROS = [
    ("13", "Cotas ativas", "Cotas ativas - Automóveis", 5558.34, "mil"),
    ("88", "Valor Médio", "Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Automóveis", 75.95, "R$ mil"),
    ("95", "Prazo Médio", "Prazo médio dos grupos constituídos nos últimos 12 meses - Automóveis", 90.0, "meses"),
    ("81", "Taxa de Administração", "Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Automóveis", 15.16, "%"),
    ("34", "Ativos Contemplados", "Cotas ativas contempladas nos últimos 12 meses - Automóveis", 818.74, "mil"),
    ("14", "Cotas ativas", "Cotas ativas - Motocicletas", 3301.54, "mil"),
    ("89", "Valor Médio", "Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Motocicletas", 20.72, "R$ mil"),
    ("96", "Prazo Médio", "Prazo médio dos grupos constituídos nos últimos 12 meses - Motocicletas", 64.0, "meses"),
    ("82", "Taxa de Administração", "Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Motocicletas", 21.07, "%"),
    ("37", "Ativos Contemplados", "Cotas ativas contempladas nos últimos 12 meses - Motocicletas", 664.99, "mi"),
    ("10", "Cotas ativas", "Cotas ativas - Total", 13376.26, "mil"),
    ("85", "Valor Médio", "Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - TOTAL", 103.42, "R$ mil"),
    ("92", "Prazo Médio", "Prazo médio dos grupos constituídos nos últimos 12 meses - TOTAL", 167.0, "meses"),
    ("78", "Taxa de Administração", "Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - TOTAL", 18.97, "%"),
    ("28", "Ativos Contemplados", "Cotas ativas contempladas no últimos 12 meses - Total", 1855.35, "mil"),
]


def resposta(registros=REGISTROS, periodo=202606):
    value = [
        {"DataBase": periodo, "IdMetrica": codigo, "Grupo": grupo, "Metrica": nome,
         "Valor": valor, "Unidade": unidade}
        for codigo, grupo, nome, valor, unidade in registros
    ]
    return RespostaBCB(json.dumps({"value": value}, ensure_ascii=False), "https://olinda.bcb.gov.br/fixture")


def test_automoveis_mapeamento_unidades_e_mensagem():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("Automóveis", "2026-06"), "2026-06")
    assert resultado.segmento == "Automóveis"
    assert resultado.periodo_referencia == "2026-06"
    assert resultado.cotas_ativas == 5558340
    assert resultado.credito_medio == Decimal("75950.00")
    assert resultado.prazo_medio == Decimal("90.0")
    assert resultado.taxa_administracao_media == Decimal("15.16")
    assert resultado.contemplacoes == 818740
    assert resultado.campos_indisponiveis == []
    assert resultado.data_consulta.utcoffset().total_seconds() == 0
    mensagem = gerar_mensagem(resultado)
    assert "consórcios de automóveis" in mensagem
    assert "2026-06 (2º trimestre)" in mensagem
    assert "5.558.340" in mensagem
    assert "R$ 75.950,00" in mensagem
    assert "90 meses" in mensagem
    assert "15,16%" in mensagem
    assert "818.740" in mensagem
    assert all(texto not in mensagem for texto in ("None", "null", "undefined", "NaN"))


def test_motocicletas_contemplacoes_ambiguas_sao_omitidas():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("Motocicletas"), "2026-06")
    assert resultado.cotas_ativas == 3301540
    assert resultado.credito_medio == Decimal("20720.00")
    assert resultado.contemplacoes is None
    assert resultado.campos_indisponiveis == ["contemplacoes"]
    mensagem = gerar_mensagem(resultado)
    assert "Crédito médio: R$ 20.720,00" in mensagem
    assert "Contemplações" not in mensagem
    assert "Não disponível" not in mensagem


def test_mercado_total_agregado():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("Total"), "2026-06")
    assert resultado.cotas_ativas == 13376260
    assert resultado.credito_medio == Decimal("103420.00")
    assert resultado.prazo_medio == Decimal("167.0")
    assert resultado.taxa_administracao_media == Decimal("18.97")
    assert resultado.contemplacoes == 1855350
    assert "todo o mercado" in gerar_mensagem(resultado)


def test_indicadores_opcionais_ausentes_nao_invalidam_consulta():
    apenas_cotas = [REGISTROS[0]]
    resultado = normalizar_agregado(resposta(apenas_cotas), ConsultaMercado("Automóveis"), "2026-06")
    assert resultado.cotas_ativas == 5558340
    assert resultado.campos_indisponiveis == ["credito_medio", "prazo_medio", "taxa_administracao_media", "contemplacoes"]
    mensagem = gerar_mensagem(resultado)
    assert "Cotas ativas: 5.558.340" in mensagem
    assert "Crédito médio:" not in mensagem
    assert "Prazo médio:" not in mensagem
    assert "Taxa média de administração:" not in mensagem
    assert "Contemplações" not in mensagem


@pytest.mark.parametrize("alteracao", [
    {"Unidade": "unidade"}, {"Valor": -1}, {"Valor": "NaN"},
    {"Metrica": "Outra métrica"}, {"DataBase": 202603},
])
def test_metrica_selecionada_invalida(alteracao):
    item = resposta([REGISTROS[0]])
    payload = json.loads(item.texto)
    payload["value"][0].update(alteracao)
    with pytest.raises(DadosInvalidosError):
        normalizar_agregado(RespostaBCB(json.dumps(payload), item.url), ConsultaMercado("Automóveis"), "2026-06")


def test_resposta_vazia_ou_sem_cotas_ativas():
    assert normalizar_agregado(resposta([]), ConsultaMercado("Automóveis"), "2026-06") is None
    assert normalizar_agregado(resposta([REGISTROS[1]]), ConsultaMercado("Automóveis"), "2026-06") is None


@pytest.mark.parametrize("payload", ["not json", "{}", '{"value":"inválido"}'])
def test_envelope_invalido(payload):
    with pytest.raises(DadosInvalidosError):
        normalizar_agregado(RespostaBCB(payload, "https://olinda.bcb.gov.br/fixture"), ConsultaMercado("Automóveis"), "2026-06")


def test_ultimo_periodo_usa_resposta_bcb():
    class FakeCollector:
        def __init__(self):
            self.consultados = []

        async def extrair_periodo(self, periodo):
            self.consultados.append(periodo)
            return resposta([]) if periodo == "2026-09" else resposta()

    fake = FakeCollector()
    assert periodos_candidatos(date(2026, 9, 23))[:2] == ["2026-09", "2026-06"]
    resultado = asyncio.run(BCBMercadoService(fake, hoje=lambda: date(2026, 9, 23)).consultar(ConsultaMercado("Automóveis")))
    assert fake.consultados == ["2026-09", "2026-06"]
    assert resultado.periodo_referencia == "2026-06"


def test_identidade_consulta_e_formatacao_brasileira():
    consulta = ConsultaMercado("Automóveis", "2026-06")
    assert consulta.hash_consulta == ConsultaMercado("Automóveis", "2026-06").hash_consulta
    assert consulta.hash_consulta != ConsultaMercado("Imóveis", "2026-06").hash_consulta
    assert "administradora" not in consulta.parametros
    assert _moeda_br(Decimal("48754.39")) == "R$ 48.754,39"
    assert _decimal_br(Decimal("18.426")) == "18,43"


@pytest.mark.parametrize("kwargs", [
    {"segmento": ""}, {"segmento": "Inventado"},
    {"segmento": "Automóveis", "periodo": "2026-13"},
])
def test_input_invalido(kwargs):
    with pytest.raises(ValueError):
        ConsultaMercado(**kwargs)
