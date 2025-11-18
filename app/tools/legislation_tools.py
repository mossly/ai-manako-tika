"""Tool definitions and execution handlers for legislation navigation."""
from typing import List, Dict, Any
from urllib.parse import quote
from loguru import logger
from ..rag.indexer import store
from ..db.metadata import metadata_db


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
        },
        {
            "type": "function",
            "function": {
                "name": "list_all_acts_tool",
                "description": "Get a complete list of all legislation acts in the database. Use this when the user asks questions like 'what acts exist', 'list all legislation', or 'what laws are available'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sort_by": {
                            "type": "string",
                            "enum": ["name", "year"],
                            "description": "Sort by act name alphabetically or by year (newest first)",
                            "default": "name"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of acts to return (default 100)",
                            "default": 100
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_acts_by_title_tool",
                "description": "Search for acts by title using keyword matching (not semantic search). Use this when the user wants to find acts by name, e.g., 'find all banking acts' or 'acts with education in the title'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title_query": {
                            "type": "string",
                            "description": "Keywords to search for in act titles (case-insensitive)"
                        },
                        "year": {
                            "type": "integer",
                            "description": "Optional: filter results to a specific year"
                        }
                    },
                    "required": ["title_query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "filter_acts_by_year_tool",
                "description": "Filter legislation acts by year or year range. Use this when the user asks about acts from a specific time period, e.g., 'acts from 2020', 'legislation between 2015 and 2020', or 'recent acts'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "year": {
                            "type": "integer",
                            "description": "Specific year to filter by (e.g., 2020)"
                        },
                        "year_from": {
                            "type": "integer",
                            "description": "Start year for range filter (inclusive)"
                        },
                        "year_to": {
                            "type": "integer",
                            "description": "End year for range filter (inclusive)"
                        }
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_act_metadata_tool",
                "description": "Get detailed metadata for a specific act including its sections, page count, and other information. Use this when the user wants to know about the structure or details of a specific act",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "act_name_or_id": {
                            "type": "string",
                            "description": "Act name (e.g., 'Banking Act 1996') or document ID (e.g., 'banking_act_1996')"
                        },
                        "include_sections": {
                            "type": "boolean",
                            "description": "Whether to include list of all sections (default false)",
                            "default": False
                        }
                    },
                    "required": ["act_name_or_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "find_definitions_tool",
                "description": "Find sections that contain definitions or interpretations of terms. Use this when the user asks 'what does X mean', 'define Y', or 'what are the definitions in this act'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "act_filter": {
                            "type": "string",
                            "description": "Optional: filter to a specific act name"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of definition sections to retrieve (default 5)",
                            "default": 5
                        }
                    }
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

    elif tool_name == "list_all_acts_tool":
        sort_by = arguments.get('sort_by', 'name')
        limit = arguments.get('limit', 100)

        documents = metadata_db.get_all_documents(sort_by=sort_by, limit=limit)

        return {
            'success': True,
            'tool': tool_name,
            'acts': documents,
            'count': len(documents),
            'sort_by': sort_by
        }

    elif tool_name == "search_acts_by_title_tool":
        title_query = arguments.get('title_query', '')
        year = arguments.get('year')

        documents = metadata_db.search_by_title(title_query, year=year)

        return {
            'success': True,
            'tool': tool_name,
            'query': title_query,
            'year': year,
            'acts': documents,
            'count': len(documents)
        }

    elif tool_name == "filter_acts_by_year_tool":
        year = arguments.get('year')
        year_from = arguments.get('year_from')
        year_to = arguments.get('year_to')

        documents = metadata_db.filter_by_year(year=year, year_from=year_from, year_to=year_to)

        return {
            'success': True,
            'tool': tool_name,
            'year': year,
            'year_from': year_from,
            'year_to': year_to,
            'acts': documents,
            'count': len(documents)
        }

    elif tool_name == "get_act_metadata_tool":
        act_name_or_id = arguments.get('act_name_or_id', '')
        include_sections = arguments.get('include_sections', False)

        # Try to find by doc_id first, then by name
        document = metadata_db.get_document_metadata(act_name_or_id, include_sections=include_sections)

        if not document:
            # Try by name
            document = metadata_db.get_document_by_name(act_name_or_id)
            if document and include_sections:
                # Re-fetch with sections
                doc_id = document['doc_id']
                document = metadata_db.get_document_metadata(doc_id, include_sections=True)

        if not document:
            return {
                'success': False,
                'tool': tool_name,
                'error': f"Act not found: {act_name_or_id}"
            }

        return {
            'success': True,
            'tool': tool_name,
            'act': document
        }

    elif tool_name == "find_definitions_tool":
        act_filter = arguments.get('act_filter')
        top_k = arguments.get('top_k', 5)

        # Search for sections titled "Interpretation", "Definitions", etc.
        # Use semantic search with definition-related queries
        definition_queries = [
            "interpretation definitions meanings",
            "definitions of terms",
            "interpretation section"
        ]

        # Combine results from multiple queries
        all_results = []
        seen_ids = set()

        for query_text in definition_queries:
            query_vec = await store.embed_query(query_text)
            results = store.search(query_vec, k=top_k, filter_act=act_filter)

            # Filter for definition-like sections
            for r in results:
                chunk_id = r.get('chunk_id')
                if chunk_id in seen_ids:
                    continue

                heading = r.get('heading_path', '').lower()
                section_title = r.get('meta', {}).get('section_title', '').lower()

                # Check if it's a definition section
                if any(keyword in heading or keyword in section_title
                       for keyword in ['interpretation', 'definition', 'meaning']):
                    all_results.append(r)
                    seen_ids.add(chunk_id)

                if len(all_results) >= top_k:
                    break

            if len(all_results) >= top_k:
                break

        # Limit to top_k
        all_results = all_results[:top_k]
        enhanced_results = enhance_results_with_citations(all_results)

        return {
            'success': True,
            'tool': tool_name,
            'act_filter': act_filter,
            'results': enhanced_results,
            'count': len(enhanced_results)
        }

    else:
        logger.warning(f"Unknown tool: {tool_name}")
        return {
            'success': False,
            'error': f"Unknown tool: {tool_name}"
        }
