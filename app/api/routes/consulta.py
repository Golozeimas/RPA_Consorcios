from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domain import Consulta, ConsultaMercado, DATASET, EnvioError, FONTE, METRICA, SEGMENTOS_PRINCIPAIS_BCB, SUBSEGMENTOS_BCB
from app.schemas.consulta import ConsultaInput, ExecucaoResponse
from app.schemas.consorcios import ConsultaMercadoInput
from app.services.consulta_service import ConsultaService
from app.services.envio_service import EnvioService
from app.schemas.envio import EnvioInput, EnvioResponse


def criar_router(service: ConsultaService, mercado_service: ConsultaService, envio_service: EnvioService,
                 usa_template: bool = False) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")

    @router.get("/", response_class=HTMLResponse)
    async def inicio(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="consulta.html", context={
            "fonte": FONTE, "dataset": DATASET, "metrica": METRICA,
            "segmentos_principais": SEGMENTOS_PRINCIPAIS_BCB,
            "subsegmentos": SUBSEGMENTOS_BCB,
            "usa_template": usa_template,
        })

    @router.post("/api/consultas", response_model=ExecucaoResponse)
    async def executar(entrada: ConsultaInput) -> ExecucaoResponse:
        return ExecucaoResponse.model_validate(await service.executar(Consulta(entrada.periodo)))

    @router.post("/api/consultas/mercado", response_model=ExecucaoResponse)
    async def executar_mercado(entrada: ConsultaMercadoInput) -> ExecucaoResponse:
        consulta = ConsultaMercado(**entrada.model_dump())
        return ExecucaoResponse.model_validate(await mercado_service.executar(consulta))

    @router.get("/api/consultas", response_model=list[ExecucaoResponse])
    async def historico() -> list[ExecucaoResponse]:
        return [ExecucaoResponse.model_validate(item) for item in service.historico()]

    @router.get("/api/consultas/{id}", response_model=ExecucaoResponse)
    async def obter(id: str) -> ExecucaoResponse:
        execucao = service.obter(id)
        if execucao is None:
            raise HTTPException(404, "Execução não encontrada.")
        return ExecucaoResponse.model_validate(execucao)

    @router.post("/api/consultas/{id}/envios", response_model=EnvioResponse)
    async def enviar(id: str, entrada: EnvioInput) -> EnvioResponse:
        try:
            return EnvioResponse.model_validate(await envio_service.enviar(id, entrada.destinatario))
        except EnvioError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/consultas/{id}/envios", response_model=list[EnvioResponse])
    async def envios(id: str) -> list[EnvioResponse]:
        return [EnvioResponse.model_validate(item) for item in envio_service.listar(id)]

    return router
