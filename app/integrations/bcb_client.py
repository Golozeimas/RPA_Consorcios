"""Transporte HTTP do contrato Olinda verificado no Swagger oficial."""

import logging

import httpx

from app.domain import Consulta, FonteIndisponivelError
from app.services.ports import MAXIMO_REGISTROS_BCB, RespostaBCB

logger = logging.getLogger(__name__)
BCB_ODATA = "https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/odata"


class BCBClient:
    def __init__(self, client: httpx.AsyncClient, timeout_seconds: int = 30) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    async def extrair_periodo(self, periodo: str) -> RespostaBCB:
        consulta = Consulta(periodo)
        logger.info("bcb_http_inicio periodo=%s", periodo)
        try:
            response = await self.client.get(
                f"{BCB_ODATA}/Metricas(DataBase=@DataBase)",
                params={"@DataBase": consulta.data_base, "$format": "json", "$top": MAXIMO_REGISTROS_BCB},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FonteIndisponivelError("O Banco Central excedeu o tempo de resposta.") from exc
        except httpx.HTTPError as exc:
            raise FonteIndisponivelError("O serviço do Banco Central está indisponível. Tente mais tarde.") from exc
        logger.info("bcb_http_recebido periodo=%s status=%s", periodo, response.status_code)
        # O parser existente valida o envelope, as unidades e a precisão Decimal.
        return RespostaBCB(response.text, str(response.url))

    async def extrair(self, consulta: Consulta) -> str:
        return (await self.extrair_periodo(consulta.periodo)).texto
