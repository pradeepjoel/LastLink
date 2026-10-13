# API

OpenAPI schema: `/openapi.json`; interactive docs: `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process health and data-loaded flag |
| GET | `/api/data-sources/status` | Local feed provenance and scheduled-only flag |
| GET | `/api/destinations` | Nice centre, Antibes, and Cannes availability |
| POST | `/api/journeys/assess` | Evaluate one simulated flight and complete onward journeys |

Example request:

```json
{
  "airport": "NCE",
  "destination": "cannes",
  "scheduled_arrival": "2026-10-13T20:50:00",
  "delay_minutes": 30,
  "checked_baggage": false,
  "exit_minutes": 25,
  "exit_uncertainty_minutes": 10,
  "stop_access_minutes": 8,
  "boarding_buffer_minutes": 5,
  "transfer_buffer_minutes": 5,
  "preferred_modes": ["tram", "train", "bus"]
}
```

Arrival is interpreted as Europe/Paris local time; callers can include a UTC offset to disambiguate a daylight-saving transition. `exit_minutes` is measured from simulated landing to airport exit; checked baggage adds 15 minutes. The four additional time controls are planning assumptions in minutes.

The response has a top-level `status`, `scheduled_arrival`, `simulated_arrival`, `estimated_exit`, `exit_range_end`, `assumptions`, and `warnings`. `original_itinerary` shows the earliest complete no-delay plan, classified under the delayed scenario. `recommended_itinerary`, up to three `itinerary_alternatives`, and `last_feasible_itinerary` are complete journeys for the delayed scenario; each can be `null` or empty. Each itinerary has a status, first vehicle departure, final arrival, duration from airport exit, transfers, total assumed walking, minimum spare connection time, providers, and an ordered `legs` timeline. Ride legs include mode, route, source, GTFS trip/stop IDs and service day; walk legs include their assumption note. `data.sources` gives feed URL, SHA-256, fetch/content dates, validity, and stale/outside-validity flags. The source's outside-validity flag compares the requested calendar date; individual ride statuses use their actual GTFS service day, which matters for 24:xx trips after midnight. All times include an offset.

`FEASIBLE` means the schedule is reachable under the supplied assumptions, including the slower airport-exit scenario. `AT_RISK` means the base estimate catches a vehicle but uncertainty or tight transfer slack makes it vulnerable. `NOT_FEASIBLE` means the original plan is missed or no complete path remains. `UNKNOWN` means a path depends on stale or out-of-validity data. A feasible recommendation can exist even while the **original** plan has status `NOT_FEASIBLE`; callers should display both fields.

`503` means a required database or assessment is unavailable. `422` means invalid input, unsupported mode, or an ambiguous/nonexistent local arrival without an offset. The service never returns invented departures.
