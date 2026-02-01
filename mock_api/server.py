from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "base_dataset"

app = FastAPI(title="Mock Bureau API")
app.mount("/images", StaticFiles(directory=BASE_DIR / "images"), name="images")


class BureauRequest(BaseModel):
    name: str = Field(..., min_length=1)
    pan: str = Field(..., min_length=1)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/bureau")
def bureau(payload: BureauRequest) -> dict:
    data_path = DATA_DIR / "bureau.json"
    try:
        records = json.loads(data_path.read_text())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="base dataset missing") from exc

    key_name = payload.name.strip().lower()
    key_pan = payload.pan.strip().lower()

    for item in records:
        if item.get("name", "").strip().lower() == key_name and item.get("pan", "").strip().lower() == key_pan:
            return item.get("response", {})

    raise HTTPException(status_code=404, detail="no matching bureau record")
