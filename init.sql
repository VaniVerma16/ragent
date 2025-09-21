-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- raw_events (your worker reads from this)
CREATE TABLE IF NOT EXISTS raw_events (
  id SERIAL PRIMARY KEY,
  source TEXT,
  type TEXT,             -- e.g., 'metric' or 'log'
  payload TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- incidents (your worker writes here)
CREATE TABLE IF NOT EXISTS incidents (
  id SERIAL PRIMARY KEY,
  event_id INTEGER,
  labels TEXT[],
  summary_text TEXT,
  anomaly_score FLOAT,
  confidence FLOAT,
  evidence JSONB,
  status VARCHAR(50) DEFAULT 'open',
  created_at TIMESTAMP DEFAULT NOW()
);

-- vector table your vector_store.py uses
CREATE TABLE IF NOT EXISTS memory_item (
  id            TEXT PRIMARY KEY,
  summary       TEXT,
  labels        TEXT[],
  service       TEXT,
  incident_type TEXT,
  model         TEXT NOT NULL DEFAULT 'sentence-transformers/all-MiniLM-L6-v2',
  dim           INT  NOT NULL DEFAULT 384,
  embedding     VECTOR(384)
);

-- ANN index (cosine); tune lists later
CREATE INDEX IF NOT EXISTS memory_item_embedding_ivf
ON memory_item USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS memory_item_service_idx ON memory_item(service);
