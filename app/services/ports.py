from datetime import datetime
from typing import Protocol

from app.domain import Consulta, Execucao, Resultado, Status


class RpaGateway(Protocol):
    async def extrair(self, consulta: Consulta) -> str: ...


class PublicQueryGateway(Protocol):
    async def consultar(self, consulta: Consulta) -> Resultado | None: ...


class ExecutionRepository(Protocol):
    def reservar(self, consulta: Consulta, agora: datetime) -> Execucao: ...

    def finalizar(
        self, id: str, status: Status, resultado: Resultado | None, erro: str | None
    ) -> Execucao: ...

    def obter(self, id: str) -> Execucao | None: ...

    def listar(self) -> list[Execucao]: ...
