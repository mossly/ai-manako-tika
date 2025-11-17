"""RAG Store for Cook Islands legislation embeddings."""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import os, json
import hashlib
from loguru import logger

# Minimal local RAG store: embeddings via OpenAI, vectors in a simple list (upgradeable to FAISS/Qdrant later)
import numpy as np
from openai import AsyncOpenAI

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_EMBED_MODEL = os.getenv('OPENAI_EMBED_MODEL', 'text-embedding-3-large')

WORKING_DIR = os.getenv('WORKING_DIR', '/data/rag_storage')
EMBED_PATH = os.path.join(WORKING_DIR, 'embeddings.jsonl')

os.makedirs(WORKING_DIR, exist_ok=True)

class Chunk(BaseModel):
    """Legislation chunk with hierarchical metadata."""
    id: str
    heading_path: str
    text: str
    meta: Dict[str, Any] = {}

class RAGStore:
    def __init__(self):
        self.chunks: List[Chunk] = []
        self.vectors: List[List[float]] = []
        # indices for dedup + updates
        self._index: Dict[str, int] = {}
        self._fp: Dict[str, str] = {}
        self._model: Dict[str, str] = {}
        self._load()

    def _load(self):
        if os.path.exists(EMBED_PATH):
            try:
                loaded = 0
                logger.info(f"Loading embeddings from {EMBED_PATH}...")
                with open(EMBED_PATH, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            o = json.loads(line)
                            chunk_dict = o.get('chunk') or {}
                            vec = o.get('vector')
                            if not chunk_dict or vec is None:
                                continue
                            c = Chunk(**chunk_dict)
                            fp = self._fingerprint(c)
                            model = o.get('model') or OPENAI_EMBED_MODEL
                            if c.id in self._index:
                                idx = self._index[c.id]
                                self.chunks[idx] = c
                                self.vectors[idx] = vec
                            else:
                                self._index[c.id] = len(self.chunks)
                                self.chunks.append(c)
                                self.vectors.append(vec)
                            self._fp[c.id] = fp
                            self._model[c.id] = model
                            loaded += 1

                            # Progress logging every 10K chunks
                            if loaded % 10000 == 0:
                                logger.info(f"Loading progress: {loaded:,} chunks processed...")
                        except Exception:
                            logger.exception("Malformed embeddings line encountered; skipping")
                            continue
                logger.info(f"Loaded {len(self.chunks)} unique chunks from store (lines={loaded})")
            except Exception:
                logger.exception(f"Failed to load embeddings file at {EMBED_PATH}")

    def _save_append(self, chunk: Chunk, vector: List[float]):
        try:
            with open(EMBED_PATH, 'a', encoding='utf-8') as f:
                record = {
                    "chunk": chunk.dict(),
                    "vector": vector,
                    "model": OPENAI_EMBED_MODEL,
                }
                f.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception(f"Failed to append embedding for chunk_id='{chunk.id}' to {EMBED_PATH}")
            raise

    def _fingerprint(self, chunk: Chunk) -> str:
        """Stable fingerprint for a chunk's identity + content.

        Combines chunk.id, file_hash (if present), and text to detect changes.
        """
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
        """Return True if the chunk is new, changed, or model changed."""
        old_fp = self._fp.get(chunk.id)
        if old_fp is None:
            return True
        if old_fp != self._fingerprint(chunk):
            return True
        if self._model.get(chunk.id) != OPENAI_EMBED_MODEL:
            return True
        return False

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Create embeddings for a list of texts.

        - Ensures inputs are plain strings (no None/objects)
        - Splits overly-long texts into smaller slices, then averages their vectors
        - Sends requests in small batches to avoid payload issues
        """
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set; cannot create embeddings.")

        # Helper: sanitize a single text value into a safe string
        def _to_safe_str(x: Any) -> str:
            try:
                s = x if isinstance(x, str) else ("" if x is None else str(x))
            except Exception:
                s = ""
            # Remove problematic NULLs and normalize whitespace
            s = s.replace("\x00", "").strip()
            # Collapse excessive whitespace
            s = " ".join(s.split())
            return s

        # Maximum characters per slice (heuristic; keeps under token limits)
        MAX_CHARS = 4000
        BATCH = 64

        # Build a flattened list of sanitized slices and a mapping back to originals
        sanitized_slices: List[str] = []
        mapping: List[tuple[int, int]] = []  # (start_idx_in_sanitized, count)

        for t in texts:
            s = _to_safe_str(t)
            if not s:
                # Keep alignment by embedding a minimal placeholder
                s = "."
            if len(s) > MAX_CHARS:
                # Split deterministically on character windows
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

            # Batch over sanitized_slices
            all_slice_vecs: List[List[float]] = []
            for i in range(0, len(sanitized_slices), BATCH):
                batch = sanitized_slices[i:i+BATCH]
                resp = await client.embeddings.create(model=OPENAI_EMBED_MODEL, input=batch)
                all_slice_vecs.extend([d.embedding for d in resp.data])

            # Fold slices back to one vector per original input (average if split)
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
        if not chunks:
            logger.warning("ingest_chunks called with empty chunk list")
            return
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

        logger.info(f"Embedding and persisting chunks: to_embed={len(to_embed)} of total={len(chunks)}")
        vectors = await self.embed_texts([c.text for c in to_embed])
        for c, v in zip(to_embed, vectors):
            fp = self._fingerprint(c)
            if c.id in self._index:
                idx = self._index[c.id]
                self.chunks[idx] = c
                self.vectors[idx] = v
            else:
                self._index[c.id] = len(self.chunks)
                self.chunks.append(c)
                self.vectors.append(v)
            self._fp[c.id] = fp
            self._model[c.id] = OPENAI_EMBED_MODEL
            self._save_append(c, v)
        logger.info(f"Ingested/updated {len(to_embed)} chunks; total_unique_chunks={len(self.chunks)}")

    def search(self, query_vec: List[float], k: int = 5, filter_act: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search for chunks by vector similarity with optional filtering.

        Args:
            query_vec: Query embedding vector
            k: Number of results to return
            filter_act: Optional act name filter (case-insensitive partial match)

        Returns:
            List of dicts with chunk_id, heading_path, text, score, and metadata
        """
        if not self.vectors:
            return []

        # Apply filtering if requested
        if filter_act:
            filter_act_lower = filter_act.lower()
            filtered_indices = [
                i for i, chunk in enumerate(self.chunks)
                if filter_act_lower in chunk.meta.get('act_name', '').lower()
            ]
            if not filtered_indices:
                logger.warning(f"No chunks match filter act='{filter_act}'")
                return []
            mat = np.array([self.vectors[i] for i in filtered_indices])
            chunk_map = filtered_indices
        else:
            mat = np.array(self.vectors)
            chunk_map = list(range(len(self.chunks)))

        q = np.array(query_vec)
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) + 1e-8) + 1e-8)
        idx = np.argsort(-sims)[:k]
        results = []
        for i in idx:
            chunk_idx = chunk_map[i]
            chunk = self.chunks[chunk_idx]
            results.append({
                'chunk_id': chunk.id,
                'heading_path': chunk.heading_path,
                'text': chunk.text,
                'score': float(sims[i]),
                'meta': chunk.meta
            })
        return results

    async def embed_query(self, text: str) -> List[float]:
        vecs = await self.embed_texts([text])
        return vecs[0]

    def get_section(self, section_id: str, include_subsections: bool = True) -> List[Dict[str, Any]]:
        """Retrieve a complete section with all its subsections.

        Args:
            section_id: Section identifier (e.g., 'banking_act_1996-section-5')
            include_subsections: Whether to include subsections (default True)

        Returns:
            List of chunks belonging to this section
        """
        results = []
        for chunk in self.chunks:
            chunk_section_id = chunk.meta.get('section_id')
            if chunk_section_id == section_id:
                if include_subsections:
                    results.append({
                        'chunk_id': chunk.id,
                        'heading_path': chunk.heading_path,
                        'text': chunk.text,
                        'meta': chunk.meta
                    })
                elif chunk.meta.get('element_type') == 'section':
                    # Only the section itself, not subsections
                    results.append({
                        'chunk_id': chunk.id,
                        'heading_path': chunk.heading_path,
                        'text': chunk.text,
                        'meta': chunk.meta
                    })

        logger.info(f"get_section({section_id}): found {len(results)} chunks")
        return results

    def get_subsections(self, section_id: str, subsection_numbers: List[str]) -> List[Dict[str, Any]]:
        """Retrieve specific subsections from a section.

        Args:
            section_id: Section identifier
            subsection_numbers: List of subsection numbers (e.g., ['1', '2', '3'])

        Returns:
            List of matching subsection chunks
        """
        results = []
        for chunk in self.chunks:
            if chunk.meta.get('section_id') == section_id:
                subsection_num = chunk.meta.get('subsection_number')
                if subsection_num in subsection_numbers:
                    results.append({
                        'chunk_id': chunk.id,
                        'heading_path': chunk.heading_path,
                        'text': chunk.text,
                        'meta': chunk.meta
                    })

        logger.info(f"get_subsections({section_id}, {subsection_numbers}): found {len(results)} chunks")
        return results

    def get_adjacent_sections(self, section_id: str, direction: str = "both", count: int = 1) -> List[Dict[str, Any]]:
        """Get adjacent sections (previous/next) for broader context.

        Args:
            section_id: Current section identifier (e.g., 'banking_act_1996-section-5')
            direction: 'previous', 'next', or 'both'
            count: Number of adjacent sections to retrieve in each direction

        Returns:
            List of chunks from adjacent sections
        """
        # Extract doc_id and section number from section_id
        # Format: {doc_id}-section-{number}
        import re
        match = re.match(r'(.+)-section-(.+)', section_id)
        if not match:
            logger.warning(f"Invalid section_id format: {section_id}")
            return []

        doc_id = match.group(1)
        section_num_str = match.group(2).replace('-', '.')  # Convert back from '5-1' to '5.1'

        # Parse section number (handle 5, 5A, 5.1, etc.)
        try:
            # Try to extract base number
            base_match = re.match(r'(\d+)([A-Z])?(?:\.(\d+))?', section_num_str)
            if not base_match:
                logger.warning(f"Could not parse section number: {section_num_str}")
                return []

            base_num = int(base_match.group(1))
            suffix = base_match.group(2) or ''
            sub_num = base_match.group(3) or ''
        except ValueError:
            logger.warning(f"Could not parse section number: {section_num_str}")
            return []

        # Collect all sections from the same document
        all_sections = {}
        for chunk in self.chunks:
            if chunk.meta.get('doc_id') == doc_id and chunk.meta.get('section_number'):
                sec_id = chunk.meta.get('section_id')
                sec_num = chunk.meta.get('section_number')
                if sec_id not in all_sections:
                    all_sections[sec_id] = {
                        'section_id': sec_id,
                        'section_number': sec_num,
                        'chunks': []
                    }
                all_sections[sec_id]['chunks'].append({
                    'chunk_id': chunk.id,
                    'heading_path': chunk.heading_path,
                    'text': chunk.text,
                    'meta': chunk.meta
                })

        # Sort sections by number
        sorted_sections = sorted(all_sections.values(), key=lambda x: x['section_number'])

        # Find current section index
        current_idx = None
        for idx, sec in enumerate(sorted_sections):
            if sec['section_id'] == section_id:
                current_idx = idx
                break

        if current_idx is None:
            logger.warning(f"Section {section_id} not found in document")
            return []

        # Collect adjacent sections
        results = []

        if direction in ['previous', 'both']:
            for i in range(1, count + 1):
                prev_idx = current_idx - i
                if prev_idx >= 0:
                    results.extend(sorted_sections[prev_idx]['chunks'])

        if direction in ['next', 'both']:
            for i in range(1, count + 1):
                next_idx = current_idx + i
                if next_idx < len(sorted_sections):
                    results.extend(sorted_sections[next_idx]['chunks'])

        logger.info(f"get_adjacent_sections({section_id}, {direction}, {count}): found {len(results)} chunks")
        return results

# Singleton instance
store = RAGStore()
