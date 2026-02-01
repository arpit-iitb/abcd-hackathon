.PHONY: api ui up uo dev

api:
	uvicorn server:app --reload --port 8000

ui:
	streamlit run streamlit_demo.py

up: api

uo: up

dev:
	uvicorn server:app --reload --port 8000 & \
	streamlit run streamlit_demo.py; \
	wait
