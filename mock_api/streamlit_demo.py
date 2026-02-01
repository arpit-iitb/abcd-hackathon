from __future__ import annotations

import json
from typing import Any, Dict, List

import requests
import streamlit as st

DEFAULT_API_BASE = "http://localhost:8000"
BUREAU_DATASET_PATH = "base_dataset/bureau.json"
BANK_DATASET_PATH = "base_dataset/bank_statement.json"
LEAD_DATASET_PATH = "base_dataset/lead_sourcing.json"

st.set_page_config(page_title="Mock Bureau Demo", page_icon="✅")
st.title("Mock Credit API Demo")
st.caption("Tip: run the API with `uvicorn server:app --reload --port 8000` inside `mock_api/`.")

sample_records: List[Dict[str, Any]] = []
bank_records: List[Dict[str, Any]] = []
lead_records: List[Dict[str, Any]] = []
try:
    with open(BUREAU_DATASET_PATH, "r", encoding="utf-8") as handle:
        sample_records = json.load(handle)
    with open(BANK_DATASET_PATH, "r", encoding="utf-8") as handle:
        bank_records = json.load(handle)
    with open(LEAD_DATASET_PATH, "r", encoding="utf-8") as handle:
        lead_records = json.load(handle)
except FileNotFoundError:
    pass
except json.JSONDecodeError:
    st.warning("Local base dataset is invalid JSON. Samples are hidden.")

if "name" not in st.session_state:
    st.session_state.name = ""
if "pan" not in st.session_state:
    st.session_state.pan = ""
if "account_number" not in st.session_state:
    st.session_state.account_number = ""
if "lead_id" not in st.session_state:
    st.session_state.lead_id = ""

api_base = st.text_input("API base URL", value=DEFAULT_API_BASE)
doc_type = st.selectbox("Document type", options=["Bureau", "Bank Statement", "Lead Sourcing"])

if doc_type == "Bureau" and sample_records:
    options = [f"{r.get('name', '')} — {r.get('pan', '')}" for r in sample_records]
    selected = st.selectbox("Sample records", options=options)
    if st.button("Use selected sample"):
        idx = options.index(selected)
        st.session_state.name = sample_records[idx].get("name", "")
        st.session_state.pan = sample_records[idx].get("pan", "")
elif doc_type == "Bank Statement" and bank_records:
    options = [r.get("account_number", "") for r in bank_records]
    selected = st.selectbox("Sample account numbers", options=options)
    if st.button("Use selected sample"):
        idx = options.index(selected)
        st.session_state.account_number = bank_records[idx].get("account_number", "")
elif doc_type == "Lead Sourcing" and lead_records:
    options = [r.get("lead_id", "") for r in lead_records]
    selected = st.selectbox("Sample lead IDs", options=options)
    if st.button("Use selected sample"):
        idx = options.index(selected)
        st.session_state.lead_id = lead_records[idx].get("lead_id", "")

if doc_type == "Bureau":
    with st.form("bureau_form"):
        name = st.text_input("Name", placeholder="Jane Doe", key="name")
        pan = st.text_input("PAN", placeholder="ABCDE1234F", key="pan")
        submitted = st.form_submit_button("Fetch Bureau Report")
elif doc_type == "Bank Statement":
    with st.form("bank_form"):
        account_number = st.text_input("Account Number", placeholder="1234567890", key="account_number")
        submitted = st.form_submit_button("Fetch Bank Statement")
else:
    with st.form("lead_form"):
        lead_id = st.text_input("Lead ID", placeholder="L-1001", key="lead_id")
        submitted = st.form_submit_button("Fetch Lead Sourcing")

if submitted:
    if doc_type == "Bureau" and (not name.strip() or not pan.strip()):
        st.error("Please enter both name and PAN.")
    elif doc_type == "Bank Statement" and not account_number.strip():
        st.error("Please enter an account number.")
    elif doc_type == "Lead Sourcing" and not lead_id.strip():
        st.error("Please enter a lead ID.")
    else:
        try:
            if doc_type == "Bureau":
                endpoint = f"{api_base.rstrip('/')}/bureau"
                payload = {"name": name.strip(), "pan": pan.strip()}
            elif doc_type == "Bank Statement":
                endpoint = f"{api_base.rstrip('/')}/bank-statement"
                payload = {"account_number": account_number.strip()}
            else:
                endpoint = f"{api_base.rstrip('/')}/lead-sourcing"
                payload = {"lead_id": lead_id.strip()}
            resp = requests.post(endpoint, json=payload, timeout=10)
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
