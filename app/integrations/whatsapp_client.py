"""Adaptador WhatsApp pelo SDK oficial Twilio; nenhuma repetição automática."""

import asyncio
import json
import logging
import re
from datetime import datetime
from urllib.parse import urlencode

from aiohttp import ClientError
from pydantic import BaseModel, ConfigDict, Field
from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.rest import Client

from app.domain import ConfirmacaoEnvio, EnvioError, EnvioIncertoError, StatusEnvio, normalizar_destinatario
from app.services.mensagem_automoveis import CAMPOS_AUTOMOVEIS, TEXTO_AUTOMOVEIS

logger = logging.getLogger(__name__)

ERROS_TWILIO = {
    20003: "Credenciais ou permissões da conta Twilio inválidas. Confira Account SID e Auth Token.",
    21654: "A Twilio exige ContentSid neste ambiente. O fluxo Try out WhatsApp aceita apenas templates de teste; para enviar a mensagem da consulta, atualize a conta e configure um remetente WhatsApp habilitado.",
    63002: "Remetente WhatsApp não encontrado na conta Twilio. Confira o número configurado.",
    63007: "Remetente WhatsApp não habilitado nesta conta Twilio. Confira o Sandbox e o número configurado.",
    63015: "Destinatário não aderiu a este Sandbox ou a adesão expirou. Peça uma nova adesão.",
    63016: "Janela de atendimento encerrada. Peça ao destinatário uma nova mensagem antes de enviar texto livre.",
}

STATUS_TWILIO = {
    "created": StatusEnvio.CRIADO, "accepted": StatusEnvio.ACEITO,
    "queued": StatusEnvio.NA_FILA, "scheduled": StatusEnvio.NA_FILA,
    "sending": StatusEnvio.ENVIANDO, "sent": StatusEnvio.ENVIADO,
    "delivered": StatusEnvio.ENTREGUE, "read": StatusEnvio.LIDO,
    "failed": StatusEnvio.FALHOU, "undelivered": StatusEnvio.NAO_ENTREGUE,
    "canceled": StatusEnvio.FALHOU,
}


def telefone_whatsapp(valor: str) -> str:
    return f"whatsapp:+{normalizar_destinatario(valor)}"


def erro_twilio(codigo: int | None) -> str:
    detalhe = ERROS_TWILIO.get(codigo, "Twilio informou falha. Consulte o código no Console da Twilio.")
    return f"{detalhe} (código Twilio {codigo})" if codigo is not None else detalhe


def texto_template_automoveis() -> str:
    texto = TEXTO_AUTOMOVEIS
    for indice, campo in enumerate(CAMPOS_AUTOMOVEIS, 1):
        texto = texto.replace("{" + campo + "}", "{{" + str(indice) + "}}")
    return texto


