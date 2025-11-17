"""MCP server exposing Cook Islands legislation RAG search tools."""
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from loguru import logger

from .rag.indexer import store

# Create MCP server instance
mcp = FastMCP("Cook Islands Legislation RAG")


@mcp.tool()
async def search_legislation_tool(
    query: str,
    top_k: int = 6,
    filter_act: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search Cook Islands legislation by semantic similarity.

    Use this tool to find relevant sections of Cook Islands Acts and Regulations
    based on a natural language query. The tool performs vector similarity search
    over embedded legislation chunks.

    Args:
        query: Natural language query about legislation (e.g., "What are the capital requirements for banks?")
        top_k: Number of relevant sections to retrieve (1-10, default: 6)
        filter_act: Optional filter for specific act name (case-insensitive partial match, e.g., "Banking Act")

    Returns:
        List of relevant legislation sections with metadata:
        - chunk_id: Unique identifier for the section
        - heading_path: Hierarchical path (Act > Part > Section)
        - text: The legislation text
        - score: Similarity score (0-1, higher is more relevant)
        - meta: Metadata including act_name, hierarchy, etc.

    Example:
        search_legislation_tool("banking license requirements", top_k=5, filter_act="Banking Act")
    """
    try:
        # Validate top_k
        top_k = max(1, min(10, top_k))

        logger.info(f"MCP search_legislation_tool called: query='{query}', top_k={top_k}, filter_act={filter_act}")

        # Check if store has data
        if not store.chunks:
            logger.warning("RAG store is empty - no legislation has been ingested yet")
            return [{
                'chunk_id': 'error',
                'heading_path': 'Error',
                'text': 'No legislation has been ingested yet. Please ingest legislation PDFs first.',
                'score': 0.0,
                'meta': {}
            }]

        # Embed query
        query_vec = await store.embed_query(query)

        # Search
        results = store.search(query_vec, k=top_k, filter_act=filter_act)

        logger.info(f"Found {len(results)} results for query='{query}'")

        return results

    except Exception as e:
        logger.exception(f"search_legislation_tool failed: {e}")
        return [{
            'chunk_id': 'error',
            'heading_path': 'Error',
            'text': f'Search failed: {str(e)}',
            'score': 0.0,
            'meta': {}
        }]


@mcp.tool()
def get_legislation_stats() -> Dict[str, Any]:
    """Get statistics about the legislation RAG store.

    Returns current state of the RAG system including number of chunks,
    unique acts, and other metadata.

    Returns:
        Dict with statistics:
        - total_chunks: Number of embedded legislation chunks
        - total_vectors: Number of embedding vectors
        - unique_acts: Number of unique acts in the store
        - sample_acts: Sample of act names
    """
    try:
        # Get unique act names
        act_names = set()
        for chunk in store.chunks:
            act_name = chunk.meta.get('act_name')
            if act_name:
                act_names.add(act_name)

        stats = {
            'total_chunks': len(store.chunks),
            'total_vectors': len(store.vectors) if store.vectors else 0,
            'unique_acts': len(act_names),
            'sample_acts': sorted(list(act_names))[:10]
        }

        logger.info(f"Legislation stats: {stats}")
        return stats

    except Exception as e:
        logger.exception(f"get_legislation_stats failed: {e}")
        return {'error': str(e)}
