-- Run this in Supabase SQL Editor (https://supabase.com/dashboard/project/ejkngjxuksrjazgutvvz/sql/new)

-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- raw_events table
CREATE TABLE IF NOT EXISTS raw_events (
  id SERIAL PRIMARY KEY,
  source TEXT,
  type TEXT,
  payload TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- incidents table  
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

-- memory_item table (vector storage)
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

-- Indexes for performance
CREATE INDEX IF NOT EXISTS memory_item_embedding_ivf
ON memory_item USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS memory_item_service_idx ON memory_item(service);

-- Row Level Security (Supabase best practice)
ALTER TABLE raw_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY; 
ALTER TABLE memory_item ENABLE ROW LEVEL SECURITY;

-- Policies for service role access
CREATE POLICY "Enable all access for service role" ON raw_events FOR ALL USING (true);
CREATE POLICY "Enable all access for service role" ON incidents FOR ALL USING (true);
CREATE POLICY "Enable all access for service role" ON memory_item FOR ALL USING (true);
