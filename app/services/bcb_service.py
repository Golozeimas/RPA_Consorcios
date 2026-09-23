from datetime import datetime, timezone
from decimal import Decimal
import json
import logging

from app.domain import Consulta, DATASET, DadosInvalidosError, FONTE, METRICA, METRICA_ID, Resultado
from app.schemas.consulta import MetricaBCB, ResultadoConsultaBCB
from app.services.ports import RpaGateway

logger = logging.getLogger(__name__)


def normalizar_resultado(texto: str, consulta: Consulta) -> Resultado | None:
    try:
        payload = json.loads(texto, parse_float=Decimal)
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ValueError("Envelope BCB inválido")
        if payload.get("@odata.nextLink") or payload.get("odata.nextLink"):
            raise ValueError("Resposta BCB incompleta/paginada")
        registros = payload["value"]
        selecionados = []
        for registro in registros:
            if not isinstance(registro, dict) or not isinstance(registro.get("IdMetrica"), str):
                raise ValueError("Registro sem identificador válido")
            if registro["IdMetrica"].strip() == METRICA_ID:
                selecionados.append(registro)
        if not selecionados:
            return None
        if len(selecionados) != 1:
            raise ValueError("Métrica duplicada na fonte")
        metrica = MetricaBCB.model_validate(selecionados[0])
        if metrica.DataBase != int(consulta.data_base) or metrica.Metrica != METRICA:
            raise ValueError("Resultado diverge da consulta")
        validado = ResultadoConsultaBCB(
            fonte=FONTE, consulta=DATASET, periodo=consulta.periodo,
            metrica=metrica.Metrica, valor=metrica.Valor, unidade=metrica.Unidade,
            consultado_em=datetime.now(timezone.utc),
        )
        return Resultado(**validado.model_dump())
    except (ValueError, TypeError) as exc:
        raise DadosInvalidosError("O BCB retornou dados incompletos ou inválidos.") from exc


class BCBService:
    def __init__(self, rpa: RpaGateway) -> None:
        self.rpa = rpa

    async def consultar(self, consulta: Consulta) -> Resultado | None:
        bruto = await self.rpa.extrair(consulta)
        resultado = normalizar_resultado(bruto, consulta)
        logger.info("bcb_normalizado periodo=%s encontrado=%s", consulta.periodo, resultado is not None)
        return resultado
