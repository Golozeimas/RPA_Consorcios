import asyncio
import logging

from app.domain import Envio, EnvioError, EnvioIncertoError, EventoEnvio, StatusEnvio
from app.services.ports import EnvioRepository, MessageGateway

logger = logging.getLogger(__name__)


class EnvioService:
    def __init__(self, gateway: MessageGateway, repository: EnvioRepository) -> None:
        self.gateway = gateway
        self.repository = repository

    async def enviar(self, execucao_id: str, destinatario: str) -> Envio:
        """Recebe o telefone internacional já validado e normalizado na fronteira."""
        envio, reservado = self.repository.reservar_envio(execucao_id, destinatario)
        if not reservado:
            logger.info("envio_duplicado_bloqueado id=%s", envio.id)
            return envio
        logger.info("envio_inicio id=%s execucao=%s", envio.id, execucao_id)
        status, provedor_id, erro = StatusEnvio.INCERTO, None, None
        provedor_status = None
        error_code = None
        remetente = None
        criado_em = None
        mensagem_enviada = None
        try:
            confirmacao = await self.gateway.enviar(envio.destinatario, envio.mensagem, envio.id)
            provedor_id, provedor_status = confirmacao.provedor_id, confirmacao.provedor_status
            status, erro = confirmacao.status, confirmacao.erro
            error_code, remetente, criado_em = confirmacao.error_code, confirmacao.remetente, confirmacao.criado_em
            mensagem_enviada = confirmacao.mensagem_enviada
        except asyncio.CancelledError:
            self.repository.finalizar_envio(envio.id, StatusEnvio.INCERTO, None, "Envio interrompido; confirme no provedor antes de repetir.")
            raise
        except EnvioIncertoError as exc:
            erro = str(exc)
        except EnvioError as exc:
            status = StatusEnvio.FALHOU if (exc.error_code in {21654, 63015, 63016} or "ambiente de demonstração" in str(exc) or "Try out WhatsApp" in str(exc)) else StatusEnvio.ERRO
            erro = str(exc)
            error_code = exc.error_code
        except Exception as exc:
            # Exceções de transporte podem carregar dados privados: registrar só categoria.
            logger.error("envio_inesperado id=%s categoria=%s", envio.id, type(exc).__name__)
            erro = "Não foi possível confirmar o envio. Verifique o provedor antes de repetir."
        final = self.repository.finalizar_envio(envio.id, status, provedor_id, erro, provedor_status,
                                               error_code, remetente, criado_em, mensagem_enviada)
        logger.info("envio_finalizado id=%s status=%s", envio.id, final.status)
        return final

    def atualizar_status(self, evento: EventoEnvio, envio_id: str | None = None) -> Envio | None:
        envio = self.repository.atualizar_status(evento, envio_id)
        logger.info("callback_status resultado=%s status=%s", "atualizado" if envio else "sid_desconhecido", evento.status)
        return envio

    def listar(self, execucao_id: str) -> list[Envio]:
        return self.repository.listar_envios(execucao_id)
