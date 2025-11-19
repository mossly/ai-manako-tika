"""Quick check of metadata database counts."""
import sqlite3
import os

DB_PATH = os.getenv('METADATA_DB', '/data/metadata.db')

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get document and chunk counts
cursor.execute("SELECT COUNT(*) as docs, SUM(chunk_count) as total_chunks FROM documents")
result = cursor.fetchone()
print(f"Documents: {result[0]}")
print(f"Total chunks: {result[1]}")

# Get top 10 documents by chunk count
cursor.execute("""
    SELECT act_name, chunk_count
    FROM documents
    ORDER BY chunk_count DESC
    LIMIT 10
""")
print("\nTop 10 documents by chunk count:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} chunks")

conn.close()
