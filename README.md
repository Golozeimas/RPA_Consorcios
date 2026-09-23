# Consulta pública BCB — Consórcios

MVP Python/FastAPI: API oficial BCB via httpx → validação Pydantic → SQLite
→ resultado e mensagem → envio explícito pela Meta WhatsApp Cloud API → histórico.

## Executar

Python 3.12+ e as dependências já listadas no projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000. O período é opcional; em branco, a aplicação consulta
os períodos trimestrais até encontrar o mais recente publicado para o filtro.
Informe `2025-12` para reproduzir o exemplo inicial investigado.
Chromium não é necessário para consultar pela aplicação. O adaptador Playwright
anterior foi preservado para os testes/demonstrações de navegador existentes.

O SQLite é criado em `data/consultas.sqlite3` na inicialização. Não há reset de
dados existentes. `.env` é opcional; `.env.example` contém somente nomes. Valores
vazios usam os padrões abaixo:

| Variável | Padrão |
| --- | --- |
| DATABASE_PATH | data/consultas.sqlite3 na raiz do projeto |
| BROWSER_TIMEOUT_MS | 30000 |
| QUERY_TIMEOUT_SECONDS | 120 |
| DUPLICATE_SECONDS | 30 |
| BROWSER_HEADLESS | true |
| HTTP_TIMEOUT_SECONDS | 30 |
| WHATSAPP_ACCESS_TOKEN | vazio (envio desabilitado até configurar) |
| WHATSAPP_PHONE_NUMBER_ID | vazio |
| WHATSAPP_API_VERSION | vazio; informe uma versão Graph API suportada, no formato vNN.0 |

As três variáveis `WHATSAPP_*` devem ser configuradas juntas em `.env`. Nunca
versione esse arquivo. Configuração parcial/ inválida impede a inicialização.
As variáveis `BROWSER_*` são usadas somente pelo adaptador de navegador legado.
Bootstrap 5 é carregado por CDN; o formulário e o JavaScript local não dependem
de JavaScript do Bootstrap. A consulta requer acesso ao domínio Olinda.

## Consultas implementadas

