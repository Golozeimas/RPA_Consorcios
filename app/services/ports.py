from datetime import datetime
from dataclasses import dataclass
from typing import Protocol

from app.domain import ConfirmacaoEnvio, Consulta, ConsultaMercado, ConsorcioResultado, Envio, EventoEnvio, Execucao, PanoramaResultado, Resultado, Status, StatusEnvio

MAXIMO_REGISTROS_BCB = 200


@dataclass(frozen=True)
class RespostaBCB:
    texto: str
    url: str


class RpaGateway(Protocol):
    async def extrair(self, consulta: Consulta) -> str: ...


class MetricasBCBGateway(Protocol):
    async def extrair_periodo(self, periodo: str) -> RespostaBCB: ...


class PublicQueryGateway(Protocol):
    async def consultar(
        self, consulta: Consulta | ConsultaMercado
    ) -> Resultado | ConsorcioResultado | PanoramaResultado | None: ...


class ExecutionRepository(Protocol):
    def reservar(self, consulta: Consulta | ConsultaMercado, agora: datetime) -> Execucao: ...

    def finalizar(
        self, id: str, status: Status, resultado: Resultado | ConsorcioResultado | PanoramaResultado | None,
        erro: str | None, mensagem_gerada: str | None = None,
    ) -> Execucao: ...

    def obter(self, id: str) -> Execucao | None: ...

    def listar(self) -> list[Execucao]: ...


class MessageGateway(Protocol):
    async def enviar(self, destinatario: str, mensagem: str, envio_id: str | None = None) -> ConfirmacaoEnvio: ...


class EnvioRepository(Protocol):
    def reservar_envio(self, execucao_id: str, destinatario: str) -> tuple[Envio, bool]: ...

    def finalizar_envio(self, id: str, status: StatusEnvio, provedor_id: str | None, erro: str | None,
                       provedor_status: str | None = None, error_code: int | None = None,
                       remetente: str | None = None, criado_em: datetime | None = None,
                       mensagem_enviada: str | None = None) -> Envio: ...

    def atualizar_status(self, evento: EventoEnvio, envio_id: str | None = None) -> Envio | None: ...

    def listar_envios(self, execucao_id: str) -> list[Envio]: ...
