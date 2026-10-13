"""Deterministic synthetic tests. Real-source checks live in test_real_feed.py."""
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.engine import NO_CONNECTION, assess, local_arrival
from app.gtfs import connect, direct_journeys, import_feed, service_instant
from app.main import app
from app.network import Ride, Walk, find_itineraries

PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc


def feed(kind="urban", *, missing_coordinates=False, cancel=False):
    if kind == "urban":
        stops = [
            ("a","Aéroport Terminal 2","",1,43.660621,7.205213),
            ("a1","Aéroport Terminal 2","a",0,43.660621,7.205213),
            ("g","Grand Arénas","",1,43.669233,7.210433),
            ("g1","Grand Arénas","g",0,None if missing_coordinates else 43.669233,7.210433),
            ("j","Jean Médecin","",1,43.701,7.267),
            ("j1","Jean Médecin","j",0,43.701,7.267),
        ]
        routes = [("r","L2",0)]
        trips = [("u1","r"),("u2","r"),("u3","r")]
        calls = {
            "u1":[("a1","21:30:00"),("g1","21:38:00"),("j1","22:00:00")],
            "u2":[("a1","22:00:00"),("g1","22:08:00"),("j1","22:30:00")],
            "u3":[("a1","22:20:00"),("g1","22:28:00"),("j1","22:50:00")],
        }
    else:
        stops = [
            ("ba","Aéroport Terminal 2","",0,43.66101,7.20498),
            ("s","Nice-Saint-Augustin","",1,43.67072,7.2162),
            ("s1","Nice Saint-Augustin","s",0,43.67072,7.2162),
            ("ab","Antibes","",1,43.5859,7.1199),
            ("ab1","Antibes","ab",0,43.5859,7.1199),
            ("ca","Cannes","",1,43.5539,7.0197),
            ("ca1","Cannes","ca",0,43.5539,7.0197),
            ("cb","Gare SNCF Cannes","",0,43.5539,7.0197),
        ]
        routes = [("rail","C13",2),("bus","81",3)]
        trips = [("r1","rail"),("r2","rail"),("b1","bus")]
        calls = {
            "r1":[("s1","22:00:00"),("ab1","22:25:00"),("ca1","22:45:00")],
            "r2":[("s1","22:50:00"),("ab1","23:15:00"),("ca1","23:35:00")],
            "b1":[("ba","21:55:00"),("cb","22:45:00")],
        }
    files = {
        "stops.txt":"stop_id,stop_name,parent_station,location_type,stop_lat,stop_lon\n"+"".join(
            f"{sid},{name},{parent},{typ},{'' if lat is None else lat},{lon}\n" for sid,name,parent,typ,lat,lon in stops),
        "routes.txt":"route_id,route_short_name,route_type\n"+"".join(f"{rid},{name},{typ}\n" for rid,name,typ in routes),
        "trips.txt":"trip_id,route_id,service_id\n"+"".join(f"{tid},{rid},service\n" for tid,rid in trips),
        "stop_times.txt":"trip_id,stop_id,stop_sequence,arrival_time,departure_time\n"+"".join(
            f"{tid},{sid},{i},{time},{time}\n" for tid,rows in calls.items() for i,(sid,time) in enumerate(rows,1)),
        "calendar.txt":"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nservice,1,1,1,1,1,1,1,20260101,20271231\n",
        "calendar_dates.txt":"service_id,date,exception_type\n"+("service,20261013,2\n" if cancel else ""),
        "feed_info.txt":"feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\nTest,https://example.org,en,20260101,20271231\n",
    }
    out=io.BytesIO()
    with zipfile.ZipFile(out,"w") as z:
        for name,text in files.items():
            info=zipfile.ZipInfo(name,date_time=(2026,10,13,12,0,0))
            z.writestr(info,text)
    return out.getvalue()


