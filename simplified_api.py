# simplified_api.py - Just event ingestion, no search
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
import psycopg
import redis
import json
from pydantic import BaseModel
from config import settings

app = FastAPI(title="Event Processor API")

# Data model for incoming events
class EventData(BaseModel):
    source: str
    type: str  # "log" or "metric"
    payload: str
    metadata: Dict[str, Any] = {}

# Redis connection for queuing - require REDIS_URL (Upstash)
if not getattr(settings, "REDIS_URL", None):
    raise RuntimeError("REDIS_URL is required and should point to an Upstash TLS URL (rediss://...)")
redis_client = redis.Redis.from_url(settings.REDIS_URL)

@app.post("/events")
def receive_event(event: EventData):
    """Receive events and queue them for processing - that's it!"""
    try:
        # 1. Store in raw_events table
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO raw_events (source, type, payload, metadata)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (event.source, event.type, event.payload, json.dumps(event.metadata)))
                event_id = cur.fetchone()[0]
                conn.commit()
        
        # 2. Queue for processing
        queue_data = {
            "id": event_id,
            "source": event.source,
            "type": event.type,
            "payload": event.payload,
            "metadata": event.metadata
        }
        
        redis_client.lpush(settings.QUEUE_NAME, json.dumps(queue_data))
        
        return {
            "status": "success",
            "event_id": event_id,
            "message": "Event queued for processing"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process event: {str(e)}")

@app.get("/health")
def health_check():
    """Simple health check"""
    return {"status": "healthy", "service": "event-processor"}

@app.get("/agent/notifications")
def get_agent_notifications(limit: int = 10):
    """Get notifications for the Agent about ready incidents"""
    try:
        notifications = []
        
        for _ in range(limit):
            result = redis_client.rpop("agent_notifications")
            if not result:
                break
            
            notification_data = json.loads(result.decode('utf-8'))
            notifications.append(notification_data)
        
        return {
            "status": "success",
            "count": len(notifications),
            "notifications": notifications
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get notifications: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
