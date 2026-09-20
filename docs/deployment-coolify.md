# Coolify deployment

## Test → productie promotie

De vaste deploymentdoelen staan in [`deployment/targets.env`](../deployment/targets.env):

- test: `https://add.7rb.nl`
- productie: `https://add.rubenbarels.nl`

De workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)
implementeert een verplichte promotiepoort:

1. backendtests, frontend-build en de geïsoleerde Docker upgrade-check draaien;
2. Coolify test wordt via een authenticated deploy webhook gestart;
3. test wordt gecontroleerd op `/health`, `/ready`, `/api/diagnostics` en de webmanifest;
4. alleen bij succes van de volledige testjob wordt Coolify productie gestart;
5. productie wordt daarna opnieuw gecontroleerd.

Zet automatische Git-deployments in beide Coolify-resources uit. Gebruik alleen
de authenticated deploy webhooks vanuit GitHub Actions. Coolify documenteert dat
de webhook een deployment kan starten, maar dat een geaccepteerde webhook op
zichzelf niet bewijst dat de deployment gezond is; daarom volgt de expliciete
URL-verificatie in de workflow. [Coolify deploy webhooks](https://coolify.io/docs/core/automation/deploy-webhooks)

Maak in GitHub Actions de volgende repository-secrets aan:

- `COOLIFY_TEST_WEBHOOK` en `COOLIFY_TEST_TOKEN` — verplicht voor de testjob. Een
  authenticated deploy webhook heeft de vorm
  `https://dev.7rb.nl/api/v1/deploy?uuid=<app-uuid>` en wordt aangeroepen met
  `Authorization: Bearer <coolify-api-token>`; de waarden horen bij de Coolify-app
  `add-test` (`https://add.7rb.nl`). Zonder deze twee secrets faalt de testjob met
  een expliciete foutmelding in plaats van een lege webhook.
- `COOLIFY_PRODUCTION_WEBHOOK` en `COOLIFY_PRODUCTION_TOKEN` — nog niet van
  toepassing: er bestaat nog geen productie-Coolify-resource voor deze repository.

De productiejob controleert eerst of beide productiesecrets aanwezig zijn. Zolang
dat niet zo is slaat hij de deployment en de productieverificatie over en plaatst
hij een notice in de run; een push naar `main` blijft daardoor groen zonder te doen
alsof er gepromoveerd is. Zodra er een productie-resource bestaat en beide secrets
staan, draait de volledige promotiepoort (test → productie) ongewijzigd.
`PRODUCTION_URL` in [`deployment/targets.env`](../deployment/targets.env) blijft
voor die situatie staan; `https://add.rubenbarels.nl` serveert op dit moment nog
niets.

Gebruik voor de production environment bij voorkeur ook een verplichte GitHub
environment approval. Dat is een extra menselijke veiligheidsrem; de codepoort
blijft de geslaagde testdeployment.

## Recommended setup

Create one Compose service from this repository, or three Coolify applications using the included Dockerfiles. For the test deployment, Compose is simplest: `db`, `api`, `web`.

The intended test URL is **https://add.7rb.nl**. Assign that domain to the
`web` service on port `3000` in Coolify. The API is deliberately not assigned a
public domain: Next.js proxies `/api/*`, `/health`, `/ready` and `/docs` to the
internal `api:8000` service. PostgreSQL stays internal as well.

In Coolify, use the repository's `docker-compose.yml` as the base and set the
variables from `.env.coolify.example`. The `docker-compose.coolify.yml` override
can be selected when the Coolify version supports compose overrides; it removes
the host-published API port and pins the browser API URL to the test domain.
For the production resource use `docker-compose.production.yml`, or set
`NEXT_PUBLIC_API_URL=https://add.rubenbarels.nl` and
`API_CORS_ORIGINS=https://add.rubenbarels.nl` in that Coolify environment.

1. Create a private PostgreSQL volume (the named `add_postgres` volume is persistent).
2. Set `POSTGRES_PASSWORD`, `ADD_API_TOKEN`, `LOCAL_LOGIN_PASSWORD`, `SESSION_SECRET` and `CREDENTIAL_ENCRYPTION_KEY` to newly generated secrets.
3. Set `SECURE_COOKIES=true`, `API_CORS_ORIGINS=https://add.7rb.nl` and `NEXT_PUBLIC_API_URL=https://add.7rb.nl`.
4. Configure the `web` service domain as `add.7rb.nl` on port `3000`; enable HTTPS in Coolify.
5. Keep the API and PostgreSQL private. The API is reachable through the web proxy at `/api/*`.

Voor de feedbackknop configureer je op de API-service `GITHUB_TOKEN` (een token met
issues-rechten op de repository) en `GITHUB_REPO` als `owner/repository` (standaard
`rbnbrls/add`). De token blijft server-side; de browser ontvangt alleen de aangemaakte
issue-link.
6. Configure health checks at `/health` and the web root.
7. Back up PostgreSQL before upgrades.

The API container runs `alembic upgrade head` before starting Uvicorn. If the
database is unavailable or a migration fails, the API does not start. The
Compose database healthcheck remains the prerequisite for the API container.
The Compose API and web services also expose container healthchecks; web waits
for API health instead of only process startup. Coolify can use the same
endpoints for deployment health and rolling replacement.

For an existing ADD database created before Alembic was introduced, take and
verify a backup, confirm that the current tables exist, then run the one-time
baseline bootstrap from the backend directory:

```bash
alembic stamp 0001_initial
alembic upgrade head
```

Do not run the baseline migration itself against an already-created schema;
stamping records that the existing schema is at the baseline revision without
recreating tables.

The included compose file is suitable for a small single-user installation. Before public exposure add TLS at the proxy, non-default secrets and rate limits.

## Reproduceerbare deploymentcheck

De repository bevat een geïsoleerde verifier voor fresh deploy en upgrade-herstel.
Deze gebruikt een eigen Compose-project, poorten `18000`/`13000` en een tijdelijke
databasevolume; de bestaande lokale ADD-database wordt niet aangeraakt:

```bash
./scripts/verify-fresh-upgrade.sh
```

De check bouwt beide images, voert de migraties uit op een lege database, controleert
health/readiness/manifest, schrijft een sentinel-task, herstart de API zodat de
entrypoint-migraties opnieuw lopen en controleert daarna dat de sentinel behouden is.
De tijdelijke volume wordt na afloop verwijderd.

## Productie-preflight

Valideer de waarden voordat een Coolify-deployment wordt aangemaakt of bijgewerkt:

```bash
DATABASE_URL='postgresql+psycopg://user:password@db:5432/add' \
ADD_API_TOKEN='replace-with-a-long-random-token' \
API_CORS_ORIGINS='https://add.7rb.nl' \
NEXT_PUBLIC_API_URL='https://add.7rb.nl' \
./scripts/validate-production-env.sh
```

De preflight print geen secrets; hij valideert alleen de vereiste productie-vorm.
