from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from app.domain import StatusEnvio, normalizar_destinatario


class EnvioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destinatario: str

    @field_validator("destinatario")
    @classmethod
    def telefone_valido(cls, valor: str) -> str:
        return normalizar_destinatario(valor)


class EnvioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    execucao_id: str
    destinatario: str
    mensagem: str
    status: StatusEnvio
    data_hora: AwareDatetime
    provedor_id: str | None
    erro: str | None
