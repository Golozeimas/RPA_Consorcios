# Consulta BCB selecionada

Inspeção em 23/09/2026, antes da implementação, usando Chromium/Playwright.

- Dataset: Dados Agregados do Segmento de Consórcios.
- Portal: https://dadosabertos.bcb.gov.br/dataset/dados-agregados-do-segmento-de-consorcios
- Interface vinculada pelo portal: https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/aplicacao#!/
- Recursos observados: GrupoDeMetricas, CadastroDeMetricas e Metricas; documentação,
  Swagger e endpoint OData também estão vinculados pelo portal.
- Consulta escolhida: **Cotas ativas - Total**, IdMetrica `10`, unidade `mil`.
  É um agregado nacional simples, sem necessidade de somar segmentos.
- Entrada: período mensal `AAAA-MM`, convertido para DataBase `AAAAMM`.
  A existência de dados depende da publicação; não presumir que todo mês tem resultado.
- Campos reais: DataBase (inteiro), IdMetrica (texto), Grupo, Metrica, Valor
  (decimal JSON) e Unidade.

## Evidência e comportamento

O catálogo retornou o código 10 e o nome acima. A consulta Metricas para `202512`
retornou 125 registros; a métrica 10 tinha Valor `12821.11`, Unidade `mil`.
`201001` retornou HTTP 200 e `value: []`. `202513` também retorna vazio na fonte,
mas será rejeitado pela aplicação como mês inválido.

A interface é Angular e carrega os resultados de forma assíncrona após **Executar**.
O formulário gera a URL OData; a aplicação implementada não fará HTTP direto.
O RPA aguarda a resposta disparada pelo clique, abre a aba JSON e lê `pre.dados`
no DOM. A grade é virtualizada, portanto extrair somente suas linhas visíveis
perderia registros. A aba JSON contém o conjunto retornado.

Há limitação/paginação por Primeiro e Máximo. Máximo inicia em 100; a página
mostra um aviso quando existem mais registros (a resposta pode incluir um registro
adicional). Usaremos 200, suficiente para os 125 observados, e rejeitaremos resposta
truncada ou com nextLink, sem apresentar um resultado parcial como completo.

O filtro `IdMetrica eq '10'`, apesar de corresponder ao tipo documentado, retornou
HTTP 500 e `Erro desconhecido` em `pre.alert-danger`. Por isso consultaremos as
métricas do período sem filtro e selecionaremos a métrica 10 após extração.
Remover Máximo não concluiu prontamente na inspeção; manteremos limite explícito.

Seletores verificados:

- `li.resource-item` contendo `a[title="API - Navegador de Dados"]`; link
  `Explorar` revela o link com href exato do navegador, que abre nova aba
  (`target="_blank"`), aguardada por `expect_popup`.
- Link por role/nome `Métricas`.
- `#param0`: único parâmetro do recurso Metricas, Data Base. O label não possui
  `for`, portanto get_by_label não funciona nessa interface.
- `input[ng-model="formulario.$top"]`: Máximo, sem id/label associado.
- Botão por role/nome `Executar`; aba por role/nome `JSON`.
- `pre.dados:visible`: resultado JSON; `pre.alert-danger`: erro.
- `.loader`: sobreposição de carregamento controlada pelo Angular; aguardar ocultação.

## Decisões do MVP

Uma métrica fixa e período informado pelo usuário; unidade original preservada.
Resultado validado antes de persistir. Estados PROCESSANDO, SUCESSO,
SEM_RESULTADO, ERRO e DUPLICADA. Duplicatas apontam para a execução original.
Reserva transacional SQLite e chave ativa única impedem corrida; uma janela curta
após conclusão evita reenvio imediato. Após a janela uma nova consulta é permitida.
Execuções interrompidas expiram após o prazo total mais uma margem e ficam como
ERRO quando uma nova tentativa da mesma consulta as encontra.
