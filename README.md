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
| WHATSAPP_TEMPLATE_NAME | vazio preserva o envio de texto; preenchido seleciona template aprovado |
| WHATSAPP_TEMPLATE_LANGUAGE | pt_BR; deve corresponder ao idioma aprovado do template |

Token, Phone Number ID e versão da API devem ser configurados juntos em `.env`. Nunca
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

A tela usa `POST /api/consultas/mercado`: seleciona um segmento publicado pelo
BCB e, opcionalmente, um período de referência. Em branco, o período mais recente
com cotas ativas para o segmento é descoberto a partir das respostas oficiais.
As opções seguem as métricas oficiais de cotas ativas: Mercado total, Imóveis,
Veículos Pesados, Automóveis, Motocicletas, Outros bens móveis duráveis
(eletroeletrônicos, eletrodomésticos, móveis e outros), Serviços e cinco categorias
adicionais (Ônibus e Micro-ônibus, Caminhões e Caminhões-Tratores, Equipamentos
Rodoviários e Agrícolas, Máquinas Agrícolas, Embarcações e Aeronaves).
Nessas cinco categorias adicionais, o catálogo só permite mostrar cotas ativas.
Nas demais, o resultado mostra cotas ativas,
crédito médio, prazo médio, taxa média de administração e contemplações quando
as métricas correspondentes existem. Não há entrada por administradora.

O cliente `httpx.AsyncClient` consulta o recurso documentado
`/odata/Metricas(DataBase=@DataBase)` com `@DataBase=AAAAMM`, `$format=json` e
`$top=200`. O Swagger foi conferido antes da implementação. O parser rejeita
paginação/truncamento inesperados. Quantidades na unidade `mil` e crédito médio
em `R$ mil` são multiplicados por 1000 com `Decimal`. Taxas são percentuais já
expressos em `%`; prazos são meses. Contemplações de Motocicletas têm unidade
`mi` no catálogo, ambígua para quantidade, e são omitidas. Veículos Pesados,
Outros bens móveis duráveis e Serviços não têm contemplações individualizadas
equivalentes; a consulta continua válida sem esse indicador.
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
`{"segmento":"Automóveis","periodo":null}`.
`GET /api/consultas` lista
as 20 últimas tentativas; `GET /api/consultas/{id}` recupera uma execução.
Registros antigos com o formato anterior permanecem legíveis no histórico.
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

Após consultar, confira os dados e a mensagem. Informe o telefone com DDD e
clique **Enviar WhatsApp**. Entradas como `(86) 99999-9999`, `86 99999-9999`
e `+55 86 99999-9999` são normalizadas para `5586999999999`, na tela e no backend.
A validação é de formato; somente o provedor pode confirmar que há uma conta
WhatsApp disponível nesse número. O botão fica bloqueado com telefone inválido,
durante o envio e quando já existe uma tentativa para a execução.
A aplicação envia a mensagem salva, não um
texto arbitrário recebido do navegador. A consulta nunca dispara envio sozinha.
O destinatário deve autorizar o contato e ter iniciado uma conversa nas últimas
24 horas, conforme a [documentação da Meta](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/).
Envios fora dessa janela exigem templates aprovados. Configure
`WHATSAPP_TEMPLATE_NAME` e `WHATSAPP_TEMPLATE_LANGUAGE` para habilitar esse modo.
O adaptador suporta um template previamente aprovado com **um parâmetro posicional
de texto no corpo (`{{1}}`)**, sem parâmetros em cabeçalho/botões. Esse parâmetro
recebe a mensagem gerada, com espaços normalizados para uma única linha e limite
de 1024 caracteres (mensagens maiores falham sem envio, nunca são truncadas).
O texto fixo e a aprovação do modelo são administrados na Meta; o template deve
ser compatível com esse contrato. O aplicativo não cria nem aprova templates.
Referência: [envio de templates na documentação da Meta](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/messages/template/).
Não há fallback de template para texto em caso de falha. A tela informa a modalidade
configurada; no modo texto, o operador deve verificar a janela de atendimento,
pois este MVP não recebe webhooks de mensagens de entrada.

`POST /api/consultas/{id}/envios` recebe `{"destinatario":"(86) 99999-9999"}`.
O ID da execução identifica a mensagem persistida; não é necessário reenviá-la
pelo navegador. As credenciais e a requisição à Meta ficam somente no servidor.
`GET /api/consultas/{id}/envios` exibe o histórico, também acessível pelos detalhes
da consulta na tela. A tabela adicional `envios` é criada sem alterar ou apagar
as consultas existentes. Guarda destinatário, mensagem, datas, status, ID da Meta,
erro e contador de tentativas repetidas.

Uma reserva transacional por execução, além da unicidade existente
`(execucao_id, destinatario)`, impede envios concorrentes/repetidos, inclusive após
reiniciar o servidor ou trocar o telefone. A mesma operação
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
