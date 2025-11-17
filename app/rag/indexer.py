"""RAG Store for Cook Islands legislation embeddings using Pinecone."""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os, json
import hashlib
from loguru import logger

import numpy as np
from openai import AsyncOpenAI
from pinecone import Pinecone, ServerlessSpec

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_EMBED_MODEL = os.getenv('OPENAI_EMBED_MODEL', 'text-embedding-3-large')

# Pinecone configuration
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY', '')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'cook-islands-legislation')
PINECONE_CLOUD = os.getenv('PINECONE_CLOUD', 'aws')
PINECONE_REGION = os.getenv('PINECONE_REGION', 'us-east-1')

# Embedding dimension for text-embedding-3-large
EMBEDDING_DIMENSION = 3072


class Chunk(BaseModel):
    """Legislation chunk with hierarchical metadata."""
    id: str
    heading_path: str
    text: str
    meta: Dict[str, Any] = {}


class RAGStore:
    def __init__(self):
        self.chunks: List[Chunk] = []
        self._index: Dict[str, int] = {}
        self._fp: Dict[str, str] = {}
        self._pc_client = None
        self._pc_index = None
        self._init_pinecone()
        self._load_metadata()

    def _init_pinecone(self):
        """Initialize Pinecone client and index."""
        if not PINECONE_API_KEY:
            logger.warning("PINECONE_API_KEY not set - running in degraded mode")
            return

        try:
            self._pc_client = Pinecone(api_key=PINECONE_API_KEY)

            # Check if index exists, create if not
            existing_indexes = [idx.name for idx in self._pc_client.list_indexes()]

            if PINECONE_INDEX_NAME not in existing_indexes:
                logger.info(f"Creating Pinecone index: {PINECONE_INDEX_NAME}")
                self._pc_client.create_index(
                    name=PINECONE_INDEX_NAME,
                    dimension=EMBEDDING_DIMENSION,
                    metric='cosine',
                    spec=ServerlessSpec(
                        cloud=PINECONE_CLOUD,
                        region=PINECONE_REGION
                    )
                )
                logger.info(f"Pinecone index created: {PINECONE_INDEX_NAME}")

            self._pc_index = self._pc_client.Index(PINECONE_INDEX_NAME)
            logger.info(f"Connected to Pinecone index: {PINECONE_INDEX_NAME}")

        except Exception as e:
            logger.exception(f"Failed to initialize Pinecone: {e}")
            raise

    def _load_metadata(self):
        """Load chunk metadata from Pinecone.

        Note: We fetch metadata on-demand during search rather than loading all chunks
        into memory. This keeps memory usage low.
        """
        if not self._pc_index:
            logger.warning("Pinecone not initialized - no metadata to load")
            return

        try:
            # Get index stats to populate chunks count
            stats = self._pc_index.describe_index_stats()
            total_vectors = stats.get('total_vector_count', 0)
            logger.info(f"Pinecone index has {total_vectors:,} vectors")

            # We don't load all chunks into memory anymore
            # Just keep track of the count for status endpoints
            self.chunks = []  # Empty list, populated on-demand

        except Exception as e:
            logger.exception(f"Failed to load metadata from Pinecone: {e}")

    def _fingerprint(self, chunk: Chunk) -> str:
        """Stable fingerprint for a chunk's identity + content."""
        file_hash = ""
        try:
            file_hash = str((chunk.meta or {}).get('file_hash', ''))
        except Exception:
            file_hash = ""
        h = hashlib.sha1()
        h.update((chunk.id or '').encode('utf-8'))
        h.update(b"|")
        h.update(file_hash.encode('utf-8'))
        h.update(b"|")
        h.update((chunk.text or "").encode('utf-8'))
        return h.hexdigest()

    def _needs_embedding(self, chunk: Chunk) -> bool:
        """Return True if the chunk is new or changed.

        Checks Pinecone metadata to see if chunk exists and matches fingerprint.
        """
        if not self._pc_index:
            return True

        try:
            # Fetch existing vector metadata
            result = self._pc_index.fetch(ids=[chunk.id])

            if chunk.id not in result.get('vectors', {}):
                return True  # New chunk

            # Check fingerprint
            existing_meta = result['vectors'][chunk.id].get('metadata', {})
            existing_fp = existing_meta.get('fingerprint')
            current_fp = self._fingerprint(chunk)

            if existing_fp != current_fp:
                return True  # Changed chunk

            # Check if model changed
            if existing_meta.get('model') != OPENAI_EMBED_MODEL:
                return True

            return False

        except Exception as e:
            logger.warning(f"Error checking if chunk needs embedding: {e}")
            return True  # Re-embed on error

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings for a list of texts using OpenAI."""
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set; cannot create embeddings.")

        def _to_safe_str(x: Any) -> str:
            try:
                s = x if isinstance(x, str) else ("" if x is None else str(x))
            except Exception:
                s = ""
            s = s.replace("\x00", "").strip()
            s = " ".join(s.split())
            return s

        MAX_CHARS = 4000
        BATCH = 64

        sanitized_slices: List[str] = []
        mapping: List[tuple[int, int]] = []

        for t in texts:
            s = _to_safe_str(t)
            if not s:
                s = "."
            if len(s) > MAX_CHARS:
                parts = [s[i:i+MAX_CHARS] for i in range(0, len(s), MAX_CHARS)]
                start = len(sanitized_slices)
                sanitized_slices.extend(parts)
                mapping.append((start, len(parts)))
            else:
                start = len(sanitized_slices)
                sanitized_slices.append(s)
                mapping.append((start, 1))

        try:
            client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            logger.info(
                f"Creating embeddings: inputs={len(texts)}, slices={len(sanitized_slices)}, model='{OPENAI_EMBED_MODEL}'"
            )

            all_slice_vecs: List[List[float]] = []
            for i in range(0, len(sanitized_slices), BATCH):
                batch = sanitized_slices[i:i+BATCH]
                resp = await client.embeddings.create(model=OPENAI_EMBED_MODEL, input=batch)
                all_slice_vecs.extend([d.embedding for d in resp.data])

            result_vecs: List[List[float]] = []
            for start, count in mapping:
                if count == 1:
                    result_vecs.append(all_slice_vecs[start])
                else:
                    seg = np.array(all_slice_vecs[start:start+count], dtype=float)
                    avg = seg.mean(axis=0)
                    result_vecs.append(avg.tolist())

            logger.info(f"Embeddings created: count={len(result_vecs)}")
            return result_vecs
        except Exception:
            logger.exception("OpenAI embeddings request failed")
            raise

    async def ingest_chunks(self, chunks: List[Chunk]):
        """Ingest chunks into Pinecone."""
        if not chunks:
            logger.warning("ingest_chunks called with empty chunk list")
            return

        if not self._pc_index:
            raise RuntimeError("Pinecone not initialized")

        # Partition into new/changed vs unchanged
        to_embed: List[Chunk] = []
        for c in chunks:
            if self._needs_embedding(c):
                to_embed.append(c)

        skipped = len(chunks) - len(to_embed)
        if skipped:
            logger.info(f"Skipping {skipped} unchanged chunks (already embedded)")
        if not to_embed:
            logger.info("No new/changed chunks to embed")
            return

        logger.info(f"Embedding and upserting chunks: to_embed={len(to_embed)} of total={len(chunks)}")
        vectors = await self.embed_texts([c.text for c in to_embed])

        # Prepare vectors for Pinecone upsert
        upsert_data = []
        for c, v in zip(to_embed, vectors):
            fp = self._fingerprint(c)

            # Prepare metadata (Pinecone has size limits, so store essentials)
            metadata = {
                'heading_path': c.heading_path,
                'text': c.text[:1000],  # Truncate text for metadata storage
                'fingerprint': fp,
                'model': OPENAI_EMBED_MODEL,
                **{k: v for k, v in c.meta.items() if isinstance(v, (str, int, float, bool))}
            }

            upsert_data.append({
                'id': c.id,
                'values': v,
                'metadata': metadata
            })

        # Batch upsert to Pinecone (max 100 per batch)
        batch_size = 100
        for i in range(0, len(upsert_data), batch_size):
            batch = upsert_data[i:i+batch_size]
            self._pc_index.upsert(vectors=batch)
            logger.info(f"Upserted batch {i//batch_size + 1}/{(len(upsert_data)-1)//batch_size + 1}")

        logger.info(f"Ingested/updated {len(to_embed)} chunks into Pinecone")

    def search(self, query_vec: List[float], k: int = 5, filter_act: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for chunks by vector similarity with optional filtering."""
        if not self._pc_index:
            logger.warning("Pinecone not initialized - cannot search")
            return []

        try:
            # Build filter if act name provided
            filter_dict = None
            if filter_act:
                filter_dict = {
                    'act_name': {'$eq': filter_act}
                }

            # Query Pinecone
            results = self._pc_index.query(
                vector=query_vec,
                top_k=k,
                filter=filter_dict,
                include_metadata=True
            )

            # Format results
            formatted_results = []
            for match in results.get('matches', []):
                metadata = match.get('metadata', {})
                formatted_results.append({
                    'chunk_id': match['id'],
                    'heading_path': metadata.get('heading_path', ''),
                    'text': metadata.get('text', ''),
                    'score': float(match.get('score', 0.0)),
                    'meta': {k: v for k, v in metadata.items()
                            if k not in ['heading_path', 'text', 'fingerprint', 'model']}
                })

            return formatted_results

        except Exception as e:
            logger.exception(f"Pinecone search failed: {e}")
            return []

    async def embed_query(self, text: str) -> List[float]:
        """Embed a query text."""
        vecs = await self.embed_texts([text])
        return vecs[0]

    def get_section(self, section_id: str, include_subsections: bool = True) -> List[Dict[str, Any]]:
        """Retrieve a complete section with all its subsections from Pinecone."""
        if not self._pc_index:
            logger.warning("Pinecone not initialized")
            return []

        try:
            # Query by metadata filter
            filter_dict = {'section_id': {'$eq': section_id}}

            # Pinecone doesn't support pure metadata queries without a vector
            # We'll use a dummy vector and filter, then ignore scores
            dummy_vec = [0.0] * EMBEDDING_DIMENSION

            results = self._pc_index.query(
                vector=dummy_vec,
                top_k=10000,  # Get all matching
                filter=filter_dict,
                include_metadata=True
            )

            formatted_results = []
            for match in results.get('matches', []):
                metadata = match.get('metadata', {})

                # Filter by element_type if not including subsections
                if not include_subsections and metadata.get('element_type') != 'section':
                    continue

                formatted_results.append({
                    'chunk_id': match['id'],
                    'heading_path': metadata.get('heading_path', ''),
                    'text': metadata.get('text', ''),
                    'meta': {k: v for k, v in metadata.items()
                            if k not in ['heading_path', 'text', 'fingerprint', 'model']}
                })

            logger.info(f"get_section({section_id}): found {len(formatted_results)} chunks")
            return formatted_results

        except Exception as e:
            logger.exception(f"Failed to get section from Pinecone: {e}")
            return []

    def get_subsections(self, section_id: str, subsection_numbers: List[str]) -> List[Dict[str, Any]]:
        """Retrieve specific subsections from a section."""
        if not self._pc_index:
            logger.warning("Pinecone not initialized")
            return []

        try:
            filter_dict = {
                'section_id': {'$eq': section_id},
                'subsection_number': {'$in': subsection_numbers}
            }

            dummy_vec = [0.0] * EMBEDDING_DIMENSION
            results = self._pc_index.query(
                vector=dummy_vec,
                top_k=10000,
                filter=filter_dict,
                include_metadata=True
            )

            formatted_results = []
            for match in results.get('matches', []):
                metadata = match.get('metadata', {})
                formatted_results.append({
                    'chunk_id': match['id'],
                    'heading_path': metadata.get('heading_path', ''),
                    'text': metadata.get('text', ''),
                    'meta': {k: v for k, v in metadata.items()
                            if k not in ['heading_path', 'text', 'fingerprint', 'model']}
                })

            logger.info(f"get_subsections({section_id}, {subsection_numbers}): found {len(formatted_results)} chunks")
            return formatted_results

        except Exception as e:
            logger.exception(f"Failed to get subsections from Pinecone: {e}")
            return []

    def get_adjacent_sections(self, section_id: str, direction: str = "both", count: int = 1) -> List[Dict[str, Any]]:
        """Get adjacent sections for broader context.

        Note: This is complex with Pinecone. For now, return empty list.
        This feature can be implemented if needed by storing section ordering in metadata.
        """
        logger.warning("get_adjacent_sections not yet implemented for Pinecone backend")
        return []

    @property
    def vectors(self):
        """Compatibility property - returns None since vectors are in Pinecone."""
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from Pinecone index."""
        if not self._pc_index:
            return {
                'total_vectors': 0,
                'total_chunks': 0,
                'unique_acts': 0,
                'sample_acts': []
            }

        try:
            stats = self._pc_index.describe_index_stats()
            total_vectors = stats.get('total_vector_count', 0)

            # Get unique acts from namespaces if available
            # For now, return basic stats
            return {
                'total_vectors': total_vectors,
                'total_chunks': total_vectors,  # Same as vectors in Pinecone
                'unique_acts': 'N/A (query Pinecone metadata)',
                'sample_acts': []
            }

        except Exception as e:
            logger.exception(f"Failed to get stats from Pinecone: {e}")
            return {
                'total_vectors': 0,
                'total_chunks': 0,
                'unique_acts': 0,
                'sample_acts': []
            }


# Singleton instance
store = RAGStore()
