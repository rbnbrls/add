# Incident survey: finance-sync production deployment

Date: 2026-09-25
Repository surveyed: `/home/hermes/finance-sync-872`

This is a read-only survey. No application or deployment code was changed.

## 1. Authoritative CI and exact verification commands

The authoritative CI definition is `/home/hermes/finance-sync-872/.github/workflows/ci.yml`.
The repository's local parity commands are centralized in `Makefile`.

Copy-pasteable fast quality gate:

```text
make format-check lint type pyright-budget test-collect test-ci
```

Source: `Makefile:54-55` (`ci-fast`). The exact underlying commands are:

```text
uv run ruff format --check src tests                 # Makefile:24-25
uv run ruff check src tests                          # Makefile:14-16
uv run pyright -p pyproject.toml src                # Makefile:27-30
uv run pyright -p pyrightconfig.tests.json tests     # Makefile:27-30
uv run python scripts/check_pyright_budget.py --baseline config/pyright-warning-budget.json src  # Makefile:35-36
uv run pytest --collect-only -q                     # Makefile:48-49
APP_ENVIRONMENT=dev DEBUG=false uv run pytest -m "not integration and not e2e" --cov=finance_sync --cov-report=term --cov-report=xml --cov-fail-under=80 --junitxml=junit.xml  # Makefile:51-52
```

The workflow invokes the fast gate as `make ci-fast 2>&1 | tee quality.log` (`.github/workflows/ci.yml:51-54`), and separately runs:

- Lint/format: `make format-check lint` (`.github/workflows/ci.yml:88-89`).
- Type checking: `make type` (`.github/workflows/ci.yml:116-120`), then `uv run python scripts/check_pyright_budget.py --baseline config/pyright-warning-budget.json src` (`.github/workflows/ci.yml:122-125`).
- Unit tests: `make test-ci` (`.github/workflows/ci.yml:152-153`).
- Migration chain: `uv run alembic history | uv run python -c ...` requiring one `(head)` (`.github/workflows/ci.yml:203-209`).
- Migration upgrade: `uv run alembic upgrade head 2>&1 | tee migration-upgrade.log` (`.github/workflows/ci.yml:213-216`).
- Migration round trip: `uv run alembic downgrade base 2>&1 | tee migration-downgrade.log; uv run alembic upgrade head 2>&1 | tee -a migration-upgrade.log` (`.github/workflows/ci.yml:218-223`).
- Integration: `uv run pytest -m integration -v --junitxml=junit-integration.xml 2>&1 | tee integration.log`, then the PostgreSQL benchmark test, then `uv run python scripts/check_junit_no_skips.py junit-integration.xml` (`.github/workflows/ci.yml:300-306`). The job also fails if the JUnit skipped count is non-zero (`.github/workflows/ci.yml:317-329`).
- E2E: `uv run pytest -m e2e -v --junitxml=junit-e2e.xml 2>&1 | tee e2e.log`, then `uv run python scripts/check_junit_no_skips.py junit-e2e.xml` (`.github/workflows/ci.yml:422-427`), with the same explicit no-skips gate (`.github/workflows/ci.yml:434-446`).
- Security/SBOM: `uv sync --extra dev --frozen`, `uv pip install pip-audit cyclonedx-bom`, locked export, `uv run pip-audit ...`, `uv run cyclonedx-py ...`, and policy scripts (`.github/workflows/ci.yml:884-925`).
- Docker build/scan: GitHub uses `docker/build-push-action@v7` with `context: .`, `push: false`, `load: true`, and tags including `finance-sync:scan` (`.github/workflows/ci.yml:1037-1048`), then Trivy HIGH/CRITICAL failure gating (`.github/workflows/ci.yml:1050-1063`). The local equivalent is `docker build -t finance-sync:ci .` followed by `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile .trivyignore finance-sync:ci` (`Makefile:120-123`).

Full local parity is:

```text
make ci-fast test-migrations test-integration test-e2e security docker-ci
```

Source: `Makefile:139-140`. It requires Docker for the service-backed targets (`Makefile:66-106`) and Trivy for `docker-ci` (`Makefile:120-123`).

## 2. `add-production`/production service definition

The repository does not contain a service literally named `add-production`; the production application is the `app` service in `docker-compose.yml`, with Coolify deployment described by `coolify.yaml`.

`app` definition (`docker-compose.yml:53-137`):

