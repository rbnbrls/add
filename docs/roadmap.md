# ADD — product roadmap

Dit document is de enige roadmap voor ADD. `docs/plan.md` bevat geen tweede planning; het verwijst alleen naar dit document.

## Productdoel

ADD helpt een gebruiker van intentie naar actie: vastleggen, één uitvoerbare volgende stap kiezen, kort beginnen en een eerlijke uitkomst registreren. Het product groeit in verticale slices: iedere slice levert een bruikbare uitbreiding op een werkend product en laat de bestaande kern intact.

De volgende regels zijn niet onderhandelbaar:

1. ADD is de bron van waarheid voor tasks, actions, sessions en completions.
2. Hermes/LLM mag voorstellen, splitsen of drafts maken, maar schrijft nooit rechtstreeks naar de database.
3. Home Assistant en andere bronnen leveren context of voorstellen; zij bezitten geen task-state.
4. State-transitions zijn expliciet, transactioneel en getest.
5. De hoofdflow toont maximaal één primaire actie; alternatieven zijn secundair.
6. Geen Redis, worker, gamification of complexe planning zonder aangetoonde MVP-noodzaak.

## Definition of done voor iedere slice

Een coding agent is pas klaar wanneer hij:

- de slice als verticale backend + frontend-flow heeft gebouwd;
- een Alembic-migratie toevoegt wanneer het schema verandert;
- API-schema’s, foutgevallen en state-transitions test;
- de one-primary-action-regel en toegankelijkheid behoudt;
- `pytest` in `backend/` en `npm run build` in `frontend` draait;
- de relevante contractdocumentatie bijwerkt;
- verse database én bestaande database controleert waar dat relevant is;
- in het eindrapport files, migratie, API/UI, tests, beperkingen en volgende slice noemt.

Iedere slice legt bovendien expliciet vast: actor, input, output, muterende stap, foutgedrag, idempotency-key (indien van toepassing) en wat niet in scope is.

## Statuslegenda

- **done** — aanwezig in de codebase; acceptance-checks zijn vastgelegd.
- **revalidate** — aanwezig, maar de volledige integratie/deployment-check moet opnieuw worden bewezen.
- **next** — eerstvolgende productwerk.
- **planned** — afhankelijk van eerdere slices.
- **deferred** — alleen bouwen na meetbare behoefte.

---

## Roadmap in één opbouwende lijn

### R0 — Werkend fundament en migratiebetrouwbaarheid

**Status:** done · **Dependencies:** geen · **Outcome:** ADD start op een verse database en voert de kernworkflow uit.

**Scope**

- PostgreSQL + SQLAlchemy-modellen voor `Task`, `Action`, `ExecutionSession` en append-only completion log.
- Alembic als enige schema-authoriteit; container start pas na migratie.
- FastAPI-laag, Next.js-shell en Docker/Coolify-runbook.
- Expliciete states: task `inbox/active/done/archived`, action `ready/active/done/blocked`, session `running/done/continue/stuck/stop`.
- `GET /api/now` retourneert maximaal één uitvoerbare action.

**Acceptance**

- verse PostgreSQL krijgt alle tabellen en enum-types zonder duplicate-object fouten;
- bestaande database kan upgraden zonder verlies;
- start/finish is transactioneel en double-finish geeft `409`;
- `pytest` in `backend/` en `npm run build` in `frontend/` slagen;
- hoofdscherm toont één volgende actie of een lege-state.

**Niet bouwen:** auth, AI, planning, workers.

### R1 — Capture → action → done

**Status:** done · **Dependencies:** R0 · **Outcome:** een gebruiker kan in minder dan een minuut iets vastleggen en uitvoeren.

**Scope**

- Inbox capture zonder verplichte metadata.
- Task aanmaken met eerste concrete action.
- `/`, `/intake`, `/execute`, `/history` en completion-audit.
- Start, done, continue, stuck en stop-for-today.
- Deterministische selectie op energie, thuis, computer, duur, deadline en dagelijkse limiet.
- Focusflow met timer, herstel na reload en toetsenbord-Enter.

**Acceptance**

- API- en domeintests dekken iedere transition en ongeldige transition;
- uitvoering blijft herstelbaar na refresh;
- geen tweede primaire knop wordt zichtbaar gemaakt;
- completion log is append-only en bevat task/action-context.

### R2 — Task-eigenaarschap en bruikbare metadata

**Status:** done · **Dependencies:** R1 · **Outcome:** tasks blijven vindbaar en planbaar zonder een klassieke todo-browser te worden.

**Scope**

- `PATCH`/`DELETE /api/tasks/{id}` met validatie.
- `description`, `planned_at`, `deadline`, `actual_minutes`, `tags`, `priority`.
- Parent/child-relatie met cycle-preventie.
- Server-side session time accounting.
- Compacte task-detail/edit-flow in `/overview`.

**Acceptance**

- `deadline` en `planned_at` zijn semantisch verschillend;
- self-parenting, descendant-parenting en verwijderen van actieve/parent tasks geven expliciete `409`/`422`;
- tags worden genormaliseerd en priority is begrensd;
- backup/export behoudt alle metadata.

### R3 — Eén betrouwbare review-inbox

**Status:** done · **Dependencies:** R1, R2 · **Outcome:** elke bron levert voorstellen die de gebruiker één voor één beoordeelt.

**Scope**

- `TaskSuggestion` als generieke pending/accepted/rejected record.
- Brain dump, meeting note, email, chat, kalender en HA-events naar dezelfde queue.
- `/review` toont exact één voorstel; approve/reject laadt de volgende.
- `source_type`, `source_ref`, `original_input`, `batch_id` en idempotency.
- Alleen approve maakt een task/action; reject muteert geen task-state.

**Acceptance**

- retries op provider-id maken geen duplicate proposal;
- een batch blijft onafhankelijk reviewbaar;
- lege queue, onbekende source en opnieuw beslissen zijn veilige states;
- Enter/Escape werkt zonder extra zichtbare primaire actie.

### R4 — AI-assisted capture, estimates en decomposition

**Status:** done · **Dependencies:** R2, R3 · **Outcome:** AI verlaagt invoerwerk zonder eigenaarschap over te nemen.

**Scope**

- Herbruikbare, mockbare OpenAI-compatible `LLMGateway` met timeout, secret lookup, typed errors en strict Pydantic JSON-validatie.
- Natural-language capture naar pending voorstel met title, description, planned time, tags en next action.
- Optionele duration-estimate: advisory op voorstel; handmatige waarde wint.
- Task decomposition naar begrensde pending batch van child-task previews.
- Approve/reject decomposition transactioneel; approval maakt inbox-children, nooit automatisch actions of sessions.
- Plain-text fallback wanneer AI faalt.