class RespostaTwilio(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sid: str = Field(pattern=r"^(SM|MM)[0-9a-fA-F]{32}$", strict=True)
    status: str = Field(min_length=1, max_length=40, strict=True)
    to: str = Field(pattern=r"^whatsapp:\+[1-9][0-9]{7,14}$", strict=True)
    error_code: int | None = Field(default=None, strict=True)
    date_created: datetime | None = None


class WhatsAppClient:
    def __init__(self, account_sid: str, auth_token: str, whatsapp_from: str,
                 timeout_seconds: int = 30, content_sid: str = "",
                 is_production: bool = False, status_callback_url: str = "",
                 panorama_content_sid: str = "", content_variables: str = "") -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.whatsapp_from = whatsapp_from
        self.timeout_seconds = timeout_seconds
        self.content_sid = content_sid or panorama_content_sid
        self.panorama_content_sid = panorama_content_sid
        self.is_production = is_production
        self.status_callback_url = status_callback_url
        self.content_variables = content_variables

    def _conteudo(self, mensagem: str) -> tuple[dict[str, str], str]:
        sid = self.content_sid or self.panorama_content_sid
        if self.is_production and not sid:
            return {"body": mensagem}, mensagem

        if not sid:
            raise EnvioError("Envio WhatsApp indisponível no ambiente de demonstração. Configure TWILIO_CONTENT_SID com um template permitido pelo Twilio Try out WhatsApp.")

        conteudo: dict[str, str] = {"content_sid": sid}
        descricao_enviada = f"[Template Twilio Content SID: {sid}]"

        if self.content_variables:
            conteudo["content_variables"] = self.content_variables
            descricao_enviada = f"[Template Twilio Content SID: {sid} | Variáveis: {self.content_variables}]"
        elif self.panorama_content_sid and not self.content_variables:
            padrao = re.escape(TEXTO_AUTOMOVEIS)
            for campo in CAMPOS_AUTOMOVEIS:
                padrao = padrao.replace(re.escape("{" + campo + "}"), f"(?P<{campo}>[^\\r\\n]+)")
            valores = re.fullmatch(padrao, mensagem)
            if valores is None:
                raise EnvioError("O template configurado aceita somente o panorama de Automóveis. Faça uma nova consulta desse segmento.")
            conteudo["content_variables"] = json.dumps({
                str(indice): valores.group(campo)
                for indice, campo in enumerate(CAMPOS_AUTOMOVEIS, start=1)
            }, ensure_ascii=False)
            descricao_enviada = f"[Template Twilio Content SID: {sid} | Variáveis: {conteudo['content_variables']}]"

        return conteudo, descricao_enviada

    async def enviar(self, destinatario: str, mensagem: str, envio_id: str | None = None) -> ConfirmacaoEnvio:
        if not all((self.account_sid, self.auth_token, self.whatsapp_from)):
            raise EnvioError("WhatsApp não configurado no servidor.")
        if not mensagem.strip() or len(mensagem) > 1600:
            raise EnvioError("A mensagem deve conter de 1 a 1600 caracteres para envio.")
        destino = telefone_whatsapp(destinatario)
        conteudo, descricao_enviada = self._conteudo(mensagem)
        if self.status_callback_url:
            conteudo["status_callback"] = self.status_callback_url + (
                "?" + urlencode({"envio_id": envio_id}) if envio_id else "")
        try:
            # O contexto fecha a sessão inclusive em cancelamento/timeout. Retries ficam desabilitados.
            async with AsyncTwilioHttpClient(timeout=self.timeout_seconds) as http_client:
                client = Client(self.account_sid, self.auth_token, http_client=http_client)
                async with asyncio.timeout(self.timeout_seconds):
                    message = await client.messages.create_async(from_=self.whatsapp_from, to=destino, **conteudo)
            resposta = RespostaTwilio.model_validate(message)
        except TwilioRestException as exc:
            logger.warning("twilio_rejeitado status_http=%s codigo=%s", exc.status, exc.code)
            if exc.status >= 500 or exc.status == 408:
                raise EnvioIncertoError("O provedor não confirmou o envio. Verifique antes de repetir.") from exc
            detalhe = ERROS_TWILIO.get(exc.code, "Twilio recusou o envio. Consulte o código no Console da Twilio.")
            codigo = f" (código Twilio {exc.code})" if isinstance(exc.code, int) else ""
            raise EnvioError(f"{detalhe}{codigo}", exc.code if isinstance(exc.code, int) else None) from exc
        except (TimeoutError, ClientError, TwilioException, ValueError) as exc:
            logger.warning("twilio_resposta_incerta categoria=%s", type(exc).__name__)
            raise EnvioIncertoError("Não foi possível confirmar o envio. Verifique o provedor antes de repetir.") from exc
        if resposta.to != destino:
            raise EnvioIncertoError("O provedor retornou um destinatário diferente. Verifique antes de repetir.")
        if resposta.status in {"failed", "undelivered", "canceled"} or resposta.error_code is not None:
            logger.warning("twilio_mensagem_falhou status=%s codigo=%s", resposta.status, resposta.error_code)
            return ConfirmacaoEnvio(resposta.sid, resposta.status,
                                    STATUS_TWILIO.get(resposta.status, StatusEnvio.FALHOU),
                                    erro_twilio(resposta.error_code), resposta.error_code,
                                    self.whatsapp_from, resposta.date_created,
                                    mensagem_enviada=descricao_enviada)
        if resposta.status not in {"accepted", "queued", "sending", "sent", "delivered", "read", "scheduled"}:
            return ConfirmacaoEnvio(resposta.sid, resposta.status, StatusEnvio.INCERTO,
                                    "O provedor retornou um estado não reconhecido. Verifique antes de repetir.",
                                    mensagem_enviada=descricao_enviada)
        return ConfirmacaoEnvio(resposta.sid, resposta.status,
                                STATUS_TWILIO[resposta.status], remetente=self.whatsapp_from,
                                criado_em=resposta.date_created, mensagem_enviada=descricao_enviada)

