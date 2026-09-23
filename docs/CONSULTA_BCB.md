# Consulta BCB selecionada

## Integração atual: HTTP/OData

O Swagger oficial foi revalidado em 23/09/2026:
https://olinda.bcb.gov.br/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/swagger-ui3#/

O documento embutido declara basePath
`/olinda/servico/PANORAMA_DE_CONSORCIOS/versao/v1/odata` e os recursos
`GrupoDeMetricas()`, `CadastroDeMetricas()` e `Metricas(DataBase=@DataBase)`.
O último exige `@DataBase` inteiro; `$format`, `$top`, `$skip`, `$filter` e
`$orderby` são opcionais. O cliente atual usa `@DataBase`, `$format=json` e
`$top=200`, sem filtros por campos não suportados. Seleção de métricas ocorre
no parser validado. Nomes e tipos de resposta continuam iguais ao mapeamento abaixo.

Ambas as rotas da aplicação agora usam HTTP via `BCBClient`, sem navegador no
caminho da consulta. O Playwright anterior permanece disponível e testado, mas
não é instanciado pela aplicação. A investigação de DOM abaixo é histórica.

## Investigação original do navegador

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
O formulário gera a URL OData. O adaptador de navegador original
aguarda a resposta disparada pelo clique, abre a aba JSON e lê `pre.dados`
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

## Mapeamento verificado para a consulta ampliada

Inspeção da documentação oficial e dos recursos `GrupoDeMetricas`,
`CadastroDeMetricas` e `Metricas` em 23/09/2026. O recurso `Metricas` recebe
somente `DataBase` (`AAAAMM`) e devolve `DataBase`, `IdMetrica`, `Grupo`,
`Metrica`, `Valor` e `Unidade`. Não há dimensão ou identificador de
administradora, segmento ou UF no registro; os dois últimos aparecem como
métricas distintas no catálogo. Os resultados são agregados, sem atribuição
a uma administradora.

| Campo | IdMetrica / nome oficial | Unidade | Limite semântico |
| --- | --- | --- | --- |
| grupos_ativos | 9 — Grupos de Consórcio ativos - Total | unidade | Nacional; não há desagregação por segmento/UF |
| cotas_ativas | 10 — Cotas ativas - Total | mil | Nacional |
| cotas_contempladas | 28 — Cotas ativas contempladas no últimos 12 meses - Total | mil | Janela de 12 meses até a DataBase |
| cotas_comercializadas | 54 — Cotas Comercializadas nos últimos 12 meses - Total | mil | Janela de 12 meses até a DataBase |
| créditos_comercializados | Nenhuma métrica correspondente | — | 85 é **valor médio** de créditos de grupos constituídos, não total comercializado |
| administradora | Nenhum campo/ID no recurso | — | Nome informado pelo usuário não é comprovação de vínculo aos dados |
| período_referencia | DataBase retornado | AAAAMM | Obtido da resposta, não da data de execução |

Desagregação verificada no catálogo: cotas ativas 11 (Imóveis), 12 (Veículos
Pesados), 13 (Automóveis), 14 (Motocicletas) e 16 (Serviços); contempladas
31 (Imóveis), 34 (Automóveis), 37 (Motocicletas); comercializadas 55
(Imóveis), 56 (Veículos Pesados), 57 (Automóveis), 58 (Motocicletas), 60
(Serviços). A métrica 37 consta com unidade `mi` no catálogo/retorno, ambígua
em relação a `mil`; não converter sem confirmação do BCB. Métricas 99–125
representam **somente cotas ativas por estado**. A entrada simultânea de
segmento e UF não tem métrica conjunta.

Respostas reais: para DataBase `202606`, 125 registros, incluindo IDs 9=16251
unidades, 10=13376.26 mil, 28=1855.35 mil e 54=5723.74 mil. Para `202609`,
resposta HTTP 200 com `value: []`. Assim, junho/2026 é o período mais recente
observado, mas o código deve descobri-lo consultando as respostas, sem fixar
esse mês.
