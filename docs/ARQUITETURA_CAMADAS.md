# Arquitetura em Camadas — RPA para Consulta Pública e Envio via WhatsApp

## 1. Objetivo

Este documento define a arquitetura em camadas do sistema desenvolvido para o desafio técnico de **RPA para consulta pública e envio via WhatsApp**.

A solução tem como fluxo principal:

1. Receber uma solicitação de consulta pela interface web.
2. Executar uma automação em um sistema público.
3. Extrair e estruturar os dados encontrados.
4. Validar e tratar as informações obtidas.
5. Registrar a execução e seu histórico.
6. Gerar uma mensagem personalizada.
7. Enviar a mensagem via WhatsApp.
8. Registrar o status final do processamento e do envio.

A arquitetura foi organizada para manter separação clara de responsabilidades, facilitar manutenção, testes, rastreabilidade e evolução do sistema.

---

## 2. Stack utilizada

A arquitetura considera a stack definida para o projeto:

- **Python 3.12+** — linguagem principal.
- **FastAPI** — backend e API da aplicação.
- **Uvicorn** — servidor ASGI.
- **Playwright** — automação do navegador e extração dos dados.
- **Pydantic** — validação e estruturação dos dados.
- **SQLAlchemy** — persistência e acesso ao banco.
- **SQLite** — banco de dados do MVP.
- **httpx** — comunicação HTTP com serviços externos.
- **Meta WhatsApp Cloud API** — envio das mensagens.
- **Jinja2** — renderização das páginas HTML.
- **Bootstrap 5** — interface e responsividade.
- **python-dotenv** — carregamento das variáveis de ambiente.
- **logging** — registro de logs técnicos.
- **pytest** — testes automatizados.

---

## 3. Visão geral da arquitetura

A aplicação será dividida nas seguintes camadas:

```text
┌──────────────────────────────────────────┐
│          Camada de Apresentação          │
│   FastAPI Routes + Jinja2 + Bootstrap    │
└──────────────────────┬───────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────┐
│          Camada de Aplicação             │
│              Services                    │
│ Coordenação dos casos de uso e regras    │
└───────────────┬───────────────┬──────────┘
                │               │
                ▼               ▼
┌──────────────────────┐  ┌──────────────────────┐
│ Camada de Automação  │  │ Camada de Integração │
│      Playwright      │  │ WhatsApp Cloud API   │
└──────────────────────┘  └──────────────────────┘
                │
                ▼
┌──────────────────────────────────────────┐
│           Camada de Dados                │
│ Repositories + SQLAlchemy + SQLite       │
└──────────────────────────────────────────┘

        Camadas de apoio transversais
   Schemas / Configuração / Logs / Testes
```

A camada de apresentação não deve acessar diretamente o Playwright, o banco de dados ou a API do WhatsApp. Essas dependências devem ser coordenadas pela camada de aplicação.

---

## 4. Estrutura de diretórios

