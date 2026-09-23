"""Texto para WhatsApp; geração pura, sem envio."""

from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain import ConsorcioResultado


def _inteiro_br(valor: int | None) -> str:
    return f"{valor:,}".replace(",", ".") if valor is not None else "Não disponível"


def _moeda_br(valor: Decimal | None) -> str:
    if valor is None:
        return "Não disponível"
    parte_inteira, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {parte_inteira.replace(',', '.')},{centavos}"


def gerar_mensagem(resultado: ConsorcioResultado) -> str:
    data_local = resultado.data_consulta.astimezone(ZoneInfo("America/Sao_Paulo"))
    linhas = [
        "Consulta de Consórcios — Banco Central",
        "Dados agregados do mercado; sem atribuição a uma administradora específica.",
        f"Período de referência: {resultado.periodo_referencia}",
        f"Abrangência: {resultado.abrangencia}",
    ]
    if resultado.segmento:
        linhas.append(f"Segmento: {resultado.segmento}")
    linhas.extend([
        f"Grupos ativos: {_inteiro_br(resultado.grupos_ativos)}",
        f"Cotas ativas: {_inteiro_br(resultado.cotas_ativas)}",
        f"Cotas contempladas (últimos 12 meses): {_inteiro_br(resultado.cotas_contempladas)}",
        f"Cotas comercializadas (últimos 12 meses): {_inteiro_br(resultado.cotas_comercializadas)}",
        f"Créditos comercializados: {_moeda_br(resultado.creditos_comercializados)}",
        f"Fonte: {resultado.fonte}",
        f"Consulta realizada em: {data_local:%d/%m/%Y %H:%M} (Brasília)",
    ])
    return "\n".join(linhas)
