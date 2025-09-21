import psycopg
from config import settings

def test_vector_connection():
    """Simple test to verify database connection and vector extension"""
    try:
        print("=== VECTOR CONNECTION TEST ===")
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Test basic connection
                cur.execute("SELECT 1")
                print("✓ Database connection works")
                
                # Test pgvector extension
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                ext = cur.fetchone()
                if ext:
                    print("✓ pgvector extension is installed")
                else:
                    print("✗ pgvector extension NOT found")
                    return False
                
                # Test table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'memory_item'
                    )
                """)
                table_exists = cur.fetchone()[0]
                if table_exists:
                    print("✓ memory_item table exists")
                else:
                    print("✗ memory_item table NOT found")
                    return False
                
                # Test embedding column
                cur.execute("""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'memory_item' 
                    AND column_name = 'embedding'
                """)
                col_info = cur.fetchone()
                if col_info:
                    print(f"✓ embedding column exists: {col_info[1]}")
                else:
                    print("✗ embedding column NOT found")
                    return False
                
                # Count total rows
                cur.execute("SELECT COUNT(*) FROM public.memory_item")
                total = cur.fetchone()[0]
                print(f"✓ Total rows: {total}")
                
                # Count rows with embeddings
                cur.execute("SELECT COUNT(*) FROM public.memory_item WHERE embedding IS NOT NULL")
                with_embeddings = cur.fetchone()[0]
                print(f"✓ Rows with embeddings: {with_embeddings}")
                
                if with_embeddings > 0:
                    # Check embedding dimension
                    cur.execute("SELECT array_length(embedding, 1) FROM public.memory_item WHERE embedding IS NOT NULL LIMIT 1")
                    dim = cur.fetchone()[0]
                    print(f"✓ Embedding dimension: {dim}")
                    
                    # Test simple vector operation
                    cur.execute("SELECT embedding <-> embedding FROM public.memory_item WHERE embedding IS NOT NULL LIMIT 1")
                    distance = cur.fetchone()[0]
                    print(f"✓ Vector distance operation works: {distance}")
                
                return True
                
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def _vec_literal(vec):
    if hasattr(vec, "tolist"):
        vec = vec.tolist()
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"

def search_similar_incidents(embedding, filters=None, k=5):
    """
    Deterministic pgvector search using string literal for vector.
    """
    try:
        print(f"DEBUG: search_similar_incidents called with k={k}")
        
        # Convert embedding to vector string using our working function
        vstr = _vec_literal(embedding)
        print(f"DEBUG: Vector string created, length: {len(vstr)}")
        
        where_sql = ""
        params = []

        if filters and filters.get("service"):
            where_sql = "WHERE service = %s"
            params.append(filters["service"])

        print(f"DEBUG: Attempting database connection...")
        with psycopg.connect(settings.DATABASE_URL) as conn:
            print(f"DEBUG: Database connected successfully")
            with conn.cursor() as cur:
                # Get existing columns
                cur.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'memory_item' 
                    ORDER BY ordinal_position
                """)
                columns = [row[0] for row in cur.fetchall()]
                print(f"DEBUG: Available columns: {columns}")
                
                # Check if table has data
                cur.execute("SELECT COUNT(*) FROM public.memory_item")
                total_count = cur.fetchone()[0]
                print(f"DEBUG: Total rows in memory_item: {total_count}")
                
                if total_count == 0:
                    print("DEBUG: Table is empty!")
                    return []
                
                # Use columns that exist
                existing_columns = [col for col in ['id', 'summary', 'labels', 'service', 'incident_type'] if col in columns]
                col_list = ', '.join(existing_columns)
                print(f"DEBUG: Will select columns: {existing_columns}")
                
                # Build SQL - use the working approach without ORDER BY in main query
                sql = f"""
                    SELECT {col_list}, embedding <=> '{vstr}'::vector AS dist
                    FROM public.memory_item
                    {where_sql}
                    LIMIT %s
                """
                
                # Only parameterize non-vector parameters
                query_params = params + [k]
                
                print(f"DEBUG: Executing SQL with {len(query_params)} params")
                cur.execute(sql, query_params)
                rows = cur.fetchall()
                
                print(f"DEBUG: Query returned {len(rows)} rows")
                
                # Sort results by distance in Python (since ORDER BY was causing issues)
                if rows:
                    rows = sorted(rows, key=lambda x: x[-1])  # Sort by distance (last column)
                    print(f"DEBUG: First result distance: {rows[0][-1]}")
                
                # Return results with proper column mapping
                results = []
                for r in rows:
                    result = {"distance": r[-1]}  # Distance is always last
                    for i, col in enumerate(existing_columns):
                        result[col] = r[i]
                    # Add missing columns with defaults
                    if 'labels' not in result:
                        result['labels'] = None
                    if 'service' not in result:
                        result['service'] = None
                    if 'incident_type' not in result:
                        result['type'] = None
                    else:
                        result['type'] = result.pop('incident_type')
                    results.append(result)
                
                print(f"DEBUG: Returning {len(results)} results")
                return results
                
    except Exception as e:
        print(f"ERROR in vector search: {e}")
        import traceback
        traceback.print_exc()
        return []


def index_incident(incident_data, embedding):
    """Index an incident into the vector store"""
    try:
        print(f"DEBUG: Indexing incident {incident_data['id']}")
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Insert or update the incident in memory_item
                cur.execute("""
                    INSERT INTO memory_item (id, summary, labels, service, incident_type, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        summary = EXCLUDED.summary,
                        labels = EXCLUDED.labels,
                        service = EXCLUDED.service,
                        incident_type = EXCLUDED.incident_type,
                        embedding = EXCLUDED.embedding
                """, (
                    str(incident_data["id"]),
                    incident_data["summary"],
                    incident_data["labels"],
                    incident_data["service"],
                    incident_data.get("type", "unknown"),
                    embedding
                ))
                conn.commit()
                print(f"Indexed incident {incident_data['id']} into vector store")
    except Exception as e:
        print(f"Error indexing incident: {e}")
        import traceback
        traceback.print_exc()


