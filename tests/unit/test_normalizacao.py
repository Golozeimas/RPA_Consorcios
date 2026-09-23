from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from app.domain import Consulta, DadosInvalidosError
from app.schemas.consulta import ConsultaInput
from app.services.bcb_service import normalizar_resultado


def registro(**campos):
    return {"DataBase": 202512, "IdMetrica": "10", "Grupo": "Cotas ativas",
            "Metrica": " Cotas  ativas - Total ", "Valor": 12821.11, "Unidade": " mil ", **campos}


def test_normaliza_valor_texto_periodo_e_unidade():
    resultado = normalizar_resultado(json.dumps({"value": [registro()]}), Consulta("2025-12"))
    assert resultado.valor == Decimal("12821.11")
    assert resultado.metrica == "Cotas ativas - Total"
    assert resultado.unidade == "mil"
    assert resultado.consultado_em.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("value", [[], [registro(IdMetrica="11")]])
def test_sem_resultado(value):
    assert normalizar_resultado(json.dumps({"value": value}), Consulta("2025-12")) is None


@pytest.mark.parametrize("campos", [
    {"Valor": None}, {"Valor": "abc"}, {"Valor": -1}, {"Valor": "NaN"},
    {"Valor": True}, {"Valor": "Infinity"}, {"DataBase": 202511},
    {"DataBase": 202512.5}, {"Unidade": "unidade"}, {"Metrica": "Outra métrica"},
    {"Grupo": " "}, {"IdMetrica": None},
])
def test_rejeita_dados_invalidos(campos):
    with pytest.raises(DadosInvalidosError):
        normalizar_resultado(json.dumps({"value": [registro(**campos)]}), Consulta("2025-12"))


@pytest.mark.parametrize("payload", [
    {}, {"value": None}, {"value": [{}]}, {"value": [registro(), registro()]},
    {"value": [], "@odata.nextLink": "https://example.invalid"},
    {"value": [registro()] * 201},
])
def test_rejeita_envelope_incompleto_ou_duplicado(payload):
    with pytest.raises(DadosInvalidosError):
        normalizar_resultado(json.dumps(payload), Consulta("2025-12"))


def test_rejeita_json_invalido():
    with pytest.raises(DadosInvalidosError):
        normalizar_resultado("<html>Erro</html>", Consulta("2025-12"))


def test_campo_obrigatorio_ausente():
    item = registro()
    del item["Valor"]
    with pytest.raises(DadosInvalidosError):
        normalizar_resultado(json.dumps({"value": [item]}), Consulta("2025-12"))


@pytest.mark.parametrize("periodo", ["", "2025-13", "2025-00", "202512", "2025-1", "0000-01"])
def test_input_rejeita_periodo_invalido(periodo):
    with pytest.raises(ValidationError):
        ConsultaInput(periodo=periodo)


def test_hash_deterministico_normalizado_e_sensivel_ao_periodo():
    a = Consulta(ConsultaInput(periodo=" 2025-12 ").periodo)
    assert a.hash_consulta == Consulta("2025-12").hash_consulta
    assert a.hash_consulta != Consulta("2025-11").hash_consulta
    assert len(a.hash_consulta) == 64
