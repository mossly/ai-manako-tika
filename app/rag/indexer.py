"""RAG Store for Cook Islands legislation embeddings using Pinecone."""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os, json
import hashlib
from loguru import logger

import numpy as np
from openai import AsyncOpenAI
from pinecone import Pinecone, ServerlessSpec

# Import metadata DB and year extraction
from ..db.metadata import metadata_db
from ..utils.extract_year import extract_year_from_act_name

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

    def _batch_check_needs_embedding(self, chunks: List[Chunk]) -> List[bool]:
        """Batch check if chunks need embedding.

        Returns list of booleans indicating which chunks need embedding.
        Consolidates Pinecone fetch operations to reduce read quota usage.
        """
        if not self._pc_index:
            return [True] * len(chunks)

        if not chunks:
            return []

        try:
            # Batch fetch all chunk IDs at once (max 1000 per fetch)
            chunk_ids = [c.id for c in chunks]
            needs_embedding = [False] * len(chunks)

            # Process in batches of 1000 (Pinecone fetch limit)
            batch_size = 1000
            for batch_start in range(0, len(chunk_ids), batch_size):
                batch_end = min(batch_start + batch_size, len(chunk_ids))
                batch_ids = chunk_ids[batch_start:batch_end]
                batch_chunks = chunks[batch_start:batch_end]

                result = self._pc_index.fetch(ids=batch_ids)
                existing_vectors = result.get('vectors', {})

                # Check each chunk in this batch
                for i, chunk in enumerate(batch_chunks):
                    global_idx = batch_start + i

                    if chunk.id not in existing_vectors:
                        needs_embedding[global_idx] = True  # New chunk
                        continue

                    # Check fingerprint
                    existing_meta = existing_vectors[chunk.id].get('metadata', {})
                    existing_fp = existing_meta.get('fingerprint')
                    current_fp = self._fingerprint(chunk)

                    if existing_fp != current_fp:
                        needs_embedding[global_idx] = True  # Changed chunk
                        continue

                    # Check if model changed
                    if existing_meta.get('model') != OPENAI_EMBED_MODEL:
                        needs_embedding[global_idx] = True
                        continue

            return needs_embedding

        except Exception as e:
            logger.warning(f"Error batch checking chunks for embedding: {e}")
            return [True] * len(chunks)  # Re-embed all on error

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
        """Ingest chunks into Pinecone and SQLite metadata database."""
        if not chunks:
            logger.warning("ingest_chunks called with empty chunk list")
            return

        if not self._pc_index:
            raise RuntimeError("Pinecone not initialized")

        # Batch check which chunks need embedding (consolidates Pinecone reads)
        needs_embedding_flags = self._batch_check_needs_embedding(chunks)
        to_embed: List[Chunk] = [c for c, needs in zip(chunks, needs_embedding_flags) if needs]

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

        # Batch upsert to Pinecone
        # Note: Pinecone supports up to 1000 vectors per upsert, but we use smaller batches
        # to reduce memory usage and provide better progress feedback
        batch_size = 200  # Increased from 100 to reduce number of write operations
        for i in range(0, len(upsert_data), batch_size):
            batch = upsert_data[i:i+batch_size]
            self._pc_index.upsert(vectors=batch)
            logger.info(f"Upserted batch {i//batch_size + 1}/{(len(upsert_data)-1)//batch_size + 1}")

        logger.info(f"Ingested/updated {len(to_embed)} chunks into Pinecone")

        # Also update SQLite metadata database
        try:
            # Get document info from first chunk
            if to_embed:
                first_chunk = to_embed[0]
                doc_id = first_chunk.meta.get('doc_id')
                act_name = first_chunk.meta.get('act_name')
                pdf_path = first_chunk.meta.get('pdf_path')
                pdf_filename = first_chunk.meta.get('pdf_filename')
                file_hash = first_chunk.meta.get('file_hash')

                if doc_id and act_name:
                    # Extract year
                    year = extract_year_from_act_name(act_name)

                    # Upsert document
                    metadata_db.upsert_document(
                        doc_id=doc_id,
                        act_name=act_name,
                        year=year,
                        pdf_filename=pdf_filename,
                        pdf_path=pdf_path,
                        file_hash=file_hash
                    )

                    # Upsert all chunks
                    for chunk in to_embed:
                        metadata_db.upsert_chunk(
                            chunk_id=chunk.id,
                            doc_id=doc_id,
                            metadata=chunk.meta
                        )

                    # Update chunk count
                    metadata_db.update_document_chunk_count(doc_id)

                    logger.info(f"Updated SQLite metadata for {doc_id}: {len(to_embed)} chunks")

        except Exception as e:
            # Don't fail the entire ingestion if SQLite update fails
            logger.exception(f"Failed to update SQLite metadata (non-fatal): {e}")

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
        """Retrieve a complete section with all its subsections from Pinecone.

        Also handles Parts and other structural elements by ID.
        """
        if not self._pc_index:
            logger.warning("Pinecone not initialized")
            return []

        try:
            # First try to fetch by ID directly (for Parts, Schedules, etc.)
            # These elements use their ID as the chunk ID but don't populate section_id
            try:
                fetch_result = self._pc_index.fetch(ids=[section_id])
                if fetch_result.get('vectors') and section_id in fetch_result['vectors']:
                    # Found by direct ID lookup
                    vector_data = fetch_result['vectors'][section_id]
                    metadata = vector_data.get('metadata', {})

                    formatted_results = [{
                        'chunk_id': section_id,
                        'heading_path': metadata.get('heading_path', ''),
                        'text': metadata.get('text', ''),
                        'meta': {k: v for k, v in metadata.items()
                                if k not in ['heading_path', 'text', 'fingerprint', 'model']}
                    }]

                    logger.info(f"get_section({section_id}): found by direct ID fetch")
                    return formatted_results
            except Exception as fetch_err:
                logger.debug(f"Direct ID fetch failed (will try metadata filter): {fetch_err}")

            # If not found by ID, try metadata filter (for regular Sections)
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

            logger.info(f"get_section({section_id}): found {len(formatted_results)} chunks via metadata filter")
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