**Acceptance**

- malformed, partial, timeout en provider-unavailable responses zijn getest;
- LLM-service heeft geen database-writer en geen publiek mutatie-endpoint;
- duplicate child titles en duplicate approval worden geweigerd;
- oorspronkelijke input blijft auditbaar; backup/restore blijft compatibel.

**UAT-opmerking:** de veilige provider-unavailable flow is in de GUI bevestigd;
de happy path vereist een geconfigureerde LLM-provider en is in deze lokale
acceptatiesessie daarom niet als provider-backed output bevestigd.

### R5 — Hermes/MCP en context-adapters

**Status:** done · **Dependencies:** R1–R4 · **Outcome:** externe assistenten kunnen ADD veilig gebruiken.

**Scope**

- Token-protected JSON-RPC/MCP adapter met initialize, initialized, ping, tools, resources en prompts.
- `execution_*` tools mappen één-op-één op bestaande API-transitions.
- Hermes task suggestions, current action, today status, search en drafts.
- Home Assistant context (`is_home`, energy, computer, max minutes), beperkte read-only mirror en outbox met origin-loop prevention.
- Setup-wizards `/setup`, `/mcp/setup`, `/ha/setup`, `/outbox/setup`.

**Acceptance**

- malformed tool arguments geven `-32602` zonder state-mutatie;
- adapters kunnen geen task rechtstreeks opslaan;
- outbound mirror is synchronous, replayable en idempotent;
- disabled/misconfigured HA meldt een unresolved state, geen succes;
- secrets/config worden nooit in responses of logs teruggegeven.

**Niet bouwen:** background polling of automatische task-completion.

### R6 — Tekst- en communicatiehulp

**Status:** done · **Dependencies:** R4 · **Outcome:** ADD helpt met taal zonder berichten namens de gebruiker te versturen.

**Scope**

- `/communications` voor formeel/informeel herschrijven en toon-analyse.
- `POST /api/text/rewrite` en `/api/text/analyze` met inputlimiet.
- Gmail-, Calendar- en WhatsApp-vormen als interne intake naar R3.
- Draft endpoint met `send_required`; externe send blijft expliciet bevestigd.

**Acceptance**

- resultaten zijn tijdelijk en veranderen task-state niet;
- provider failure is veilige `503` zonder provider-details;
- source refs en inbound ids zijn zichtbaar/auditbaar;
- zonder echte connector wordt nooit beweerd dat een bericht verzonden is.

### R7 — Dagelijkse feedback en selectie-signalen

**Status:** done · **Dependencies:** R2, R3, R1 completion log · **Outcome:** ADD leert waar de dag vastloopt zonder de kernselector onvoorspelbaar te maken.

**Scope**

- Expliciete day-start/check boundary voor overdue rollover.
- Rollover is idempotent en bewaart herkomst.
- Selectiestrategie expliciet in API: deterministic default en optionele seeded weighted/random keuze.
- Deferral count en long-open signalen.
- Uitgebreide `/api/today-summary` met tijd, rollover/postponed counts en bestaande outcomes.

**Acceptance**

- timezone/date-boundary, repeated rollover en incomplete session zijn getest;
- seeded selection is reproduceerbaar en blijft context-safe;
- Vandaag toont signalen zonder full task browser;
- summary is read-only en verandert geen task-state.

### R8 — Planning als hulpmiddel, niet als tweede waarheid

**Status:** done · **Dependencies:** R7, R2 · **Outcome:** een gebruiker kan een realistische dag plannen en daarna nog steeds via `/execute` werken.

**Scope**

- Time blocks met start/eind, validatie en conflictweergave.
- `/today` timeline; een focused “plan this action”-flow.
- Planned time blijft los van deadline en execution start.
- Geen drag-and-drop voordat de simpele planactie bewezen bruikbaar is.

**Acceptance**

- invalid/overlapping blocks geven een expliciete keuze of fout;
- timeline kan geen task uitvoeren/completen;
- `/api/now` blijft source of truth voor de volgende uitvoerbare action;
- één primaire actie blijft zichtbaar op timeline en execute.

### R9 — Routines en quiet reminders

**Status:** done · **Dependencies:** R8 · **Outcome:** herhaalbare patronen kosten minder handwerk.

**Scope**

- `Routine` met daily/weekly/specific-day recurrence en timezone.
- Expliciete, idempotente materialization naar tasks/actions met provenance.
- Reminder preview en opt-in browser/HA delivery.
- Quiet hours, duplicate suppression en disabled-provider state.

**Acceptance**

- DST/timezone en recurrence boundaries zijn getest;
- materialization kan veilig opnieuw worden aangeroepen;
- reminder voert nooit automatisch een task uit;
- worker/scheduler pas toevoegen na gemeten delivery-volume.

### R10 — Product hardening en portable gebruik

**Status:** revalidate · **Dependencies:** R1–R9 · **Outcome:** veilig self-hosted dagelijks gebruik.

**Scope**

- Local single-user account, PBKDF2 hash, lock/unlock en app-wide auth gate.
- Encrypted integration credentials en secret-safe status endpoint.
- Backup export, validate, preview en afzonderlijke expliciet bevestigde restore.
- Structured logging, request IDs, integration rate limits en operationele health checks.
- Accessible keyboard/mobile pass, PWA manifest en documented real-device UAT.
- Offline read/execute subset via IndexedDB plus expliciete mutation queue; conflict policy eerst documenteren.

**Acceptance**

- credentials/passwords komen nooit terug in API/logs;
- restore heeft preview, confirm en rollback/backup-procedure;
- idempotency, auth en rate-limit tests bestaan;
- offline conflicts worden getoond, nooit stil overschreven;
- Coolify fresh deploy en upgrade zijn reproduceerbaar.

### R11 — Configurable focus en lokale accountability

**Status:** done · **Dependencies:** R1, R7 · **Outcome:** starten en stoppen wordt makkelijker zonder nieuwe externe afhankelijkheid.

**Scope**

- configurable focus duration, pause en break state bovenop bestaande session;
- veilige timer-state bij reload/reconnect;
- lokale `/accountability` start/stop rond actieve session.

**Acceptance**

- duration en pauses zijn expliciet opgeslagen of reproduceerbaar;
- één session kan niet dubbel worden afgerond;
- accountability wijzigt geen task outcome buiten de bestaande API;
- één completion action blijft primary.

