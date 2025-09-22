This repository runs an API and a worker for event ingestion and processing.

Render deployment notes
- You can deploy the API and Worker as two separate Render services (recommended):
  - Web service: start command `uvicorn simplified_api:app --host 0.0.0.0 --port $PORT`
  - Worker service: start command `python -u worker.py`

- Or build a single Docker image and run both processes inside it using supervisord.
  - Build image (Render will build it from `Dockerfile` automatically)
  - To run both processes set the environment variable `RUN_MODE=supervised` (this runs supervisord)
  - To run only the API set `RUN_MODE=api` (default)


