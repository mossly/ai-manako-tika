"""Subsection-based chunking for legal documents with context preservation."""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import re
from loguru import logger


def find_page_number(text_position: int, page_map: Dict[int, Dict[str, int]]) -> Optional[int]:
    """Find which page a text position belongs to.

    Args:
        text_position: Character position in the full text
        page_map: Dict mapping page numbers to {'start': int, 'end': int}

    Returns:
        Page number (1-indexed) or None if not found
    """
    for page_num, positions in page_map.items():
        if positions['start'] <= text_position <= positions['end']:
            return page_num
    # If not found, return the closest page
    if page_map:
        return max(page_map.keys())
    return None


@dataclass
class LegislationElement:
    """Represents a structural element in legislation."""
    type: str  # 'part', 'section', 'subsection', 'text'
    number: Optional[str]  # '5', '2', 'a', etc.
    title: Optional[str]  # Section title
    text: List[str]  # Lines of text
    line_start: int  # Starting line number
    line_end: int  # Ending line number
    char_start: int  # Starting character position
    char_end: int  # Ending character position
    parent_section: Optional[str] = None  # Section number for subsections


def parse_legislation_structure(markdown_text: str) -> List[LegislationElement]:
    """Parse legislation markdown into structural elements.

    First pass: identify all parts, sections, and subsections.

    Args:
        markdown_text: Legislation text in markdown format

    Returns:
        List of LegislationElement objects in document order
    """
    lines = markdown_text.split('\n')
    elements = []

    # Regex patterns for Cook Islands legislation format
    # Parts: "PART I" or "Part 1" etc.
    part_pattern = re.compile(r'^(PART\s+[IVX\d]+|Part\s+[IVX\d]+)', re.IGNORECASE)
    # Sections: "1 Title", "2 Commencement", "13 Powers of arbitral tribunal"
    # Format: number followed by space and title
    # Must be at line start, number 1-3 digits optionally followed by A-Z, then space and capital letter
    section_pattern = re.compile(r'^(\d{1,3}[A-Z]?)\s+([A-Z].*?)$', re.IGNORECASE)
    # Subsections: "(1) text", "(a) text", "(i) text"
    subsection_pattern = re.compile(r'^\(([0-9]+|[a-z]+|[ivx]+)\)\s+(.*)', re.IGNORECASE)

    current_section = None
    current_element = None
    char_pos = 0

    for line_num, line in enumerate(lines):
        # Check for Part
        part_match = part_pattern.match(line)
        if part_match:
            if current_element:
                current_element.line_end = line_num - 1
                current_element.char_end = char_pos
                elements.append(current_element)

            part_text = line.strip().lstrip('#').strip()
            current_element = LegislationElement(
                type='part',
                number=None,
                title=part_text,
                text=[line],
                line_start=line_num,
                line_end=line_num,
                char_start=char_pos,
                char_end=char_pos + len(line)
            )
            char_pos += len(line) + 1
            continue

        # Check for Section
        section_match = section_pattern.match(line)
        if section_match:
            if current_element:
                current_element.line_end = line_num - 1
                current_element.char_end = char_pos
                elements.append(current_element)

            section_num = section_match.group(1)
            section_title = section_match.group(2).strip()
            current_section = section_num

            current_element = LegislationElement(
                type='section',
                number=section_num,
                title=section_title,
                text=[line],
                line_start=line_num,
                line_end=line_num,
                char_start=char_pos,
                char_end=char_pos + len(line)
            )
            char_pos += len(line) + 1
            continue

        # Check for Subsection
        subsection_match = subsection_pattern.match(line)
        if subsection_match:
            if current_element:
                current_element.line_end = line_num - 1
                current_element.char_end = char_pos
                elements.append(current_element)

            subsection_num = subsection_match.group(1)
            current_element = LegislationElement(
                type='subsection',
                number=subsection_num,
                title=None,
                text=[line],
                line_start=line_num,
                line_end=line_num,
                char_start=char_pos,
                char_end=char_pos + len(line),
                parent_section=current_section
            )
            char_pos += len(line) + 1
            continue

        # Regular text line - append to current element
        if current_element:
            current_element.text.append(line)
            current_element.line_end = line_num
            current_element.char_end = char_pos + len(line)
        else:
            # Unstructured text at the beginning (preamble, etc.)
            current_element = LegislationElement(
                type='text',
                number=None,
                title=None,
                text=[line],
                line_start=line_num,
                line_end=line_num,
                char_start=char_pos,
                char_end=char_pos + len(line)
            )

        char_pos += len(line) + 1

    # Don't forget the last element
    if current_element:
        elements.append(current_element)

    logger.info(f"Parsed {len(elements)} structural elements")
    return elements


