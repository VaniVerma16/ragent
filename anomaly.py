import json, time, numpy as np
from redis import Redis
import redis
import statistics
from config import settings

# Require REDIS_URL (Upstash)
if not getattr(settings, "REDIS_URL", None):
    raise RuntimeError("REDIS_URL is required for anomaly detection and should point to Upstash TLS URL")

r = Redis.from_url(settings.REDIS_URL, decode_responses=True)
def push_metric(service: str, metric: str, value: float, ttl=3600):
    k=f"win:{metric}:{service}"; r.lpush(k, json.dumps({"ts":time.time(),"v":value})); r.ltrim(k,0,settings.WINDOW_N-1); r.expire(k,ttl)
def anomaly_score(service: str, metric: str, value: float):
    k=f"win:{metric}:{service}"; vals=r.lrange(k,0,settings.WINDOW_N-1)
    hist=[json.loads(x)["v"] for x in vals][::-1]
    if len(hist) < max(10, settings.WINDOW_N//2): return None
    mu=float(np.mean(hist)); sigma=float(np.std(hist)+1e-6); return (value-mu)/sigma
