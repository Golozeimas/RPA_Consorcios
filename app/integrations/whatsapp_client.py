"""Adaptador WhatsApp pelo SDK oficial Twilio; nenhuma repetição automática."""

import asyncio
import logging

from aiohttp import ClientError
from pydantic import BaseModel, ConfigDict, Field
from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

from app.domain import ConfirmacaoEnvio, EnvioError, EnvioIncertoError, StatusEnvio

logger = logging.getLogger(__name__)

ERROS_TWILIO = {
    20003: "Credenciais ou permissões da conta Twilio inválidas. Confira Account SID e Auth Token.",
    63002: "Remetente WhatsApp não encontrado na conta Twilio. Confira o número configurado.",
    63007: "Remetente WhatsApp não habilitado nesta conta Twilio. Confira o Sandbox e o número configurado.",
    63015: "Destinatário não aderiu a este Sandbox ou a adesão expirou. Peça uma nova adesão.",
    63016: "Janela de atendimento encerrada. Peça ao destinatário uma nova mensagem antes de enviar texto livre.",
}


class RespostaTwilio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sid: str = Field(pattern=r"^(SM|MM)[0-9a-fA-F]{32}$", strict=True)
    status: str = Field(min_length=1, max_length=40, strict=True)
    to: str = Field(pattern=r"^whatsapp:\+[1-9][0-9]{7,14}$", strict=True)
    error_code: int | None = Field(default=None, strict=True)


class WhatsAppClient:
    def __init__(self, account_sid: str, auth_token: str, whatsapp_from: str,
                 timeout_seconds: int = 30) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.whatsapp_from = whatsapp_from
        self.timeout_seconds = timeout_seconds

    async def enviar(self, destinatario: str, mensagem: str) -> ConfirmacaoEnvio:
        if not all((self.account_sid, self.auth_token, self.whatsapp_from)):
            raise EnvioError("WhatsApp não configurado no servidor.")
        if not mensagem.strip() or len(mensagem) > 1600:
            raise EnvioError("A mensagem deve conter de 1 a 1600 caracteres para envio.")
        destino = f"whatsapp:+{destinatario}"
        try:
            # O contexto fecha a sessão inclusive em cancelamento/timeout. Retries ficam desabilitados.
            async with AsyncTwilioHttpClient(timeout=self.timeout_seconds) as http_client:
                client = Client(self.account_sid, self.auth_token, http_client=http_client)
                async with asyncio.timeout(self.timeout_seconds):
                    message = await client.messages.create_async(body=mensagem, from_=self.whatsapp_from, to=destino)
            resposta = RespostaTwilio.model_validate(message)
        except TwilioRestException as exc:
            logger.warning("twilio_rejeitado status_http=%s codigo=%s", exc.status, exc.code)
            if exc.status >= 500 or exc.status == 408:
                raise EnvioIncertoError("O provedor não confirmou o envio. Verifique antes de repetir.") from exc
            detalhe = ERROS_TWILIO.get(exc.code, "Twilio recusou o envio. Consulte o código no Console da Twilio.")
            codigo = f" (código Twilio {exc.code})" if isinstance(exc.code, int) else ""
            raise EnvioError(f"{detalhe}{codigo}") from exc
        except (TimeoutError, ClientError, TwilioException, ValueError) as exc:
            logger.warning("twilio_resposta_incerta categoria=%s", type(exc).__name__)
            raise EnvioIncertoError("Não foi possível confirmar o envio. Verifique o provedor antes de repetir.") from exc
        if resposta.to != destino:
            raise EnvioIncertoError("O provedor retornou um destinatário diferente. Verifique antes de repetir.")
        if resposta.status in {"failed", "undelivered", "canceled"} or resposta.error_code is not None:
            logger.warning("twilio_mensagem_falhou status=%s codigo=%s", resposta.status, resposta.error_code)
            return ConfirmacaoEnvio(resposta.sid, resposta.status, StatusEnvio.ERRO,
                                    "O provedor informou falha no envio. Consulte o histórico e o provedor.")
        if resposta.status not in {"accepted", "queued", "sending", "sent", "delivered", "read", "scheduled"}:
            return ConfirmacaoEnvio(resposta.sid, resposta.status, StatusEnvio.INCERTO,
                                    "O provedor retornou um estado não reconhecido. Verifique antes de repetir.")
        return ConfirmacaoEnvio(resposta.sid, resposta.status)
