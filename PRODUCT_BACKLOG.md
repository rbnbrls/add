# ADD product backlog

Dit is de actuele backlog van ADD. De uitgewerkte roadmap en historische
acceptatie-aantekeningen staan in [`docs/roadmap.md`](docs/roadmap.md); dit
bestand bevat alleen werk dat nog openstaat of bewust is uitgesteld.

## Productregels

Iedere backlogbijdrage moet deze regels behouden:

1. ADD is de bron van waarheid voor tasks, actions, sessions en completions.
2. Hermes/LLM mag voorstellen, splitsen of drafts maken, maar schrijft nooit
   rechtstreeks naar de database.
3. Home Assistant en andere bronnen leveren context of voorstellen; zij bezitten
   geen task-state.
4. State-transitions zijn expliciet, transactioneel en getest.
5. De hoofdflow toont maximaal één primaire actie; alternatieven zijn secundair.
6. Geen Redis, worker, gamification of complexe planning zonder aangetoonde
   MVP-noodzaak.

## Actief

### R10 — Product hardening en portable gebruik

**Status:** revalidate  
**Prioriteit:** P0  
**Dependencies:** R1–R9

De implementatie is aanwezig. De resterende backlog is bewijsvoering in de
doelomgeving:

- [ ] Voer een Coolify-specifieke fresh deployment uit en leg de uitkomst vast.
- [ ] Voer een Coolify-specifieke upgrade uit vanaf een bestaande database en
  leg migratie-, health- en rollback-uitkomst vast.
- [ ] Voer herhaalbare UAT uit op echte mobiele en desktopapparaten voor PWA,
  offline lezen/uitvoeren en reconnect.
- [ ] Test multi-device mutation conflicts op echte apparaten; leg vast dat
  conflicten zichtbaar worden en nooit stil worden overschreven.
- [ ] Werk de deployment-, offline- en UAT-contracten bij met reproduceerbare
  stappen en bewijs.

**Done wanneer:** de Coolify fresh-deploy/upgrade en real-device UAT herhaalbaar
zijn uitgevoerd, de resultaten zijn gedocumenteerd en `pytest` in `backend/` en
`npm run build` in `frontend/` groen zijn.

## Uitgesteld — alleen na evidence gate

### R12 — Optionele motivation experiments

**Status:** deferred  
**Prioriteit:** P3  
**Dependencies:** R7, R11

Niet starten voordat er een meetbaar motivatieprobleem is aangetoond.

Evidence gate:

- [ ] Definieer een meetbare hypothese.
- [ ] Leg een baseline vast.
- [ ] Definieer een evaluatieperiode en succes-/stopcriteria.

Mogelijke scope na goedkeuring:

- append-only points, uitsluitend afgeleid van completion events;
- een minimale, toegankelijke visual companion, afgeleid van points;
- geen streak punishment, verliesmechaniek of blokkade van uitvoering.

### R13 — True shared body doubling

**Status:** deferred  
**Prioriteit:** P3  
**Dependencies:** R11

Niet starten zonder een concrete tweede-client use case en testscenario.

Evidence gate:

- [ ] Bevestig een concrete tweede-device use case.
- [ ] Leg een testscenario met twee echte clients vast.
- [ ] Beoordeel privacy, disconnect en reconnect gedrag.

Mogelijke scope na goedkeuring:

- signaling/presence;
- session join, begin-doel en eind-resultaat;
- WebRTC alleen wanneer de tweede-device use case is gevalideerd.

Niet in scope zonder aanvullende noodzaak: video/audio-infrastructuur.

## Bewust niet op de backlog

Deze ideeën zijn in de roadmap onderzocht maar zijn geen goedgekeurde backlog:

- Kanban, Eisenhower Matrix, uitgebreide projectboards en meerdere parallelle
  primaire acties.
- Habits, punten, streaks, virtuele companions, themes, icons en decoratie
  buiten de R12-evidence gate.
- Collaboration of taaktoewijzing zonder aangetoonde single-user MVP-behoefte.
- Audio meeting summaries en OCR/scans vóór bewezen voice/text capture en
  duidelijke privacy- en retentie-eisen.
- Constant-, e-mail- of location-reminders als standaard.

## Afgerond en daarom niet meer backlog

Volgens de actuele audit in `docs/roadmap.md` zijn R0–R9, R11 en C1–C6
afgerond. Ze blijven daar staan als product- en acceptatiehistorie, maar worden
hier niet als open werk gedupliceerd.

## Verificatie bij ieder backlog-item

Een item is pas klaar wanneer het als verticale backend/frontend-flow is
geleverd, schemawijzigingen een Alembic-migratie hebben, state-transitions en
foutgevallen zijn getest, de one-primary-action-regel en toegankelijkheid zijn
behouden, relevante contractdocumentatie is bijgewerkt en het volgende draait:

```text
pytest                 # vanuit backend/
npm run build          # vanuit frontend/
```

