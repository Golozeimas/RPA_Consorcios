"""Fronteira form-urlencoded do Twilio; valida assinatura antes de atualizar."""

import logging
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

from app.core.config import Settings
from app.domain import EnvioError, EventoEnvio, StatusEnvio
from app.integrations.whatsapp_client import STATUS_TWILIO, erro_twilio
from app.services.envio_service import EnvioService

logger = logging.getLogger(__name__)


class CallbackTwilio(BaseModel):
    MessageSid: str = Field(pattern=r"^(SM|MM)[0-9a-fA-F]{32}$")
    MessageStatus: str | None = Field(default=None, max_length=40, pattern=r"^[a-z_]+$")
    ErrorCode: int | None = Field(default=None, ge=0)
    ChannelStatusMessage: str | None = Field(default=None, max_length=2000)
    EventType: str | None = Field(default=None, max_length=80)
    AccountSid: str | None = None


def criar_webhook_twilio(service: EnvioService, settings: Settings) -> APIRouter:
    router = APIRouter()
    validator = RequestValidator(settings.twilio_auth_token)

    @router.post("/webhooks/twilio/message-status", status_code=204)
    async def status_callback(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/x-www-form-urlencoded":
            raise HTTPException(415, "Callback deve usar application/x-www-form-urlencoded.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                raise HTTPException(413, "Callback excede o limite permitido.")
        try:
            form = FormData(parse_qsl(body.decode("utf-8"), keep_blank_values=True, max_num_fields=100))
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(400, "Callback inválido.") from exc
        if settings.twilio_validate_signature:
            if not settings.twilio_auth_token or not settings.twilio_status_callback_url:
                raise HTTPException(503, "Validação do callback não configurada.")
            url = settings.twilio_status_callback_url
            if request.url.query:
                url += "?" + request.url.query
            if not validator.validate(url, form, request.headers.get("x-twilio-signature", "")):
                logger.warning("callback_assinatura_invalida")
                raise HTTPException(403, "Assinatura Twilio inválida.")
        else:
            logger.warning("callback_validacao_desabilitada_explicitamente")
        # Validar todos os parâmetros na assinatura, mas consumir só campos conhecidos.
        if any(len(form.getlist(key)) != 1 for key in CallbackTwilio.model_fields if key in form):
            raise HTTPException(400, "Campos duplicados no callback.")
        try:
            campos = dict(form)
            if campos.get("ErrorCode") == "":
                campos["ErrorCode"] = None
            callback = CallbackTwilio.model_validate(campos)
            envio_id = request.query_params.get("envio_id")
            if envio_id:
                envio_id = str(UUID(envio_id))
        except (ValidationError, ValueError) as exc:
            raise HTTPException(400, "Campos do callback inválidos.") from exc
        if callback.AccountSid and callback.AccountSid != settings.twilio_account_sid:
            raise HTTPException(403, "Conta do callback divergente.")
        status = "read" if (callback.EventType or "").lower() == "read" else callback.MessageStatus
        if not status:
            raise HTTPException(400, "Callback sem status.")
        interno = STATUS_TWILIO.get(status, StatusEnvio.INCERTO)
        erro = erro_twilio(callback.ErrorCode) if interno in {StatusEnvio.FALHOU, StatusEnvio.NAO_ENTREGUE} or callback.ErrorCode else None
        # Não persistir ChannelStatusMessage bruto: pode conter telefone ou conteúdo privado.
        evento = EventoEnvio(callback.MessageSid, status, interno, callback.ErrorCode, erro, callback.EventType)
        try:
            envio = service.atualizar_status(evento, envio_id)
        except EnvioError as exc:
            raise HTTPException(409, str(exc)) from exc
        if envio is None:
            raise HTTPException(404, "MessageSid não encontrado.")
        return Response(status_code=204)

    return router
