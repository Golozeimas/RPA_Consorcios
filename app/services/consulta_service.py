import asyncio
from datetime import datetime, timezone
import logging

from app.domain import Consulta, ConsultaError, ConsultaMercado, Execucao, Status
from app.services.mensagem_service import gerar_mensagem
from app.services.ports import ExecutionRepository, PublicQueryGateway

logger = logging.getLogger(__name__)


class ConsultaService:
    def __init__(
        self, bcb: PublicQueryGateway, repository: ExecutionRepository, timeout_seconds: int = 120
    ) -> None:
        self.bcb = bcb
        self.repository = repository
        self.timeout_seconds = timeout_seconds

    async def executar(self, consulta: Consulta | ConsultaMercado) -> Execucao:
        execucao = self.repository.reservar(consulta, datetime.now(timezone.utc))
        logger.info("consulta_inicio id=%s tipo=%s", execucao.id, execucao.tipo_consulta)
        if execucao.status == Status.DUPLICADA:
            logger.info("consulta_duplicada id=%s original=%s", execucao.id, execucao.duplicada_de)
            return execucao
        resultado = None
        mensagem_gerada = None
        erro = None
        status = Status.ERRO
        try:
            async with asyncio.timeout(self.timeout_seconds):
                resultado = await self.bcb.consultar(consulta)
            if resultado is not None:
                mensagem_gerada = gerar_mensagem(resultado)
            status = Status.SUCESSO if resultado is not None else Status.SEM_RESULTADO
            logger.info("consulta_resultado id=%s status=%s", execucao.id, status)
        except asyncio.CancelledError:
            self.repository.finalizar(execucao.id, Status.ERRO, None, "Execução interrompida.")
            raise
        except TimeoutError:
            erro = "A consulta excedeu o tempo máximo. Tente novamente mais tarde."
            logger.warning("consulta_timeout id=%s", execucao.id)
        except ConsultaError as exc:
            erro = str(exc)
            logger.exception("consulta_falha id=%s categoria=%s", execucao.id, type(exc).__name__)
        except Exception:
            erro = "Não foi possível concluir a consulta. Tente novamente mais tarde."
            logger.exception("consulta_inesperada id=%s", execucao.id)
        # A reserva continua no histórico se o banco falhar; a rota trata o erro.
        final = self.repository.finalizar(execucao.id, status, resultado, erro, mensagem_gerada)
        logger.info("consulta_fim id=%s status=%s", final.id, final.status)
        return final

    def obter(self, id: str) -> Execucao | None:
        return self.repository.obter(id)

    def historico(self) -> list[Execucao]:
        return self.repository.listar()
