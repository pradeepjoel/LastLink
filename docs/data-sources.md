# Transport sources — verified 13 October 2026

Both selected archives are **scheduled GTFS**, retrieved over public HTTPS without an account or API key. They contain timetables, not current operating status. The importer records each ZIP's SHA-256, retrieval time, latest member date, and feed validity. It refuses an archive if the required airport and destination corridors cannot be found in the trip/stop sequence. Refresh manually; no polling is required.

## Lignes d’Azur urban GTFS

| Item | Verified finding |
| --- | --- |
| Publisher | Métropole Nice Côte d’Azur / Lignes d’Azur |
| Dataset | [Transport portal entry](https://transport.data.gouv.fr/datasets/donnees-statiques-et-dynamiques-du-reseau-de-transport-lignes-dazur) |
| Download | `https://chouette.enroute.mobi/api/v1/datas/OpendataRLA/gtfs.zip` |
| Format and access | Public scheduled GTFS ZIP; no key or account used |
| Licence | [Licence Ouverte 2.0](https://www.etalab.gouv.fr/wp-content/uploads/2017/04/ETALAB-Licence-Ouverte-v2.0.pdf); retain attribution and update information |
| Tested archive | SHA-256 `7f1dc2c6d387d6fc9817e96ac97fd721c4eede343efe4a939ebfc1c273a0d238`; `feed_info.txt` 2026-10-09–2026-11-18 |
| Verified coverage | Terminal 2 → Jean Médecin direct L2/B trips, and Terminal 2 → Grand Arénas trips in stop order and active service calendars |

The tested urban ZIP has no `transfers.txt`; the user-configured transfer buffer still applies. The archive has 1,424 Terminal 2 → Jean Médecin direct trip records across service patterns before date filtering; this is **not** a daily departure count. No published download rate limit or guaranteed refresh cadence was found; imports are manual.

## ZOU ! Région Sud Express GTFS

| Item | Verified finding |
| --- | --- |
| Publisher | ZOU ! Région Sud via DataSud / national transport portal |
| Dataset | [ZOU Express portal entry](https://transport.data.gouv.fr/datasets/lignes-des-reseaux-transport-zou-provence-alpes-cote-d-azur-express-3-3) |
| Download | `https://www.datasud.fr/fr/dataset/datasets/3743/resource/5153/download/` |
| Format and access | Public scheduled GTFS ZIP; no key or account used |
| Licence | Licence Ouverte 2.0 as stated on the portal; retain attribution and update information |
| Tested archive | SHA-256 `99991149b7e5d755e6198759ef445c27c6e1dac55b994f308a31c2f1a0883ae4`; calendar span 2026-10-09–2027-04-09 |
| Verified coverage | Nice Saint-Augustin → Antibes and → Cannes rail trips; airport Terminal 2 → Gare SNCF Cannes bus 81 trips, all validated from GTFS stop order |

The tested ZOU archive has two Nice Saint-Augustin naming/stop variants. Its raw trip table contains 78 rail trip records to Antibes and 78 to Cannes and 25 airport-to-Cannes bus records across all service patterns, **before** active-date filtering. Each query applies `calendar.txt` and `calendar_dates.txt`. The archive also has optional GTFS transfer rules; the router applies rules that match supported exact stop IDs. No published rate limit or guaranteed refresh cadence was found. The archive's own member timestamp and the local retrieval timestamp are both checked against a seven-day confidence threshold.

## Cross-feed airport access

[Nice Côte d’Azur Airport's train access page](https://www.nice.aeroport.fr/acces/trains) describes the free L2/B tram between Terminal 2, Terminal 1, and Grand Arénas, plus the pedestrian link to Nice Saint-Augustin. Its seven-minute description starts at Terminal 1. LastLink uses an **8-minute planning assumption** from Grand Arénas to Nice Saint-Augustin, not a measured promise from the airport. The stop coordinates in both GTFS archives must be present and near one another (Grand Arénas–station within 850 m; the two Terminal 2 stops within 350 m), or the cross-feed rail walk is disabled. The passenger can change airport exit and stop-access estimates; the 8-minute inter-stop walk is displayed separately.

## Sources considered for later milestones

- The Lignes d’Azur [dataset](https://transport.data.gouv.fr/datasets/donnees-statiques-et-dynamiques-du-reseau-de-transport-lignes-dazur) also lists GTFS-RT trip updates and vehicle positions. An endpoint probe succeeded, but content, update cadence, access rights, and caching terms were not validated. No live feed is used.
- A separate [ZOU regional rail dataset](https://transport.data.gouv.fr/datasets/trains-zou-en-provence-alpes-cote-dazur) exists. It was inspected but not combined with the ZOU Express archive, which already covers the selected rail corridor, to avoid duplicate journeys.
- [SNCF national GTFS](https://transport.data.gouv.fr/datasets/horaires-sncf) is available, but its ODbL and specific usage conditions require separate evaluation, and the selected regional feed supplies this corridor.
- No suitably documented, licensed, unauthenticated Nice Airport flight-status API was verified. Flight times and delays remain explicitly simulated passenger inputs.

The app labels both feeds and their content dates. Public deployment should re-check each publisher's terms and validate freshly downloaded archives before showing schedules.
