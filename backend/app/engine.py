"""Passenger-facing assessment of deterministic scheduled itineraries."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from sqlite3 import Connection
from zoneinfo import ZoneInfo

from .gtfs import metadata
from .network import DESTINATION_NODES, PROVIDERS, State, build_rides, find_itineraries, service_window_end

PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
NO_CONNECTION = "No feasible public transport connection was found for this destination using the available schedule data."


def local_arrival(value: datetime) -> datetime:
    if value.tzinfo is None:
        a = value.replace(tzinfo=PARIS, fold=0)
        b = value.replace(tzinfo=PARIS, fold=1)
        if a.utcoffset() != b.utcoffset():
            raise ValueError("Ambiguous or nonexistent Europe/Paris time; include an explicit UTC offset")
        value = a
    return value.astimezone(PARIS)


def _source_status(connections: dict[str, Connection], day: date) -> list[dict]:
    now = datetime.now(UTC)
    sources = []
    for source, con in connections.items():
        data = metadata(con)
        if data.get("schema_version") != "2":
            raise ValueError(f"{source} GTFS database must be refreshed")
        fetched = datetime.fromisoformat(data["fetched_at"])
        archive_date = date.fromisoformat(data["archive_content_date"])
        key = day.strftime("%Y%m%d")
        stale = (now-fetched > timedelta(days=7) or now.date()-archive_date > timedelta(days=7))
        outside = bool(data["feed_start"] and key < data["feed_start"] or data["feed_end"] and key > data["feed_end"])
        sources.append({"id": source, "provider": PROVIDERS[source], "source_url": data["source_url"],
                        "sha256": data["sha256"], "fetched_at": fetched,
                        "archive_content_date": data["archive_content_date"],
                        "feed_start": data["feed_start"], "feed_end": data["feed_end"],
                        "stale": stale, "outside_validity": outside})
    return sources


def _status(state: State, airport_exit: datetime, stop_access: int, boarding_buffer: int,
            exit_uncertainty: int, risk_margin: int, health: dict[str, dict]) -> str:
    if any(health[ride.source]["stale"] or
           (health[ride.source]["feed_start"] and ride.service_day.strftime("%Y%m%d") < health[ride.source]["feed_start"]) or
           (health[ride.source]["feed_end"] and ride.service_day.strftime("%Y%m%d") > health[ride.source]["feed_end"])
           for ride in state.rides):
        return "UNKNOWN"
    first = state.rides[0]
    ready = airport_exit.astimezone(UTC) + timedelta(minutes=stop_access+boarding_buffer)
    if first.departure < ready:
        return "NOT_FEASIBLE"
    if first.departure < ready + timedelta(minutes=exit_uncertainty):
        return "AT_RISK"
    if any(slack < risk_margin for slack in state.buffers[1:]):
        return "AT_RISK"
    return "FEASIBLE"


def _serialize(state: State, airport_exit: datetime, stop_access: int, status: str) -> dict:
    exit_utc = airport_exit.astimezone(UTC)
    parts = [{"kind": "walk", "from_stop": "Airport exit", "to_stop": state.rides[0].from_stop,
              "departure": exit_utc.astimezone(PARIS),
              "arrival": (exit_utc+timedelta(minutes=stop_access)).astimezone(PARIS),
              "duration_minutes": stop_access, "note": "Estimated stop access time"}]
    walks = {(w.from_node, w.to_node): w for w in state.walks}
    previous = None
    for ride, slack in zip(state.rides, state.buffers):
        if previous and previous.to_node != ride.from_node:
            walk = walks.get((previous.to_node, ride.from_node))
            if walk:
                parts.append({"kind": "walk", "from_stop": previous.to_stop, "to_stop": ride.from_stop,
                              "departure": previous.arrival.astimezone(PARIS),
                              "arrival": (previous.arrival+timedelta(minutes=walk.minutes)).astimezone(PARIS),
                              "duration_minutes": walk.minutes, "note": walk.note})
        parts.append({"kind": "ride", "mode": ride.mode, "route": ride.route, "source": PROVIDERS[ride.source],
                      "source_id": ride.source, "trip_id": ride.trip_id, "from_stop": ride.from_stop,
                      "to_stop": ride.to_stop, "from_stop_id": ride.from_stop_id, "to_stop_id": ride.to_stop_id,
                      "service_day": ride.service_day.isoformat(),
                      "departure": ride.departure.astimezone(PARIS), "arrival": ride.arrival.astimezone(PARIS),
                      "connection_buffer_minutes": slack})
        previous = ride
    walk_minutes = stop_access + sum(w.minutes for w in state.walks)
    return {"status": status, "departure": state.rides[0].departure.astimezone(PARIS),
            "arrival": state.rides[-1].arrival.astimezone(PARIS),
            "duration_minutes": int((state.rides[-1].arrival-exit_utc).total_seconds()//60),
            "transfers": len(state.rides)-1, "walk_minutes": walk_minutes,
            "minimum_connection_buffer_minutes": min(state.buffers),
            "sources": sorted({PROVIDERS[ride.source] for ride in state.rides}),
            "legs": parts}


def _rank(item: dict):
    priority = {"FEASIBLE": 0, "AT_RISK": 1, "UNKNOWN": 2, "NOT_FEASIBLE": 3}
    return (priority[item["status"]], item["arrival"].astimezone(UTC), item["transfers"], item["walk_minutes"])


def assess(connections: dict[str, Connection], scheduled: datetime, destination: str, delay_minutes: int,
           exit_minutes: int, checked_baggage: bool, exit_uncertainty_minutes: int = 10,
           stop_access_minutes: int = 8, boarding_buffer_minutes: int = 5,
           transfer_buffer_minutes: int = 5, preferred_modes: list[str] | None = None) -> dict:
    if destination not in DESTINATION_NODES:
        raise ValueError("Unsupported destination")
    flight = local_arrival(scheduled)
    simulated = (flight.astimezone(UTC)+timedelta(minutes=delay_minutes)).astimezone(PARIS)
    exit_total = exit_minutes + (15 if checked_baggage else 0)
    planned_exit = (flight.astimezone(UTC)+timedelta(minutes=exit_total)).astimezone(PARIS)
    estimated_exit = (simulated.astimezone(UTC)+timedelta(minutes=exit_total)).astimezone(PARIS)
    latest_exit = (estimated_exit.astimezone(UTC)+timedelta(minutes=exit_uncertainty_minutes)).astimezone(PARIS)
    end = max(service_window_end(planned_exit), service_window_end(estimated_exit))
    if end <= estimated_exit.astimezone(UTC):
        end += timedelta(days=1)
    health_list = _source_status(connections, simulated.date())
    health = {item["id"]: item for item in health_list}
    modes = set(preferred_modes or ["tram", "train", "bus"])
    by_node, walks, rules, routing_warnings = build_rides(connections,
        min(planned_exit.astimezone(UTC), estimated_exit.astimezone(UTC)), end, modes)
    kwargs = {"stop_access_minutes": stop_access_minutes, "boarding_buffer_minutes": boarding_buffer_minutes,
              "transfer_buffer_minutes": transfer_buffer_minutes, "end": end, "transfer_rules": rules}
    planned = find_itineraries(by_node, walks, DESTINATION_NODES[destination], planned_exit, **kwargs)
    current = find_itineraries(by_node, walks, DESTINATION_NODES[destination], estimated_exit, **kwargs)
    ontime_items = [(_serialize(s, planned_exit, stop_access_minutes,
                   _status(s, planned_exit, stop_access_minutes, boarding_buffer_minutes,
                           exit_uncertainty_minutes, 5, health)), s) for s in planned]
    # The original plan is the earliest complete arrival reachable with the base estimate.
    # Keep its risk visible even when a later, safer route is recommended.
    ontime_items.sort(key=lambda pair: (pair[0]["arrival"].astimezone(UTC),
                                       pair[0]["transfers"], pair[0]["walk_minutes"]))
    original_state = ontime_items[0][1] if ontime_items else None
    original = (_serialize(original_state, planned_exit, stop_access_minutes,
                _status(original_state, estimated_exit, stop_access_minutes, boarding_buffer_minutes,
                        exit_uncertainty_minutes, 5, health)) if original_state else None)
    current_items = [_serialize(s, estimated_exit, stop_access_minutes,
                     _status(s, estimated_exit, stop_access_minutes, boarding_buffer_minutes,
                             exit_uncertainty_minutes, 5, health)) for s in current]
    current_items.sort(key=_rank)
    recommendation = next((item for item in current_items if item["status"] in ("FEASIBLE", "AT_RISK")), None)
    alternatives = sorted((item for item in current_items if item is not recommendation),
                          key=lambda item: (item["arrival"].astimezone(UTC), item["transfers"], item["walk_minutes"]))[:3]
    safe = [item for item in current_items if item["status"] == "FEASIBLE"]
    last = max(safe, key=lambda item: (item["departure"].astimezone(UTC),
                                      -item["arrival"].astimezone(UTC).timestamp())) if safe else None
    if original:
        status = original["status"]
    elif recommendation:
        status = recommendation["status"]
    elif any(item["stale"] or item["outside_validity"] for item in health_list):
        status = "UNKNOWN"
    else:
        status = "NOT_FEASIBLE"
    warnings = ["Flight arrival and delay are simulated. All transport times are scheduled, not live."] + routing_warnings
    for item in health_list:
        if item["stale"]:
            warnings.append(f"{item['provider']} local archive is stale; refresh it before relying on routes from that source.")
        # A 24:xx trip after midnight can still use the prior valid GTFS
        # service day, even when the passenger's calendar date is outside it.
        valid_overnight = any(ride.source == item["id"] and
                              item["feed_start"] <= ride.service_day.strftime("%Y%m%d") <= item["feed_end"]
                              for state in current for ride in state.rides)
        if item["outside_validity"] and not valid_overnight:
            warnings.append(f"Requested date is outside {item['provider']} feed validity.")
    if not safe:
        warnings.append(NO_CONNECTION)
    if recommendation and recommendation["status"] == "FEASIBLE":
        warnings.append("This is feasible only under the displayed exit, walking and transfer assumptions; it is not guaranteed.")
    last_warning = None
    if last:
        left = int((last["departure"].astimezone(UTC)-latest_exit.astimezone(UTC)).total_seconds()//60)
        if left <= 30:
            last_warning = "The last feasible complete journey leaves soon under the slower exit scenario."
    return {"status": status, "destination": destination,
            "scheduled_arrival": flight, "simulated_arrival": simulated,
            "estimated_exit": estimated_exit, "exit_range_end": latest_exit,
            "exit_duration_minutes": exit_total, "boarding_buffer_minutes": boarding_buffer_minutes,
            "assumptions": {"exit_uncertainty_minutes": exit_uncertainty_minutes,
                            "stop_access_minutes": stop_access_minutes,
                            "boarding_buffer_minutes": boarding_buffer_minutes,
                            "transfer_buffer_minutes": transfer_buffer_minutes,
                            "grand_arenas_station_walk_minutes": 8,
                            "service_window_end": end.astimezone(PARIS)},
            "original_itinerary": original, "recommended_itinerary": recommendation,
            "itinerary_alternatives": alternatives, "last_feasible_itinerary": last,
            "last_connection_warning": last_warning,
            "data": {"kind": "scheduled_gtfs", "realtime": False, "sources": health_list},
            "warnings": warnings}
