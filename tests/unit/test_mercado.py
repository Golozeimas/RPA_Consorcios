import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from app.domain import ConsultaMercado, DadosInvalidosError
from app.services.bcb_mercado_service import BCBMercadoService, normalizar_agregado, periodos_candidatos
from app.services.mensagem_service import gerar_mensagem, _moeda_br
from app.services.ports import RespostaBCB


# Seleção mínima de registros reais observados no BCB para DataBase 202606.
REGISTROS = [
    ("9", "Grupos ativos", "Grupos de Consórcio ativos - Total", 16251.0, "unidade"),
    ("10", "Cotas ativas", "Cotas ativas - Total", 13376.26, "mil"),
    ("28", "Ativos Contemplados", "Cotas ativas contempladas no últimos 12 meses - Total", 1855.35, "mil"),
    ("54", "Cotas Comercializadas", "Cotas Comercializadas nos últimos 12 meses - Total", 5723.74, "mil"),
    ("13", "Cotas ativas", "Cotas ativas - Automóveis", 5558.34, "mil"),
    ("34", "Ativos Contemplados", "Cotas ativas contempladas nos últimos 12 meses - Automóveis", 818.74, "mil"),
    ("57", "Cotas Comercializadas", "Cotas comercializadas nos últimos 12 meses - Automóveis", 2048.73, "mil"),
    ("14", "Cotas ativas", "Cotas ativas - Motocicletas", 3301.54, "mil"),
    ("37", "Ativos Contemplados", "Cotas ativas contempladas nos últimos 12 meses - Motocicletas", 664.99, "mi"),
    ("58", "Cotas Comercializadas", "Cotas comercializadas nos últimos 12 meses - Motocicletas", 1519.66, "mil"),
    ("85", "Valor Médio", "Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - TOTAL", 103.42, "R$ mil"),
    ("114", "Cotas Ativas por Estado", "Cotas Ativas por Estado - PI", 241.21, "mil"),
]


def resposta(registros=REGISTROS, periodo=202606):
    value = [
        {"DataBase": periodo, "IdMetrica": codigo, "Grupo": grupo, "Metrica": nome,
         "Valor": valor, "Unidade": unidade}
        for codigo, grupo, nome, valor, unidade in registros
    ]
    return RespostaBCB(json.dumps({"value": value}, ensure_ascii=False), "https://olinda.bcb.gov.br/fixture")


def test_mapeamento_nacional_e_unidade_mil():
    consulta = ConsultaMercado("ADMINISTRADORA INFORMADA", periodo="2026-06")
    resultado = normalizar_agregado(resposta(), consulta, "2026-06")
    assert resultado.administradora is None
    assert resultado.periodo_referencia == "2026-06"
    assert (resultado.grupos_ativos, resultado.cotas_ativas) == (16251, 13376260)
    assert (resultado.cotas_contempladas, resultado.cotas_comercializadas) == (1855350, 5723740)
    assert resultado.creditos_comercializados is None
    assert resultado.abrangencia == "Brasil"
    assert resultado.data_consulta.utcoffset().total_seconds() == 0
    assert resultado.campos_indisponiveis == ["administradora", "creditos_comercializados"]


def test_segmento_automoveis_sem_grupos_do_total():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("ADMIN", segmento="Automóveis"), "2026-06")
    assert resultado.cotas_ativas == 5558340
    assert resultado.cotas_contempladas == 818740
    assert resultado.cotas_comercializadas == 2048730
    assert resultado.grupos_ativos is None
    assert "grupos_ativos" in resultado.campos_indisponiveis


def test_unidade_ambigua_nao_vira_cotas_contempladas():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("ADMIN", segmento="Motocicletas"), "2026-06")
    assert resultado.cotas_ativas == 3301540
    assert resultado.cotas_contempladas is None
    assert resultado.cotas_comercializadas == 1519660
    assert "cotas_contempladas" in resultado.campos_indisponiveis


def test_uf_nao_recebe_metricas_nacionais():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("ADMIN", uf="PI"), "2026-06")
    assert resultado.uf == "PI"
    assert resultado.abrangencia == "UF PI"
    assert resultado.cotas_ativas == 241210
    assert resultado.grupos_ativos is None
    assert resultado.cotas_contempladas is None
    assert resultado.cotas_comercializadas is None


def test_metricas_ausentes_viram_parciais():
    parcial = [item for item in REGISTROS if item[0] != "28"]
    resultado = normalizar_agregado(resposta(parcial), ConsultaMercado("ADMIN"), "2026-06")
    assert resultado.cotas_contempladas is None
    assert "cotas_contempladas" in resultado.campos_indisponiveis


@pytest.mark.parametrize("alteracao", [
    {"Unidade": "R$ mil"}, {"Valor": -1}, {"Valor": "NaN"},
    {"Metrica": "Outra métrica"}, {"DataBase": 202603},
])
def test_metrica_selecionada_invalida_nao_e_aceita(alteracao):
    item = resposta([REGISTROS[1]])
    payload = json.loads(item.texto)
    payload["value"][0].update(alteracao)
    with pytest.raises(DadosInvalidosError):
        normalizar_agregado(RespostaBCB(json.dumps(payload), item.url), ConsultaMercado("ADMIN"), "2026-06")


def test_resposta_vazia_e_sem_metrica_alvo():
    assert normalizar_agregado(resposta([]), ConsultaMercado("ADMIN"), "2026-06") is None
    assert normalizar_agregado(resposta([REGISTROS[0]]), ConsultaMercado("ADMIN"), "2026-06") is None


def test_envelope_json_invalido():
    with pytest.raises(DadosInvalidosError):
        normalizar_agregado(RespostaBCB("not json", "https://olinda.bcb.gov.br/fixture"), ConsultaMercado("ADMIN"), "2026-06")


def test_sondagem_usa_respostas_e_periodo_real():
    class FakeRpa:
        def __init__(self):
            self.consultados = []

        async def extrair_periodo(self, periodo):
            self.consultados.append(periodo)
            return resposta([]) if periodo == "2026-09" else resposta()

    fake = FakeRpa()
    assert periodos_candidatos(date(2026, 9, 23))[:2] == ["2026-09", "2026-06"]
    resultado = asyncio.run(BCBMercadoService(fake, hoje=lambda: date(2026, 9, 23)).consultar(ConsultaMercado("ADMIN")))
    assert fake.consultados[:2] == ["2026-09", "2026-06"]
    assert resultado.periodo_referencia == "2026-06"


def test_mensagem_br_sem_none_e_sem_atribuicao_empresa():
    resultado = normalizar_agregado(resposta(), ConsultaMercado("ADMIN"), "2026-06")
    texto = gerar_mensagem(resultado)
    assert "13.376.260" in texto
    assert "5.723.740" in texto
    assert "últimos 12 meses" in texto
    assert "sem atribuição a uma administradora" in texto
    assert "ADMIN" not in texto
    assert "None" not in texto
    assert "Não disponível" in texto
    assert _moeda_br(Decimal("1500000000.50")) == "R$ 1.500.000.000,50"


@pytest.mark.parametrize("kwargs", [
    {"administradora": ""},
    {"administradora": "ADMIN", "segmento": "Inventado"},
    {"administradora": "ADMIN", "uf": "XX"},
    {"administradora": "ADMIN", "segmento": "Imóveis", "uf": "PI"},
])
def test_input_invalido(kwargs):
    with pytest.raises(ValueError):
        ConsultaMercado(**kwargs)
