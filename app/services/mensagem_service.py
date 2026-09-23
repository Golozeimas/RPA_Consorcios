"""Texto para WhatsApp; geração pura, sem envio."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timezone

from app.domain import ConsorcioResultado, DATASET, PanoramaResultado, Resultado


def _inteiro_br(valor: int | None) -> str:
    return f"{valor:,}".replace(",", ".") if valor is not None else "Não disponível"


def _decimal_br(valor: Decimal, casas: int = 2) -> str:
    arredondado = valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    texto = f"{arredondado:,.{casas}f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def _moeda_br(valor: Decimal | None) -> str:
    if valor is None:
        return "Não disponível"
    return f"R$ {_decimal_br(valor)}"


def gerar_mensagem(resultado: ConsorcioResultado | PanoramaResultado | Resultado) -> str:
    if isinstance(resultado, Resultado):
        valor = format(resultado.valor, "f").replace(".", ",")
        return (f"Consulta de Consórcios — Banco Central\nPeríodo: {resultado.periodo}\n"
                f"{resultado.metrica}: {valor} {resultado.unidade}\n"
                f"Fonte: {resultado.fonte}\n"
                f"Consulta realizada em: {resultado.consultado_em:%d/%m/%Y %H:%M} UTC")
    if isinstance(resultado, PanoramaResultado):
        segmento = "todo o mercado" if resultado.segmento == "Total" else resultado.segmento.lower()
        trimestre = int(resultado.periodo_referencia[-2:]) // 3
        linhas = [
            "Olá! 👋", "",
            f"Consultei os dados agregados do Banco Central sobre consórcios de {segmento}.", "",
            "📊 Panorama do mercado", "",
            f"Período: {resultado.periodo_referencia} ({trimestre}º trimestre)",
            f"Cotas ativas: {_inteiro_br(resultado.cotas_ativas)}",
        ]
        if resultado.credito_medio is not None:
            linhas.append(f"Crédito médio: {_moeda_br(resultado.credito_medio)}")
        if resultado.prazo_medio is not None:
            prazo = _decimal_br(resultado.prazo_medio).removesuffix(",00")
            linhas.append(f"Prazo médio: {prazo} meses")
        if resultado.taxa_administracao_media is not None:
            linhas.append(f"Taxa média de administração: {_decimal_br(resultado.taxa_administracao_media)}%")
        if resultado.contemplacoes is not None:
            linhas.append(f"Contemplações (cotas ativas, últimos 12 meses): {_inteiro_br(resultado.contemplacoes)}")
        linhas.extend(["", f"Fonte: {resultado.fonte} — {DATASET}."])
        return "\n".join(linhas)
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
