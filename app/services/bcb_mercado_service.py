"""Mapeamento do catálogo oficial PANORAMA_DE_CONSORCIOS, versão v1."""

from dataclasses import dataclass
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import logging

from pydantic import ValidationError

from app.domain import ConsultaMercado, ConsorcioResultado, DadosInvalidosError, FONTE
from app.schemas.consulta import MetricaBCB
from app.schemas.consorcios import ConsorcioConsultaResult
from app.services.ports import MAXIMO_REGISTROS_BCB, MetricasBCBGateway, RespostaBCB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricaOficial:
    codigo: str
    nome: str
    grupo: str
    unidade: str


METRICAS_TOTAIS = {
    "grupos_ativos": MetricaOficial("9", "Grupos de Consórcio ativos - Total", "Grupos ativos", "unidade"),
    "cotas_ativas": MetricaOficial("10", "Cotas ativas - Total", "Cotas ativas", "mil"),
    "cotas_contempladas": MetricaOficial("28", "Cotas ativas contempladas no últimos 12 meses - Total", "Ativos Contemplados", "mil"),
    "cotas_comercializadas": MetricaOficial("54", "Cotas Comercializadas nos últimos 12 meses - Total", "Cotas Comercializadas", "mil"),
}

METRICAS_SEGMENTO = {
    "Imóveis": {
        "cotas_ativas": MetricaOficial("11", "Cotas ativas - Imóveis", "Cotas ativas", "mil"),
        "cotas_contempladas": MetricaOficial("31", "Cotas ativas contempladas nos últimos 12 meses - Imóveis", "Ativos Contemplados", "mil"),
        "cotas_comercializadas": MetricaOficial("55", "Cotas comercializadas nos últimos 12 meses - Imóveis", "Cotas Comercializadas", "mil"),
    },
    "Veículos Pesados": {
        "cotas_ativas": MetricaOficial("12", "Cotas ativas - Veículos Pesados", "Cotas ativas", "mil"),
        "cotas_comercializadas": MetricaOficial("56", "Cotas comercializadas nos últimos 12 meses - Veículos Pesados", "Cotas Comercializadas", "mil"),
    },
    "Automóveis": {
        "cotas_ativas": MetricaOficial("13", "Cotas ativas - Automóveis", "Cotas ativas", "mil"),
        "cotas_contempladas": MetricaOficial("34", "Cotas ativas contempladas nos últimos 12 meses - Automóveis", "Ativos Contemplados", "mil"),
        "cotas_comercializadas": MetricaOficial("57", "Cotas comercializadas nos últimos 12 meses - Automóveis", "Cotas Comercializadas", "mil"),
    },
    "Motocicletas": {
        "cotas_ativas": MetricaOficial("14", "Cotas ativas - Motocicletas", "Cotas ativas", "mil"),
        # Id 37 informa unidade 'mi', ambígua; não converter em quantidade.
        "cotas_comercializadas": MetricaOficial("58", "Cotas comercializadas nos últimos 12 meses - Motocicletas", "Cotas Comercializadas", "mil"),
    },
    "Serviços": {
        "cotas_ativas": MetricaOficial("16", "Cotas ativas - Serviços", "Cotas ativas", "mil"),
        "cotas_comercializadas": MetricaOficial("60", "Cotas comercializadas nos últimos 12 meses - Serviços", "Cotas Comercializadas", "mil"),
    },
}

QUANTIDADES = ("grupos_ativos", "cotas_ativas", "cotas_contempladas", "cotas_comercializadas")


