"""Tool definitions and execution handlers for legislation navigation."""
from typing import List, Dict, Any
from urllib.parse import quote
from loguru import logger
from ..rag.indexer import store


def create_tool_definitions() -> List[Dict[str, Any]]:
    """Create OpenAI function tool definitions for legislation navigation.

    Returns:
        List of tool definition dictionaries
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "search_legislation_tool",
                "description": "Search Cook Islands legislation by semantic similarity to find relevant sections of Acts and Regulations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query about legislation"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of relevant sections to retrieve (1-10)",
                            "default": 6
                        },
                        "filter_act": {
                            "type": "string",
                            "description": "Optional filter for specific act name (case-insensitive partial match)"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_section_tool",
                "description": "Retrieve a complete section with all its subsections for comprehensive context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section_id": {
                            "type": "string",
                            "description": "Section identifier from search results (e.g., 'banking_act_1996-section-5')"
                        },
                        "include_subsections": {
                            "type": "boolean",
                            "description": "Whether to include all subsections (default true)",
                            "default": True
                        }
                    },
                    "required": ["section_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_subsections_tool",
                "description": "Retrieve specific subsections from a section",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section_id": {
                            "type": "string",
                            "description": "Section identifier from search results"
                        },
                        "subsection_numbers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of subsection numbers to retrieve (e.g., ['1', '2', '3'])"
                        }
                    },
                    "required": ["section_id", "subsection_numbers"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_adjacent_sections_tool",
                "description": "Get previous or next sections for broader legal context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section_id": {
                            "type": "string",
                            "description": "Current section identifier"
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["previous", "next", "both"],
                            "description": "Which direction to look (default 'both')",
                            "default": "both"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of sections to retrieve in each direction (default 1)",
                            "default": 1
                        }
                    },
                    "required": ["section_id"]
                }
            }
        }
    ]


def enhance_results_with_citations(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enhance search results with PDF links and text fragments for citations.

    Args:
        results: Raw search results from RAG store

    Returns:
        Enhanced results with pdf_link and citation_format fields
    """
    enhanced = []

    for r in results:
        result = r.copy()
        meta = r.get('meta', {})

        pdf_filename = meta.get('pdf_filename')
        page_number = meta.get('page_number')
        text_fragment = meta.get('text_fragment', '')

        if pdf_filename:
            # Build PDF link
            pdf_link_parts = [f"/pdfs/{pdf_filename}"]

            # Add page number if available
            if page_number:
                pdf_link_parts.append(f"#page={page_number}")

            # Add text fragment for precise highlighting (Chromium browsers)
            if text_fragment:
                # URL-encode the text fragment
                # Remove markdown formatting and limit length
                clean_fragment = text_fragment.replace('#', '').replace('*', '').replace('_', '').strip()
                if len(clean_fragment) > 50:
                    clean_fragment = clean_fragment[:50]

                encoded_fragment = quote(clean_fragment)
                if page_number:
                    pdf_link_parts.append(f"&:~:text={encoded_fragment}")
                else:
                    pdf_link_parts.append(f"#:~:text={encoded_fragment}")

            pdf_link = ''.join(pdf_link_parts)
            result['pdf_link'] = pdf_link

            # Create citation format suggestion
            act_name = meta.get('act_name', 'Act')
            section_num = meta.get('section_number')
            subsection_num = meta.get('subsection_number')

            citation_text_parts = [act_name]
            if section_num:
                section_part = f"Section {section_num}"
                if subsection_num:
                    section_part += f"({subsection_num})"
                citation_text_parts.append(section_part)

            if page_number:
                citation_text_parts.append(f"Page {page_number}")

            citation_text = " - ".join(citation_text_parts)
            result['citation_format'] = f"[{citation_text}]({pdf_link})"

        enhanced.append(result)

    return enhanced


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a legislation tool and return results.

    Args:
        tool_name: Name of the tool to execute
        arguments: Tool arguments

    Returns:
        Dict with results and metadata
    """
    logger.info(f"Executing tool: {tool_name} with args: {arguments}")

    if tool_name == "search_legislation_tool":
        query = arguments.get('query', '')
        top_k = arguments.get('top_k', 6)
        filter_act = arguments.get('filter_act')

        query_vec = await store.embed_query(query)
        results = store.search(query_vec, k=top_k, filter_act=filter_act)
        enhanced_results = enhance_results_with_citations(results)

        return {
            'success': True,
            'tool': tool_name,
            'results': enhanced_results,
            'count': len(enhanced_results)
        }

    elif tool_name == "get_section_tool":
        section_id = arguments.get('section_id', '')
        include_subsections = arguments.get('include_subsections', True)

        results = store.get_section(section_id, include_subsections)
        enhanced_results = enhance_results_with_citations(results)

        return {
            'success': True,
            'tool': tool_name,
            'section_id': section_id,
            'results': enhanced_results,
            'count': len(enhanced_results)
        }

    elif tool_name == "get_subsections_tool":
        section_id = arguments.get('section_id', '')
        subsection_numbers = arguments.get('subsection_numbers', [])

        results = store.get_subsections(section_id, subsection_numbers)
        enhanced_results = enhance_results_with_citations(results)

        return {
            'success': True,
            'tool': tool_name,
            'section_id': section_id,
            'subsection_numbers': subsection_numbers,
            'results': enhanced_results,
            'count': len(enhanced_results)
        }

    elif tool_name == "get_adjacent_sections_tool":
        section_id = arguments.get('section_id', '')
        direction = arguments.get('direction', 'both')
        count = arguments.get('count', 1)

        results = store.get_adjacent_sections(section_id, direction, count)
        enhanced_results = enhance_results_with_citations(results)

        return {
            'success': True,
            'tool': tool_name,
            'section_id': section_id,
            'direction': direction,
            'results': enhanced_results,
            'count': len(enhanced_results)
        }

    else:
        logger.warning(f"Unknown tool: {tool_name}")
        return {
            'success': False,
            'error': f"Unknown tool: {tool_name}"
        }
