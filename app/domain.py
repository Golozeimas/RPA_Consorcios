"""Conceitos independentes de navegador, HTTP e persistência."""

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
SEGMENTOS_BCB = ("Imóveis", "Veículos Pesados", "Automóveis", "Motocicletas", "Serviços")
UFS_BCB = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
})


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
    dados_extraidos: Resultado | "ConsorcioResultado" | None = None
    erro: str | None = None
    duplicada_de: str | None = None
    mensagem_gerada: str | None = None


@dataclass(frozen=True)
class ConsultaMercado:
    administradora: str
    periodo: str | None = None
    segmento: str | None = None
    uf: str | None = None

    def __post_init__(self) -> None:
        administradora = " ".join(self.administradora.split())
        if not administradora or len(administradora) > 160:
            raise ValueError("Informe uma administradora válida.")
        object.__setattr__(self, "administradora", administradora)
        if self.periodo is not None:
            object.__setattr__(self, "periodo", Consulta(self.periodo).periodo)
        if self.segmento is not None and self.segmento not in SEGMENTOS_BCB:
            raise ValueError("Segmento não suportado pelo conjunto de dados.")
        if self.uf is not None and self.uf not in UFS_BCB:
            raise ValueError("UF não suportada pelo conjunto de dados.")
        if self.segmento is not None and self.uf is not None:
            raise ValueError("O BCB não oferece cruzamento de segmento e UF.")

    @property
    def parametros(self) -> dict[str, str]:
        return {
            "administradora_solicitada": self.administradora,
            "periodo": self.periodo or "mais_recente",
            "segmento": self.segmento or "",
            "uf": self.uf or "",
        }

    @property
    def hash_consulta(self) -> str:
        identidade = {"fonte": FONTE, "consulta": "mercado_consorcios", **self.parametros}
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
