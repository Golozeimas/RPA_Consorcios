from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain import ConsultaMercado


class ConsultaMercadoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    segmento: str = Field(min_length=1)
    periodo: str | None = None

    @model_validator(mode="after")
    def validar_consulta(self) -> "ConsultaMercadoInput":
        ConsultaMercado(**self.model_dump())
        return self


class PanoramaConsultaResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    segmento: str = Field(min_length=1)
    periodo_referencia: str = Field(pattern=r"^[1-9][0-9]{3}-(03|06|09|12)$")
    cotas_ativas: int = Field(ge=0)
    credito_medio: Decimal | None = Field(ge=0, allow_inf_nan=False)
    prazo_medio: Decimal | None = Field(ge=0, allow_inf_nan=False)
    taxa_administracao_media: Decimal | None = Field(ge=0, allow_inf_nan=False)
    contemplacoes: int | None = Field(ge=0)
    data_consulta: AwareDatetime
    fonte: Literal["Banco Central do Brasil"]
    source_url: str = Field(min_length=1)
    campos_indisponiveis: list[str]


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
