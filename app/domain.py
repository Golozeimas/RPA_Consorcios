"""Conceitos independentes de navegador, HTTP e persistência."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
import re

FONTE = "Banco Central do Brasil"
DATASET = "Dados Agregados do Segmento de Consórcios"
METRICA = "Cotas ativas - Total"
METRICA_ID = "10"


class Status(StrEnum):
    PROCESSANDO = "PROCESSANDO"
    SUCESSO = "SUCESSO"
    SEM_RESULTADO = "SEM_RESULTADO"
    ERRO = "ERRO"
    DUPLICADA = "DUPLICADA"


class ConsultaError(Exception):
    """Falha controlada, com mensagem segura para o usuário."""


class NavegacaoError(ConsultaError):
    pass


class FonteIndisponivelError(ConsultaError):
    pass


class ExtracaoError(ConsultaError):
    pass


class DadosInvalidosError(ConsultaError):
    pass


class PersistenciaError(ConsultaError):
    pass


@dataclass(frozen=True)
class Consulta:
    periodo: str

    def __post_init__(self) -> None:
        periodo = self.periodo.strip()
        if not re.fullmatch(r"[1-9][0-9]{3}-(0[1-9]|1[0-2])", periodo):
            raise ValueError("Informe um período válido no formato AAAA-MM.")
        object.__setattr__(self, "periodo", periodo)

    @property
    def data_base(self) -> str:
        return self.periodo.replace("-", "")

    @property
    def parametros(self) -> dict[str, str]:
        return {"metrica": METRICA_ID, "periodo": self.periodo}

    @property
    def hash_consulta(self) -> str:
        identidade = {"fonte": FONTE, "consulta": DATASET, **self.parametros}
        return sha256(json.dumps(identidade, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Resultado:
    fonte: str
    consulta: str
    periodo: str
    metrica: str
    valor: Decimal
    unidade: str
    consultado_em: datetime


@dataclass(frozen=True)
class Execucao:
    id: str
    fonte: str
    tipo_consulta: str
    parametros: dict[str, str]
    data_hora: datetime
    status: Status
    hash_consulta: str
    dados_extraidos: Resultado | None = None
    erro: str | None = None
    duplicada_de: str | None = None
