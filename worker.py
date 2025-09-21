import json
import time
import re
import redis
import psycopg
import urllib.request
import urllib.error
from config import settings
from classifier import classify
from anomaly import anomaly_score
from embedder import create_embedding
from vector_store import index_incident

def process_event(event_id: int):
    """Process a single event from the queue"""
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM raw_events WHERE id = %s", (event_id,))
                row = cur.fetchone()
                if not row:
                    print(f"Event {event_id} not found in database")
                    return

                # row: [id, source, type, payload, metadata, created_at]
                raw_metadata = row[4]
                if raw_metadata is None:
                    metadata = {}
                elif isinstance(raw_metadata, str):
                    metadata = json.loads(raw_metadata)
                else:
                    metadata = raw_metadata  # already a dict (JSONB)

                payload_str = row[3] or ""  # <-- define it once, guard NULL

                event_data = {
                    "id": row[0],
                    "source": row[1],
                    "type": row[2],
                    "payload": payload_str,
                    "metadata": metadata,
                    "created_at": row[5],
                }

                print(f"Processing event {event_id}: {payload_str[:50]}...")

                # Classify
                classification = classify(payload_str)

                # Anomaly (if metric + "latency" present)
                anomaly = None
                if event_data["type"] == "metric" and "latency" in payload_str:
                    m = re.search(r"(\d+)\s*ms", payload_str)
                    if m:
                        latency_ms = int(m.group(1))
                        anomaly = anomaly_score(
                            service=event_data["source"],
                            metric="latency",
                            value=latency_ms,
                        )

                # Summary + embedding
                summary = f"{event_data['source']} {event_data['type']}: {payload_str[:100]}"
                embedding = create_embedding(summary)

                # Persist incident
                cur.execute(
                    """
                    INSERT INTO incidents (event_id, labels, summary_text, anomaly_score, confidence, evidence)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        event_id,
                        classification.get("labels", []),
                        summary,
                        anomaly,
                        classification.get("confidence", 0.0),
                        json.dumps(classification.get("evidence", [])),
                    ),
                )
                incident_id = cur.fetchone()[0]
                conn.commit()

                # Index into pgvector
                index_incident(
                    {
                        "id": incident_id,
                        "summary": summary,
                        "labels": classification.get("labels", []),
                        "service": event_data["source"],
                        "type": event_data.get("type", ""),
                        "timestamp": str(event_data["created_at"]),
                    },
                    embedding,
                )

                print(f"Created incident {incident_id} for event {event_id}")

                # 🚀 NEW: Publish notification to Redis for Agent
                return incident_id  # Return incident_id so we can notify about it

    except Exception as e:
        print(f"Error processing event {event_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def publish_incident_notification(redis_client, incident_id: int, event_data: dict):
    """Publish notification that a new incident is ready for Agent to handle"""
    try:
        notification = {
            "type": "new_incident",
            "incident_id": incident_id,
            "source": event_data.get("source"),
            "summary": f"{event_data.get('source')} {event_data.get('type')}: {event_data.get('payload', '')[:50]}...",
            "timestamp": time.time(),
            "status": "ready_for_agent"
        }
        
        # Publish to a notification channel/queue
        redis_client.lpush("agent_notifications", json.dumps(notification))
        print(f"📢 Published notification for incident {incident_id} to agent_notifications queue")
        
        # Optional: Also publish to a Redis channel for real-time notifications
        redis_client.publish("incident_alerts", json.dumps(notification))
        print(f"📡 Published real-time alert for incident {incident_id}")
        # If Upstash REST config is present, also LPUSH via the REST API so external agents
        # that only read Upstash can see new ids.
        if getattr(settings, 'UPSTASH_REDIS_REST_URL', '') and getattr(settings, 'UPSTASH_REDIS_REST_TOKEN', ''):
            try:
                up_url = settings.UPSTASH_REDIS_REST_URL.rstrip('/') + '/lpush/agent_notifications'
                data = json.dumps([json.dumps(notification)]).encode('utf-8')
                req = urllib.request.Request(up_url, data=data, method='POST')
                req.add_header('Authorization', 'Bearer ' + settings.UPSTASH_REDIS_REST_TOKEN)
                req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
                print(f"🔁 Also pushed notification to Upstash REST for incident {incident_id}")
            except urllib.error.URLError as e:
                print(f"Failed to push to Upstash REST: {e}")
        
    except Exception as e:
        print(f"Error publishing notification: {e}")


def process_event(event_id: int, redis_client=None):
    """Process a single event from the queue"""
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM raw_events WHERE id = %s", (event_id,))
                row = cur.fetchone()
                if not row:
                    print(f"Event {event_id} not found in database")
                    return None

                # row: [id, source, type, payload, metadata, created_at]
                raw_metadata = row[4]
                if raw_metadata is None:
                    metadata = {}
                elif isinstance(raw_metadata, str):
                    metadata = json.loads(raw_metadata)
                else:
                    metadata = raw_metadata  # already a dict (JSONB)

                payload_str = row[3] or ""  # <-- define it once, guard NULL

                event_data = {
                    "id": row[0],
                    "source": row[1],
                    "type": row[2],
                    "payload": payload_str,
                    "metadata": metadata,
                    "created_at": row[5],
                }

                print(f"Processing event {event_id}: {payload_str[:50]}...")

                # Classify
                classification = classify(payload_str)

                # Anomaly (if metric + "latency" present)
                anomaly = None
                if event_data["type"] == "metric" and "latency" in payload_str:
                    m = re.search(r"(\d+)\s*ms", payload_str)
                    if m:
                        latency_ms = int(m.group(1))
                        anomaly = anomaly_score(
                            service=event_data["source"],
                            metric="latency",
                            value=latency_ms,
                        )

                # Summary + embedding
                summary = f"{event_data['source']} {event_data['type']}: {payload_str[:100]}"
                embedding = create_embedding(summary)

                # Persist incident
                cur.execute(
                    """
                    INSERT INTO incidents (event_id, labels, summary_text, anomaly_score, confidence, evidence)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        event_id,
                        classification.get("labels", []),
                        summary,
                        anomaly,
                        classification.get("confidence", 0.0),
                        json.dumps(classification.get("evidence", [])),
                    ),
                )
                incident_id = cur.fetchone()[0]
                conn.commit()

                # Index into pgvector
                index_incident(
                    {
                        "id": incident_id,
                        "summary": summary,
                        "labels": classification.get("labels", []),
                        "service": event_data["source"],
                        "type": event_data.get("type", ""),
                        "timestamp": str(event_data["created_at"]),
                    },
                    embedding,
                )

                print(f"Created incident {incident_id} for event {event_id}")

                # 🚀 NEW: Publish notification to Redis for Agent
                if redis_client:
                    publish_incident_notification(redis_client, incident_id, event_data)

                return incident_id  # Return incident_id so we can notify about it

    except Exception as e:
        print(f"Error processing event {event_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

    except Exception as e:
        print(f"Error processing event {event_id}: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main worker loop"""
    print("Starting processor worker...")

    # Require REDIS_URL (Upstash). Fail fast with clear message if missing.
    if not getattr(settings, "REDIS_URL", None):
        raise RuntimeError("REDIS_URL is required and should point to an Upstash TLS URL (rediss://...)")
    r = redis.from_url(settings.REDIS_URL)

    queue = settings.QUEUE_NAME
    print(f"Listening for events on queue: {queue}")
    print(f"Will publish notifications to: agent_notifications queue")

    while True:
        try:
            result = r.brpop(queue, timeout=5)
            if result:
                _, data_bytes = result
                data_str = data_bytes.decode("utf-8")
                
                # Handle both old format (just event_id) and new format (JSON)
                try:
                    # Try to parse as JSON first (new format)
                    event_data = json.loads(data_str)
                    event_id = event_data.get("id")
                except (json.JSONDecodeError, TypeError):
                    # Fall back to old format (just event_id)
                    event_id = int(data_str)
                
                if event_id:
                    incident_id = process_event(event_id, redis_client=r)
                    if incident_id:
                        print(f"✅ Successfully processed event {event_id} → incident {incident_id}")
                    else:
                        print(f"❌ Failed to process event {event_id}")
                        
        except KeyboardInterrupt:
            print("Worker stopped")
            break
        except Exception as e:
            print(f"Worker error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