### R12 — Optionele motivation experiments

**Status:** deferred · **Dependencies:** R7, R11 · **Outcome:** alleen bouwen wanneer gebruiksdata een motivatieprobleem laat zien.

**Scope bij goedkeuring**

- append-only points, uitsluitend afgeleid van completion events;
- minimale toegankelijke visual companion, afgeleid van points;
- geen streak punishment, verliesmechaniek of blokkade van uitvoering.

**Gate:** vooraf een meetbare hypothese, baseline en evaluatieperiode toevoegen.

### R13 — True shared body doubling

**Status:** deferred · **Dependencies:** R11 · **Outcome:** twee echte clients kunnen vrijwillig dezelfde focus-sessie delen.

**Scope bij goedkeuring**

- signaling/presence, session join, begin-doel en eind-resultaat;
- privacy, disconnect en reconnect gedrag;
- WebRTC alleen na een gevalideerde tweede-device use case.

**Niet bouwen:** video/audio-infrastructuur als er geen concrete tweede client en testscenario beschikbaar is.

---

## Competitive research addendum — aanbevolen ADD-uitbreidingen

Onderstaande aanbevelingen zijn afgeleid uit de actuele publieke product- en
helpdocumentatie van Structured en TickTick. Structured koppelt een inbox aan
een tijdlijn, laat taken tussen inbox en timeline bewegen, ondersteunt herplannen
van onaf werk, subtaken/notities, recurring tasks en shortcuts. TickTick voegt
snelle capture, NLP voor datum/tijd, voice input, filters, meerdere kalender- en
timeline-views, recurring reminders en dagelijkse planning toe. Zie de bronnen
onderaan dit addendum.

De selectie hieronder is gefilterd door ADD’s productregel: iedere functie moet
helpen om bronnen te verzamelen, één reviewfunnel te vullen, een haalbare actie
te plannen of die actie uit te voeren. Functies die vooral meer beheer, sociale
druk of visuele configuratie toevoegen worden niet overgenomen.

### C1 — Capture from anywhere naar dezelfde inbox

**Status:** done · **Dependencies:** R3, R4 · **Outcome:** een taak kan worden
vastgelegd zonder de huidige context te verlaten.

**Prioriteit:** P1

**Toevoegen**

- één ingest-contract voor web share/link, desktop global shortcut, e-mail
  forwarding en voice transcript;
- bronmetadata: `source_type`, `source_ref`, `received_at`, `original_input`;
- elke input komt als pending suggestion in R3, nooit direct als task;
- retries gebruiken een provider/source-id als idempotency-key;
- browser/desktop capture mag alleen titel, URL en optionele notitie leveren;
- voice is transcriptie + review, geen automatische uitvoering.

**Acceptance voor een coding agent**

- minimaal web-link en één tekst-shortcut end-to-end bewezen;
- dezelfde input twee keer levert één voorstel;
- bron en originele tekst zijn in Review zichtbaar;
- providerfout laat de ruwe capture behouden;
- API-, idempotency- en frontend-buildtests zijn groen.

**Waarom:** Structured maakt Inbox de plek voor ongesorteerde taken en TickTick
legt de nadruk op shortcuts, widgets, e-mail/browser-capture en voice input.
Voor ADD is de funnel belangrijker dan het kanaal: alle kanalen eindigen in R3.

### C2 — Inbox → haalbare dag → uitvoering

**Status:** done · **Dependencies:** R7, R8 · **Outcome:** de gebruiker kan een
voorstel met één beslissing op een realistische plek in de dag zetten.

**Prioriteit:** P1

**Toevoegen**

- `Plan`-actie op één reviewed inbox-item: vandaag, een gekozen datum/tijd of
  “later in inbox”;
- duur is verplicht voor tijdblokken maar mag advisory blijven vóór approval;
- dag-, week- en agenda-overzicht als read model; `/api/now` blijft execution
  source of truth;
- `Replan`-flow voor onaf werk: terug naar inbox, volgende vrije plek of
  expliciete datum; nooit stil verplaatsen;
- undo voor de laatste planning/review-beslissing via een auditeerbare inverse
  transition.

**Acceptance voor een coding agent**

- planning verandert geen task-content behalve de expliciete schedulevelden;
- overlap, ontbrekende duur en verleden worden duidelijk gemeld;
- replan vraagt één expliciete keuze per item en is idempotent;
- timeline toont geplande items maar slechts één primaire uitvoeractie;
- undo herstelt alleen de laatste toegestane transition en is getest.

**Waarom:** Structured’s sterkste patroon is Inbox ↔ Timeline en het opnieuw
plannen van onaf werk; TickTick onderbouwt dat met agenda-, week-, multi-day- en
timeline-views. ADD moet dit als planning-hulpmiddel gebruiken, niet als tweede
taakbron of volledige projectmanager.

### C3 — Natural-language scheduling en voice capture

**Status:** done · **Dependencies:** C1, R4 · **Outcome:** “morgen om 15:00,
  30 minuten” wordt een controleerbaar voorstel, geen verborgen mutatie.

**Prioriteit:** P1

**Toevoegen**

- parse `date`, `time`, `duration`, `deadline`, `recurrence` en timezone uit
  tekst/transcript;
- toon parsed fields naast de oorspronkelijke tekst;
- onbekende of conflicterende tijdsaanduidingen worden gemarkeerd;
- approval vereist wanneer de parser een planning of recurrence toevoegt;
- voice-provider blijft verwisselbaar; transcriptie wordt als input opgeslagen,
  audio zelf niet standaard.

**Acceptance voor een coding agent**

- relatieve datumtests rond timezone en DST;
- “volgende dinsdag” en “om 15:00” worden deterministisch geïnterpreteerd;
- ambiguïteit blokkeert auto-approval en toont een keuze;
- LLM/transcript failure valt terug naar plain-text review;
- geen provider-call schrijft rechtstreeks naar tasks/actions.

**Waarom:** TickTick gebruikt NLP voor tijdinstellingen en voice capture; Structured
AI accepteert tekst, stem en scans. Voor ADD is tekst eerst P1; voice volgt pas
nadat C1 en de reviewcontracten stabiel zijn. Scan/OCR is voorlopig geen P1.

### C4 — Smart views zonder task-browser

**Status:** done · **Dependencies:** R7, C2 · **Outcome:** overzicht ontstaat
  via een paar betekenisvolle lenzen, niet via tientallen lijsten.

**Prioriteit:** P2

