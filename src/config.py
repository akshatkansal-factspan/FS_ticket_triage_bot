from pathlib import Path
import json
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

MOCK_DATA_PATH = ROOT / "documents" / "level2_mock_data.json"
KB_PATH = ROOT / "documents" / "knowledge_base.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def get_mock_data():
    return load_json(MOCK_DATA_PATH)


def get_knowledge_base():
    return load_json(KB_PATH)