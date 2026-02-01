from __future__ import annotations

import json
from typing import Any, Dict, List

import requests
import streamlit as st

DEFAULT_API_URL = "http://localhost:8000/bureau"
DATASET_PATH = "base_dataset/bureau.json"

st.set_page_config(page_title="Mock Bureau Demo", page_icon="✅")
st.title("Mock Bureau API Demo")
st.caption("Tip: run the API with `uvicorn server:app --reload --port 8000` inside `mock_api/`.")

sample_records: List[Dict[str, Any]] = []
try:
    with open(DATASET_PATH, "r", encoding="utf-8") as handle:
        sample_records = json.load(handle)
except FileNotFoundError:
    pass
except json.JSONDecodeError:
    st.warning("Local base dataset is invalid JSON. Samples are hidden.")

if "name" not in st.session_state:
    st.session_state.name = ""
if "pan" not in st.session_state:
    st.session_state.pan = ""

api_url = st.text_input("API URL", value=DEFAULT_API_URL)

if sample_records:
    options = [f"{r.get('name', '')} — {r.get('pan', '')}" for r in sample_records]
    selected = st.selectbox("Sample records", options=options)
    if st.button("Use selected sample"):
        idx = options.index(selected)
        st.session_state.name = sample_records[idx].get("name", "")
        st.session_state.pan = sample_records[idx].get("pan", "")

with st.form("bureau_form"):
    name = st.text_input("Name", placeholder="Jane Doe", key="name")
    pan = st.text_input("PAN", placeholder="ABCDE1234F", key="pan")
    submitted = st.form_submit_button("Fetch Bureau Report")

if submitted:
    if not name.strip() or not pan.strip():
        st.error("Please enter both name and PAN.")
    else:
        try:
            resp = requests.post(api_url, json={"name": name.strip(), "pan": pan.strip()}, timeout=10)
        except requests.RequestException as exc:
            st.error("Failed to reach the mock API. Make sure the server is running on port 8000.")
            st.code(str(exc))
        else:
            if resp.status_code == 404:
                st.warning("No matching record found. Try a sample record from the dropdown.")
                try:
                    st.json(resp.json())
                except json.JSONDecodeError:
                    st.code(resp.text)
            else:
                try:
                    resp.raise_for_status()
                except requests.HTTPError as exc:
                    st.error("API returned an error.")
                    st.code(str(exc))
                    st.code(resp.text)
                else:
                    try:
                        payload: Any = resp.json()
                    except json.JSONDecodeError:
                        st.error("API returned invalid JSON.")
                        st.code(resp.text)
                    else:
                        st.success("Bureau report received.")
                        st.json(payload)