[Dados Agregados do Segmento de Consórcios](https://dadosabertos.bcb.gov.br/dataset/dados-agregados-do-segmento-de-consorcios),
métrica **Cotas ativas - Total** (`10`), unidade **mil**, por mês/ano.
O valor é preservado na unidade oficial: `12821.11 mil` não significa 12.821 cotas.
O período não garante publicação. A fonte retorna conjunto vazio para períodos
sem dados. Resultado real observado para dezembro/2025: `12821.11 mil` (pode ser revisado pelo BCB).

O endpoint inicial `POST /api/consultas` permanece compatível: consulta a métrica
10 em um período obrigatório, agora usando o mesmo cliente HTTP oficial.

A tela usa `POST /api/consultas/mercado`: requer o nome da administradora
solicitada, aceita período, segmento ou UF opcionais e retorna métricas agregadas.
O conjunto oficial **não permite filtrar por administradora**. Por isso o nome é
registrado como entrada, enquanto `administradora` no resultado é `null` e aparece
em `campos_indisponiveis`. A interface e a mensagem deixam claro que os valores
não pertencem à empresa informada. Segmento e UF não podem ser combinados; o BCB
não publica esse cruzamento. UF oferece somente cotas ativas por estado.

O cliente `httpx.AsyncClient` consulta o recurso documentado
`/odata/Metricas(DataBase=@DataBase)` com `@DataBase=AAAAMM`, `$format=json` e
`$top=200`. O Swagger foi conferido antes da implementação. O parser rejeita
paginação/truncamento inesperados. Quantidades na unidade `mil` são multiplicadas por 1000 com `Decimal`
antes de virarem inteiros. Créditos comercializados permanecem indisponíveis:
o catálogo traz valor **médio** de crédito, semanticamente diferente do total.
A mensagem é gerada a partir dos dados validados e salva no histórico antes do envio.
Veja [o mapeamento e a investigação](docs/CONSULTA_BCB.md).

## Arquitetura e contratos

- `app/api`, `templates`, `static`: apresentação; POST JSON validado, GET de histórico/detalhe.
- `app/services`: caso de uso, transformação BCB e portas injetadas.
- `app/domain.py`: entidades, estados, identidade normalizada e erros.
- `app/automation`: adaptador Playwright.
- `app/integrations`: clientes HTTP BCB e Meta; sem regras de negócio nas rotas.
- `app/models`, `repositories`: infraestrutura SQLAlchemy/SQLite, seguindo as pastas existentes.
- `app/main.py`: composição das dependências e ciclo de vida.

`POST /api/consultas` recebe `{"periodo":"2025-12"}`.
`POST /api/consultas/mercado` recebe, por exemplo,
`{"administradora":"Nome solicitado","periodo":null,"segmento":null,"uf":null}`.
`GET /api/consultas` lista
as 20 últimas tentativas; `GET /api/consultas/{id}` recupera uma execução.
Pydantic rejeita entrada inválida com 422 antes da consulta. Tentativas válidas são
registradas, inclusive duplicatas e falhas. Não se armazenam payloads HTTP inválidos.

Cada consulta válida reserva um registro PROCESSANDO antes de acessar o BCB.
Uma transação curta `BEGIN IMMEDIATE` e uma chave ativa única previnem corridas.
Repetições durante execução ou até 30 segundos depois da conclusão são registradas
como DUPLICADA, vinculadas ao original, sem nova requisição. Depois desse intervalo
a mesma consulta pode ser realizada novamente. A janela não é prorrogada por duplicatas.
Se o processo morrer, a próxima tentativa da mesma consulta marca a reserva vencida
como ERRO após o timeout total + 30 segundos; o intervalo de duplicidade ainda se aplica.

Estados finais: SUCESSO, SEM_RESULTADO, ERRO e DUPLICADA. Falhas externas são
controladas, com detalhes técnicos em logging e mensagem segura na interface.
Se o banco falhar antes da reserva, a consulta não começa (503); se falhar ao finalizar,
a reserva existente continua rastreável. Um banco indisponível não pode registrar
novas tentativas; nesse caso o log é a evidência disponível.

## Enviar WhatsApp

Após consultar, confira os dados e a mensagem. Informe o telefone internacional
com DDI e clique **Enviar WhatsApp**. A aplicação envia o texto salvo, não um
texto arbitrário recebido do navegador. A consulta nunca dispara envio sozinha.
O destinatário deve autorizar o contato e ter iniciado uma conversa nas últimas
24 horas, conforme a [documentação da Meta](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/).
Envios fora dessa janela exigem templates aprovados, fora deste fluxo de texto.

`POST /api/consultas/{id}/envios` recebe `{"destinatario":"<telefone internacional>"}`.
`GET /api/consultas/{id}/envios` exibe o histórico, também acessível pelos detalhes
da consulta na tela. A tabela adicional `envios` é criada sem alterar ou apagar
as consultas existentes. Guarda destinatário, mensagem, datas, status, ID da Meta,
erro e contador de tentativas repetidas.

Uma reserva transacional e unicidade `(execucao_id, destinatario)` impedem envios
concorrentes/repetidos, inclusive após reiniciar o servidor. A mesma operação
retorna seu registro anterior, mesmo em caso de erro. Uma nova consulta deliberada
pode originar um novo envio; a janela de duplicidade da consulta continua valendo.
Não há retries automáticos. Para corrigir falhas definitivas, ajuste a configuração
e faça uma nova consulta; antes disso, confira o histórico.

Estados: ENVIANDO, ACEITO, ERRO e INCERTO. ACEITO exige ID válido devolvido pela
Meta e não significa entregue/lido; não implementamos webhooks de entrega.
Timeout, HTTP 5xx ou resposta inválida ficam INCERTO. Interrupção abrupta ou falha
ao salvar deixa a reserva bloqueada; uma tentativa repetida após o prazo converte
ENVIANDO em INCERTO. Verifique no provedor antes de iniciar outro envio.

## Verificação

```powershell
python -m pytest
python -m compileall -q app tests
$env:RUN_BROWSER_TESTS="1"
python -m playwright install chromium
python -m pytest tests/integration/test_browser.py
$env:RUN_LIVE_BCB="1"
python -m pytest tests/integration/test_live_bcb.py
```

Os testes comuns usam fakes/SQLite temporário e não dependem do BCB. Testes de
navegador determinísticos são opcionais e usam rotas locais interceptadas; a
consulta real deve ser conferida separadamente pela aplicação. Não há linter ou
verificador de tipos configurado no repositório. A Meta é simulada com
`httpx.MockTransport`; os testes nunca enviam mensagens reais.

Em 23/09/2026, a consulta agregada real encontrou DataBase `202606` e
normalizou 16.251 grupos ativos, 13.376.260 cotas ativas, 1.855.350 cotas
contempladas e 5.723.740 comercializadas. Resultados podem mudar na fonte.
