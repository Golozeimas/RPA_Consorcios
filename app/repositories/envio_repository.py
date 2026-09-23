from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain import Envio, EnvioError, PersistenciaError, Status, StatusEnvio
from app.models.envio import EnvioModel
from app.models.execucao import ExecucaoModel


def atualizar_schema_envios(engine: Engine) -> None:
    """Migração aditiva para bancos anteriores ao registro do status do provedor."""
    with engine.begin() as connection:
        connection.execute(text("BEGIN IMMEDIATE"))
        colunas = {linha[1] for linha in connection.execute(text("PRAGMA table_info(envios)"))}
        if "provedor_status" not in colunas:
            connection.execute(text("ALTER TABLE envios ADD COLUMN provedor_status VARCHAR(40)"))


def _entidade(model: EnvioModel) -> Envio:
    return Envio(
        id=model.id, execucao_id=model.execucao_id, destinatario=model.destinatario,
        mensagem=model.mensagem, status=StatusEnvio(model.status),
        data_hora=datetime.fromtimestamp(model.data_hora, timezone.utc),
        provedor_id=model.provedor_id, provedor_status=model.provedor_status, erro=model.erro,
    )


class SQLiteEnvioRepository:
    def __init__(self, engine: Engine, stale_seconds: int = 150) -> None:
        self.engine = engine
        self.stale_seconds = stale_seconds

    def reservar_envio(self, execucao_id: str, destinatario: str) -> tuple[Envio, bool]:
        try:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                # Serializa a reserva por execução, inclusive quando o telefone muda.
                # Mantém os registros antigos sem exigir uma migração destrutiva.
                existente = session.scalar(select(EnvioModel).where(
                    EnvioModel.execucao_id == execucao_id,
                ).order_by(EnvioModel.data_hora.desc()))
                if existente:
                    existente.tentativas += 1
                    if (existente.status == StatusEnvio.ENVIANDO and
                            existente.data_hora < datetime.now(timezone.utc).timestamp() - self.stale_seconds):
                        existente.status = StatusEnvio.INCERTO
                        existente.erro = "Envio interrompido ou sem confirmação. Verifique no provedor antes de repetir."
                    return _entidade(existente), False
                execucao = session.get(ExecucaoModel, execucao_id)
                if execucao is None or execucao.status != Status.SUCESSO or not execucao.dados_extraidos:
                    raise EnvioError("Somente consultas concluídas com sucesso podem ser enviadas.")
                mensagem = execucao.dados_extraidos.get("_mensagem_gerada")
                if not isinstance(mensagem, str) or not mensagem.strip() or len(mensagem) > 4096:
                    raise EnvioError("A consulta não possui uma mensagem válida para envio. Execute uma nova consulta.")
                model = EnvioModel(
                    id=str(uuid4()), execucao_id=execucao_id, destinatario=destinatario,
                    mensagem=mensagem, status=StatusEnvio.ENVIANDO,
                    data_hora=datetime.now(timezone.utc).timestamp(),
                )
                session.add(model)
                session.flush()
                return _entidade(model), True
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível registrar o envio. Nenhuma nova mensagem foi enviada.") from exc

    def finalizar_envio(self, id: str, status: StatusEnvio, provedor_id: str | None, erro: str | None,
                       provedor_status: str | None = None) -> Envio:
        try:
            with Session(self.engine) as session, session.begin():
                model = session.get(EnvioModel, id)
                if model is None or model.status not in {StatusEnvio.ENVIANDO, StatusEnvio.INCERTO}:
                    raise PersistenciaError("O envio não está disponível para atualização.")
                model.status, model.provedor_id, model.erro = status, provedor_id, erro
                model.provedor_status = provedor_status
                model.finalizado_em = datetime.now(timezone.utc).timestamp()
                session.flush()
                return _entidade(model)
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível salvar a confirmação. Verifique o histórico e o provedor antes de repetir.") from exc

    def listar_envios(self, execucao_id: str) -> list[Envio]:
        try:
            with Session(self.engine) as session:
                return [_entidade(item) for item in session.scalars(select(EnvioModel).where(
                    EnvioModel.execucao_id == execucao_id,
                ).order_by(EnvioModel.data_hora.desc()))]
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível carregar o histórico de envios.") from exc
