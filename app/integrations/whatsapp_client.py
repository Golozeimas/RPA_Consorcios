"""Envio de texto pela Meta Cloud API, sem retries automáticos."""

import logging

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.domain import EnvioError, EnvioIncertoError

logger = logging.getLogger(__name__)


class MensagemAceita(BaseModel):
    id: str = Field(min_length=1, max_length=512, strict=True)


class RespostaMeta(BaseModel):
    messages: list[MensagemAceita] = Field(min_length=1, max_length=1)


class WhatsAppClient:
    def __init__(
        self, client: httpx.AsyncClient, token: str, phone_number_id: str,
        api_version: str, timeout_seconds: int = 30,
    ) -> None:
        self.client = client
        self.token = token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    async def enviar(self, destinatario: str, mensagem: str) -> str:
        if not all((self.token, self.phone_number_id, self.api_version)):
            raise EnvioError("WhatsApp não configurado no servidor.")
        try:
            response = await self.client.post(
                f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"messaging_product": "whatsapp", "to": destinatario,
                      "type": "text", "text": {"preview_url": False, "body": mensagem}},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            # Não incluir request, headers ou payload do provedor nos logs.
            logger.warning("whatsapp_transporte_falhou categoria=%s", type(exc).__name__)
            raise EnvioIncertoError("Não foi possível confirmar o envio. Verifique o provedor antes de reenviar.") from exc
        if response.status_code >= 500 or response.status_code == 408:
            raise EnvioIncertoError("O provedor não confirmou o envio. Verifique antes de reenviar.")
        if not response.is_success:
            logger.warning("whatsapp_rejeitado status_http=%s", response.status_code)
            raise EnvioError("O WhatsApp rejeitou o envio. Verifique a configuração, o destinatário e a janela de atendimento.")
        try:
            return RespostaMeta.model_validate_json(response.content).messages[0].id
        except ValidationError as exc:
            raise EnvioIncertoError("Resposta do WhatsApp inválida; o envio pode ter sido aceito. Não repita sem verificar.") from exc