```text
rpa-honda/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── consulta.py
│   │       └── historico.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── consulta_service.py
│   │   ├── mensagem_service.py
│   │   └── rpa_service.py
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── execucao_repository.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── execucao.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── consulta.py
│   │   └── execucao.py
│   │
│   ├── automation/
│   │   ├── __init__.py
│   │   └── consulta_rpa.py
│   │
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── whatsapp.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── logging_config.py
│   │
│   ├── templates/
│   │   ├── index.html
│   │   └── historico.html
│   │
│   └── static/
│       ├── css/
│       └── js/
│
├── tests/
│   ├── test_consulta_service.py
│   ├── test_mensagem_service.py
│   └── test_rpa.py
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 5. Responsabilidade das camadas

### 5.1. Camada de apresentação — `app/api`

Responsável por receber as interações do usuário e transformar as requisições em chamadas para a camada de aplicação.

Responsabilidades:

- Receber os dados de consulta.
- Validar parâmetros básicos da requisição.
- Chamar os serviços correspondentes.
- Renderizar páginas HTML ou retornar respostas da API.
- Exibir mensagens de sucesso ou erro.
- Disponibilizar consulta ao histórico.

Não deve:

- Executar Playwright diretamente.
- Fazer consultas SQL diretamente.
- Chamar a API do WhatsApp diretamente.
- Concentrar regras de negócio.

---

### 5.2. Camada de aplicação — `app/services`

Responsável por coordenar os casos de uso do sistema.

Responsabilidades:

- Iniciar uma nova execução.
- Verificar se a consulta já foi processada.
- Coordenar a execução do RPA.
- Validar o resultado obtido.
- Solicitar a persistência dos dados.
- Gerar a mensagem personalizada.
- Solicitar o envio via WhatsApp.
- Atualizar o status final da execução.
- Coordenar tratamento de falhas.

Exemplos de serviços:

- `ConsultaService`
- `RPAService`
- `MensagemService`

Essa camada representa a principal orquestração do fluxo da aplicação.

---

### 5.3. Camada de automação — `app/automation`

Responsável exclusivamente pela interação com o sistema público por meio do navegador.

Responsabilidades:

- Abrir o navegador.
- Acessar o sistema de consulta.
- Navegar até a área necessária.
- Preencher os dados da consulta.
- Aguardar carregamentos.
- Identificar os elementos relevantes da página.
- Extrair as informações encontradas.
- Detectar ausência de resultados.
- Detectar falhas de navegação ou timeout.
- Devolver os dados extraídos para a camada de aplicação.

Tecnologia principal:

- Playwright.

A automação não deve conhecer detalhes da interface web administrativa, do banco de dados ou da API do WhatsApp.

---

### 5.4. Camada de dados — `app/repositories`

Responsável pelo acesso ao banco de dados.

Responsabilidades:

- Salvar novas execuções.
- Consultar histórico.
- Buscar execuções anteriores.
- Atualizar status de processamento e envio.
- Registrar mensagens e erros.
- Apoiar o controle de duplicidade.

A camada de aplicação deve utilizar os repositórios em vez de executar consultas diretamente no banco.

---

### 5.5. Modelos de persistência — `app/models`

Responsáveis por representar as entidades persistidas no banco de dados por meio do SQLAlchemy.

Um registro de execução deve ser capaz de armazenar, conforme necessário:

- Identificador da execução.
- Dado utilizado na consulta.
- Informações encontradas.
- Data e hora.
- Destinatário.
- Mensagem gerada.
- Status do processamento.
- Status do envio.
- Descrição do erro, quando houver.
- Identificador ou hash utilizado para evitar duplicidade.

---

### 5.6. Schemas e validação — `app/schemas`

Responsáveis por estruturar e validar dados que entram e saem das diferentes partes do sistema.

Tecnologia principal:

- Pydantic.

Responsabilidades:

- Validar campos obrigatórios.
- Garantir tipos corretos.
- Normalizar os dados extraídos.
- Representar respostas da aplicação.
- Reduzir o acoplamento entre modelos do banco e respostas da API.

---

### 5.7. Camada de integração — `app/integrations`

Responsável pela comunicação com serviços externos.

Para este projeto, a principal integração é o WhatsApp.

Responsabilidades:

- Montar a requisição HTTP necessária.
- Utilizar as credenciais configuradas no ambiente.
- Enviar a mensagem pela Meta WhatsApp Cloud API.
- Interpretar a resposta da API.
- Retornar o status do envio.
- Tratar erros de comunicação.

Tecnologias principais:

- `httpx`
- Meta WhatsApp Cloud API.

---

### 5.8. Camada de infraestrutura e configuração — `app/core`

Responsável por configurações compartilhadas da aplicação.

Responsabilidades:

- Configuração do banco de dados.
- Leitura das variáveis de ambiente.
- Configuração de logs.
- Definição de parâmetros globais.
- Configuração de serviços necessários à aplicação.

Arquivos sugeridos:

```text
core/
├── config.py
├── database.py
└── logging_config.py
```

---

## 6. Fluxo entre as camadas

### Caso de uso: executar consulta e enviar mensagem

```text
Usuário
  │
  ▼
Interface Web
  │
  ▼
Route FastAPI
  │
  ▼
ConsultaService
  │
  ├──► Repository
  │      Verifica duplicidade
  │
  ├──► RPAService
  │       │
  │       ▼
  │    Playwright
  │       │
  │       ▼
  │    Sistema público
  │
  ├──► Pydantic
  │      Valida e estrutura dados
  │
  ├──► Repository
  │      Registra execução
  │
  ├──► MensagemService
  │      Gera mensagem
  │
  ├──► WhatsAppIntegration
  │       │
  │       ▼
  │    WhatsApp Cloud API
  │
  └──► Repository
         Atualiza status final
```

---

## 7. Regras de dependência

Para manter a arquitetura organizada, devem ser respeitadas as seguintes regras:

### Permitido

```text
api           → services
services      → automation
services      → repositories
services      → integrations
services      → schemas
repositories  → models
repositories  → core/database
integrations  → core/config
models        → core/database
```

### Evitar

```text
api → SQLAlchemy diretamente
api → Playwright diretamente
api → WhatsApp diretamente
automation → banco de dados
automation → interface web
repository → FastAPI
models → services
```

A regra principal é que a camada externa não deve assumir responsabilidades pertencentes a outra camada.

---

## 8. Controle de duplicidade e idempotência

O sistema deve impedir processamento ou envio duplicado.

A estratégia pode utilizar um identificador único ou hash calculado a partir das informações relevantes da consulta.

Fluxo recomendado:

```text
Nova consulta
    │
    ▼
