"""Utility to extract year from act names."""
import re
from typing import Optional
from loguru import logger


def extract_year_from_act_name(act_name: str) -> Optional[int]:
    """Extract year from act name using regex patterns.

    Handles various formats:
    - "Banking Act 1996"
    - "Banking Act (Amendment) 2005"
    - "Electoral Act 2004-05"
    - "Cook Islands Act 1915"
    - "Criminal Procedure (Reform and Modernisation) Act 2023"

    Args:
        act_name: The act name to parse

    Returns:
        Year as integer, or None if not found
    """
    if not act_name:
        return None

    # Pattern 1: Year at end (most common)
    # Matches: "Banking Act 1996", "Banking Act (Amendment) 2005"
    match = re.search(r'\b(19|20)\d{2}\b(?!-)', act_name)
    if match:
        year = int(match.group(0))
        logger.debug(f"Extracted year {year} from '{act_name}'")
        return year

    # Pattern 2: Year range (take first year)
    # Matches: "Electoral Act 2004-05" -> 2004
    match = re.search(r'\b(19|20)(\d{2})-\d{2}\b', act_name)
    if match:
        year = int(match.group(1) + match.group(2))
        logger.debug(f"Extracted year {year} from year range in '{act_name}'")
        return year

    # Pattern 3: Year in parentheses
    # Matches: "Act (2005)", "Act(1996)"
    match = re.search(r'\((\d{4})\)', act_name)
    if match:
        year_str = match.group(1)
        if year_str.startswith('19') or year_str.startswith('20'):
            year = int(year_str)
            logger.debug(f"Extracted year {year} from parentheses in '{act_name}'")
            return year

    logger.warning(f"Could not extract year from act name: '{act_name}'")
    return None
