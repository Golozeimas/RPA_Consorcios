from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domain import Consulta, DATASET, FONTE, METRICA
from app.schemas.consulta import ConsultaInput, ExecucaoResponse
from app.services.consulta_service import ConsultaService


def criar_router(service: ConsultaService) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")

    @router.get("/", response_class=HTMLResponse)
    async def inicio(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="consulta.html", context={
            "fonte": FONTE, "dataset": DATASET, "metrica": METRICA,
        })

    @router.post("/api/consultas", response_model=ExecucaoResponse)
    async def executar(entrada: ConsultaInput) -> ExecucaoResponse:
        return ExecucaoResponse.model_validate(await service.executar(Consulta(entrada.periodo)))

    @router.get("/api/consultas", response_model=list[ExecucaoResponse])
    async def historico() -> list[ExecucaoResponse]:
        return [ExecucaoResponse.model_validate(item) for item in service.historico()]

    @router.get("/api/consultas/{id}", response_model=ExecucaoResponse)
    async def obter(id: str) -> ExecucaoResponse:
        execucao = service.obter(id)
        if execucao is None:
            raise HTTPException(404, "Execução não encontrada.")
        return ExecucaoResponse.model_validate(execucao)

    return router
