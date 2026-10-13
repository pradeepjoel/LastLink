"""Deterministic, bounded time-dependent label-correcting transit routing."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from sqlite3 import Connection
from zoneinfo import ZoneInfo

from .gtfs import active_service, named_boardable_stop_ids, service_instant

UTC = timezone.utc
PARIS = ZoneInfo("Europe/Paris")
DESTINATION_NODES = {"nice-centre": "jean", "antibes": "antibes", "cannes": "cannes"}
STOP_GROUPS = {
    "urban": {
        "airport": ["Aéroport Terminal 2"],
        "grand": ["Grand Arénas"],
        "jean": ["Jean Médecin"],
    },
    "regional": {
        "airport": ["Aéroport Terminal 2"],
        "saint_augustin": ["Nice Saint-Augustin", "Nice-Saint-Augustin"],
        "antibes": ["Antibes"],
        "cannes": ["Cannes", "Gare SNCF Cannes"],
    },
}
PROVIDERS = {"urban": "Lignes d'Azur", "regional": "ZOU ! Région Sud"}
MODES = {"0": "tram", "2": "train", "3": "bus"}


@dataclass(frozen=True)
class Ride:
    source: str
    trip_id: str
    route: str
    mode: str
    from_node: str
    to_node: str
    from_stop: str
    to_stop: str
    from_stop_id: str
    to_stop_id: str
    departure: datetime  # UTC
    arrival: datetime  # UTC
    service_day: date | None = None


@dataclass(frozen=True)
class Walk:
    from_node: str
    to_node: str
    minutes: int
    note: str


@dataclass(frozen=True)
class State:
    node: str
    time: datetime  # UTC
    rides: tuple[Ride, ...]
    walks: tuple[Walk, ...]
    buffers: tuple[int, ...]
    last_alight: datetime | None
    seen: frozenset[str]


TransferRules = dict[tuple[str, str, str], tuple[int, int]]


def service_window_end(arrival: datetime) -> datetime:
    local = arrival.astimezone(PARIS)
    day = local.date() if local.hour < 4 else local.date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, 4, tzinfo=PARIS).astimezone(UTC)


def _stop_map(con: Connection, source: str) -> dict[str, str]:
    mapping = {}
    for node, names in STOP_GROUPS[source].items():
        for stop_id in named_boardable_stop_ids(con, names):
            mapping[stop_id] = node
    return mapping


def _validate_link_coordinates(urban: Connection, regional: Connection, urban_map: dict[str, str],
                               regional_map: dict[str, str]) -> bool:
    """Refuse the cross-feed link if required stop coordinates are absent or implausible."""
    from math import asin, cos, radians, sin, sqrt

    def coords(con, mapping, node):
        ids = [key for key, value in mapping.items() if value == node]
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        return [(row[0], row[1]) for row in con.execute(
            f"SELECT lat,lon FROM stops WHERE id IN ({marks}) AND lat IS NOT NULL AND lon IS NOT NULL", ids)]

    def metres(a, b):
        lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
        h = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
        return 2*6_371_000*asin(sqrt(h))

    airport_urban = coords(urban, urban_map, "airport")
    airport_regional = coords(regional, regional_map, "airport")
    grand = coords(urban, urban_map, "grand")
    station = coords(regional, regional_map, "saint_augustin")
    if not all((airport_urban, airport_regional, grand, station)):
        return False
    return (min(metres(a,b) for a in airport_urban for b in airport_regional) <= 350
            and min(metres(a,b) for a in grand for b in station) <= 850)


def build_rides(connections: dict[str, Connection], start: datetime, end: datetime,
                allowed_modes: set[str]) -> tuple[dict[str, list[Ride]], list[Walk], TransferRules, list[str]]:
    """Build corridor edges from actual GTFS trips, not inferred frequencies."""
    urban_map = _stop_map(connections["urban"], "urban")
    regional_map = _stop_map(connections["regional"], "regional")
    warnings = []
    link_ok = _validate_link_coordinates(connections["urban"], connections["regional"], urban_map, regional_map)
    if not link_ok:
        warnings.append("The tram-to-rail walking link could not be verified from stop coordinates.")
    walks = [Walk("grand", "saint_augustin", 8, "Grand Arénas to Nice Saint-Augustin; 8-minute walking assumption")]
    if not link_ok:
        walks = []
    by_node: dict[str, list[Ride]] = defaultdict(list)
    transfer_rules: TransferRules = {}
    date0 = start.astimezone(PARIS).date() - timedelta(days=1)
    date1 = end.astimezone(PARIS).date()
    for source, con in connections.items():
        mapping = urban_map if source == "urban" else regional_map
        if not mapping:
            continue
        ids = list(mapping)
        marks = ",".join("?" for _ in ids)
        for rule in con.execute(f"SELECT from_id,to_id,type,min_seconds FROM transfers WHERE from_id IN ({marks})", ids):
            if rule["to_id"] in mapping:
                transfer_rules[(source, rule["from_id"], rule["to_id"])] = (rule["type"], rule["min_seconds"])
        rows = con.execute(f"""SELECT st.trip_id,st.stop_id,st.seq,st.arrival,st.departure,st.pickup,st.dropoff,
            t.service_id,r.name route,r.type mode,s.name stop_name
            FROM stop_times st JOIN trips t ON t.id=st.trip_id JOIN routes r ON r.id=t.route_id
            JOIN stops s ON s.id=st.stop_id WHERE st.stop_id IN ({marks}) ORDER BY st.trip_id,st.seq""", ids)
        trip_calls: dict[str, list] = defaultdict(list)
        for row in rows:
            if row["mode"] in MODES and MODES[row["mode"]] in allowed_modes:
                trip_calls[row["trip_id"]].append(row)
        active_cache: dict[tuple[str, str], bool] = {}
        for calls in trip_calls.values():
            service_id = calls[0]["service_id"]
            day = date0
            while day <= date1:
                key = (service_id, day.isoformat())
                if key not in active_cache:
                    active_cache[key] = active_service(con, service_id, day)
                if active_cache[key]:
                    for index, a in enumerate(calls):
                        if a["pickup"] in ("1", "3"):
                            continue
                        dep = service_instant(day, a["departure"]).astimezone(UTC)
                        if dep < start or dep > end:
                            continue
                        for b in calls[index+1:]:
                            if b["dropoff"] in ("1", "3") or mapping[a["stop_id"]] == mapping[b["stop_id"]]:
                                continue
                            arr = service_instant(day, b["arrival"]).astimezone(UTC)
                            if arr <= dep or arr > end:
                                continue
                            ride = Ride(source, a["trip_id"], a["route"], MODES[a["mode"]],
                                        mapping[a["stop_id"]], mapping[b["stop_id"]],
                                        a["stop_name"], b["stop_name"], a["stop_id"], b["stop_id"], dep, arr,
                                        service_day=day)
                            by_node[ride.from_node].append(ride)
                day += timedelta(days=1)
    for rides in by_node.values():
        rides.sort(key=lambda r: (r.departure, r.arrival, r.trip_id))
    return by_node, walks, transfer_rules, warnings


def find_itineraries(by_node: dict[str, list[Ride]], walks: list[Walk], destination: str,
                     airport_exit: datetime, stop_access_minutes: int, boarding_buffer_minutes: int,
                     transfer_buffer_minutes: int, end: datetime, max_rides: int = 4,
                     transfer_rules: TransferRules | None = None) -> list[State]:
    """Label-correcting search of simple paths with at most four vehicle legs."""
    start = airport_exit.astimezone(UTC) + timedelta(minutes=stop_access_minutes)
    walk_by_node: dict[str, list[Walk]] = defaultdict(list)
    for walk in walks:
        walk_by_node[walk.from_node].append(walk)
    stack = [State("airport", start, (), (), (), None, frozenset({"airport"}))]
    completed = []
    seen_signatures = set()
    # Keep only nondominated partial journeys for the same first departure,
    # node, transfer platform, visited nodes and leg count. Slack above five
    # minutes has the same transfer-risk classification, so it need not create
    # another label. This prevents timetable combinations from exploding at
    # daytime frequencies while retaining the last first departure.
    labels: dict[tuple, list[tuple[datetime, int]]] = defaultdict(list)
    while stack:
        state = stack.pop()
        if state.rides:
            last = state.rides[-1]
            key = (state.node, state.rides[0].departure, len(state.rides),
                   last.source, last.to_stop_id, state.seen)
            score = min(5, min(state.buffers[1:], default=5))
            prior = labels[key]
            if any(time <= state.time and risk >= score for time, risk in prior):
                continue
            labels[key] = [(time, risk) for time, risk in prior
                           if not (state.time <= time and score >= risk)] + [(state.time, score)]
        if state.node == destination and state.rides:
            signature = tuple((r.source, r.trip_id, r.departure) for r in state.rides)
            if signature not in seen_signatures:
                completed.append(state)
                seen_signatures.add(signature)
            continue
        if len(state.rides) >= max_rides:
            continue
        for walk in walk_by_node[state.node]:
            if walk.to_node not in state.seen:
                reached = state.time + timedelta(minutes=walk.minutes)
                if reached <= end:
                    stack.append(State(walk.to_node, reached, state.rides, state.walks+(walk,),
                                       state.buffers, state.last_alight, state.seen|{walk.to_node}))
        candidates = []
        for ride in by_node.get(state.node, []):
            if ride.departure > end:
                break
            boarding_ready = state.time + timedelta(minutes=boarding_buffer_minutes)
            required_transfer_seconds = transfer_buffer_minutes * 60
            if state.rides and transfer_rules and state.rides[-1].source == ride.source:
                rule = transfer_rules.get((ride.source, state.rides[-1].to_stop_id, ride.from_stop_id))
                if rule:
                    if rule[0] == 3:
                        continue
                    required_transfer_seconds = max(required_transfer_seconds, rule[1])
            if state.last_alight:
                boarding_ready = max(boarding_ready, state.last_alight + timedelta(seconds=required_transfer_seconds))
            if ride.departure < boarding_ready or ride.to_node in state.seen:
                continue
            slack = int((ride.departure-boarding_ready).total_seconds() // 60)
            candidates.append(State(ride.to_node, ride.arrival, state.rides+(ride,), state.walks,
                                    state.buffers+(slack,), ride.arrival, state.seen|{ride.to_node}))
        # Earliest departures are popped first, improving label pruning.
        stack.extend(reversed(candidates))
    return completed
