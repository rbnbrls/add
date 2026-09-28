# ADD

ADD (Activation, Do, Done) is een self-hosted execution app voor mensen die vooral hulp nodig hebben met beginnen en afronden. De app is geen klassieke todo-lijst: een `Task` beschrijft een gewenst resultaat, een `Action` is de ene concrete stap die nu uitvoerbaar is.

## MVP

- Inbox capture zonder verplichte metadata.
- Eén primaire actie op het `NU`-scherm.
- Start, Done, Continue, Stuck en Stop for today.
- Deterministische selectie-engine met context, energie, duur, limiet en deadlines.
- Execution sessions en completion log.
- Hermes MCP/API-contracten voor suggesties, huidige actie en sessies.
- Home Assistant interface voor home/away-context en todo-mirror.
- PostgreSQL-ready productieopstelling; geen Redis/worker in de eerste versie.
- Mail intake voor Gmail, Outlook/Graph en IMAP met rules-first triage; de
  optionele 15-minuten poller blijft zonder Redis of aparte worker draaien.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

De lokale test-URL is [http://localhost:3000](http://localhost:3000). De API is
beschikbaar op [http://localhost:8000/docs](http://localhost:8000/docs) en het
MCP-endpoint op `POST http://localhost:8000/api/mcp`.

- UI: http://localhost:3000
- Integration Lab: http://localhost:3000/integrations
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

Voor lokale backend-tests:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=75
cd .. && python3 scripts/coverage_report.py --summary
```

De dekking wordt gepubliceerd als `coverage.xml` in de repository-root. Dat is de
enige plek waar een lezer — en de quality lane van de darkfactory — een percentage
uit kan halen: een artifact verloopt en een regel in een CI-log is geen bewijs.
`scripts/coverage_report.py` publiceert de meting van de run en haalt het
volatiele `timestamp` eruit, zodat dezelfde meting altijd dezelfde bytes oplevert.
CI doet exact hetzelfde en faalt daarna op `git diff --exit-code -- coverage.xml`
als de gepubliceerde kopie de huidige boom niet meer beschrijft. Wie de dekking
verandert, publiceert het rapport dus opnieuw in dezelfde pull request; CI pusht
nooit zelf, want dat zou schrijfrechten op het workflow-token vragen.

Kwaliteitscontroles (dezelfde commando's als CI, vanuit de repository-root):

```bash
ruff check backend
mypy backend/app
cd frontend && npm ci && npm run typecheck && npm run build
```

De API maakt bij import of startup geen tabellen meer automatisch aan. Voor een
nieuwe lokale database voer je eerst `alembic upgrade head` uit. Voor een
bestaande database die door een oudere ADD-versie met `create_all()` is gemaakt:
maak eerst een backup, controleer de tabellen en voer daarna uit:

```bash
cd backend
alembic stamp 0001_initial
alembic upgrade head
```

## Productregel

De UI mag maximaal één primaire actie tegelijk presenteren. Alternatieven zijn beperkt tot drie en mogen nooit uitgroeien tot een volledige taakbrowser.

## Documentatie

- [Product specification](docs/product-spec.md)
- [Architecture](docs/architecture.md)
- [Integrations](docs/integrations.md)
- [API contracts](docs/api-contracts.md)
- [Coolify deployment](docs/deployment-coolify.md)
- [Roadmap and backlog](docs/roadmap.md)
- [Agent instructions](AGENTS.md)

## Status

Core MVP is geïmplementeerd als vertical slice. Auth, multi-user, AI-runtime, OAuth providers en push-notificaties zijn bewust buiten scope gehouden totdat de kernworkflow in dagelijks gebruik is gevalideerd.
