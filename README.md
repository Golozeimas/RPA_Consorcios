# Consulta pública BCB — Consórcios

MVP Python/FastAPI: navegador Playwright → extração → validação Pydantic → SQLite
→ resultado e histórico. Não inclui WhatsApp, autenticação ou infraestrutura externa.

## Executar

Python 3.12+ e as dependências já listadas no projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abra http://127.0.0.1:8000. Informe `2025-12` para reproduzir o exemplo investigado.
No Windows execute sem `--reload`/múltiplos workers: o subprocesso do Playwright
precisa de um event loop com suporte a subprocessos.

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

Defina `BROWSER_HEADLESS=false` para acompanhar o navegador na demonstração.
Bootstrap 5 é carregado por CDN; o formulário e o JavaScript local não dependem
de JavaScript do Bootstrap. A consulta requer acesso ao portal e ao domínio Olinda.

## Consulta implementada

[Dados Agregados do Segmento de Consórcios](https://dadosabertos.bcb.gov.br/dataset/dados-agregados-do-segmento-de-consorcios),
métrica **Cotas ativas - Total** (`10`), unidade **mil**, por mês/ano.
O valor é preservado na unidade oficial: `12821.11 mil` não significa 12.821 cotas.
O período não garante publicação. A fonte retorna conjunto vazio para períodos
sem dados. Resultado real observado para dezembro/2025: `12821.11 mil` (pode ser revisado pelo BCB).

O RPA abre o portal, segue o link para o Navegador de Dados, abre Métricas,
preenche Data Base e Máximo, clica Executar e extrai a aba JSON do DOM. Não usa
httpx, requests nem APIRequestContext para substituir o navegador.
Veja [a investigação e os seletores](docs/CONSULTA_BCB.md).

## Arquitetura e contratos

- `app/api`, `templates`, `static`: apresentação; POST JSON validado, GET de histórico/detalhe.
- `app/services`: caso de uso, transformação BCB e portas injetadas.
- `app/domain.py`: entidades, estados, identidade normalizada e erros.
- `app/automation`: adaptador Playwright.
- `app/models`, `repositories`: infraestrutura SQLAlchemy/SQLite, seguindo as pastas existentes.
- `app/main.py`: composição das dependências e ciclo de vida.

`POST /api/consultas` recebe `{"periodo":"2025-12"}`. `GET /api/consultas` lista
as 20 últimas tentativas; `GET /api/consultas/{id}` recupera uma execução.
Pydantic rejeita entrada inválida com 422 antes do RPA. Tentativas válidas são
registradas, inclusive duplicatas e falhas. Não se armazenam payloads HTTP inválidos.

Cada consulta válida reserva um registro PROCESSANDO antes de abrir o navegador.
Uma transação curta `BEGIN IMMEDIATE` e uma chave ativa única previnem corridas.
Repetições durante execução ou até 30 segundos depois da conclusão são registradas
como DUPLICADA, vinculadas ao original, sem nova navegação. Depois desse intervalo
a mesma consulta pode ser realizada novamente. A janela não é prorrogada por duplicatas.
Se o processo morrer, a próxima tentativa da mesma consulta marca a reserva vencida
como ERRO após o timeout total + 30 segundos; o intervalo de duplicidade ainda se aplica.

Estados finais: SUCESSO, SEM_RESULTADO, ERRO e DUPLICADA. Falhas externas são
controladas, com detalhes técnicos em logging e mensagem segura na interface.
Se o banco falhar antes da reserva, o RPA não começa (503); se falhar ao finalizar,
a reserva existente continua rastreável. Um banco indisponível não pode registrar
novas tentativas; nesse caso o log é a evidência disponível.

## Verificação

```powershell
python -m pytest
python -m compileall -q app tests
$env:RUN_BROWSER_TESTS="1"
python -m pytest tests/integration/test_browser.py
```

Os testes comuns usam fakes/SQLite temporário e não dependem do BCB. Testes de
navegador determinísticos são opcionais e usam rotas locais interceptadas; a
consulta real deve ser conferida separadamente pela aplicação. Não há linter ou
verificador de tipos configurado no repositório.

Em 23/09/2026, o projeto foi verificado com Python 3.13.15 sem contornos no
interpretador: 47 testes comuns passaram, 2 testes opcionais de Chromium
passaram, o servidor Uvicorn iniciou e uma consulta real ao BCB retornou
`12821.11 mil` para `2025-12`.