def periodos_candidatos(hoje: date) -> list[str]:
    """Trimestres para sondagem; o período escolhido vem sempre da resposta BCB."""
    ano = hoje.year
    mes = ((hoje.month - 1) // 3 + 1) * 3
    periodos = []
    while (ano, mes) >= (2015, 12):
        periodos.append(f"{ano:04d}-{mes:02d}")
        mes -= 3
        if mes == 0:
            ano -= 1
            mes = 12
    return periodos


def _seletores(consulta: ConsultaMercado) -> dict[str, MetricaOficial]:
    if consulta.uf:
        return {"cotas_ativas": MetricaOficial(
            "", f"Cotas Ativas por Estado - {consulta.uf}", "Cotas Ativas por Estado", "mil"
        )}
    if consulta.segmento:
        return METRICAS_SEGMENTO[consulta.segmento]
    return METRICAS_TOTAIS


def _valor_inteiro(registro: MetricaBCB, definicao: MetricaOficial) -> int:
    if (registro.Metrica, registro.Grupo, registro.Unidade) != (
        definicao.nome, definicao.grupo, definicao.unidade
    ):
        raise ValueError("Identidade ou unidade da métrica mudou no BCB")
    quantidade = registro.Valor * (Decimal("1000") if definicao.unidade == "mil" else Decimal("1"))
    if quantidade != quantidade.to_integral_value():
        raise ValueError("Quantidade fracionária após conversão da unidade")
    return int(quantidade)


def normalizar_agregado(
    resposta: RespostaBCB, consulta: ConsultaMercado, periodo_sondado: str
) -> ConsorcioResultado | None:
    try:
        payload = json.loads(resposta.texto, parse_float=Decimal)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ValueError("Envelope OData inválido")
        if payload.get("@odata.nextLink") or payload.get("odata.nextLink"):
            raise ValueError("Resposta paginada")
        registros = payload["value"]
        if len(registros) >= MAXIMO_REGISTROS_BCB:
            raise ValueError("Resposta possivelmente truncada")
        if not registros:
            return None
        por_codigo: dict[str, dict[str, object]] = {}
        por_nome: dict[str, dict[str, object]] = {}
        for registro in registros:
            if not isinstance(registro, dict) or not isinstance(registro.get("IdMetrica"), str):
                raise ValueError("Registro sem IdMetrica textual")
            if registro.get("DataBase") != int(periodo_sondado.replace("-", "")):
                raise ValueError("DataBase divergente")
            codigo = registro["IdMetrica"].strip()
            if codigo in por_codigo:
                raise ValueError("IdMetrica duplicado")
            por_codigo[codigo] = registro
            nome = registro.get("Metrica")
            if isinstance(nome, str):
                por_nome[nome.strip()] = registro
        seletores = _seletores(consulta)
        quantidades: dict[str, int | None] = dict.fromkeys(QUANTIDADES)
        for campo, definicao in seletores.items():
            bruto = por_nome.get(definicao.nome) if consulta.uf else por_codigo.get(definicao.codigo)
            if bruto is None:
                continue
            validado = MetricaBCB.model_validate(bruto)
            if consulta.uf and not 99 <= int(validado.IdMetrica) <= 125:
                raise ValueError("Métrica de UF fora do catálogo verificado")
            quantidades[campo] = _valor_inteiro(validado, definicao)
        if quantidades["cotas_ativas"] is None:
            return None
        data_base = next(iter(registros))["DataBase"]
        periodo_real = f"{data_base // 100:04d}-{data_base % 100:02d}"
        indisponiveis = ["administradora", "creditos_comercializados"]
        indisponiveis.extend(campo for campo in QUANTIDADES if quantidades[campo] is None)
        validado = ConsorcioConsultaResult(
            administradora=None, periodo_referencia=periodo_real,
            **quantidades, creditos_comercializados=None,
            segmento=consulta.segmento, uf=consulta.uf,
            abrangencia=f"UF {consulta.uf}" if consulta.uf else "Brasil",
            data_consulta=datetime.now(timezone.utc), fonte=FONTE,
            source_url=resposta.url, campos_indisponiveis=indisponiveis,
        )
        return ConsorcioResultado(**validado.model_dump())
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise DadosInvalidosError("O BCB retornou métricas incompletas ou inválidas.") from exc


class BCBMercadoService:
    def __init__(self, collector: MetricasBCBGateway, hoje: Callable[[], date] | None = None) -> None:
        self.collector = collector
        self.hoje = hoje or (lambda: datetime.now(timezone.utc).date())

    async def consultar(self, consulta: ConsultaMercado) -> ConsorcioResultado | None:
        hoje = self.hoje()
        periodos = [consulta.periodo] if consulta.periodo else periodos_candidatos(hoje)
        for periodo in periodos:
            resposta = await self.collector.extrair_periodo(periodo)
            resultado = normalizar_agregado(resposta, consulta, periodo)
            if resultado is not None:
                logger.info("bcb_metricas_normalizadas periodo=%s campos=%s", resultado.periodo_referencia, len(QUANTIDADES) - len([c for c in QUANTIDADES if c in resultado.campos_indisponiveis]))
                return resultado
        return None
