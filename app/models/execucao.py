from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExecucaoModel(Base):
    __tablename__ = "execucoes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fonte: Mapped[str]
    tipo_consulta: Mapped[str]
    parametros: Mapped[dict[str, str]] = mapped_column(JSON)
    dados_extraidos: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    data_hora: Mapped[float] = mapped_column(Float)
    finalizado_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str]
    erro: Mapped[str | None]
    hash_consulta: Mapped[str] = mapped_column(String(64), index=True)
    # NULL libera a chave após finalizar, preservando todo o histórico.
    chave_ativa: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    duplicada_de: Mapped[str | None] = mapped_column(ForeignKey("execucoes.id"), nullable=True)