Gerar identificador/hash
    │
    ▼
Consultar histórico
    │
    ├── Já enviado ──► impedir novo envio
    │
    └── Não existe ──► continuar processamento
```

O status da execução também deve ser utilizado para evitar reenvios acidentais.

---

## 9. Tratamento de erros

A aplicação deve tratar explicitamente os principais cenários previstos no desafio:

- Consulta sem resultado.
- Dados incompletos.
- Timeout durante a navegação.
- Indisponibilidade temporária do sistema público.
- Falha na extração dos dados.
- Falha de conexão com o WhatsApp.
- Erro retornado pela API do WhatsApp.
- Tentativa de processamento duplicado.

Os erros devem ser registrados no histórico e nos logs técnicos.

Exemplo de fluxo:

```text
Execução
   │
   ├── sucesso
   │     └── status = CONCLUIDO
   │
   └── falha
         ├── registrar erro
         ├── atualizar status
         └── retornar resposta controlada
```

---

## 10. Logs e rastreabilidade

O projeto deve manter logs técnicos suficientes para acompanhar a execução do RPA.

Exemplos de eventos relevantes:

- Início da consulta.
- Navegador iniciado.
- Sistema público acessado.
- Consulta submetida.
- Resultado encontrado.
- Resultado não encontrado.
- Dados estruturados.
- Execução persistida.
- Mensagem gerada.
- Tentativa de envio ao WhatsApp.
- Envio concluído.
- Falha de envio.
- Exceção inesperada.

Os logs técnicos complementam o histórico persistido no banco, mas não substituem o registro da execução.

---

## 11. Segurança e configuração

Tokens, chaves, identificadores e credenciais não devem permanecer diretamente no código-fonte.

Arquivos utilizados:

```text
.env
.env.example
.gitignore
```

Exemplo de `.env.example`:

```env
DATABASE_URL=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_API_VERSION=
```

O arquivo `.env` deve permanecer fora do versionamento.

---

## 12. Testes

A pasta `tests/` concentra testes das regras mais importantes do sistema.

Prioridades:

- Validação e normalização dos dados.
- Geração correta da mensagem.
- Controle de processamento duplicado.
- Tratamento de ausência de resultados.
- Comportamento dos serviços.
- Persistência do histórico.

A integração real com o sistema público e com o WhatsApp pode exigir testes específicos ou uso de mocks durante testes automatizados.

---

## 13. Princípios adotados

A arquitetura segue os seguintes princípios:

- Separação de responsabilidades.
- Baixo acoplamento entre componentes.
- Código organizado por responsabilidade.
- Regras de negócio concentradas nos serviços.
- Isolamento da automação Playwright.
- Isolamento das integrações externas.
- Persistência centralizada nos repositórios.
- Validação de dados antes do processamento e persistência.
- Configuração externa para credenciais e tokens.
- Registro de histórico e logs para rastreabilidade.

A solução permanece deliberadamente simples para atender ao escopo do MVP e permitir que a implementação e a demonstração técnica permaneçam focadas no processo automatizado.

---

## 14. Possível evolução para produção

Caso a solução evolua além do desafio técnico, a arquitetura permite substituir componentes sem reestruturar todo o sistema.

Exemplos:

```text
SQLite        → PostgreSQL
Execução local → Docker / infraestrutura em nuvem
Processamento síncrono → fila de tarefas
Logs locais    → serviço centralizado de observabilidade
Interface simples → frontend independente
```

Essas mudanças não fazem parte do escopo obrigatório do MVP e devem ser avaliadas conforme necessidade futura.

---

## 15. Resumo arquitetural

```text
APRESENTAÇÃO
FastAPI + Jinja2 + Bootstrap
        │
        ▼
APLICAÇÃO
Services
        │
        ├───────────────┬─────────────────┐
        ▼               ▼                 ▼
AUTOMAÇÃO           PERSISTÊNCIA       INTEGRAÇÃO
Playwright          Repository         WhatsApp
                    SQLAlchemy          httpx
                    SQLite              Cloud API

SUPORTE
Pydantic + Config + Logging + Pytest
```

Essa organização atende ao fluxo solicitado no desafio e mantém cada responsabilidade isolada, permitindo que automação, persistência, regras de negócio, interface e integrações externas possam evoluir de maneira independente.