**Toevoegen**

- server-side read-only filters: `vandaag`, `deze week`, `overdue`, `bron`,
  `priority`, `blocked`, `zonder planning`;
- maximaal drie user-saved views, elk met naam en expliciete query;
- dezelfde views kunnen Review en Plan voeden;
- NU blijft altijd context- en execution-first.

**Acceptance voor een coding agent**

- filterresultaat is read-only en kan geen verborgen state transition uitvoeren;
- query’s zijn begrensd en getest op timezone/overdue;
- saved view is per gebruiker lokaal en exporteerbaar;
- UI toont nooit meer dan één primaire actie in de hoofdflow.

**Waarom:** TickTick’s filters, tags en group/sort views zijn nuttig voor bron- en
statusoverzicht. Een beperkte set saved views geeft ADD hetzelfde overzicht met
veel minder beheerlast dan lijsten, Kanban en een volledige matrix.

### C5 — Dagelijkse review en rustige reminders

**Status:** done · **Dependencies:** R9, C2 · **Outcome:** de funnel blijft
  schoon en gepland werk blijft zichtbaar zonder notification pressure.

**Prioriteit:** P2

**Toevoegen**

- één daily review met: open proposals, ongeplande inbox, overdue en vandaag;
- recurring tasks/routines uit R9 met provenance en idempotente materialization;
- opt-in reminder voor review of gepland blok, quiet hours en duplicate suppression;
- “constant reminder” alleen als expliciete per-task instelling, nooit default.

**Acceptance voor een coding agent**

- reminder kan niet starten, completen of verplaatsen;
- recurring materialization respecteert timezone/DST en maakt geen duplicates;
- daily review is één gefocuste flow met één primaire volgende beslissing;
- disabled provider en quiet hours zijn zichtbare, geteste states.

**Waarom:** beide producten benadrukken routines, recurring tasks en reminders.
ADD neemt de onderhoudsarme variant over; persistent/nagging reminders blijven
optioneel omdat ze botsen met de rustige execution-filosofie.

### C6 — Snelle cross-device ingang

**Status:** done · **Dependencies:** C1, R10 · **Outcome:** de gebruiker kan
  overzicht en capture openen vanaf het apparaat waar de taak ontstaat.

**Prioriteit:** P3

**Toevoegen wanneer gebruik dit bewijst**

- PWA quick action voor capture en “show next action”;
- eenvoudige home-screen/inbox widget-readmodel waar het platform dat ondersteunt;
- keyboard command menu voor capture, review en start.

**Niet in scope:** realtime multi-user sync, native widgets per platform of
platformspecifieke Control Center-integraties voordat PWA/desktopgebruik wordt
gemeten.

### Bewust niet overnemen

- Kanban, Eisenhower Matrix, uitgebreide projectboards en meerdere parallelle
  primaire acties: te veel planning-oppervlak voor ADD.
- Habits, punten, streaks, virtuele companions, themes, icons en decoratie:
  alleen via de bestaande evidence gate R12.
- Collaboration/taaktoewijzing: geen aangetoonde single-user MVP-behoefte.
- Audio meeting summaries en OCR/scans: pas na bewezen voice/text capture en
  duidelijke privacy-/retentie-eisen.
- Constant/email/location reminders als standaard: te veel signalen en externe
  afhankelijkheid voor de kernfunnel.

### Aanbevolen roadmapvolgorde na R6

1. **R7** dagelijkse feedback en selectie-signalen afronden.
2. **C1** capture from anywhere met web-link en desktop shortcut.
3. **C2** inbox naar dagplanning met replan en undo.
4. **C3** natural-language scheduling; voice als tweede adapter.
5. **R9 + C5** routines, daily review en rustige reminders.
6. **C4** beperkte smart views.
7. **R10 + C6** portable/cross-device surfaces.

### Bronnen

