from pathlib import Path
import os

SOURCE_URL = "https://chouette.enroute.mobi/api/v1/datas/OpendataRLA/gtfs.zip"
SOURCE_PAGE = "https://transport.data.gouv.fr/datasets/donnees-statiques-et-dynamiques-du-reseau-de-transport-lignes-dazur"
REGIONAL_SOURCE_URL = "https://www.datasud.fr/fr/dataset/datasets/3743/resource/5153/download/"
REGIONAL_SOURCE_PAGE = "https://transport.data.gouv.fr/datasets/lignes-des-reseaux-transport-zou-provence-alpes-cote-d-azur-express-3-3"
DB_PATH = Path(os.getenv("LASTLINK_DB", Path(__file__).resolve().parents[2] / "data" / "lastlink.sqlite"))
REGIONAL_DB_PATH = Path(os.getenv("LASTLINK_REGIONAL_DB", Path(__file__).resolve().parents[2] / "data" / "zou-express.sqlite"))
AIRPORT = "NCE"
ORIGIN_NAME = "Aéroport Terminal 2"
DESTINATION_NAME = "Jean Médecin"