def create_subsection_chunks(
    elements: List[LegislationElement],
    doc_id: str,
    act_name: str,
    page_map: Dict[int, Dict[str, int]],
    metadata: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Create chunks from parsed elements with subsection boundaries and context.

    Each subsection becomes a chunk with:
    - Section heading
    - Previous subsection heading (if exists)
    - Current subsection text
    - Next subsection heading (if exists)

    Args:
        elements: Parsed legislation elements
        doc_id: Document identifier
        act_name: Act name
        page_map: Page number mapping
        metadata: Additional metadata

    Returns:
        List of chunk dictionaries
    """
    chunks = []
    chunk_counter = 0

    # Group elements by section
    i = 0
    while i < len(elements):
        element = elements[i]

        # Handle Parts - create a single chunk
        if element.type == 'part':
            text = '\n'.join(element.text).strip()
            if len(text) >= 20:
                page_num = find_page_number(element.char_start + len(text) // 2, page_map)
                chunks.append({
                    'id': f"{doc_id}-part-{chunk_counter}",
                    'heading_path': f"{act_name} > {element.title}",
                    'text': text,
                    'meta': {
                        'doc_id': doc_id,
                        'act_name': act_name,
                        'element_type': 'part',
                        'part_title': element.title,
                        'page_number': page_num,
                        'chunk_index': chunk_counter,
                        **metadata
                    }
                })
                chunk_counter += 1
            i += 1
            continue

        # Handle Sections with subsections
        if element.type == 'section':
            section_elem = element
            section_num = section_elem.number
            section_title = section_elem.title or ""
            section_heading = f"Section {section_num}" + (f": {section_title}" if section_title else "")
            section_id = f"{doc_id}-section-{section_num.replace('.', '-')}"

            # Collect all subsections for this section
            subsections = []
            j = i + 1
            while j < len(elements) and elements[j].type == 'subsection' and elements[j].parent_section == section_num:
                subsections.append(elements[j])
                j += 1

            # If no subsections, create a single chunk for the section
            if not subsections:
                text = '\n'.join(section_elem.text).strip()
                if len(text) >= 20:
                    page_num = find_page_number(section_elem.char_start + len(text) // 2, page_map)

                    # Extract first few words for text fragment
                    first_line = text.split('\n')[0][:50]

                    chunks.append({
                        'id': section_id,
                        'heading_path': f"{act_name} > {section_heading}",
                        'text': text,
                        'meta': {
                            'doc_id': doc_id,
                            'act_name': act_name,
                            'element_type': 'section',
                            'section_number': section_num,
                            'section_title': section_title,
                            'section_id': section_id,
                            'page_number': page_num,
                            'text_fragment': first_line,
                            'chunk_index': chunk_counter,
                            **metadata
                        }
                    })
                    chunk_counter += 1
                i += 1
                continue

            # Create chunks for each subsection with context
            for sub_idx, subsection in enumerate(subsections):
                # Build chunk text with context
                chunk_text_parts = []

                # 1. Section heading
                chunk_text_parts.append(f"## {section_heading}\n")

                # 2. Previous subsection heading (if exists)
                if sub_idx > 0:
                    prev_subsection = subsections[sub_idx - 1]
                    chunk_text_parts.append(f"*Previous: ({prev_subsection.number})*\n")

                # 3. Current subsection text
                chunk_text_parts.append('\n'.join(subsection.text))

                # 4. Next subsection heading (if exists)
                if sub_idx < len(subsections) - 1:
                    next_subsection = subsections[sub_idx + 1]
                    chunk_text_parts.append(f"\n*Next: ({next_subsection.number})*")

                chunk_text = '\n'.join(chunk_text_parts).strip()

                if len(chunk_text) >= 20:
                    page_num = find_page_number(subsection.char_start + len('\n'.join(subsection.text)) // 2, page_map)

                    # Extract text fragment from subsection start
                    subsection_first_line = '\n'.join(subsection.text).strip().split('\n')[0][:50]

                    subsection_id = f"{section_id}-subsection-{subsection.number}"

                    chunks.append({
                        'id': subsection_id,
                        'heading_path': f"{act_name} > {section_heading} > ({subsection.number})",
                        'text': chunk_text,
                        'meta': {
                            'doc_id': doc_id,
                            'act_name': act_name,
                            'element_type': 'subsection',
                            'section_number': section_num,
                            'section_title': section_title,
                            'subsection_number': subsection.number,
                            'section_id': section_id,
                            'subsection_id': subsection_id,
                            'has_prev_subsection': sub_idx > 0,
                            'has_next_subsection': sub_idx < len(subsections) - 1,
                            'page_number': page_num,
                            'text_fragment': subsection_first_line,
                            'chunk_index': chunk_counter,
                            **metadata
                        }
                    })
                    chunk_counter += 1

            # Move past this section and its subsections
            i = j
            continue

        # Handle standalone text elements
        if element.type == 'text':
            text = '\n'.join(element.text).strip()
            if len(text) >= 20:
                page_num = find_page_number(element.char_start + len(text) // 2, page_map)
                chunks.append({
                    'id': f"{doc_id}-text-{chunk_counter}",
                    'heading_path': act_name,
                    'text': text,
                    'meta': {
                        'doc_id': doc_id,
                        'act_name': act_name,
                        'element_type': 'text',
                        'page_number': page_num,
                        'chunk_index': chunk_counter,
                        **metadata
                    }
                })
                chunk_counter += 1
            i += 1
            continue

        i += 1

    return chunks


def from_legislation_markdown(
    doc_id: str,
    act_name: str,
    markdown_text: str,
    page_map: Optional[Dict[int, Dict[str, int]]] = None,
    metadata: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """Chunk legislation markdown with subsection-based boundaries and context.

    Two-pass algorithm:
    1. Parse document structure (parts, sections, subsections)
    2. Create chunks with subsection boundaries and context windows

    Args:
        doc_id: Unique document identifier (e.g., 'banking_act_1996')
        act_name: Human-readable act name (e.g., 'Banking Act 1996')
        markdown_text: Legislation text in markdown format
        page_map: Optional mapping of page numbers to character positions
        metadata: Optional metadata (file_hash, effective_date, etc.)

    Returns:
        List of chunk dictionaries with id, heading_path, text, and meta
    """
    if metadata is None:
        metadata = {}
    if page_map is None:
        page_map = {}

    # Pass 1: Parse structure
    elements = parse_legislation_structure(markdown_text)

    # Pass 2: Create chunks with context
    chunks = create_subsection_chunks(elements, doc_id, act_name, page_map, metadata)

    logger.info(f"Chunked {act_name}: {len(chunks)} chunks created from {len(elements)} elements")
    return chunks


def from_plaintext(
    doc_id: str,
    act_name: str,
    text: str,
    page_map: Optional[Dict[int, Dict[str, int]]] = None,
    metadata: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """Fallback: chunk plaintext by paragraphs when structure detection fails.

    Args:
        doc_id: Unique document identifier
        act_name: Human-readable act name
        text: Plain text content
        page_map: Optional mapping of page numbers to character positions
        metadata: Optional metadata

    Returns:
        List of chunk dictionaries
    """
    if metadata is None:
        metadata = {}
    if page_map is None:
        page_map = {}

    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    current_position = 0

    for i, p in enumerate(paras):
        if len(p) < 20:  # Skip very short paragraphs
            current_position += len(p) + 2  # +2 for \n\n
            continue

        # Find page number
        para_middle_pos = current_position + len(p) // 2
        page_number = find_page_number(para_middle_pos, page_map) if page_map else None

        # Extract text fragment
        first_words = p[:50]

        chunk_meta = {
            'doc_id': doc_id,
            'act_name': act_name,
            'element_type': 'paragraph',
            'paragraph_index': i,
            'text_fragment': first_words,
            **metadata
        }

        if page_number is not None:
            chunk_meta['page_number'] = page_number

        chunks.append({
            'id': f"{doc_id}-para-{i}",
            'heading_path': act_name,
            'text': p,
            'meta': chunk_meta
        })

        current_position += len(p) + 2  # +2 for \n\n

    logger.info(f"Chunked {act_name} (plaintext fallback): {len(chunks)} chunks created")
    return chunks