@pytest.fixture
def sources(tmp_path):
    paths={"urban":tmp_path/"urban.sqlite","regional":tmp_path/"regional.sqlite"}
    for kind,path in paths.items():
        import_feed(feed(kind),path,datetime.now(UTC),kind=kind)
        with connect(path) as con:
            con.execute("UPDATE metadata SET value=? WHERE key='archive_content_date'",(datetime.now(UTC).date().isoformat(),))
            con.commit()
    opened={kind:connect(path) for kind,path in paths.items()}
    yield opened
    for con in opened.values():con.close()


def at(text="2026-10-13T20:50:00"):
    return datetime.fromisoformat(text).replace(tzinfo=PARIS)


def test_direct_tram_and_exit_uncertainty(sources):
    result=assess(sources,at(),"nice-centre",0,25,False)
    assert result["original_itinerary"]["legs"][-1]["to_stop"]=="Jean Médecin"
    assert result["status"]=="AT_RISK"
    sure=assess(sources,at(),"nice-centre",0,25,False,exit_uncertainty_minutes=0)
    assert sure["status"]=="FEASIBLE"


def test_walking_and_boarding_time_change_feasibility(sources):
    base=assess(sources,at(),"nice-centre",0,25,False,exit_uncertainty_minutes=0)
    assert base["original_itinerary"]["departure"].hour==21
    slower=assess(sources,at(),"nice-centre",0,25,False,0,12,5)
    assert slower["original_itinerary"]["departure"].hour==22


def test_delay_misses_original_and_finds_complete_alternative(sources):
    result=assess(sources,at(),"antibes",30,25,False)
    assert result["status"]=="NOT_FEASIBLE"
    rec=result["recommended_itinerary"]
    assert rec and rec["transfers"]==1
    assert [x["mode"] for x in rec["legs"] if x["kind"]=="ride"]==["tram","train"]
    assert rec["legs"][-1]["to_stop"]=="Antibes"
    assert any(x["kind"]=="walk" and "Saint-Augustin" in x["to_stop"] for x in rec["legs"])


def test_cannes_direct_bus_or_rail_and_last_complete_journey(sources):
    result=assess(sources,at(),"cannes",0,25,False)
    assert result["recommended_itinerary"]["legs"][-1]["to_stop"] in ("Cannes","Gare SNCF Cannes")
    assert result["last_feasible_itinerary"]["legs"][-1]["to_stop"] in ("Cannes","Gare SNCF Cannes")
    assert any(any(leg.get("mode")=="bus" for leg in x["legs"]) for x in [result["recommended_itinerary"],*result["itinerary_alternatives"]])


def test_missing_coordinates_disables_cross_feed_walk(tmp_path):
    u=tmp_path/"u.sqlite";r=tmp_path/"r.sqlite"
    import_feed(feed("urban",missing_coordinates=True),u)
    import_feed(feed("regional"),r,kind="regional")
    with connect(u) as uc,connect(r) as rc:
        result=assess({"urban":uc,"regional":rc},at(),"antibes",0,25,False)
    assert result["recommended_itinerary"] is None
    assert any("coordinates" in text for text in result["warnings"])


def test_cancelled_service_and_no_journey(tmp_path):
    u=tmp_path/"u.sqlite";r=tmp_path/"r.sqlite"
    import_feed(feed("urban",cancel=True),u)
    import_feed(feed("regional",cancel=True),r,kind="regional")
    with connect(u) as uc,connect(r) as rc:
        result=assess({"urban":uc,"regional":rc},at(),"antibes",0,25,False)
    assert result["recommended_itinerary"] is None
    assert NO_CONNECTION in result["warnings"]


def test_last_connection_missed(sources):
    result=assess(sources,at("2026-10-13T23:00:00"),"antibes",0,25,False)
    assert result["status"]=="NOT_FEASIBLE"
    assert result["last_feasible_itinerary"] is None


