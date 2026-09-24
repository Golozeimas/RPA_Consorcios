"""Formato da mensagem de automóveis exibida e persistida pela aplicação."""

CAMPOS_AUTOMOVEIS = (
    "periodo", "cotas_ativas", "credito_medio", "prazo_medio",
    "taxa_administracao", "contemplacoes",
)

TEXTO_AUTOMOVEIS = (
    "Olá! 👋\n\n"
    "Consultei os dados agregados do Banco Central sobre consórcios de automóveis.\n\n"
    "📊 Panorama do mercado\n\n"
    "Período: {periodo}\n"
    "Cotas ativas: {cotas_ativas}\n"
    "Crédito médio: {credito_medio}\n"
    "Prazo médio: {prazo_medio}\n"
    "Taxa média de administração: {taxa_administracao}\n"
    "Contemplações (cotas ativas, últimos 12 meses): {contemplacoes}\n\n"
    "Fonte: Banco Central do Brasil  Dados Agregados do Segmento de Consórcios."
)
