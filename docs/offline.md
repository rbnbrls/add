# Offline gebruik

ADD ondersteunt een beperkte offline execute-flow.

- De laatst bekende action wordt lokaal gecachet in IndexedDB.
- Een offline completion wordt als mutation opgeslagen en later naar
  `POST /api/offline/complete` gestuurd.
- De API accepteert de mutation alleen wanneer de action nog `ready` is.
  Anders bewaart de UI een persistent conflictrecord in IndexedDB, toont de
  serverreden en overschrijft ADD nooit stil een nieuwe serverstate. Het record
  verdwijnt pas na de expliciete actie `Conflict gezien`.
- De service worker cachet de execute-shell en manifest voor heropenen zonder netwerk,
  verwijdert oude `add-shell-*` caches bij activatie en gebruikt alleen de execute-shell
  als fallback voor navigaties; API- en asset-fouten worden niet als HTML vermomd.
- Externe integraties, nieuwe captures, planning en restore zijn offline niet beschikbaar.

## UAT

1. Open `/execute` eenmaal online en laad een action.
2. Schakel netwerk uit en heropen `/execute`; controleer `OFFLINE KOPIE`.
3. Start en rond af; controleer de queue-indicator.
4. Schakel netwerk in; controleer dat de queue verdwijnt.
5. Laat dezelfde action intussen server-side wijzigen; controleer de expliciete
   `offline conflict`-melding.
