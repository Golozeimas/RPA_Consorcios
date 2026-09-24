from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain import Envio, EnvioError, EventoEnvio, PersistenciaError, Status, StatusEnvio, pode_avancar_envio
from app.models.envio import EnvioModel
from app.models.execucao import ExecucaoModel


def atualizar_schema_envios(engine: Engine) -> None:
    """Migração aditiva para bancos anteriores ao registro do status do provedor."""
    with engine.begin() as connection:
        connection.execute(text("BEGIN IMMEDIATE"))
        colunas = {linha[1] for linha in connection.execute(text("PRAGMA table_info(envios)"))}
        novas = {"provedor_status": "VARCHAR(40)", "provider": "VARCHAR(20)",
                 "initial_status": "VARCHAR(40)", "error_code": "INTEGER", "remetente": "VARCHAR",
                 "criado_em": "FLOAT", "updated_at": "FLOAT", "sent_at": "FLOAT",
                 "delivered_at": "FLOAT", "read_at": "FLOAT", "eventos": "JSON",
                 "mensagem_enviada": "VARCHAR"}
        for nome, tipo in novas.items():
            if nome not in colunas:
                connection.execute(text(f"ALTER TABLE envios ADD COLUMN {nome} {tipo}"))
        connection.execute(text("UPDATE envios SET provider = 'twilio' WHERE provider IS NULL AND (provedor_id LIKE 'SM%' OR provedor_id LIKE 'MM%')"))
        connection.execute(text("UPDATE envios SET provider = 'meta' WHERE provider IS NULL AND provedor_id LIKE 'wamid.%'"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_envios_provedor_id ON envios(provedor_id)"))


def _data(valor: float | None) -> datetime | None:
    return datetime.fromtimestamp(valor, timezone.utc) if valor is not None else None


def _entidade(model: EnvioModel) -> Envio:
    return Envio(
        id=model.id, execucao_id=model.execucao_id, destinatario=model.destinatario,
        mensagem=model.mensagem, status=StatusEnvio(model.status),
        data_hora=datetime.fromtimestamp(model.data_hora, timezone.utc),
        provedor_id=model.provedor_id, provedor_status=model.provedor_status, erro=model.erro,
        provider=model.provider, initial_status=model.initial_status, error_code=model.error_code,
        remetente=model.remetente, criado_em=_data(model.criado_em), updated_at=_data(model.updated_at),
        sent_at=_data(model.sent_at), delivered_at=_data(model.delivered_at), read_at=_data(model.read_at),
        eventos=tuple(model.eventos or []), mensagem_enviada=getattr(model, "mensagem_enviada", None),
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
                    provider="twilio", eventos=[],
                )
                session.add(model)
                session.flush()
                return _entidade(model), True
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível registrar o envio. Nenhuma nova mensagem foi enviada.") from exc

    def finalizar_envio(self, id: str, status: StatusEnvio, provedor_id: str | None, erro: str | None,
                       provedor_status: str | None = None, error_code: int | None = None,
                       remetente: str | None = None, criado_em: datetime | None = None,
                       mensagem_enviada: str | None = None) -> Envio:
        try:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                model = session.get(EnvioModel, id)
                if model is None:
                    raise PersistenciaError("O envio não está disponível para atualização.")
                if model.provedor_id and provedor_id and model.provedor_id != provedor_id:
                    raise PersistenciaError("Identificador do provedor divergente.")
                model.provedor_id = model.provedor_id or provedor_id
                model.initial_status = model.initial_status or provedor_status
                model.remetente = remetente or model.remetente
                model.criado_em = criado_em.timestamp() if criado_em else model.criado_em
                model.mensagem_enviada = mensagem_enviada or getattr(model, "mensagem_enviada", None)
                self._registrar_evento(model, status, provedor_status, error_code, erro, "create")
                model.finalizado_em = datetime.now(timezone.utc).timestamp()
                session.flush()
                return _entidade(model)
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível salvar a confirmação. Verifique o histórico e o provedor antes de repetir.") from exc

    @staticmethod
    def _registrar_evento(model: EnvioModel, status: StatusEnvio, provider_status: str | None,
                         error_code: int | None, erro: str | None, origem: str,
                         event_type: str | None = None) -> None:
        eventos = list(model.eventos or [])
        if any(e["origem"] == origem and e["provider_status"] == provider_status
               and e["error_code"] == error_code and e.get("event_type") == event_type for e in eventos):
            return
        agora = datetime.now(timezone.utc)
        aplicar = not eventos or pode_avancar_envio(StatusEnvio(model.status), status)
        eventos.append({"origem": origem, "provider_status": provider_status, "status": str(status),
                        "error_code": error_code, "erro": erro, "event_type": event_type,
                        "recebido_em": agora.isoformat(), "aplicado": aplicar})
        model.eventos = eventos
        model.updated_at = agora.timestamp()
        if aplicar:
            model.status, model.provedor_status = status, provider_status
            model.error_code, model.erro = error_code, erro
        # Apenas eventos efetivamente observados recebem timestamp; não inventar etapas anteriores.
        campo = {StatusEnvio.ENVIADO: "sent_at", StatusEnvio.ENTREGUE: "delivered_at", StatusEnvio.LIDO: "read_at"}.get(status)
        if campo and getattr(model, campo) is None:
            setattr(model, campo, agora.timestamp())

    def atualizar_status(self, evento: EventoEnvio, envio_id: str | None = None) -> Envio | None:
        try:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                model = session.scalar(select(EnvioModel).where(
                    EnvioModel.provedor_id == evento.provedor_id, EnvioModel.provider == "twilio"))
                # O callback assinado pode chegar antes da resposta de criação ser persistida.
                if model is None and envio_id:
                    candidato = session.get(EnvioModel, envio_id)
                    if candidato and candidato.provider == "twilio" and candidato.provedor_id is None and candidato.status in {StatusEnvio.ENVIANDO, StatusEnvio.INCERTO}:
                        model = candidato
                        model.provedor_id = evento.provedor_id
                if model is None:
                    return None
                if envio_id and model.id != envio_id:
                    raise EnvioError("Callback não corresponde ao envio informado.")
                self._registrar_evento(model, evento.status, evento.provedor_status,
                                       evento.error_code, evento.erro, "callback", evento.event_type)
                session.flush()
                return _entidade(model)
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível salvar o status do callback.") from exc

    def listar_envios(self, execucao_id: str) -> list[Envio]:
        try:
            with Session(self.engine) as session:
                return [_entidade(item) for item in session.scalars(select(EnvioModel).where(
                    EnvioModel.execucao_id == execucao_id,
                ).order_by(EnvioModel.data_hora.desc()))]
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível carregar o histórico de envios.") from exc
