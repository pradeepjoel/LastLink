"""Run: python -m app.import_gtfs [optional local urban and regional GTFS zips]."""
import argparse
from pathlib import Path
from .config import DB_PATH, REGIONAL_DB_PATH, REGIONAL_SOURCE_URL
from .gtfs import connect, download, import_feed, metadata


def needs_import(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        with connect(path) as con:
            return metadata(con).get("schema_version") != "2"
    except Exception:
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("urban_archive", nargs="?", type=Path, help="Local official Lignes d'Azur ZIP")
    parser.add_argument("regional_archive", nargs="?", type=Path, help="Local official ZOU Express ZIP")
    parser.add_argument("--ensure", action="store_true", help="Import only missing or old-schema databases")
    args = parser.parse_args()
    sources = [
        ("urban", DB_PATH, args.urban_archive, None),
        ("regional", REGIONAL_DB_PATH, args.regional_archive, REGIONAL_SOURCE_URL),
    ]
    for kind, path, archive, url in sources:
        if args.ensure and not needs_import(path):
            print(f"Keeping existing {kind} feed at {path}")
            continue
        data = archive.read_bytes() if archive else download(url) if url else download()
        kwargs = {"kind": kind}
        if url:
            kwargs["source_url"] = url
        result = import_feed(data, path, **kwargs)
        print(f"Imported {kind} scheduled GTFS to {path}")
        print(f"SHA256 {result['sha256']}; feed dates {result['feed_start']}–{result['feed_end']}")


if __name__ == "__main__":
    main()