def test_transfer_buffer_and_multiple_transfers():
    t=lambda h,m:datetime(2026,10,13,h,m,tzinfo=PARIS).astimezone(UTC)
    rides={"airport":[Ride("urban","a","A","tram","airport","x","Airport","X","a","x",t(20,0),t(20,10))],
           "x":[Ride("urban","b","B","tram","x","y","X","Y","x","y",t(20,13),t(20,23))],
           "y":[Ride("urban","c","C","tram","y","dest","Y","Destination","y","d",t(20,29),t(20,40))]}
    start=t(19,50)
    good=find_itineraries(rides,[],"dest",start,0,0,2,t(21,0))
    assert good and len(good[0].rides)==3
    assert find_itineraries(rides,[],"dest",start,0,0,4,t(21,0))==[]


def test_gtfs_transfer_prohibition():
    t=lambda h,m:datetime(2026,10,13,h,m,tzinfo=PARIS).astimezone(UTC)
    rides={"airport":[Ride("urban","a","A","tram","airport","x","Airport","X","a","x",t(20,0),t(20,10))],
           "x":[Ride("urban","b","B","tram","x","dest","X","Destination","y","d",t(20,20),t(20,40))]}
    assert find_itineraries(rides,[],"dest",t(19,50),0,0,2,t(21,0),transfer_rules={("urban","x","y"):(3,0)})==[]


def test_after_midnight_and_dst(sources):
    assert service_instant(date(2026,10,25),26*3600).utcoffset()==timedelta(hours=1)
    with pytest.raises(ValueError):local_arrival(datetime(2026,10,25,2,30))
    with pytest.raises(ValueError):local_arrival(datetime(2026,3,29,2,30))
    assert service_instant(date(2026,10,13),24*3600+600).date()==date(2026,10,14)


def test_after_midnight_trip_uses_previous_service_day_validity(sources):
    urban=sources["urban"]
    urban.execute("UPDATE stop_times SET arrival=arrival+7200, departure=departure+7200 WHERE trip_id='u3'")
    urban.execute("UPDATE calendar SET end='20261013'")
    urban.execute("UPDATE metadata SET value='20261013' WHERE key='feed_end'")
    result=assess(sources,at("2026-10-14T00:00:00"),"nice-centre",0,5,False,
                  exit_uncertainty_minutes=0)
    assert result["recommended_itinerary"]["status"]=="FEASIBLE"
    assert result["recommended_itinerary"]["legs"][-1]["service_day"]=="2026-10-13"


def test_invalid_feed_keeps_existing_database(tmp_path):
    path=tmp_path/"safe.sqlite"
    import_feed(feed(),path)
    with pytest.raises(ValueError):import_feed(b"bad zip",path)
    with connect(path) as con:assert con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]==3


def test_stale_feed_returns_unknown(sources):
    sources["urban"].execute("UPDATE metadata SET value=? WHERE key='archive_content_date'",("2026-01-01",))
    result=assess(sources,at(),"nice-centre",0,25,False)
    assert result["status"]=="UNKNOWN"


def test_checked_baggage_changes_first_boarding(sources):
    no_bag=assess(sources,at(),"nice-centre",0,25,False,exit_uncertainty_minutes=0)
    bag=assess(sources,at(),"nice-centre",0,25,True,exit_uncertainty_minutes=0)
    assert bag["original_itinerary"]["departure"]>no_bag["original_itinerary"]["departure"]


def test_api_missing_data_fails_without_results(monkeypatch,tmp_path):
    monkeypatch.setattr("app.main.DB_PATH",tmp_path/"missing.sqlite")
    monkeypatch.setattr("app.main.REGIONAL_DB_PATH",tmp_path/"missing2.sqlite")
    response=TestClient(app).post("/api/journeys/assess",json={"airport":"NCE","destination":"antibes","scheduled_arrival":"2026-10-13T20:50:00"})
    assert response.status_code==503 and "trip_id" not in response.text
