"""
ARCHIVED: search_api.py contents removed by automated cleanup.

This file provided an alternate semantic search API and a small web UI.
If you need it back, restore from git history or the upstream branch.
"""

if not getattr(settings, "REDIS_URL", None):
    raise RuntimeError("REDIS_URL is required and should point to Upstash TLS URL")
if not getattr(settings, "DATABASE_URL", None):
    raise RuntimeError("DATABASE_URL is required and should point to Supabase/Postgres")

# Redis connection for sending events to worker
redis_client = redis.Redis.from_url(settings.REDIS_URL)

@app.get("/search")
def search(
    q: str = Query(..., description="Natural language query"),
    service: Optional[str] = Query(None, description="Filter by service"),
    k: int = Query(5, ge=1, le=50, description="Top-K results"),
) -> Dict[str, Any]:
    try:
        print(f"DEBUG: Search query: {q}")
        qvec = create_embedding(q)
        print(f"DEBUG: Created embedding, length: {len(qvec)}")
        
        filters = {"service": service} if service else None
        print(f"DEBUG: Filters: {filters}")
        
        hits = search_similar_incidents(qvec, filters=filters, k=k)
        print(f"DEBUG: Found {len(hits)} hits")
        
        return {
            "query": q,
            "count": len(hits),
            "results": [
                {
                    "id": h["id"],
                    "service": h["service"],
                    "type": h["type"],
                    "distance": float(h["distance"]),
                    "summary": h["summary"],
                }
                for h in hits
            ],
        }
    except Exception as e:
        print(f"ERROR in search: {e}")
        import traceback
        traceback.print_exc()
        # Return a proper error response instead of crashing
        return {
            "query": q,
            "count": 0,
            "results": [],
            "error": str(e)
        }

@app.post("/events")
def receive_event(event: EventData):
    """Receive events from external systems and queue them for processing"""
    try:
        # Store in raw_events table
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO raw_events (source, type, payload, metadata)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (event.source, event.type, event.payload, json.dumps(event.metadata)))
                event_id = cur.fetchone()[0]
                conn.commit()
        
        # Send to Redis queue for worker processing
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
        print(f"ERROR receiving event: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to process event: {str(e)}")

@app.get("/agent/notifications")
def get_agent_notifications(limit: int = 10):
    """Get pending notifications for the Agent"""
    try:
        notifications = []
        
        # Get up to 'limit' notifications from the queue
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

@app.get("/agent/notifications/stream")
def stream_agent_notifications():
    """Stream real-time notifications for the Agent (Server-Sent Events)"""
    try:
        def event_stream():
            pubsub = redis_client.pubsub()
            pubsub.subscribe("incident_alerts")
            
            yield f"data: {json.dumps({'type': 'connected', 'message': 'Listening for incidents...'})}\n\n"
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    yield f"data: {message['data'].decode('utf-8')}\n\n"
        
        return StreamingResponse(event_stream(), media_type="text/plain")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stream notifications: {str(e)}")

