This repository runs an API and a worker for event ingestion and processing.

Render deployment notes
- You can deploy the API and Worker as two separate Render services (recommended):
  - Web service: start command `uvicorn simplified_api:app --host 0.0.0.0 --port $PORT`
  - Worker service: start command `python -u worker.py`

- Or build a single Docker image and run both processes inside it using supervisord.
  - Build image (Render will build it from `Dockerfile` automatically)
  - To run both processes set the environment variable `RUN_MODE=supervised` (this runs supervisord)
  - To run only the API set `RUN_MODE=api` (default)

Required environment variables
- DATABASE_URL - Postgres connection string (supports SSL)
- REDIS_URL - Redis/Upstash URL (optional if using REDIS_HOST/REDIS_PORT)
- QUEUE_NAME - Redis list name for incoming events (default `events_queue`)
- HF_MODEL - Sentence transformer model id (default `sentence-transformers/all-MiniLM-L6-v2`)

Render tips
- Use two separate services for better scaling and observability.
- If using a single Docker image + supervisord, be aware both processes share the same container resources.
- Pre-downloads of ML models happen during image build; building on Render may take longer on first deploy.

Cloudflare Tunnel (static URL via your domain)
---------------------------------------------
If you control a domain in Cloudflare, you can create a named Cloudflare Tunnel and map a stable DNS record (for example `api.yourdomain.com`) to your local service.

Quick steps:
1. Install cloudflared (macOS): `brew install cloudflare/cloudflare/cloudflared`
2. Create a tunnel: `cloudflared tunnel create ragent-tunnel` — this prints a tunnel UUID and saves credentials to `~/.cloudflared`.
3. Create a DNS CNAME in Cloudflare: point `api.yourdomain.com` to the tunnel target (Cloudflare will show the exact `TUNNEL-UUID.cfargotunnel.com` target).
4. Create `~/.cloudflared/config.yml` based on `.cloudflared/config.yml.example` in this repo and set `hostname: api.yourdomain.com`.
5. Run the tunnel: `cloudflared tunnel run ragent-tunnel`.

There is a helper script in `scripts/run-cloudflared.sh` you can adapt. The result is a stable HTTPS endpoint `https://api.yourdomain.com` routed to your local `http://localhost:8000`.

If you don't control a domain, Cloudflare offers short-lived public URLs via `cloudflared tunnel --url http://localhost:8000` but those are ephemeral (not static).
