import hashlib, json
from typing import List
from redis import Redis
import os
from functools import lru_cache
from sentence_transformers import SentenceTransformer
import numpy as np
from config import settings

# Require REDIS_URL (Upstash)
if not getattr(settings, "REDIS_URL", None):
    raise RuntimeError("REDIS_URL is required for embedding cache and should point to Upstash TLS URL")

r = Redis.from_url(settings.REDIS_URL, decode_responses=False)
_model = None
def _get_model():
    global _model
    if _model is None: _model = SentenceTransformer(settings.HF_MODEL, device="cpu")
    return _model
def create_embedding(text: str) -> List[float]:
    text=text.strip(); key="emb:%s:%s"%(settings.HF_MODEL, hashlib.sha256(text.encode()).hexdigest())
    c=r.get(key); 
    if c: return json.loads(c)
    vec = _get_model().encode([text], normalize_embeddings=True)[0].tolist()
    r.setex(key, 86400, json.dumps(vec)); return vec
