import logging
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .config import AIRPORT, DB_PATH, REGIONAL_DB_PATH, SOURCE_PAGE, REGIONAL_SOURCE_PAGE
from .engine import assess
from .gtfs import connect, metadata

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("lastlink")

app = FastAPI(title="LastLink API", version="0.2.0", description="Simulated flight arrivals against scheduled GTFS multimodal journeys")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class JourneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    airport: str = Field(pattern="^NCE$")
    destination: str = Field(pattern="^(nice-centre|antibes|cannes)$")
    scheduled_arrival: datetime
    delay_minutes: int = Field(default=0, ge=0, le=360)
    checked_baggage: bool = False
    exit_minutes: int = Field(default=25, ge=5, le=180)
    preferred_modes: list[str] = Field(default_factory=lambda: ["tram", "train", "bus"])
    exit_uncertainty_minutes: int = Field(default=10, ge=0, le=90)
    stop_access_minutes: int = Field(default=8, ge=0, le=60)
    boarding_buffer_minutes: int = Field(default=5, ge=0, le=30)
    transfer_buffer_minutes: int = Field(default=5, ge=0, le=60)


def _databases():
    if not Path(DB_PATH).exists() or not Path(REGIONAL_DB_PATH).exists():
        raise HTTPException(status_code=503, detail="Scheduled transport data is not installed. Run the GTFS import command.")
    try:
        stack = ExitStack()
        sources = {"urban": stack.enter_context(closing(connect(DB_PATH))),
                   "regional": stack.enter_context(closing(connect(REGIONAL_DB_PATH)))}
        return stack, sources
    except Exception:
        log.exception("Could not open GTFS database")
        raise HTTPException(status_code=503, detail="Scheduled transport data is unavailable")


@app.get("/health")
def health():
    return {"status": "ok", "data_loaded": Path(DB_PATH).exists() and Path(REGIONAL_DB_PATH).exists()}


@app.get("/api/data-sources/status")
def data_status():
    stack, sources = _databases()
    with stack:
        return {"licence": "Licence Ouverte 2.0", "realtime": False,
                "sources": [{"id": "urban", "dataset_page": SOURCE_PAGE, **metadata(sources["urban"])},
                            {"id": "regional", "dataset_page": REGIONAL_SOURCE_PAGE, **metadata(sources["regional"])}]}


@app.get("/api/destinations")
def destinations():
    stack, sources = _databases()
    with stack:
        loaded = bool(metadata(sources["urban"])) and bool(metadata(sources["regional"]))
    return {"airport": AIRPORT, "destinations": [
        {"id": "nice-centre", "name": "Nice city centre · Jean Médecin", "arrival_stop": "Jean Médecin", "available": loaded},
        {"id": "antibes", "name": "Antibes · railway station", "arrival_stop": "Antibes", "available": loaded},
        {"id": "cannes", "name": "Cannes · railway station", "arrival_stop": "Cannes", "available": loaded}]}


@app.post("/api/journeys/assess")
def assess_journey(request: JourneyRequest):
    if not request.preferred_modes or not set(request.preferred_modes).issubset({"tram", "train", "bus"}):
        raise HTTPException(status_code=422, detail="Preferred modes must contain tram, train or bus")
    try:
        stack, sources = _databases()
        with stack:
            return assess(sources, request.scheduled_arrival, request.destination,
                          request.delay_minutes, request.exit_minutes, request.checked_baggage,
                          request.exit_uncertainty_minutes, request.stop_access_minutes,
                          request.boarding_buffer_minutes, request.transfer_buffer_minutes,
                          request.preferred_modes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        log.exception("Journey assessment failed")
        raise HTTPException(status_code=503, detail="Journey assessment is temporarily unavailable")
