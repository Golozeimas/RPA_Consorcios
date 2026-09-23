"""Texto para WhatsApp; geração pura, sem envio."""

from decimal import Decimal
from datetime import timezone

from app.domain import ConsorcioResultado, Resultado


def _inteiro_br(valor: int | None) -> str:
    return f"{valor:,}".replace(",", ".") if valor is not None else "Não disponível"


def _moeda_br(valor: Decimal | None) -> str:
    if valor is None:
        return "Não disponível"
    parte_inteira, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {parte_inteira.replace(',', '.')},{centavos}"


def gerar_mensagem(resultado: ConsorcioResultado | Resultado) -> str:
    if isinstance(resultado, Resultado):
        valor = format(resultado.valor, "f").replace(".", ",")
        return (f"Consulta de Consórcios — Banco Central\nPeríodo: {resultado.periodo}\n"
                f"{resultado.metrica}: {valor} {resultado.unidade}\n"
                f"Fonte: {resultado.fonte}\n"
                f"Consulta realizada em: {resultado.consultado_em:%d/%m/%Y %H:%M} UTC")
    data_utc = resultado.data_consulta.astimezone(timezone.utc)
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
        f"Consulta realizada em: {data_utc:%d/%m/%Y %H:%M} UTC",
    ])
    return "\n".join(linhas)