@app.get("/", response_class=HTMLResponse)
def home() -> str:
    # very small single-file UI (no templates needed)
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Semantic Search</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu; margin:24px; line-height:1.4}
    .row{display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px}
    input,select,button{padding:8px 10px; font-size:14px}
    table{border-collapse:collapse; width:100%; margin-top:12px}
    th,td{border:1px solid #ddd; padding:8px; text-align:left; vertical-align:top}
    th{background:#f5f5f5}
    .muted{color:#666; font-size:12px}
  </style>
</head>
<body>
  <h2>Semantic Search</h2>
  <div class="nav">
    <a href="/database/html">View Database</a>
    <a href="/database">Database JSON</a>
  </div>
  <div class="row">
    <input id="q" type="text" placeholder="Search (e.g., database latency in payments)" style="flex:1; min-width:260px">
    <input id="service" type="text" placeholder="service filter (optional)" style="width:220px">
    <select id="k">
      <option value="5" selected>Top 5</option>
      <option value="10">Top 10</option>
      <option value="20">Top 20</option>
    </select>
    <button id="go">Search</button>
  </div>
  <div class="muted">Tip: try “cross site scripting” or “payments latency spike”.</div>
  <div id="out"></div>

<script>
async function run(){
  const q = document.getElementById('q').value.trim();
  if(!q){ return; }
  const service = document.getElementById('service').value.trim();
  const k = document.getElementById('k').value;
  const params = new URLSearchParams({q, k});
  if(service) params.append('service', service);
  const res = await fetch('/search?' + params.toString());
  const data = await res.json();

  const rows = (data.results || []).map(r => `
    <tr>
      <td>${r.id}</td>
      <td>${r.service || ""}</td>
      <td>${r.type || ""}</td>
      <td>${(1 - r.distance).toFixed(3)}</td>
      <td>${(r.summary || "").replace(/</g,"&lt;")}</td>
    </tr>`).join('');

  document.getElementById('out').innerHTML = `
    <div class="muted">Query: <b>${q.replace(/</g,"&lt;")}</b> · Results: ${data.count}</div>
    <table>
      <thead><tr><th>Incident ID</th><th>Service</th><th>Type</th><th>Similarity</th><th>Summary</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5">No results</td></tr>'}</tbody>
    </table>`;
}
document.getElementById('go').addEventListener('click', run);
document.getElementById('q').addEventListener('keydown', e => { if(e.key==='Enter') run(); });
</script>
</body>
</html>
"""

@app.get("/database")
def view_database():
    """View all records in the database"""
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, summary, labels, service, incident_type, 
                           CASE WHEN embedding IS NOT NULL THEN 'Yes' ELSE 'No' END as has_embedding,
                           model, dim
                    FROM memory_item 
                    ORDER BY id
                """)
                rows = cur.fetchall()
                
                records = []
                for row in rows:
                    records.append({
                        "id": row[0],
                        "summary": row[1],
                        "labels": row[2] or [],
                        "service": row[3],
                        "type": row[4],
                        "has_embedding": row[5],
                        "model": row[6],
                        "dimensions": row[7]
                    })
                
                return {
                    "total_records": len(records),
                    "records": records
                }
    except Exception as e:
        return {"error": str(e)}

@app.get("/database/html", response_class=HTMLResponse)
def view_database_html():
    """View all records in a nice HTML table"""
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, summary, labels, service, incident_type, 
                           CASE WHEN embedding IS NOT NULL THEN 'Yes' ELSE 'No' END as has_embedding,
                           model, dim
                    FROM memory_item 
                    ORDER BY id
                """)
                rows = cur.fetchall()
                
                total_with_embeddings = sum(1 for row in rows if row[5] == 'Yes')
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Database Viewer</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 20px; }}
                        table {{ border-collapse: collapse; width: 100%; }}
                        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                        th {{ background-color: #f2f2f2; }}
                        tr:nth-child(even) {{ background-color: #f9f9f9; }}
                        .summary {{ max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
                        .nav {{ margin-bottom: 20px; }}
                        .nav a {{ margin-right: 15px; text-decoration: none; color: #007bff; }}
                        .stats {{ background: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 20px; }}
                    </style>
                </head>
                <body>
                    <div class="nav">
                        <a href="/">← Back to Search</a>
                        <a href="/database">JSON View</a>
                    </div>
                    
                    <h1>Database Viewer</h1>
                    
                    <div class="stats">
                        <strong>Total Records:</strong> {len(rows)}<br>
                        <strong>Records with Embeddings:</strong> {total_with_embeddings}<br>
                        <strong>Last Updated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    </div>
                    
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>Service</th>
                            <th>Type</th>
                            <th>Summary</th>
                            <th>Labels</th>
                            <th>Embedding</th>
                        </tr>
                """
                
                for row in rows:
                    labels_str = ', '.join(row[2] or [])
                    summary = str(row[1] or 'N/A').replace('<', '&lt;').replace('>', '&gt;')
                    html += f"""
                        <tr>
                            <td>{row[0]}</td>
                            <td>{row[3] or 'N/A'}</td>
                            <td>{row[4] or 'N/A'}</td>
                            <td class="summary" title="{summary}">{summary}</td>
                            <td>{labels_str}</td>
                            <td>{row[5]}</td>
                        </tr>
                    """
                
                html += """
                    </table>
                </body>
                </html>
                """
                
                return HTMLResponse(content=html)
                
    except Exception as e:
        error_html = f"""
        <html><body>
            <h1>Database Error</h1>
            <p>Error: {str(e)}</p>
            <a href="/">← Back to Search</a>
        </body></html>
        """
        return HTMLResponse(content=error_html, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
