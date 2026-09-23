from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging
import httpx

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import URL, create_engine

from app.api.routes.consulta import criar_router
from app.integrations.bcb_client import BCBClient
from app.integrations.whatsapp_client import WhatsAppClient
from app.core.config import ROOT, Settings
from app.domain import PersistenciaError
from app.models.execucao import Base
from app.repositories.execucao_repository import SQLiteExecutionRepository
from app.repositories.envio_repository import SQLiteEnvioRepository
from app.services.bcb_service import BCBService
from app.services.bcb_mercado_service import BCBMercadoService
from app.services.consulta_service import ConsultaService
from app.services.ports import MessageGateway, PublicQueryGateway
from app.services.envio_service import EnvioService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    gateway: PublicQueryGateway | None = None,
    mercado_gateway: PublicQueryGateway | None = None,
    message_gateway: MessageGateway | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = create_engine(
        URL.create("sqlite", database=str(settings.database_path)),
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    repository = SQLiteExecutionRepository(
        engine, settings.duplicate_seconds, settings.query_timeout_seconds + 30
    )
    http_client = httpx.AsyncClient(transport=http_transport, timeout=settings.http_timeout_seconds)
    collector = BCBClient(http_client, settings.http_timeout_seconds)
    bcb = gateway or BCBService(collector)
    service = ConsultaService(bcb, repository, settings.query_timeout_seconds)
    mercado = ConsultaService(
        mercado_gateway or BCBMercadoService(collector), repository, settings.query_timeout_seconds
    )
    envio = EnvioService(
        message_gateway or WhatsAppClient(
            http_client, settings.whatsapp_token, settings.whatsapp_phone_number_id,
            settings.whatsapp_api_version, settings.http_timeout_seconds,
            settings.whatsapp_template_name, settings.whatsapp_template_language,
        ),
        SQLiteEnvioRepository(engine, settings.http_timeout_seconds * 4 + 30),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        try:
            settings.database_path.parent.mkdir(parents=True, exist_ok=True)
            Base.metadata.create_all(engine)
            logger.info("aplicacao_iniciada")
            yield
        finally:
            await http_client.aclose()
            engine.dispose()

    app = FastAPI(title="Consulta pública BCB — Consórcios", lifespan=lifespan)
    app.include_router(criar_router(service, mercado, envio, bool(settings.whatsapp_template_name)))
    app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")

    @app.exception_handler(PersistenciaError)
    async def persistencia_error(request: Request, exc: PersistenciaError) -> JSONResponse:
        logger.error("requisicao_persistencia_falhou caminho=%s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("requisicao_inesperada caminho=%s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Não foi possível atender à solicitação."})

    return app


app = create_app()