- [Structured — Getting Started](https://help.structured.app/en/articles/380546)
- [Structured — Inbox](https://help.structured.app/en/articles/338178)
- [Structured — AI task creation](https://help.structured.app/en/articles/331074)
- [Structured — Replan, timeline en inbox-overzicht](https://help.structured.app/en/categories/1823490)
- [TickTick — officiële feature-overview](https://ticktick.com/features)
- [TickTick — officiële feature guide](https://help.ticktick.com/)

---

## Eerstvolgende uitvoeringsvolgorde

De oorspronkelijke uitvoeringsvolgorde is ingehaald door de implementatie. R7,
R8, R9, R11 en C1–C6 zijn inmiddels gebouwd en hebben acceptance-notes verderop
in dit document. De actuele volgorde is daarom:

1. **R10 afronden als operationele revalidatieslice:** Coolify-specifieke
   fresh-deploy/upgrade uitvoeren en een herhaalbare real-device UAT voor PWA,
   offline uitvoering en multi-device conflictgedrag vastleggen.
2. **Daarna geen nieuwe feature-slice zonder nieuwe productevidence:** R12
   (motivation experiments) en R13 (shared body doubling) blijven `deferred` en
   zijn niet bouwbaar zonder hun expliciete evidence gates.

**Conclusie actuele audit (2026-09-20):** R10 is de enige niet-afgeronde slice
die nu uitvoeringswerk heeft. De resterende scope is bewijsvoering en
deployment/UAT, niet een ontbrekende backend- of frontendfeature. Er is dus geen
volgende vrije productfeature-slice die verantwoord vóór R10 kan worden gebouwd.

R1–R6 zijn de huidige productbasis. Een nieuwe slice mag die basis refactoren voor betrouwbaarheid, maar mag de bron-van-waarheid-, transition- of one-primary-action-regels niet verzwakken.

## Slice handoff-template voor coding agents

Gebruik bij iedere implementatie dit compacte contract:

```text
Slice: R__ / naam
Doel: één meetbaar gebruikersresultaat
Dependencies: R__
Actor: gebruiker / Hermes / HA / scheduler
Input: endpoint + schema + validatie
State mutation: exacte transition en transaction boundary
Output: endpoint/UI + success/error states
Idempotency: sleutel en retry-gedrag
Tests: domain, API, migration, frontend build/UAT
Niet in scope: expliciete grenzen
Done wanneer: checklist uit deze roadmap groen is
```

## Huidige verificatie

### Actuele implementatie-audit — 2026-09-20

De werkelijke codebase-status is:

| Gebied | Werkelijke status | Bewijs / open punt |
|---|---|---|
| R0–R9 | **done** | Backendmodellen, API, migraties, UI en acceptance-notes aanwezig |
| R10 | **revalidate** | Auth, credential-encryptie, backup/restore/rollback, logging, request IDs, rate limits, health/readiness, PWA, IndexedDB offline queue en conflict-UX zijn geïmplementeerd; Coolify-specifieke uitvoering en real-device UAT ontbreken nog als reproduceerbaar bewijs |
| R11 | **done** | Focus pause/resume, reload-herstel en lokale accountability zijn geïmplementeerd en getest |
| C1–C6 | **done** | Capture, planning/replan/undo, natural-language scheduling, smart views, daily review/reminders en PWA/widget/command-menu zijn geïmplementeerd en getest |
| R12–R13 | **deferred** | Niet bouwen vóór respectievelijk motivation- en shared-body-doubling-evidence gates |

Lokale verificatie op 2026-09-20: `backend/.venv/bin/pytest` vanuit `backend/`
geeft **100 passed** en `npm run build` vanuit `frontend/` slaagt. Een losse
`pytest` met de systeem-Python faalt bij collectie door ontbrekende
`cryptography`; dat is een lokale omgeving-/invocation-fout, niet een testfalen
van de project-venv. De eerdere acceptance-notes hieronder blijven historische
bewijzen; deze audit is de actuele bron voor de slice-status.

De status `revalidate` betekent hier: de implementatie is aanwezig, maar de
operationele/deploymentclaims zijn nog niet volledig opnieuw bewezen in de
doelomgeving. Voor R10 zijn de open gates uitsluitend Coolify-specifieke
deployment en herhaalbare UAT op echte apparaten.

### GUI-acceptatietest — 2026-09-19

Uitgevoerd in de lokale browser op `http://localhost:3000`, met API op
`http://localhost:8000` en de actuele PostgreSQL-container.

| Slice | GUI-scenario | Resultaat |
|---|---|---|
| R0/R1 | Inbox capture → voorstel → toevoegen → start → klaar | **PASS** — één primaire actie, session en lege NU-state na afronden |
| R2 | Overzicht openen, description/priority/tags wijzigen en opslaan | **PASS** — waarden blijven zichtbaar in task-overzicht en detail |
| R3 | Gmail-, Calendar- en WhatsApp-proposal door dezelfde reviewfunnel; approve/reject | **PASS** — bronreferentie zichtbaar, approve/reject sluit de queue correct |
| R4 | Natural-language capture en decomposition vanuit GUI | **PASS voor veilige fallback** — zonder LLM-provider blijft capture reviewbaar en decomposition meldt tijdelijk niet beschikbaar zonder state-mutatie |
| R5 | MCP setup-wizard: handshake, initialized, ping, tools, resources, prompts en read-only call | **PASS** — alle wizardchecks geslaagd |
| R5 | Home Assistant setup in previewmodus | **PASS** — read-only preview geslaagd, niets opgeslagen |
| R6 | Teksthulp en communicatie-draft | **PASS voor grenzen** — providerfout wordt veilig gemeld; draft wordt gemaakt met expliciete bevestiging vóór verzenden |
| R6 | Calendar/WhatsApp intake | **PASS** — voorstellen komen in review en kunnen worden overgeslagen zonder automatische actie |

### Fouten opgelost tijdens deze UAT

- PostgreSQL/Alembic enum-migraties maakten types dubbel aan. De migraties zijn
  aangepast zodat PostgreSQL enum-types één keer expliciet worden aangemaakt en
  kolommen ze daarna zonder tweede create gebruiken. Fresh `alembic upgrade head`
  door `0001`–`0005` is opnieuw bewezen.
- De standalone Next.js-container gebruikte de verkeerde startopdracht en kopieerde
  geen `.next/static`; dit veroorzaakte een `ChunkLoadError` en wit `/overview`.
  De Dockerfile serveert nu `server.js` met de standalone build en static chunks.
- De lokale testomgeving miste `alembic`; de bestaande backend-requirements zijn
  geïnstalleerd zodat de migratietests ook lokaal draaien.

### Verificatie-uitkomst

- Backend: `86 passed`.
- Frontend: `npm run build` geslaagd; 32 routes gegenereerd.
- Fresh PostgreSQL migration: geslaagd voor `0001_initial` t/m
  `0005_inbox_funnel`.
- Runtime: API health `ok`; Docker API, web en database zijn healthy/running.
 - Browserconsole na de frontend-fix: geen errors of warnings in een schone tab.
- De drie `503`-responses tijdens de UAT waren verwachte, veilig afgehandelde
  LLM-provider-unavailable responses; ze zijn geen ongecontroleerde exceptions en
  wijzigen geen domeinstate.

### R7-acceptatie — 2026-09-19

- `POST /api/day/check` met `Europe/Amsterdam` is idempotent bewezen: twee identieke
  checks leveren dezelfde nul-mutatie op zonder dubbele rollover-events.
- `/api/today-summary?timezone=Europe/Amsterdam` levert tijd, uitstel, rollover en
  lang-open signalen; de summary blijft read-only.
- `/today` toont deze signalen en de knop `Controleer doorschuiven`; de browseractie
  gaf zichtbaar `0 taken gecontroleerd` zonder consolefouten.
- R7-migratie `0006_day_feedback` draait mee in Docker en lokale fresh-database tests.
- Backend: `86 passed`; frontend: `npm run build` geslaagd.

### R8-acceptatie — 2026-09-19

- `plan_blocks` is toegevoegd als aparte planninglaag; `planned_at`, deadlines en
  execution blijven afzonderlijke concepten.
- `POST /api/plan-blocks` accepteert een geldig blok en geeft bij overlap expliciet
  `409`; `/api/today-plan` levert de tijdlijn gesorteerd terug.
- `/today` bevat een gefocuste `Plan deze actie`-flow en toont de timeline zonder
  uitvoer- of completion-controls.
- GUI-test geslaagd: actie gepland, timeline zichtbaar, overlappend lokaal tijdsblok
  toont `plan block overlaps an existing block`; browserconsole bevat geen errors of
  warnings.
- Backend: `86 passed`; frontend: `npm run build` geslaagd; Docker opnieuw gebouwd
  met migratie `0007_plan_blocks`.

### R9-acceptatie — 2026-09-19

- `Routine` ondersteunt daily, weekly en specific-day recurrence met timezone en
  lokale tijd; DST wordt via `zoneinfo` naar UTC genormaliseerd.
- Materialization maakt een task/action met `routine:<id>:<date>` provenance en is
  idempotent: een tweede call geeft `already_materialized` en maakt niets nieuws.
- Reminder settings ondersteunen opt-in provider state (`browser`/`ha`), quiet hours
  over middernacht en disabled-provider responses; reminders voeren geen task uit.
- GUI-test geslaagd op `/routines`: routine opslaan, vandaag klaarzetten en opnieuw
  klikken gaf zichtbaar `Deze routine was vandaag al klaargezet.`
- Backend: `86 passed`; frontend/Docker build geslaagd; health endpoint is `ok` en
  browserconsole bevat geen errors of warnings.

### R10a-acceptatie — operationele hardening — 2026-09-19

- `OperationalMiddleware` voegt per request een `X-Request-ID` toe en logt method,
  path, status en duration zonder request-body of credentials te loggen.
- `/ready` controleert naast liveness ook de databaseverbinding en geeft `database: ok`.
- MCP- en connector-routes hebben een tijdelijke single-process rate limit van 30
  requests per client/route per minuut; de 31e call gaf `429` met `Retry-After`.
- GUI `/status` toont API-health, dagstatus en integratieconfiguratie zonder geheimen;
  browserconsole bevat geen errors of warnings.
- R10 blijft `in_progress`: offline IndexedDB/mutation queue en volledige restore-
  rollback/Coolify upgrade-evidence zijn nog expliciete vervolg-gates.

### R10b-acceptatie — veilige restore rollback — 2026-09-19

- Backup export bevat ook plan blocks, routines, routine occurrences en reminder
  preferences; credentials blijven uitgesloten.
- Iedere bevestigde restore maakt eerst een `backup_snapshots`-herstelpunt.
- `/api/backup/rollback?confirmed=true` zet het laatste herstelpunt terug; een
  restore→rollback smoke test herstelde de sentinel-task correct.
- De GUI `/backup` toont expliciet downloaden, controleren en `Rollback laatste
  restore`; de acceptatietest bevestigde de safety affordances zonder onbedoelde
  mutatie. Browserconsole bevatte geen errors of warnings.
- Restore-volgorde is gerepareerd met expliciete task/action flush zodat bestaande
  execution sessions geen foreign-key-fout veroorzaken.

### R10c-acceptatie — offline execute queue — 2026-09-19

- Execute cachet de laatst bekende action in IndexedDB en toont bij ontbrekende
  verbinding expliciet `OFFLINE KOPIE`; online blijft `/api/now` de bron van waarheid.
- Offline completion mutations worden in IndexedDB gequeued en via
  `POST /api/offline/complete` gesynchroniseerd zodra de verbinding terugkomt.
- De server valideert dat de action nog `ready` is. Een tweede of verouderde
  mutation gaf `409 offline conflict` en werd niet stil overschreven.
- GUI `/execute` toont de queue-/online-indicator en de primary execute action;
  browserconsole bevat geen errors of warnings.
- R10 blijft `in_progress`: volledige service-worker offline navigatie, multi-device
  conflict UX en Coolify fresh-deploy/upgrade-evidence zijn nog open gates.

### R10d-acceptatie — offline shell en deploymentcontract — 2026-09-19

- Service worker cachet `/execute` en het manifest; de queue blijft IndexedDB/API-
  gedreven en verandert de server source of truth niet.
- Offline scope en conflict policy zijn vastgelegd in [offline.md](offline.md).
- De GUI `/execute` blijft de enige primary action; de shell registreert de service
  worker zonder console-errors.
- R10 blijft `in_progress` totdat echte netwerk-uit UAT, multi-device conflict UX
  en Coolify fresh-deploy/upgrade-evidence zijn uitgevoerd.

### R10e-acceptatie — persistent offline conflict UX — 2026-09-19

- Offline mutations gebruiken IndexedDB schema v2 met een aparte
  `conflicts`-store; een stale completion wordt als persistent conflict
  bewaard met serverreden, action-id en outcome.
- De `/execute`-UI toont de conflictstatus duidelijk en biedt uitsluitend de
  expliciete actie `Conflict gezien`; er is geen stille retry op een andere
  action en geen automatische overwrite.
- API-test geslaagd: een completion tegen een server-side niet-meer-ready
  action geeft `409 offline conflict` en laat de serverstate ongemoeid.
- GUI-smoke geslaagd op `/execute`: online/lege-state, offline shell-indicator
  en primary execute-flow renderen zonder browserconsole-errors. Echte
  netwerk-uit UAT blijft als deploymentgate open omdat de lokale browserlaag
  geen betrouwbare netwerk-toggle biedt.
- Deploymentacceptatie geslaagd op `/status`: `Gereed`, database `ok` en
  migratie `0013_saved_views` zijn zichtbaar in de GUI; beide gecontroleerde
  tabs hadden geen browserconsole-errors. `scripts/verify-deployment.sh`
  valideert daarnaast `/health`, `/ready`, `/api/diagnostics` en de PWA
  manifest-shortcut end-to-end.
- R10 blijft `in_progress` voor volledige echte netwerk-uit UAT, multi-device
  conflictverificatie en Coolify fresh-deploy/upgrade-evidence.

### R10f-acceptatie — betrouwbare offline shell — 2026-09-19

- Service worker gebruikt cacheversie `add-shell-v2`, ruimt oudere ADD-shellcaches
  op bij activatie en registreert met `updateViaCache: none` zodat een nieuwe shell
  niet op een verouderde worker blijft hangen.
- Offline fallback geldt alleen voor HTML-navigaties; mislukte API-requests
  retourneren geen execute-HTML meer. De Docker-image kopieert `public/` mee,
  waardoor `/sw.js` daadwerkelijk in de productiecontainer beschikbaar is.
- GUI-acceptatietest geslaagd op `/execute?uat=r10f-offline-shell`: execute-shell
  rendert correct, toont de online-status en beide gecontroleerde GUI-tabs hadden
  geen browserconsole-errors.
- Verificatie geslaagd: `node --check frontend/public/sw.js`, `npm run build`,
  Docker rebuild, `/sw.js`-runtimecheck en `scripts/verify-deployment.sh`.
- R10 blijft `in_progress` voor echte netwerk-uit UAT, multi-device
  conflictverificatie en Coolify fresh-deploy/upgrade-evidence.

### R10g-acceptatie — expliciete conflict-herbeoordeling — 2026-09-19

- Een persistent offline conflict bevat nog steeds de serverreden, action-id en
  outcome en biedt naast `Conflict gezien` nu ook de expliciete link
  `Bekijk de actuele actie in NU`; er wordt geen alternatieve action gekozen en
  geen serverstate overschreven.
- Frontend build en backendregressies geslaagd: `npm run build` en `100 passed`.
- GUI-acceptatietest geslaagd op `/execute?uat=r10g-conflict-link`: de execute-
  shell rendert online, met de primaire funnel intact en zonder
  browserconsole-errors. De link is onderdeel van de conflictstate; de lege
  fixture toont die state terecht niet.
- R10 blijft `in_progress` voor een echte netwerk-uit multi-device UAT en
  Coolify fresh-deploy/upgrade-evidence.

### R10h-acceptatie — echte netwerk-uit en multi-device conflictflow — 2026-09-19

- GUI-context A cachete de actie, waarna GUI-context B dezelfde serveractie
  startte en afrondde. Context A werd daarna offline getest terwijl API en web
  tijdelijk gestopt waren: de service worker leverde `OFFLINE KOPIE`, de actie
  startte offline en `Klaar` plaatste de mutation in de queue.
- Na herstel van API en web synchroniseerde de queue naar `1 conflict` met de
  serverreden `action is no longer ready`; de serverstate bleef dus leidend en
  werd niet overschreven. `Conflict gezien` verwijderde daarna uitsluitend het
  lokale conflictrecord en de link naar de actuele actie bleef beschikbaar.
- GUI-acceptatietest geslaagd zonder browserconsole-errors. Deploymentcheck
  bleef geslaagd (`migration=0013_saved_views`) en de tijdelijke UAT-taken zijn
  na afloop verwijderd.
- R10 blijft `in_progress` uitsluitend voor Coolify fresh-deploy/upgrade-
  evidence en herhaalbare real-device UAT buiten de lokale browseromgeving.

### R10i-acceptatie — reproduceerbare fresh deploy en upgrade-rehearsal — 2026-09-19

- `docker-compose.verify.yml` isoleert de deploymentcheck met eigen poorten en
  een eigen tijdelijke PostgreSQL-volume; de normale ADD-stack blijft intact.
- `scripts/verify-fresh-upgrade.sh` bouwt API en web, initialiseert een lege
  database via `alembic upgrade head`, controleert health/readiness/manifest,
  schrijft een sentinel-task, herstart de API en bevestigt dat de sentinel en
  migratierevisie behouden blijven. De tijdelijke volume wordt automatisch
  verwijderd.
- Fresh/upgrade-verifier geslaagd: `migration=0013_saved_views` en persisted
  sentinel-task bevestigd. De normale stack bleef daarna `api`, `web` en
  gezonde `db` draaien.
- GUI-acceptatietest geslaagd op `/status?uat=r10i-deploy`: deployment toont
  `Gereed`, `DB ok` en `0013_saved_views`; er waren geen browserconsole-errors.
- R10 blijft `in_progress` voor Coolify-specifieke uitvoering en herhaalbare
  real-device UAT buiten de lokale browseromgeving.

### R10j-acceptatie — container healthchecks voor Coolify — 2026-09-19

- Compose controleert API-health via `/health` vanuit de container en web-health
  via de container-hostnaam; web start pas nadat API `healthy` is. Een IPv6-
  localhostfout in de eerste healthcheck is tijdens UAT gevonden en opgelost.
- Normale stack geverifieerd: `db healthy`, `api healthy`, `web healthy`.
- De geïsoleerde fresh/upgrade-verifier bleef groen na de healthcheckwijziging:
  migratie `0013_saved_views` en persistente sentinel-task bevestigd.
- GUI-acceptatietest geslaagd op `/status?uat=r10j-healthchecks-final`: `Gereed`,
  `DB ok` en migratie zichtbaar; geen browserconsole-errors.
- R10 blijft `in_progress` voor Coolify-specifieke uitvoering en herhaalbare
  real-device UAT buiten de lokale browseromgeving.

### R10k-acceptatie — productie-configuratie preflight — 2026-09-19

- `scripts/validate-production-env.sh` valideert vóór deployment PostgreSQL,
  een niet-standaard token van minimaal 16 tekens, HTTPS CORS-origins en een
  HTTPS `NEXT_PUBLIC_API_URL`; secrets worden nooit geprint.
- Negatieve lokale waarden werden correct geweigerd; een productie-vormige
  configuratie werd correct geaccepteerd.
- De bestaande GUI-acceptatie op `/status?uat=r10j-healthchecks-final` blijft
  groen: deployment `Gereed`, database `ok`, migratie `0013_saved_views` en
  geen browserconsole-errors. `verify-deployment.sh` en de fresh/upgrade-
  verifier bleven geslaagd.
- R10 blijft `in_progress` voor Coolify-specifieke uitvoering en herhaalbare
  real-device UAT buiten de lokale browseromgeving.

### R11-acceptatie — configureerbare focus en lokale accountability — 2026-09-19

- `ExecutionSession` bewaart `duration_seconds`, `paused_at` en `paused_seconds`;
  migratie `0010_focus_state` draait mee in Docker en de lokale tests.
- `/focus` ondersteunt 15/25/50 minuten, pause/resume en één primaire `Klaar`-
  completion. De actieve sessie wordt bij reload/reconnect via de API hersteld.
- `/accountability` herstelt een actieve focus-sessie, kan een lokale buddy-label
  starten en stoppen, en wijzigt daarbij geen task outcome.
- GUI-acceptatietest geslaagd: actieve sessie openen, pauzeren, hervatten, naar
  accountability navigeren, buddy `acceptatie buddy` starten en stoppen, daarna de
  focus via `Klaar` afronden. De browserconsole bevatte geen foutmeldingen.
- Idempotentie/conflict geslaagd: een tweede finish op dezelfde sessie gaf `409
  session already finished`; de API-log bevatte alleen verwachte 2xx/409-statussen.
- Backend: `86 passed`; frontend/Docker build geslaagd; `/ready` gaf
  `database: ok`.

### C1-acceptatie — capture from anywhere — 2026-09-19

- `/intake` heeft een snelle tekst-ingang en een weblink-ingang; beide gebruiken
  `POST /api/inbox/capture` en maken uitsluitend een pending voorstel.
- GUI-test geslaagd: `C1 GUI shortcut test` verscheen als `shortcut` in Review,
  de originele capture was zichtbaar, en goedkeuren maakte één volgende actie.
- GUI-test geslaagd: `Lees C1 artikel` verscheen als `web_link` met de URL in
  bronreferentie, beschrijving en concrete volgende actie; goedkeuren liep door
  dezelfde Review-funnel.
- Idempotentie geslaagd: dezelfde shortcut-input en dezelfde weblink retourneerden
  het bestaande voorstel, ook nadat het was goedgekeurd; er werden geen dubbele
  voorstellen aangemaakt.
- Ongeldige `javascript:`-URL werd geweigerd met `422`; provider failure op de
  shortcut behield de ruwe tekst als `plain_text` voorstel.
- Browserconsole bevatte geen fouten; `/ready` gaf `database: ok`.
- Backend: `88 passed`; frontend/Docker build geslaagd.

### C2-acceptatie — inbox naar haalbare dag — 2026-09-19

- Migratie `0011_planning_decisions` voegt een auditlaag toe voor plan-, replan-
  en undo-transities; bestaande plan blocks blijven een read model.
- Review ondersteunt `Vandaag`, `Gekozen moment` en `Later in inbox`. Een tijdblok
  vereist expliciet startmoment en duur; planning start of completeert geen actie.
- GUI-test geslaagd: inbox-capture `C2 GUI plan test` → Review → `Plan` →
  tijdblok van 30 minuten; `/today` toonde het item in de timeline.
- GUI-test geslaagd: timeline → `Replan` → `Terug naar inbox`; het blok verdween
  en de expliciete `Undo laatste planning` herstelde exact het vorige blok.
- Backendtests bevestigen `422` voor verleden, `409` voor overlap en een
  idempotente replan wanneer de gevraagde planning al actief is.
- Planning verandert alleen `planned_at`/plan blocks; `/api/now` blijft de bron
  voor uitvoering en de timeline toont geen tweede completion-actie.
- Browserconsole bevatte geen fouten; `/ready` gaf `database: ok`.
- Backend: `90 passed`; frontend/Docker build geslaagd.

### C3-acceptatie — natural-language scheduling en voice transcript — 2026-09-19

- Migratie `0012_schedule_metadata` voegt planningmetadata en expliciete
  `parsed`/`ambiguous` status toe aan voorstellen; taken worden pas gewijzigd
  na een expliciete Review-keuze.
- Deterministische parser getest met `morgen om 15:00`, `volgende dinsdag`,
  duur, recurrence en `Europe/Amsterdam`; UTC-opslag bleef correct.
- GUI-test geslaagd: een voice transcript verscheen in Review met herkenbare
  starttijd, duur en timezone. De oorspronkelijke transcripttekst bleef
  zichtbaar en audio werd niet opgeslagen.
- GUI-test geslaagd: meerdere tijden werden als `Controleer planning` met
  concrete notities gemarkeerd; de gebruiker kreeg `Plan` als expliciete keuze
  in plaats van automatische planning.
- Provider failure viel terug naar een `plain_text` voorstel met behoud van de
  ruwe transcript/capture; er werd geen Task of Action aangemaakt.
- Browserconsole bevatte geen foutmeldingen; de reviewqueue is na de test leeg
  achtergelaten en `/ready` gaf `database: ok`.
- Backend: `93 passed`; frontend/Docker build geslaagd.

### C4-acceptatie — smart views zonder task-browser — 2026-09-19

- Migratie `0013_saved_views` maakt maximaal drie lokale, exporteerbare views
  met een expliciete filterquery.
- Server-side filters zijn getest voor `vandaag`, `deze week`, `overdue`,
  bron, prioriteit, geblokkeerd, ongepland en IANA-timezonegrenzen. De query
  retourneert read-only `TaskOut`-records en voert geen state-transition uit.
- GUI-test geslaagd op `/views`: een ongeplande view is opgeslagen, opnieuw
  geladen en toont uitsluitend de bijbehorende taken. De UI markeert het
  resultaat als `alleen lezen` en biedt links naar Review en Plan.
- GUI-test geslaagd voor de limiet: drie views (`Ongepland werk`, `Vandaag`,
  `Hoge prioriteit`) zijn opgeslagen; de vierde opslagknop is disabled als
  `3/3`.
- Backup export bevat `smart_views`; restore accepteert oudere backups zonder
  dit optionele veld.
- Browserconsole bevatte geen applicatiefouten; `/ready` gaf `database: ok`.
- Backend: `95 passed`; frontend/Docker build geslaagd. De resterende
  autoprefixer-melding in de Docker-build is een bestaande CSS-warning en geen
  runtimefout.

### C5-acceptatie — dagelijkse review en rustige reminders — 2026-09-19

- `GET /api/daily-review` bundelt pending voorstellen, ongeplande inbox,
  overdue en vandaag in één read-only dagbeeld met precies één
  `next_decision`.
- GUI-test geslaagd op `/daily-review`: een pending voorstel werd als eerste
  beslissing getoond en opende de bestaande Review-funnel. Na afwijzen verschoof
  de volgende beslissing naar `Plan ongepland werk`; er werd geen task-state
  verborgen gemuteerd.
- GUI-test geslaagd op `/reminders`: een uitgeschakelde browser-provider werd
  zichtbaar als `browser reminders zijn niet ingeschakeld.`. Quiet-hours en
  provider-disabled zijn API-getest; reminders starten of verplaatsen nooit
  een actie.
- Routine-materialisatie is API-getest op timezone/provenance en idempotentie:
  de tweede materialisatie van dezelfde occurrence retourneert
  `already_materialized` en maakt geen duplicate task.
- Browserconsole bevatte geen applicatiefouten; pending proposals zijn na de
  acceptatietest opgeruimd en `/ready` gaf `database: ok`.
- Backend: `98 passed`; frontend/Docker build geslaagd.

### C6-acceptatie — snelle cross-device ingang — 2026-09-19

- PWA-manifest exposeert shortcuts voor `Snel vastleggen` naar
  `/intake?quick=1` en `Volgende actie` naar `/`.
- `GET /api/widget` levert een compact read-only model met next action,
  open-proposal count en canonical capture/review/execute-links; de API-test
  bevestigt dat deze read model-call geen task-state muteert.
- GUI-test geslaagd op `/widget`: de widget toont de next-action/read-only state
  en de primaire `Snel vastleggen`-ingang. De quick-route opent in `/intake` met
  focus op de snelle tekstingang.
- GUI-test geslaagd voor command menu: de knop en Ctrl+K openen één menu met
  links naar snelle capture, Review, NU en uitvoeren; de browserconsole bleef
  foutvrij.
- Niet in scope gebleven: native platformwidgets, realtime multi-user sync en
  Control Center-integraties.
- Backend: `99 passed`; frontend build en Docker build geslaagd zonder
  autoprefixer-warning; `/ready` gaf `database: ok`.
