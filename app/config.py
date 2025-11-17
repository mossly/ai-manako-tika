"""Configuration management for legislation ingestion and processing."""
import os
import json
from typing import Optional, Dict, List
from loguru import logger
from filelock import FileLock

CONFIG_PATH = os.getenv('CONFIG_PATH', '/data/config.json')
CONFIG_LOCK_PATH = f"{CONFIG_PATH}.lock"


class LegislationConfig:
    """Manages persistent legislation processing configuration."""

    def __init__(self):
        self._ensure_path()

    def _ensure_path(self):
        """Ensure config directory exists."""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        if not os.path.exists(CONFIG_PATH):
            self._write({
                'documents': {},  # {doc_id: {file_hash, last_processed, act_name, ...}}
                'last_scrape': None,
                'scrape_stats': {}
            })

    def _read(self) -> dict:
        """Read config with file lock."""
        lock = FileLock(CONFIG_LOCK_PATH, timeout=5)
        with lock:
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read config: {e}, returning defaults")
                return {'documents': {}, 'last_scrape': None, 'scrape_stats': {}}

    def _write(self, data: dict):
        """Write config with file lock."""
        lock = FileLock(CONFIG_LOCK_PATH, timeout=5)
        with lock:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def get_document(self, doc_id: str) -> Optional[Dict]:
        """Get document metadata by ID."""
        config = self._read()
        return config.get('documents', {}).get(doc_id)

    def set_document(self, doc_id: str, metadata: Dict):
        """Set or update document metadata.

        Args:
            doc_id: Unique document identifier
            metadata: Dict with keys like file_hash, act_name, last_processed, etc.
        """
        config = self._read()
        if 'documents' not in config:
            config['documents'] = {}
        config['documents'][doc_id] = metadata
        self._write(config)
        logger.info(f"Updated config for doc_id={doc_id}")

    def get_all_documents(self) -> Dict[str, Dict]:
        """Get all document metadata."""
        config = self._read()
        return config.get('documents', {})

    def get_last_scrape(self) -> Optional[str]:
        """Get timestamp of last scrape."""
        config = self._read()
        return config.get('last_scrape')

    def update_scrape_stats(self, stats: Dict):
        """Update scrape statistics.

        Args:
            stats: Dict with keys like timestamp, pdfs_downloaded, new_acts, etc.
        """
        config = self._read()
        config['last_scrape'] = stats.get('timestamp')
        config['scrape_stats'] = stats
        self._write(config)
        logger.info(f"Updated scrape stats: {stats}")

    def document_needs_processing(self, doc_id: str, file_hash: str) -> bool:
        """Check if a document needs processing based on file hash.

        Args:
            doc_id: Document identifier
            file_hash: SHA256 hash of the PDF file

        Returns:
            True if document is new or has changed
        """
        doc = self.get_document(doc_id)
        if doc is None:
            return True
        return doc.get('file_hash') != file_hash

    def get_all(self) -> dict:
        """Get all config values."""
        return self._read()


# Singleton instance
legislation_config = LegislationConfig()
