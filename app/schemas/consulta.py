from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.domain import Consulta
from app.schemas.consorcios import ConsorcioConsultaResult, PanoramaConsultaResult


class ConsultaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    periodo: str

    @field_validator("periodo")
    @classmethod
    def periodo_valido(cls, value: str) -> str:
        return Consulta(value).periodo


class MetricaBCB(BaseModel):
    """Contrato real do recurso Metricas, validado na fronteira BCB."""

    model_config = ConfigDict(str_strip_whitespace=True)
    DataBase: int = Field(strict=True)
    IdMetrica: str = Field(min_length=1)
    Grupo: str = Field(min_length=1)
    Metrica: str = Field(min_length=1)
    Valor: Decimal = Field(ge=0, allow_inf_nan=False)
    Unidade: str = Field(min_length=1)

    @field_validator("Grupo", "Metrica", "Unidade", mode="before")
    @classmethod
    def normalizar_texto(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("Valor", mode="before")
    @classmethod
    def rejeitar_booleano(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Valor booleano não representa uma métrica.")
        return value


class ResultadoConsultaBCB(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    fonte: Literal["Banco Central do Brasil"]
    consulta: Literal["Dados Agregados do Segmento de Consórcios"]
    periodo: str
    metrica: Literal["Cotas ativas - Total"]
    valor: Decimal = Field(ge=0, allow_inf_nan=False)
    unidade: Literal["mil"]
    consultado_em: AwareDatetime


class ExecucaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fonte: str
    tipo_consulta: str
    parametros: dict[str, str]
    data_hora: AwareDatetime
    status: str
    hash_consulta: str
    dados_extraidos: ResultadoConsultaBCB | PanoramaConsultaResult | ConsorcioConsultaResult | None
    erro: str | None
    duplicada_de: str | None
    mensagem_gerada: str | None = None
