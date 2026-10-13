"""Optional source validation; requires two downloaded official archives."""
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import REGIONAL_SOURCE_URL
from app.engine import assess
from app.gtfs import connect, import_feed


@pytest.mark.skipif(not (os.getenv("LASTLINK_REAL_GTFS") and os.getenv("LASTLINK_REGIONAL_GTFS")),
                    reason="Both official archives are required")
def test_official_feeds_reach_all_three_destinations(tmp_path):
    urban=tmp_path/"urban.sqlite"
    regional=tmp_path/"regional.sqlite"
    import_feed(Path(os.environ["LASTLINK_REAL_GTFS"]).read_bytes(),urban,datetime.now(timezone.utc))
    import_feed(Path(os.environ["LASTLINK_REGIONAL_GTFS"]).read_bytes(),regional,
                datetime.now(timezone.utc),source_url=REGIONAL_SOURCE_URL,kind="regional")
    with connect(urban) as uc,connect(regional) as rc:
        for destination in ("nice-centre","antibes","cannes"):
            result=assess({"urban":uc,"regional":rc},
                          datetime(2026,10,13,20,50,tzinfo=ZoneInfo("Europe/Paris")),
                          destination,30,25,False)
            journey=result["recommended_itinerary"]
            assert journey is not None
            assert journey["legs"][-1]["to_stop"] in {
                "nice-centre":{"Jean Médecin"},"antibes":{"Antibes"},
                "cannes":{"Cannes","Gare SNCF Cannes"}}[destination]
            assert journey["status"] in {"FEASIBLE","AT_RISK"}
        # Daytime frequency produces many possible transfers; route search must
        # still return a complete result and preserve the last first departure.
        midday=assess({"urban":uc,"regional":rc},
                      datetime(2026,10,13,12,37,tzinfo=ZoneInfo("Europe/Paris")),
                      "cannes",30,25,False)
        assert midday["recommended_itinerary"]["legs"][-1]["to_stop"] in {"Cannes","Gare SNCF Cannes"}
        assert midday["last_feasible_itinerary"]["legs"][-1]["to_stop"] in {"Cannes","Gare SNCF Cannes"}
