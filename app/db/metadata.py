"""SQLite metadata database for legislation documents and chunks."""
import sqlite3
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import contextmanager
from loguru import logger
import threading

METADATA_DB_PATH = os.getenv('METADATA_DB_PATH', '/data/metadata.db')


class MetadataDB:
    """Thread-safe SQLite database for legislation metadata."""

    def __init__(self, db_path: str = METADATA_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._ensure_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0  # Wait up to 30 seconds for lock
            )
            self._local.conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrent access
            self._local.conn.execute('PRAGMA journal_mode=WAL')
        return self._local.conn

    @contextmanager
    def _transaction(self):
        """Context manager for database transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _ensure_db(self):
        """Create database schema if it doesn't exist."""
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else '.', exist_ok=True)

        with self._transaction() as conn:
            # Documents table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    doc_id TEXT PRIMARY KEY,
                    act_name TEXT NOT NULL,
                    year INTEGER,
                    pdf_filename TEXT,
                    pdf_path TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    file_hash TEXT,
                    last_processed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Chunks table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    section_number TEXT,
                    section_title TEXT,
                    section_id TEXT,
                    subsection_number TEXT,
                    element_type TEXT,
                    page_number INTEGER,
                    heading_path TEXT,
                    chunk_index INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
                )
            ''')

            # Definitions table (placeholder for future)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    term TEXT NOT NULL,
                    definition_text TEXT,
                    section_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
                )
            ''')

            # Sessions table for persistent authentication
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    auth_code TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')

            # Conversations table for storing chat history
            conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    title TEXT,
                    messages TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
            ''')

            # Create indexes for common queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_doc_year ON documents(year)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_doc_name ON documents(act_name)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunks(doc_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_chunk_section ON chunks(section_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_def_term ON definitions(term)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_session_active ON sessions(is_active, expires_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_session_code ON sessions(auth_code)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_conversation_session ON conversations(session_id, updated_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_conversation_updated ON conversations(updated_at)')

        logger.info(f"Metadata database initialized at {self.db_path}")

    def upsert_document(self, doc_id: str, act_name: str, year: Optional[int] = None,
                       pdf_filename: Optional[str] = None, pdf_path: Optional[str] = None,
                       file_hash: Optional[str] = None) -> None:
        """Insert or update a document record."""
        with self._transaction() as conn:
            conn.execute('''
                INSERT INTO documents (doc_id, act_name, year, pdf_filename, pdf_path, file_hash, last_processed)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(doc_id) DO UPDATE SET
                    act_name = excluded.act_name,
                    year = excluded.year,
                    pdf_filename = excluded.pdf_filename,
                    pdf_path = excluded.pdf_path,
                    file_hash = excluded.file_hash,
                    last_processed = CURRENT_TIMESTAMP
            ''', (doc_id, act_name, year, pdf_filename, pdf_path, file_hash))
        logger.debug(f"Upserted document: {doc_id}")

    def upsert_chunk(self, chunk_id: str, doc_id: str, metadata: Dict[str, Any]) -> None:
        """Insert or update a chunk record."""
        with self._transaction() as conn:
            conn.execute('''
                INSERT INTO chunks (
                    chunk_id, doc_id, section_number, section_title, section_id,
                    subsection_number, element_type, page_number, heading_path, chunk_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    section_number = excluded.section_number,
                    section_title = excluded.section_title,
                    section_id = excluded.section_id,
                    subsection_number = excluded.subsection_number,
                    element_type = excluded.element_type,
                    page_number = excluded.page_number,
                    heading_path = excluded.heading_path,
                    chunk_index = excluded.chunk_index
            ''', (
                chunk_id,
                doc_id,
                metadata.get('section_number'),
                metadata.get('section_title'),
                metadata.get('section_id'),
                metadata.get('subsection_number'),
                metadata.get('element_type'),
                metadata.get('page_number'),
                metadata.get('heading_path'),
                metadata.get('chunk_index')
            ))

    def update_document_chunk_count(self, doc_id: str) -> None:
        """Update the chunk count for a document."""
        with self._transaction() as conn:
            conn.execute('''
                UPDATE documents
                SET chunk_count = (SELECT COUNT(*) FROM chunks WHERE doc_id = ?)
                WHERE doc_id = ?
            ''', (doc_id, doc_id))

    def upsert_document_with_chunks(self, doc_id: str, act_name: str,
                                     chunks: List[Dict[str, Any]],
                                     year: Optional[int] = None,
                                     pdf_filename: Optional[str] = None,
                                     pdf_path: Optional[str] = None,
                                     file_hash: Optional[str] = None) -> None:
        """Insert/update document and all its chunks in a single transaction.

        This is more efficient and prevents database locking issues when processing
        many documents, as all operations happen atomically.
        """
        with self._transaction() as conn:
            # Insert/update document
            conn.execute('''
                INSERT INTO documents (doc_id, act_name, year, pdf_filename, pdf_path, file_hash, last_processed)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(doc_id) DO UPDATE SET
                    act_name = excluded.act_name,
                    year = excluded.year,
                    pdf_filename = excluded.pdf_filename,
                    pdf_path = excluded.pdf_path,
                    file_hash = excluded.file_hash,
                    last_processed = CURRENT_TIMESTAMP
            ''', (doc_id, act_name, year, pdf_filename, pdf_path, file_hash))

            # Insert/update all chunks
            for chunk in chunks:
                metadata = chunk.get('meta', {})
                conn.execute('''
                    INSERT INTO chunks (
                        chunk_id, doc_id, section_number, section_title, section_id,
                        subsection_number, element_type, page_number, heading_path, chunk_index
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        section_number = excluded.section_number,
                        section_title = excluded.section_title,
                        section_id = excluded.section_id,
                        subsection_number = excluded.subsection_number,
                        element_type = excluded.element_type,
                        page_number = excluded.page_number,
                        heading_path = excluded.heading_path,
                        chunk_index = excluded.chunk_index
                ''', (
                    chunk['id'],
                    doc_id,
                    metadata.get('section_number'),
                    metadata.get('section_title'),
                    metadata.get('section_id'),
                    metadata.get('subsection_number'),
                    metadata.get('element_type'),
                    metadata.get('page_number'),
                    metadata.get('heading_path'),
                    metadata.get('chunk_index')
                ))

            # Update chunk count
            conn.execute('''
                UPDATE documents
                SET chunk_count = (SELECT COUNT(*) FROM chunks WHERE doc_id = ?)
                WHERE doc_id = ?
            ''', (doc_id, doc_id))

        logger.debug(f"Upserted document {doc_id} with {len(chunks)} chunks in single transaction")

    def get_all_documents(self, sort_by: str = 'name', limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all documents with optional sorting."""
        order_clause = {
            'name': 'act_name ASC',
            'year': 'year DESC, act_name ASC',
            'recent': 'last_processed DESC'
        }.get(sort_by, 'act_name ASC')

        query = f'SELECT * FROM documents ORDER BY {order_clause}'
        if limit:
            query += f' LIMIT {int(limit)}'

        conn = self._get_connection()
        cursor = conn.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    def search_by_title(self, title_query: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search documents by title with optional year filter."""
        conn = self._get_connection()

        if year:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE act_name LIKE ? AND year = ?
                ORDER BY act_name ASC
            ''', (f'%{title_query}%', year))
        else:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE act_name LIKE ?
                ORDER BY act_name ASC
            ''', (f'%{title_query}%',))

        return [dict(row) for row in cursor.fetchall()]

    def filter_by_year(self, year: Optional[int] = None,
                      year_from: Optional[int] = None,
                      year_to: Optional[int] = None) -> List[Dict[str, Any]]:
        """Filter documents by year or year range."""
        conn = self._get_connection()

        if year:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE year = ?
                ORDER BY act_name ASC
            ''', (year,))
        elif year_from and year_to:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE year BETWEEN ? AND ?
                ORDER BY year DESC, act_name ASC
            ''', (year_from, year_to))
        elif year_from:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE year >= ?
                ORDER BY year DESC, act_name ASC
            ''', (year_from,))
        elif year_to:
            cursor = conn.execute('''
                SELECT * FROM documents
                WHERE year <= ?
                ORDER BY year DESC, act_name ASC
            ''', (year_to,))
        else:
            return []

        return [dict(row) for row in cursor.fetchall()]

    def get_document_metadata(self, doc_id: str, include_sections: bool = False) -> Optional[Dict[str, Any]]:
        """Get detailed metadata for a specific document."""
        conn = self._get_connection()

        cursor = conn.execute('SELECT * FROM documents WHERE doc_id = ?', (doc_id,))
        doc = cursor.fetchone()

        if not doc:
            return None

        result = dict(doc)

        if include_sections:
            cursor = conn.execute('''
                SELECT DISTINCT section_number, section_title, section_id
                FROM chunks
                WHERE doc_id = ? AND element_type = 'section'
                ORDER BY section_number
            ''', (doc_id,))
            result['sections'] = [dict(row) for row in cursor.fetchall()]

        return result

    def get_document_by_name(self, act_name: str) -> Optional[Dict[str, Any]]:
        """Get document by exact or partial act name."""
        conn = self._get_connection()

        # Try exact match first
        cursor = conn.execute('SELECT * FROM documents WHERE act_name = ?', (act_name,))
        doc = cursor.fetchone()

        if doc:
            return dict(doc)

        # Try partial match
        cursor = conn.execute('''
            SELECT * FROM documents WHERE act_name LIKE ?
            ORDER BY LENGTH(act_name) ASC
            LIMIT 1
        ''', (f'%{act_name}%',))
        doc = cursor.fetchone()

        return dict(doc) if doc else None

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics."""
        conn = self._get_connection()

        cursor = conn.execute('SELECT COUNT(*) as total_docs FROM documents')
        total_docs = cursor.fetchone()['total_docs']

        cursor = conn.execute('SELECT COUNT(*) as total_chunks FROM chunks')
        total_chunks = cursor.fetchone()['total_chunks']

        cursor = conn.execute('''
            SELECT year, COUNT(*) as count
            FROM documents
            WHERE year IS NOT NULL
            GROUP BY year
            ORDER BY year DESC
            LIMIT 10
        ''')
        acts_by_year = [dict(row) for row in cursor.fetchall()]

        cursor = conn.execute('''
            SELECT MIN(year) as earliest, MAX(year) as latest
            FROM documents
            WHERE year IS NOT NULL
        ''')
        year_range = cursor.fetchone()

        return {
            'total_documents': total_docs,
            'total_chunks': total_chunks,
            'acts_by_year': acts_by_year,
            'earliest_year': year_range['earliest'],
            'latest_year': year_range['latest']
        }

    def create_session(self, session_id: str, auth_code: str, expires_at: str) -> None:
        """Create a new session."""
        with self._transaction() as conn:
            conn.execute('''
                INSERT INTO sessions (session_id, auth_code, expires_at)
                VALUES (?, ?, ?)
            ''', (session_id, auth_code, expires_at))
        logger.debug(f"Created session: {session_id}")

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID if active and not expired."""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT * FROM sessions
            WHERE session_id = ? AND is_active = 1 AND expires_at > CURRENT_TIMESTAMP
        ''', (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_session_activity(self, session_id: str) -> None:
        """Update session last activity timestamp."""
        with self._transaction() as conn:
            conn.execute('''
                UPDATE sessions
                SET last_activity = CURRENT_TIMESTAMP
                WHERE session_id = ?
            ''', (session_id,))

    def deactivate_session(self, session_id: str) -> None:
        """Deactivate a session."""
        with self._transaction() as conn:
            conn.execute('''
                UPDATE sessions SET is_active = 0 WHERE session_id = ?
            ''', (session_id,))
        logger.debug(f"Deactivated session: {session_id}")

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count of removed sessions."""
        with self._transaction() as conn:
            cursor = conn.execute('''
                DELETE FROM sessions
                WHERE expires_at < CURRENT_TIMESTAMP OR is_active = 0
            ''')
            count = cursor.rowcount
        logger.info(f"Cleaned up {count} expired sessions")
        return count

    # Conversation management methods
    def create_conversation(self, conversation_id: str, session_id: str, title: Optional[str] = None) -> None:
        """Create a new conversation."""
        with self._transaction() as conn:
            conn.execute('''
                INSERT INTO conversations (conversation_id, session_id, title, messages)
                VALUES (?, ?, ?, ?)
            ''', (conversation_id, session_id, title or "New Conversation", "[]"))
        logger.debug(f"Created conversation: {conversation_id}")

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get conversation by ID."""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT * FROM conversations WHERE conversation_id = ?
        ''', (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_conversations(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List all conversations for a session, ordered by most recent."""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT conversation_id, title, created_at, updated_at
            FROM conversations
            WHERE session_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
        ''', (session_id, limit))
        return [dict(row) for row in cursor.fetchall()]

    def update_conversation(self, conversation_id: str, messages: str, title: Optional[str] = None) -> None:
        """Update conversation messages and optionally title."""
        with self._transaction() as conn:
            if title is not None:
                conn.execute('''
                    UPDATE conversations
                    SET messages = ?, title = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE conversation_id = ?
                ''', (messages, title, conversation_id))
            else:
                conn.execute('''
                    UPDATE conversations
                    SET messages = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE conversation_id = ?
                ''', (messages, conversation_id))

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation."""
        with self._transaction() as conn:
            conn.execute('''
                DELETE FROM conversations WHERE conversation_id = ?
            ''', (conversation_id,))
        logger.debug(f"Deleted conversation: {conversation_id}")

    def get_conversation_messages(self, conversation_id: str) -> Optional[str]:
        """Get messages for a conversation."""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT messages FROM conversations WHERE conversation_id = ?
        ''', (conversation_id,))
        row = cursor.fetchone()
        return row['messages'] if row else None

    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            del self._local.conn


# Singleton instance
metadata_db = MetadataDB()
