"""Conceitos independentes de navegador, HTTP e persistência."""

from __future__ import annotations

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
SEGMENTOS_PRINCIPAIS_BCB = (
    "Imóveis", "Veículos Pesados", "Automóveis", "Motocicletas",
    "Outros bens móveis duráveis (eletroeletrônicos, eletrodomésticos, móveis e outros)",
    "Serviços",
)
SUBSEGMENTOS_BCB = (
    "Ônibus e Micro-ônibus (cód. 21)",
    "Caminhões e Caminhões-Tratores (cód. 22)",
    "Equipamentos Rodoviários e Agrícolas (cód. 23)",
    "Máquinas Agrícolas (cód. 24)",
    "Embarcações e Aeronaves (cód. 25)",
)
SEGMENTOS_BCB = ("Total", *SEGMENTOS_PRINCIPAIS_BCB, *SUBSEGMENTOS_BCB)


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


class EnvioError(ConsultaError):
    def __init__(self, message: str, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class EnvioIncertoError(EnvioError):
    """O provedor pode ter aceitado; não repetir automaticamente."""


class StatusEnvio(StrEnum):
    CRIADO = "CRIADO"
    NA_FILA = "NA_FILA"
    ENVIADO = "ENVIADO"
    ENTREGUE = "ENTREGUE"
    LIDO = "LIDO"
    FALHOU = "FALHOU"
    NAO_ENTREGUE = "NAO_ENTREGUE"
    ENVIANDO = "ENVIANDO"
    ACEITO = "ACEITO"
    ERRO = "ERRO"
    INCERTO = "INCERTO"


def normalizar_destinatario(valor: str) -> str:
    valor = valor.strip()
    if valor.startswith("whatsapp:"):
        valor = valor.removeprefix("whatsapp:")
    if not re.fullmatch(r"\+?[0-9\s()-]+", valor):
        raise ValueError("Informe um número de WhatsApp válido.")
    telefone = re.sub(r"[\s()+-]", "", valor)
    nacional = r"[1-9][0-9](?:9[0-9]{7,8}|[2-5][0-9]{7})"
    if not valor.startswith("+") and re.fullmatch(nacional, telefone):
        telefone = "55" + telefone
    elif not valor.startswith("+") and len(telefone) in {10, 11}:
        # Preserva números internacionais norte-americanos já normalizados.
        if not (len(telefone) == 11 and telefone.startswith("1")):
            raise ValueError("Informe um número de WhatsApp válido com DDD.")
    if telefone.startswith("55") and not re.fullmatch("55" + nacional, telefone):
        raise ValueError("Informe um número brasileiro válido com DDD.")
    if not re.fullmatch(r"[1-9][0-9]{7,14}", telefone):
        raise ValueError("Informe um número de WhatsApp válido.")
    if not valor.startswith("+") and len(telefone) < 10:
        raise ValueError("Informe o DDD e o número de WhatsApp.")
    return telefone


@dataclass(frozen=True)
class ConfirmacaoEnvio:
    provedor_id: str
    provedor_status: str
    status: StatusEnvio = StatusEnvio.ACEITO
    erro: str | None = None
    error_code: int | None = None
    remetente: str | None = None
    criado_em: datetime | None = None
    mensagem_enviada: str | None = None


@dataclass(frozen=True)
class EventoEnvio:
    provedor_id: str
    provedor_status: str
    status: StatusEnvio
    error_code: int | None = None
    erro: str | None = None
    event_type: str | None = None


def pode_avancar_envio(atual: StatusEnvio, novo: StatusEnvio) -> bool:
    """Entrega comprovada prevalece; falhas terminais não voltam à fila."""
    ordem = {StatusEnvio.CRIADO: 0, StatusEnvio.ACEITO: 1, StatusEnvio.NA_FILA: 1,
             StatusEnvio.ENVIANDO: 2, StatusEnvio.ENVIADO: 3,
             StatusEnvio.ENTREGUE: 4, StatusEnvio.LIDO: 5}
    falhas = {StatusEnvio.FALHOU, StatusEnvio.NAO_ENTREGUE, StatusEnvio.ERRO}
    if atual in {StatusEnvio.ENTREGUE, StatusEnvio.LIDO}:
        return ordem.get(novo, -1) > ordem[atual]
    if novo in {StatusEnvio.ENTREGUE, StatusEnvio.LIDO}:
        return True
    if atual in falhas:
        return False
    if novo in falhas:
        return True
    return ordem.get(novo, -1) > ordem.get(atual, -1)


@dataclass(frozen=True)
class Envio:
    id: str
    execucao_id: str
    destinatario: str
    mensagem: str
    status: StatusEnvio
    data_hora: datetime
    provedor_id: str | None = None
    provedor_status: str | None = None
    erro: str | None = None
    provider: str | None = None
    initial_status: str | None = None
    error_code: int | None = None
    remetente: str | None = None
    criado_em: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    eventos: tuple[dict[str, str | int | bool | None], ...] = ()
    mensagem_enviada: str | None = None


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
    dados_extraidos: Resultado | ConsorcioResultado | PanoramaResultado | None = None
    erro: str | None = None
    duplicada_de: str | None = None
    mensagem_gerada: str | None = None


@dataclass(frozen=True)
class ConsultaMercado:
    segmento: str
    periodo: str | None = None

    def __post_init__(self) -> None:
        # Aceita o identificador abreviado das consultas anteriores, mas grava o nome oficial.
        if self.segmento == "Outros bens móveis duráveis":
            object.__setattr__(self, "segmento", SEGMENTOS_PRINCIPAIS_BCB[4])
        if self.segmento not in SEGMENTOS_BCB:
            raise ValueError("Selecione um segmento publicado pelo BCB.")
        if self.periodo is not None:
            object.__setattr__(self, "periodo", Consulta(self.periodo).periodo)

    @property
    def parametros(self) -> dict[str, str]:
        return {
            "periodo": self.periodo or "mais_recente",
            "segmento": self.segmento,
        }

    @property
    def hash_consulta(self) -> str:
        identidade = {"fonte": FONTE, "consulta": "panorama_consorcios", **self.parametros}
        return sha256(json.dumps(identidade, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ConsorcioResultado:
    administradora: str | None
    periodo_referencia: str
    grupos_ativos: int | None
    cotas_ativas: int | None
    cotas_contempladas: int | None
    cotas_comercializadas: int | None
    creditos_comercializados: Decimal | None
    segmento: str | None
    uf: str | None
    abrangencia: str
    data_consulta: datetime
    fonte: str
    source_url: str
    campos_indisponiveis: list[str]


@dataclass(frozen=True)
class PanoramaResultado:
    segmento: str
    periodo_referencia: str
    cotas_ativas: int
    credito_medio: Decimal | None
    prazo_medio: Decimal | None
    taxa_administracao_media: Decimal | None
    contemplacoes: int | None
    data_consulta: datetime
    fonte: str
    source_url: str
    campos_indisponiveis: list[str]
