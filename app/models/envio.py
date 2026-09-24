from sqlalchemy import Float, ForeignKey, String, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.execucao import Base


class EnvioModel(Base):
    __tablename__ = "envios"
    __table_args__ = (UniqueConstraint("execucao_id", "destinatario"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execucao_id: Mapped[str] = mapped_column(ForeignKey("execucoes.id"), index=True)
    destinatario: Mapped[str] = mapped_column(String(15))
    mensagem: Mapped[str]
    status: Mapped[str]
    data_hora: Mapped[float] = mapped_column(Float)
    finalizado_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    provedor_id: Mapped[str | None]
    provedor_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    erro: Mapped[str | None]
    tentativas: Mapped[int] = mapped_column(default=1)
    provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    initial_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[int | None]
    remetente: Mapped[str | None]
    criado_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    sent_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    read_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    eventos: Mapped[list[dict[str, str | int | bool | None]] | None] = mapped_column(JSON, nullable=True)
    mensagem_enviada: Mapped[str | None] = mapped_column(String, nullable=True)