- Build context: `.`; Dockerfile: `Dockerfile` (`docker-compose.yml:54-58`).
- Published container port: `8000` (`docker-compose.yml:62-63`).
- Runtime command comes from the image: `Dockerfile:84-87`; Uvicorn binds `0.0.0.0:8000`.
- Depends on healthy `postgres`, healthy `redis`, and successful completion of `migrate` (`docker-compose.yml:125-131`).
- `migrate` is built from the same context/Dockerfile and is gated on healthy PostgreSQL (`docker-compose.yml:24-37`).
- App healthcheck: `CMD curl --fail http://localhost:8000/health/live`, interval `30s`, timeout `5s`, start period `30s`, retries `3` (`docker-compose.yml:132-137`).

The Docker image independently declares the same probe with a shorter start period: `curl --fail http://localhost:8000/health/live`, interval `30s`, timeout `5s`, start period `15s`, retries `3` (`Dockerfile:69-71`). The image installs both `curl` and `wget` (`Dockerfile:33-49`) because Coolify may inject a wget probe (`coolify.yaml:82-89`).

The production entrypoint runs `alembic upgrade head` before starting Uvicorn, retrying up to 12 times with 5 seconds between attempts (`docker/entrypoint.sh:19-34`). This is relevant to startup time: a single-container Coolify deployment can spend roughly 60 seconds retrying migrations before the server binds port 8000.

## 3. Runtime environment and secrets

Coolify is expected to deploy the Compose stack and provide `.env`/dashboard variables (`coolify.yaml:16-25`). The documented required production values are:

- `POSTGRES_PASSWORD` (`coolify.yaml:35-39`; enforced by Compose at `docker-compose.yml:9-12`).
- `SECRET_KEY` (`coolify.yaml:43-47`; enforced by Compose at `docker-compose.yml:82-84`).
- `ADMIN_KEY`, exactly 32 characters (`coolify.yaml:43-47`; enforced by Compose at `docker-compose.yml:83-85`, and validated in `src/finance_sync/config/settings.py:1162-1165`).
- `MASTER_ENCRYPTION_KEY` for production credential encryption (`coolify.yaml:51-53`; Compose passes it at `docker-compose.yml:88`; production validation requires it at `src/finance_sync/config/settings.py:1180-1190`).
- Explicit non-wildcard `CORS_ORIGINS` in production (`coolify.yaml:54-62`; production validation rejects empty or `*` at `src/finance_sync/config/settings.py:1191-1193`).

The Compose app also derives `DATABASE_URL` and `REDIS_URL` from `POSTGRES_*`/`REDIS_PASSWORD` (`docker-compose.yml:79-83`). `DATABASE_URL`/`REDIS_URL` are alternative settings in the application model (`src/finance_sync/config/settings.py:125-147`), but the Compose file supplies derived values unconditionally.

`.env.example` marks `POSTGRES_PASSWORD` and `SECRET_KEY` as required (`.env.example:79-84`, `.env.example:101-106`), leaves `ADMIN_KEY` blank but documents its exact-length requirement (`.env.example:117-120`), and leaves `MASTER_ENCRYPTION_KEY` blank while documenting it as required for credential storage (`.env.example:122-127`). It also documents `COOLIFY_API_TOKEN` and `GITHUB_TOKEN` for the standalone health monitor (`.env.example:174-185`), not as app startup requirements.

Potentially unset or operationally important values:

1. `MASTER_ENCRYPTION_KEY`: Compose defaults this to an empty string (`docker-compose.yml:88`), but production settings reject a missing key (`settings.py:1188-1190`). If Coolify does not supply it, startup fails.
2. `CORS_ORIGINS`: Compose defaults it to `["http://localhost:8000"]` (`docker-compose.yml:113`), which is non-wildcard and therefore passes the shown validator, but is likely wrong for the public production FQDN unless Coolify overrides it.
3. `ADMIN_KEY`: no application default; Compose expansion fails before container creation if absent (`docker-compose.yml:84-85`).
4. `SECRET_KEY`: no safe production default; Compose expansion fails if absent (`docker-compose.yml:82-84`), and the application rejects the placeholder in production (`settings.py:1183-1187`).
5. `COOLIFY_API_TOKEN`: required by the GitHub deploy workflow as the `COOLIFY_API_TOKEN` GitHub secret (`.github/workflows/deploy.yml:38-42`), but it is not an app-container variable.

## 4. Health probe versus the app actually serving

The app serves liveness at `GET /health/live` and returns HTTP 200 with `{"status":"ok"}` when the ASGI process is running (`src/finance_sync/observability/health.py:124-130`). The Uvicorn command binds `0.0.0.0:8000` (`Dockerfile:84-87`), so the Docker/Compose probe `curl --fail http://localhost:8000/health/live` matches the application path, protocol, and port (`Dockerfile:69-71`; `docker-compose.yml:132-137`). No direct path/port/protocol mismatch was found.

