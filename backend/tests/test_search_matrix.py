#!/usr/bin/env python3
"""
Test Matrix for Search Query Degradation

Tests query progression to verify:
1. Longer queries return subset of shorter query results
2. All normalizations work correctly
3. Ranking doesn't reject valid results for longer queries
"""
import json
import sys
import logging
from typing import Dict, List, Any
from pdf_processor import (
    normalize_search_query,
    _tokenize_text,
    _token_sliding_window_match,
    _calculate_match_quality,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Test queries - progressive
QUERIES = [
    "quando",
    "quando saliro",
    "quando saliro su",
    "quando saliro su nel",
    "quando saliro su nel ciel",
    "quando saliro su nel ciel signor",
]

# Target text from PDF (with accent - original)
TARGET_TEXT_ORIGINAL = "Quando salirò su nel ciel Signor"

def test_search_matrix():
    """Test all query progressions"""
    print("=" * 80)
    print("SEARCH QUERY DEGRADATION TEST MATRIX")
    print("=" * 80)
    print(f"Target text (original): {TARGET_TEXT_ORIGINAL}")
    print()

    # Normalize target once
    normalized_target = normalize_search_query(TARGET_TEXT_ORIGINAL)
    target_tokens = _tokenize_text(normalized_target)
    print(f"Target normalized: {normalized_target}")
    print(f"Target tokens: {target_tokens}")
    print()

    results_per_query = {}
    
    for query in QUERIES:
        print(f"\n{'-' * 80}")
        print(f"QUERY: {query}")
        print(f"{'-' * 80}")
        
        # Step 1: Normalize query
        normalized_query = normalize_search_query(query)
        print(f"normalized_query: {normalized_query}")
        
        # Step 2: Tokenize query
        query_tokens = _tokenize_text(normalized_query)
        print(f"query_tokens: {query_tokens}")
        
        # Step 3: Try matching
        print(f"\nMatching against: {target_tokens}")
        
        # Main matching function - uses all 3 strategies internally
        match_found = _token_sliding_window_match(query_tokens, target_tokens)
        
        if match_found:
            print(f"[MATCH FOUND]")
            # Calculate quality - pass normalized text strings, not tokens
            quality = _calculate_match_quality(normalized_target, normalized_query)
            final_score = int(quality * 100)
            print(f"Quality Score: {quality}")
            print(f"Final Score: {final_score}")
        else:
            print(f"[NO MATCH - would fall back to fuzzy]")
            quality = 0.0
            final_score = 0
        
        results_per_query[query] = {
            "normalized": normalized_query,
            "query_tokens": query_tokens,
            "match_found": match_found,
            "quality": quality,
            "final_score": final_score,
        }

    # Verify invariant: longer query result set should be subset of shorter
    print("\n" + "=" * 80)
    print("INVARIANT CHECK: results(longer) MUST BE SUBSET OF results(shorter)")
    print("=" * 80)
    
    violations = 0
    for i in range(len(QUERIES) - 1):
        short_query = QUERIES[i]
        long_query = QUERIES[i + 1]
        
        short_matches = results_per_query[short_query]["match_found"]
        long_matches = results_per_query[long_query]["match_found"]
        
        if short_matches and not long_matches:
            print(f"[FAIL] '{short_query}' -> MATCH, '{long_query}' -> NO MATCH")
            print(f"       RANKING BUG DETECTED!")
            violations += 1
        elif short_matches and long_matches:
            print(f"[OK]   Both match ('{short_query}' and '{long_query}')")
        elif not short_matches and not long_matches:
            print(f"[OK]   Neither matches")
        else:
            print(f"[OK]   Only long matches ('{long_query}')")

    print("\n" + "=" * 80)
    if violations == 0:
        print("TEST PASSED: No ranking violations detected")
    else:
        print(f"TEST FAILED: {violations} ranking violation(s) detected")
    print("=" * 80)

if __name__ == "__main__":
    test_search_matrix()
