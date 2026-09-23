"""Panorama agregado: IDs, nomes e unidades conferidos no catálogo oficial v1."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import logging

from pydantic import ValidationError

from app.domain import ConsultaMercado, DadosInvalidosError, FONTE, PanoramaResultado
from app.schemas.consorcios import PanoramaConsultaResult
from app.schemas.consulta import MetricaBCB
from app.services.ports import MAXIMO_REGISTROS_BCB, MetricasBCBGateway, RespostaBCB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricaOficial:
    nome: str
    grupo: str
    unidade: str


# CadastroDeMetricas() e Metricas(DataBase=@DataBase), conferidos em 23/09/2026.
# Crédito, prazo e taxa descrevem grupos constituídos, não contratos individuais.
CATALOGO: dict[str, MetricaOficial] = {
    "10": MetricaOficial("Cotas ativas - Total", "Cotas ativas", "mil"),
    "11": MetricaOficial("Cotas ativas - Imóveis", "Cotas ativas", "mil"),
    "12": MetricaOficial("Cotas ativas - Veículos Pesados", "Cotas ativas", "mil"),
    "13": MetricaOficial("Cotas ativas - Automóveis", "Cotas ativas", "mil"),
    "14": MetricaOficial("Cotas ativas - Motocicletas", "Cotas ativas", "mil"),
    "15": MetricaOficial("Cotas Ativas - Outros bens móveis duráveis (eletroeletrônicos, eletrodomésticos, móveis e outros)", "Cotas ativas", "mil"),
    "16": MetricaOficial("Cotas ativas - Serviços", "Cotas ativas", "mil"),
    "28": MetricaOficial("Cotas ativas contempladas no últimos 12 meses - Total", "Ativos Contemplados", "mil"),
    "31": MetricaOficial("Cotas ativas contempladas nos últimos 12 meses - Imóveis", "Ativos Contemplados", "mil"),
    "34": MetricaOficial("Cotas ativas contempladas nos últimos 12 meses - Automóveis", "Ativos Contemplados", "mil"),
    # 37 (Motocicletas) informa unidade 'mi'; não converter essa unidade ambígua.
    # 40 agrega Outros Bens Móveis e Serviços: não atribuir a um segmento isolado.
    "78": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - TOTAL", "Taxa de Administração", "%"),
    "79": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Imóveis", "Taxa de Administração", "%"),
    "80": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Veículos Pesados", "Taxa de Administração", "%"),
    "81": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Automóveis", "Taxa de Administração", "%"),
    "82": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Motocicletas", "Taxa de Administração", "%"),
    "83": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Outros Bens Móveis", "Taxa de Administração", "%"),
    "84": MetricaOficial("Taxa Média Adm. dos grupos constituídos nos últimos 12 meses - Serviços", "Taxa de Administração", "%"),
    "85": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - TOTAL", "Valor Médio", "R$ mil"),
    "86": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Imóveis", "Valor Médio", "R$ mil"),
    "87": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Veículos Pesados", "Valor Médio", "R$ mil"),
    "88": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Automóveis", "Valor Médio", "R$ mil"),
    "89": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Motocicletas", "Valor Médio", "R$ mil"),
    "90": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Outros bens móveis duráveis (eletroeletrônicos, eletrodomésticos, móveis e outros)", "Valor Médio", "R$ mil"),
    "91": MetricaOficial("Valor Médio dos Créditos dos grupos constituídos nos últimos 12 meses - Serviços", "Valor Médio", "R$ mil"),
    "92": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - TOTAL", "Prazo Médio", "meses"),
    "93": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - Imóveis", "Prazo Médio", "meses"),
    "94": MetricaOficial("Prazo médio dos grupos constiotuídos no ano - Veículos Pesados", "Prazo Médio", "meses"),
    "95": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - Automóveis", "Prazo Médio", "meses"),
    "96": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - Motocicletas", "Prazo Médio", "meses"),
    "97": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - Outros bens móveis duráveis (eletroeletrônicos, eletrodomésticos, móveis e outros)", "Prazo Médio", "meses"),
    "98": MetricaOficial("Prazo médio dos grupos constituídos nos últimos 12 meses - Serviços", "Prazo Médio", "meses"),
}

METRICAS_POR_SEGMENTO: dict[str, dict[str, str]] = {
    "Total": {"cotas_ativas": "10", "credito_medio": "85", "prazo_medio": "92", "taxa_administracao_media": "78", "contemplacoes": "28"},
    "Imóveis": {"cotas_ativas": "11", "credito_medio": "86", "prazo_medio": "93", "taxa_administracao_media": "79", "contemplacoes": "31"},
    "Veículos Pesados": {"cotas_ativas": "12", "credito_medio": "87", "prazo_medio": "94", "taxa_administracao_media": "80"},
    "Automóveis": {"cotas_ativas": "13", "credito_medio": "88", "prazo_medio": "95", "taxa_administracao_media": "81", "contemplacoes": "34"},
    "Motocicletas": {"cotas_ativas": "14", "credito_medio": "89", "prazo_medio": "96", "taxa_administracao_media": "82"},
    "Outros bens móveis duráveis": {"cotas_ativas": "15", "credito_medio": "90", "prazo_medio": "97", "taxa_administracao_media": "83"},
    "Serviços": {"cotas_ativas": "16", "credito_medio": "91", "prazo_medio": "98", "taxa_administracao_media": "84"},
}

CAMPOS = ("cotas_ativas", "credito_medio", "prazo_medio", "taxa_administracao_media", "contemplacoes")


def periodos_candidatos(hoje: date) -> list[str]:
    """Sondar trimestres; o período exibido vem da DataBase retornada pelo BCB."""
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


def _valor_normalizado(registro: MetricaBCB, codigo: str, campo: str) -> int | Decimal:
    esperado = CATALOGO[codigo]
    if (registro.IdMetrica, registro.Metrica, registro.Grupo, registro.Unidade) != (
        codigo, esperado.nome, esperado.grupo, esperado.unidade
    ):
        raise ValueError("Identidade ou unidade de métrica mudou no BCB")
    valor = registro.Valor * (Decimal("1000") if esperado.unidade in {"mil", "R$ mil"} else Decimal("1"))
    if campo in {"cotas_ativas", "contemplacoes"}:
        if valor != valor.to_integral_value():
            raise ValueError("Quantidade fracionária após conversão da unidade")
        return int(valor)
    return valor


def normalizar_agregado(
    resposta: RespostaBCB, consulta: ConsultaMercado, periodo_sondado: str
) -> PanoramaResultado | None:
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
        data_base = int(periodo_sondado.replace("-", ""))
        for registro in registros:
            if not isinstance(registro, dict) or not isinstance(registro.get("IdMetrica"), str):
                raise ValueError("Registro sem IdMetrica textual")
            if registro.get("DataBase") != data_base:
                raise ValueError("DataBase divergente")
            codigo = registro["IdMetrica"].strip()
            if codigo in por_codigo:
                raise ValueError("IdMetrica duplicado")
            por_codigo[codigo] = registro
        valores: dict[str, int | Decimal | None] = dict.fromkeys(CAMPOS)
        for campo, codigo in METRICAS_POR_SEGMENTO[consulta.segmento].items():
            bruto = por_codigo.get(codigo)
            if bruto is not None:
                valores[campo] = _valor_normalizado(MetricaBCB.model_validate(bruto), codigo, campo)
        if valores["cotas_ativas"] is None:
            return None
        validado = PanoramaConsultaResult(
            segmento=consulta.segmento,
            periodo_referencia=f"{data_base // 100:04d}-{data_base % 100:02d}",
            **valores,
            data_consulta=datetime.now(timezone.utc), fonte=FONTE,
            source_url=resposta.url,
            campos_indisponiveis=[campo for campo in CAMPOS if valores[campo] is None],
        )
        return PanoramaResultado(**validado.model_dump())
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise DadosInvalidosError("O BCB retornou métricas incompletas ou inválidas.") from exc


class BCBMercadoService:
    def __init__(self, collector: MetricasBCBGateway, hoje: Callable[[], date] | None = None) -> None:
        self.collector = collector
        self.hoje = hoje or (lambda: datetime.now(timezone.utc).date())

    async def consultar(self, consulta: ConsultaMercado) -> PanoramaResultado | None:
        periodos = [consulta.periodo] if consulta.periodo else periodos_candidatos(self.hoje())
        for periodo in periodos:
            resposta = await self.collector.extrair_periodo(periodo)
            resultado = normalizar_agregado(resposta, consulta, periodo)
            if resultado is not None:
                logger.info("bcb_panorama_normalizado periodo=%s segmento=%s campos=%s", resultado.periodo_referencia, resultado.segmento, len(CAMPOS) - len(resultado.campos_indisponiveis))
                return resultado
        return None
