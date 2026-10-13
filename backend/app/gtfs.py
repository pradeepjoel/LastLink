"""Scheduled GTFS import and queries. No realtime claims are made here."""
import csv
import hashlib
import io
import sqlite3
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import SOURCE_URL, ORIGIN_NAME, DESTINATION_NAME

PARIS = ZoneInfo("Europe/Paris")
REQUIRED = {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt"}


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _rows(z: zipfile.ZipFile, name: str):
    with z.open(name + ".txt") as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def download(url: str = SOURCE_URL) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "LastLink/0.1 (GTFS scheduled data research)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(80_000_001)
    if len(data) > 80_000_000:
        raise ValueError("GTFS archive exceeds 80 MB download limit")
    return data


def import_feed(data: bytes, path: Path, fetched_at: datetime | None = None, *, source_url: str = SOURCE_URL,
                kind: str = "urban") -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("GTFS archive is not a valid ZIP file")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if not REQUIRED.issubset(z.namelist()):
            raise ValueError("GTFS archive is missing required tables")
        if any(x.file_size > 100_000_000 for x in z.infolist()):
            raise ValueError("GTFS table exceeds size limit")
        temp = path.with_suffix(".importing")
        temp.unlink(missing_ok=True)
        try:
            con = connect(temp)
            con.executescript("""
                CREATE TABLE stops(id TEXT PRIMARY KEY, name TEXT NOT NULL, parent TEXT, location_type TEXT,
                    lat REAL, lon REAL);
                CREATE TABLE routes(id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, agency_id TEXT);
                CREATE TABLE trips(id TEXT PRIMARY KEY, route_id TEXT NOT NULL, service_id TEXT NOT NULL);
                CREATE TABLE stop_times(trip_id TEXT NOT NULL, stop_id TEXT NOT NULL, seq INTEGER NOT NULL,
                    arrival INTEGER NOT NULL, departure INTEGER NOT NULL, pickup TEXT, dropoff TEXT);
                CREATE TABLE calendar(service_id TEXT PRIMARY KEY, start TEXT NOT NULL, end TEXT NOT NULL,
                    mon INTEGER, tue INTEGER, wed INTEGER, thu INTEGER, fri INTEGER, sat INTEGER, sun INTEGER);
                CREATE TABLE exceptions(service_id TEXT NOT NULL, day TEXT NOT NULL, type INTEGER NOT NULL,
                    PRIMARY KEY(service_id, day));
                CREATE TABLE transfers(from_id TEXT NOT NULL, to_id TEXT NOT NULL, type INTEGER NOT NULL,
                    min_seconds INTEGER NOT NULL);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            con.executemany("INSERT INTO stops VALUES(?,?,?,?,?,?)", ((r["stop_id"], r["stop_name"], r.get("parent_station", ""), r.get("location_type", ""), float(r["stop_lat"]) if r.get("stop_lat") else None, float(r["stop_lon"]) if r.get("stop_lon") else None) for r in _rows(z, "stops")))
            con.executemany("INSERT INTO routes VALUES(?,?,?,?)", ((r["route_id"], r.get("route_short_name") or r.get("route_long_name") or r["route_id"], r["route_type"], r.get("agency_id", "")) for r in _rows(z, "routes")))
            con.executemany("INSERT INTO trips VALUES(?,?,?)", ((r["trip_id"], r["route_id"], r["service_id"]) for r in _rows(z, "trips")))
            con.executemany("INSERT INTO stop_times VALUES(?,?,?,?,?,?,?)", ((r["trip_id"], r["stop_id"], int(r["stop_sequence"]), parse_time(r["arrival_time"]), parse_time(r["departure_time"]), r.get("pickup_type", "0"), r.get("drop_off_type", "0")) for r in _rows(z, "stop_times")))
            con.executemany("INSERT INTO calendar VALUES(?,?,?,?,?,?,?,?,?,?)", ((r["service_id"], r["start_date"], r["end_date"], *(int(r[x]) for x in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))) for r in _rows(z, "calendar")))
            con.executemany("INSERT INTO exceptions VALUES(?,?,?)", ((r["service_id"], r["date"], int(r["exception_type"])) for r in _rows(z, "calendar_dates")))
            if "transfers.txt" in z.namelist():
                con.executemany("INSERT INTO transfers VALUES(?,?,?,?)", ((r["from_stop_id"], r["to_stop_id"], int(r.get("transfer_type") or 0), int(r.get("min_transfer_time") or 0)) for r in _rows(z, "transfers")))
            con.executescript("CREATE INDEX ix_times_stop ON stop_times(stop_id,trip_id,seq); CREATE INDEX ix_times_trip ON stop_times(trip_id,seq);")
            if kind == "urban":
                origin_ids = station_child_ids(con, ORIGIN_NAME)
                destination_ids = station_child_ids(con, DESTINATION_NAME)
                if not origin_ids or not destination_ids or not _direct_trip_count(con, origin_ids, destination_ids):
                    raise ValueError("Feed has no complete Terminal 2 to Jean Médecin trip")
            elif kind == "regional":
                if not (has_direct_connection(con, ["Nice Saint-Augustin", "Nice-Saint-Augustin"], ["Antibes"], "2")
                        and has_direct_connection(con, ["Nice Saint-Augustin", "Nice-Saint-Augustin"], ["Cannes"], "2")
                        and has_direct_connection(con, ["Aéroport Terminal 2"], ["Gare SNCF Cannes"], "3")):
                    raise ValueError("Regional feed lacks a verified rail or airport bus corridor")
            else:
                raise ValueError("Unknown source kind")
            info = next(_rows(z, "feed_info"), {}) if "feed_info.txt" in z.namelist() else {}
            limits = con.execute("SELECT MIN(start),MAX(end) FROM calendar").fetchone()
            archive_date = max(x.date_time for x in z.infolist())
            meta = {
                "schema_version": "2",
                "kind": kind,
                "source_url": source_url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "fetched_at": (fetched_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
                "archive_content_date": f"{archive_date[0]:04d}-{archive_date[1]:02d}-{archive_date[2]:02d}",
                "feed_start": info.get("feed_start_date") or limits[0] or "",
                "feed_end": info.get("feed_end_date") or limits[1] or "",
            }
            con.executemany("INSERT INTO metadata VALUES(?,?)", meta.items())
            con.commit()
            con.close()
            temp.replace(path)
            return meta
        except Exception:
            try:
                con.close()
            except UnboundLocalError:
                pass
            temp.unlink(missing_ok=True)
            raise


def parse_time(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if not 0 <= hours <= 47 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise ValueError("Invalid GTFS time")
    return hours * 3600 + minutes * 60 + seconds


def station_child_ids(con: sqlite3.Connection, name: str) -> list[str]:
    return [r[0] for r in con.execute("""SELECT child.id FROM stops child JOIN stops parent ON child.parent=parent.id
        WHERE parent.name=? AND COALESCE(NULLIF(child.location_type,''),'0')='0'""", (name,))]


def named_boardable_stop_ids(con: sqlite3.Connection, names: list[str]) -> list[str]:
    if not names:
        return []
    marks = ",".join("?" for _ in names)
    return [r[0] for r in con.execute(f"SELECT id FROM stops WHERE name IN ({marks}) AND COALESCE(NULLIF(location_type,''),'0')='0'", names)]


def has_direct_connection(con: sqlite3.Connection, origin_names: list[str], destination_names: list[str], route_type: str) -> bool:
    origins = named_boardable_stop_ids(con, origin_names)
    destinations = named_boardable_stop_ids(con, destination_names)
    if not origins or not destinations:
        return False
    a = ",".join("?" for _ in origins)
    b = ",".join("?" for _ in destinations)
    return bool(con.execute(f"""SELECT 1 FROM stop_times board JOIN stop_times alight ON board.trip_id=alight.trip_id
        JOIN trips t ON t.id=board.trip_id JOIN routes r ON r.id=t.route_id
        WHERE board.stop_id IN ({a}) AND alight.stop_id IN ({b}) AND board.seq<alight.seq AND r.type=? LIMIT 1""",
        (*origins, *destinations, route_type)).fetchone())


def _direct_trip_count(con, origins, destinations) -> int:
    a = ",".join("?" for _ in origins)
    b = ",".join("?" for _ in destinations)
    return con.execute(f"""SELECT COUNT(*) FROM stop_times board JOIN stop_times alight ON board.trip_id=alight.trip_id
        WHERE board.stop_id IN ({a}) AND alight.stop_id IN ({b}) AND board.seq<alight.seq""", (*origins, *destinations)).fetchone()[0]


def active_service(con: sqlite3.Connection, service_id: str, day: date) -> bool:
    key = day.strftime("%Y%m%d")
    exception = con.execute("SELECT type FROM exceptions WHERE service_id=? AND day=?", (service_id, key)).fetchone()
    if exception:
        return exception[0] == 1
    row = con.execute("SELECT * FROM calendar WHERE service_id=? AND start<=? AND end>=?", (service_id, key, key)).fetchone()
    return bool(row and row[3 + day.weekday()])


def service_instant(day: date, seconds: int) -> datetime:
    """GTFS service-day clock: local noon minus 12 elapsed hours, then stop time."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=PARIS).astimezone(timezone.utc)
    return (noon - timedelta(hours=12) + timedelta(seconds=seconds)).astimezone(PARIS)


def direct_journeys(con: sqlite3.Connection, start: datetime, hours: int = 8) -> list[dict]:
    origins = station_child_ids(con, ORIGIN_NAME)
    dests = station_child_ids(con, DESTINATION_NAME)
    if not origins or not dests:
        return []
    a = ",".join("?" for _ in origins)
    b = ",".join("?" for _ in dests)
    rows = con.execute(f"""SELECT t.id trip_id,t.service_id,r.name route,r.type route_type,
        bs.name board_name,ds.name alight_name,board.departure,alight.arrival
        FROM trips t JOIN routes r ON r.id=t.route_id
        JOIN stop_times board ON board.trip_id=t.id JOIN stop_times alight ON alight.trip_id=t.id
        JOIN stops bs ON bs.id=board.stop_id JOIN stops ds ON ds.id=alight.stop_id
        WHERE board.stop_id IN ({a}) AND alight.stop_id IN ({b}) AND board.seq<alight.seq
        AND COALESCE(board.pickup,'0') NOT IN ('1','3') AND COALESCE(alight.dropoff,'0') NOT IN ('1','3')""", (*origins, *dests)).fetchall()
    result = []
    until = start + timedelta(hours=hours)
    for offset in (-1, 0, 1):
        day = (start.date() + timedelta(days=offset))
        for row in rows:
            if not active_service(con, row["service_id"], day):
                continue
            dep = service_instant(day, row["departure"])
            if start <= dep <= until:
                arr = service_instant(day, row["arrival"])
                if arr > dep:
                    result.append({"trip_id": row["trip_id"], "route": row["route"], "mode": "tram" if row["route_type"] == "0" else "other", "from_stop": row["board_name"], "to_stop": row["alight_name"], "departure": dep, "arrival": arr})
    result.sort(key=lambda x: (x["departure"], x["arrival"], x["trip_id"]))
    return result


def metadata(con: sqlite3.Connection) -> dict:
    return {r[0]: r[1] for r in con.execute("SELECT key,value FROM metadata")}
