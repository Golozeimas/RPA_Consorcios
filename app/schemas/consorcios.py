from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain import ConsultaMercado


class ConsultaMercadoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    administradora: str = Field(min_length=1, max_length=160)
    periodo: str | None = None
    segmento: Literal["Imóveis", "Veículos Pesados", "Automóveis", "Motocicletas", "Serviços"] | None = None
    uf: Literal[
        "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
        "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
    ] | None = None

    @model_validator(mode="after")
    def validar_consulta(self) -> "ConsultaMercadoInput":
        ConsultaMercado(**self.model_dump())
        return self


class ConsorcioConsultaResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    administradora: str | None
    periodo_referencia: str = Field(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$")
    grupos_ativos: int | None = Field(ge=0)
    cotas_ativas: int | None = Field(ge=0)
    cotas_contempladas: int | None = Field(ge=0)
    cotas_comercializadas: int | None = Field(ge=0)
    creditos_comercializados: Decimal | None = Field(ge=0, allow_inf_nan=False)
    segmento: str | None
    uf: str | None
    abrangencia: str = Field(min_length=1)
    data_consulta: AwareDatetime
    fonte: Literal["Banco Central do Brasil"]
    source_url: str = Field(min_length=1)
    campos_indisponiveis: list[str]

    @field_validator("data_consulta")
    @classmethod
    def validar_data(cls, value: datetime) -> datetime:
        return value