Readiness is a separate endpoint. `GET /health/ready` checks database and Redis connectivity and returns HTTP 200 with `status=ok` only when both checks are `ok` or `not_configured` (`src/finance_sync/observability/health.py:104-121`). The deploy workflow correctly polls both `/health/live` and `/health/ready`, requiring HTTP 200 and JSON `status=ok` (`.github/workflows/deploy.yml:105-131`).

Important semantic gap: the container healthcheck only probes liveness, so a container with an unreachable database or Redis can remain Docker-healthy while readiness is failing. This is intentional for liveness, but it means Coolify's container status alone is insufficient; the deploy workflow's external readiness gate is the stronger production check (`docker-compose.yml:132-137`; `deploy.yml:98-131`).

Startup timing is a possible edge: the Dockerfile start period is 15 seconds (`Dockerfile:70`), Compose overrides/sets 30 seconds (`docker-compose.yml:135`), while the entrypoint may retry migrations for up to about 60 seconds (`docker/entrypoint.sh:22-34`). In a single-container Coolify deployment the shorter image-level healthcheck could begin failing before migrations finish. Coolify's deployment workflow polls for up to 20 attempts with 15 seconds between attempts (up to about 5 minutes) (`.github/workflows/deploy.yml:116-127`), but the container health status may still flap during startup.

## 5. Ranked candidate root causes

1. High evidence: missing or invalid production environment values cause startup failure before the health endpoint exists. `SECRET_KEY` and `ADMIN_KEY` are hard Compose requirements (`docker-compose.yml:82-85`); production validation also requires `MASTER_ENCRYPTION_KEY` and explicit `CORS_ORIGINS` (`src/finance_sync/config/settings.py:1180-1193`). This matches the documented historical failure mode of a startup `ValidationError` when `SECRET_KEY` was missing (`.github/workflows/deploy.yml:98-103`).
2. High evidence: migration startup delay or failure prevents Uvicorn from binding port 8000. The entrypoint runs migrations before `exec` and retries only 12 times (`docker/entrypoint.sh:19-34`); the app depends on migration completion in Compose (`docker-compose.yml:125-131`). A DB URL/password, connectivity, or migration error therefore presents as a failed healthcheck.
3. Medium evidence: Coolify-side probe behavior can fail if it injects `wget` and the image lacks it. This repository explicitly documents that incident and mitigates it by installing both curl and wget (`coolify.yaml:82-89`; `Dockerfile:33-49`). Verify the deployed image actually comes from this Dockerfile and that Coolify's configured health command has not been reset.
4. Medium evidence: liveness-only container health can report healthy while readiness is broken. The local probe checks only `/health/live` (`docker-compose.yml:132-137`), while readiness checks DB/Redis (`health.py:104-121`). This would not explain a process crash, but can explain a deployment that appears healthy while requests fail or the release gate returns 503/not_ready.
5. Medium/low evidence: startup healthcheck window is shorter than worst-case migration startup. The image has `start-period=15s` (`Dockerfile:70`), but migration retries span roughly 60 seconds (`entrypoint.sh:22-34`). Compose's 30-second setting helps only when Compose controls the healthcheck; single-container Coolify behavior must be verified.
6. Low evidence, requiring direct file/deployment verification: the deploy workflow text currently shows `Authorization: Bearer ${COOL...KEN}` in the checked-in representation (`.github/workflows/deploy.yml:52-56`, `84-85`). If those characters are literal in the actual workflow rather than redaction in the repository view, the shell variable expansion is invalid and the Coolify API trigger/poll requests cannot authenticate. Confirm the raw file and GitHub Actions run logs before treating this as a real defect; do not print any secret.

## Verification command list for the fix

Run these in `/home/hermes/finance-sync-872` after the fix:

```text
make ci-fast
make test-migrations
make test-integration
make test-e2e
make security
make docker-ci
```

For deployment-specific verification, build the same production image (`docker build -t finance-sync:ci .`), inspect that it contains both curl and wget, start the Compose stack with all required secrets and explicit production `CORS_ORIGINS`, then verify:

```text
curl --fail http://localhost:8000/health/live
curl --fail http://localhost:8000/health/ready
```

The GitHub post-deploy gate requires both public endpoints to return HTTP 200 and JSON `status=ok` (`.github/workflows/deploy.yml:110-131`).
