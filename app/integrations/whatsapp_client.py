"""Envio de texto ou template pela Meta Cloud API, sem retries automáticos."""

import logging

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.domain import EnvioError, EnvioIncertoError

logger = logging.getLogger(__name__)


class MensagemAceita(BaseModel):
    id: str = Field(min_length=1, max_length=512, strict=True, pattern=r"\S")


class RespostaMeta(BaseModel):
    messages: list[MensagemAceita] = Field(min_length=1, max_length=1)


class WhatsAppClient:
    def __init__(
        self, client: httpx.AsyncClient, token: str, phone_number_id: str,
        api_version: str, timeout_seconds: int = 30,
        template_name: str = "", template_language: str = "pt_BR",
    ) -> None:
        self.client = client
        self.token = token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.template_name = template_name
        self.template_language = template_language

    def _payload(self, destinatario: str, mensagem: str) -> dict[str, object]:
        payload: dict[str, object] = {"messaging_product": "whatsapp", "to": destinatario}
        if self.template_name:
            # O template aprovado deve ter um único parâmetro posicional no corpo.
            resumo = " ".join(mensagem.split())
            if not resumo or len(resumo) > 1024:
                raise EnvioError("A mensagem não cabe no parâmetro do template configurado.")
            payload.update(type="template", template={
                "name": self.template_name,
                "language": {"code": self.template_language},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": resumo}]}],
            })
        else:
            payload.update(type="text", text={"preview_url": False, "body": mensagem})
        return payload

    async def enviar(self, destinatario: str, mensagem: str) -> str:
        if not all((self.token, self.phone_number_id, self.api_version)):
            raise EnvioError("WhatsApp não configurado no servidor.")
        try:
            response = await self.client.post(
                f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages",
                headers={"Authorization": f"Bearer {self.token}"},
                json=self._payload(destinatario, mensagem),
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
            raise EnvioError("O WhatsApp rejeitou o envio. Verifique as credenciais, o destinatário permitido e o template ou a janela de atendimento.")
        try:
            return RespostaMeta.model_validate_json(response.content).messages[0].id
        except ValidationError as exc:
            raise EnvioIncertoError("Resposta do WhatsApp inválida; o envio pode ter sido aceito. Não repita sem verificar.") from exc
