from datetime import datetime, timezone
from decimal import Decimal
import logging
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain import Consulta, ConsultaMercado, ConsorcioResultado, DATASET, Execucao, FONTE, PersistenciaError, Resultado, Status
from app.models.execucao import ExecucaoModel

logger = logging.getLogger(__name__)


def _resultado_json(
    resultado: Resultado | ConsorcioResultado | None, mensagem_gerada: str | None
) -> dict[str, object] | None:
    if resultado is None:
        return None
    if isinstance(resultado, ConsorcioResultado):
        return {
            "administradora": resultado.administradora,
            "periodo_referencia": resultado.periodo_referencia,
            "grupos_ativos": resultado.grupos_ativos,
            "cotas_ativas": resultado.cotas_ativas,
            "cotas_contempladas": resultado.cotas_contempladas,
            "cotas_comercializadas": resultado.cotas_comercializadas,
            "creditos_comercializados": str(resultado.creditos_comercializados) if resultado.creditos_comercializados is not None else None,
            "segmento": resultado.segmento, "uf": resultado.uf,
            "abrangencia": resultado.abrangencia,
            "data_consulta": resultado.data_consulta.isoformat(),
            "fonte": resultado.fonte, "source_url": resultado.source_url,
            "campos_indisponiveis": resultado.campos_indisponiveis,
            "_mensagem_gerada": mensagem_gerada,
        }
    return {
        "fonte": resultado.fonte, "consulta": resultado.consulta,
        "periodo": resultado.periodo, "metrica": resultado.metrica,
        "valor": str(resultado.valor), "unidade": resultado.unidade,
        "consultado_em": resultado.consultado_em.isoformat(),
        "_mensagem_gerada": mensagem_gerada,
    }


def _entidade(model: ExecucaoModel) -> Execucao:
    resultado = None
    mensagem_gerada = None
    if model.dados_extraidos is not None:
        registro = model.dados_extraidos
        mensagem_gerada = registro.get("_mensagem_gerada")
        if "periodo_referencia" in registro:
            resultado = ConsorcioResultado(
                administradora=registro["administradora"],
                periodo_referencia=registro["periodo_referencia"],
                grupos_ativos=registro["grupos_ativos"],
                cotas_ativas=registro["cotas_ativas"],
                cotas_contempladas=registro["cotas_contempladas"],
                cotas_comercializadas=registro["cotas_comercializadas"],
                creditos_comercializados=Decimal(registro["creditos_comercializados"]) if registro["creditos_comercializados"] is not None else None,
                segmento=registro["segmento"], uf=registro["uf"],
                abrangencia=registro["abrangencia"],
                data_consulta=datetime.fromisoformat(registro["data_consulta"]),
                fonte=registro["fonte"], source_url=registro["source_url"],
                campos_indisponiveis=registro["campos_indisponiveis"],
            )
        else:
            resultado = Resultado(
                fonte=registro["fonte"], consulta=registro["consulta"], periodo=registro["periodo"],
                metrica=registro["metrica"], valor=Decimal(registro["valor"]), unidade=registro["unidade"],
                consultado_em=datetime.fromisoformat(registro["consultado_em"]),
            )
    return Execucao(
        id=model.id, fonte=model.fonte, tipo_consulta=model.tipo_consulta,
        parametros=model.parametros, data_hora=datetime.fromtimestamp(model.data_hora, timezone.utc),
        status=Status(model.status), hash_consulta=model.hash_consulta,
        dados_extraidos=resultado, erro=model.erro, duplicada_de=model.duplicada_de,
        mensagem_gerada=mensagem_gerada,
    )


class SQLiteExecutionRepository:
    def __init__(self, engine: Engine, duplicate_seconds: int = 30, stale_seconds: int = 150) -> None:
        self.engine = engine
        self.duplicate_seconds = duplicate_seconds
        self.stale_seconds = stale_seconds

    def reservar(self, consulta: Consulta | ConsultaMercado, agora: datetime) -> Execucao:
        try:
            with Session(self.engine) as session:
                # Serializa somente a reserva, inclusive entre processos. Sem transação durante RPA.
                session.execute(text("BEGIN IMMEDIATE"))
                ativa = session.scalar(select(ExecucaoModel).where(
                    ExecucaoModel.chave_ativa == consulta.hash_consulta
                ))
                if ativa and ativa.data_hora <= agora.timestamp() - self.stale_seconds:
                    ativa.status = Status.ERRO
                    ativa.erro = "Execução interrompida ou prazo de processamento excedido."
                    ativa.chave_ativa = None
                    ativa.finalizado_em = agora.timestamp()
                    session.flush()
                    ativa = None
                recente = ativa or session.scalar(select(ExecucaoModel).where(
                    ExecucaoModel.hash_consulta == consulta.hash_consulta,
                    ExecucaoModel.status.in_([Status.SUCESSO, Status.SEM_RESULTADO, Status.ERRO]),
                    ExecucaoModel.finalizado_em > agora.timestamp() - self.duplicate_seconds,
                ).order_by(ExecucaoModel.finalizado_em.desc()).limit(1))
                model = ExecucaoModel(
                    id=str(uuid4()), fonte=FONTE,
                    tipo_consulta="mercado_consorcios" if isinstance(consulta, ConsultaMercado) else DATASET,
                    parametros=consulta.parametros, data_hora=agora.timestamp(),
                    status=Status.DUPLICADA if recente else Status.PROCESSANDO,
                    hash_consulta=consulta.hash_consulta,
                    chave_ativa=None if recente else consulta.hash_consulta,
                    duplicada_de=recente.id if recente else None,
                )
                session.add(model)
                session.flush()
                entidade = _entidade(model)
                session.commit()
                logger.info("execucao_reservada id=%s status=%s", entidade.id, entidade.status)
                return entidade
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível registrar a consulta no banco de dados.") from exc

    def finalizar(
        self, id: str, status: Status, resultado: Resultado | ConsorcioResultado | None,
        erro: str | None, mensagem_gerada: str | None = None,
    ) -> Execucao:
        try:
            with Session(self.engine) as session, session.begin():
                session.execute(text("BEGIN IMMEDIATE"))
                model = session.get(ExecucaoModel, id)
                if model is None or model.status != Status.PROCESSANDO:
                    raise PersistenciaError("A execução não está disponível para atualização.")
                model.status = status
                model.dados_extraidos = _resultado_json(resultado, mensagem_gerada)
                model.erro = erro
                model.chave_ativa = None
                model.finalizado_em = datetime.now(timezone.utc).timestamp()
                session.flush()
                entidade = _entidade(model)
            logger.info("execucao_persistida id=%s status=%s", id, status)
            return entidade
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível salvar o resultado da execução.") from exc

    def obter(self, id: str) -> Execucao | None:
        try:
            with Session(self.engine) as session:
                model = session.get(ExecucaoModel, id)
                return _entidade(model) if model else None
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível consultar a execução.") from exc

    def listar(self) -> list[Execucao]:
        try:
            with Session(self.engine) as session:
                registros = session.scalars(select(ExecucaoModel).order_by(
                    ExecucaoModel.data_hora.desc()
                ).limit(20))
                return [_entidade(registro) for registro in registros]
        except SQLAlchemyError as exc:
            raise PersistenciaError("Não foi possível carregar o histórico.") from exc
