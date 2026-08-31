#!/usr/bin/env python3
"""
End-to-End Search Pipeline Test

Simulates the complete search flow:
1. PDF text extraction and normalization
2. Indexing (tokenization)
3. Query normalization
4. Matching and ranking
5. Result filtering
"""
import json
from pdf_processor import (
    normalize_search_query,
    _tokenize_text,
    _token_sliding_window_match,
    _calculate_match_quality,
    text_matches_query,
)

# Simulate PDF pages in database
SIMULATED_PDF_PAGES = [
    {
        "id": 1,
        "pdf_name": "hymn_001.pdf",
        "page_number": 1,
        "text": "Quando salirò su nel ciel Signor aprirai per me bianca porta",
        "tags": ["chiesa", "pomigliano"]
    },
    {
        "id": 2,
        "pdf_name": "hymn_002.pdf",
        "page_number": 1,
        "text": "Quando tempesta arriverà il cielo sarà scuro",
        "tags": ["chiesa"]
    },
    {
        "id": 3,
        "pdf_name": "hymn_003.pdf",
        "page_number": 1,
        "text": "Quando son giù l'anima mia è stanca e priva di speranza",
        "tags": ["meditazione"]
    },
    {
        "id": 4,
        "pdf_name": "hymn_004.pdf",
        "page_number": 1,
        "text": "Quando per prima volta vidi la luce",
        "tags": ["chiesa"]
    },
]

def simulate_search(query: str, tag_filter: str = None):
    """Simulate the complete search pipeline"""
    print("\n" + "=" * 80)
    print(f"SIMULATED SEARCH: '{query}'")
    if tag_filter:
        print(f"TAG FILTER: {tag_filter}")
    print("=" * 80)
    
    # Step 1: Normalize query
    normalized_query = normalize_search_query(query)
    print(f"\n1. Query normalization:")
    print(f"   Original: '{query}'")
    print(f"   Normalized: '{normalized_query}'")
    
    # Step 2: Tokenize query
    query_tokens = _tokenize_text(normalized_query)
    print(f"\n2. Query tokenization:")
    print(f"   Tokens: {query_tokens}")
    print(f"   Token count: {len(query_tokens)}")
    
    # Step 3: Search through PDF pages
    print(f"\n3. Searching {len(SIMULATED_PDF_PAGES)} PDF pages...")
    
    matches = []
    for page in SIMULATED_PDF_PAGES:
        # Apply tag filter if provided
        if tag_filter and tag_filter not in page["tags"]:
            continue
        
        # Normalize page text
        normalized_text = normalize_search_query(page["text"])
        page_tokens = _tokenize_text(normalized_text)
        
        # Try matching
        match_found = _token_sliding_window_match(query_tokens, page_tokens)
        
        if match_found:
            # Calculate quality score
            quality = _calculate_match_quality(normalized_text, normalized_query)
            score = int(quality * 100)
            
            matches.append({
                "pdf_name": page["pdf_name"],
                "page": page["page_number"],
                "text": page["text"],
                "quality": quality,
                "score": score,
                "normalized_text": normalized_text,
                "tokens": page_tokens,
            })
    
    # Step 4: Sort by score
    matches.sort(key=lambda x: (-x["score"], x["pdf_name"]))
    
    print(f"\n4. Results: {len(matches)} matches found")
    
    if matches:
        for i, match in enumerate(matches, 1):
            print(f"\n   [{i}] {match['pdf_name']} (page {match['page']})")
            print(f"       Score: {match['score']} (quality: {match['quality']:.2f})")
            print(f"       Text: {match['text'][:60]}...")
    else:
        print(f"\n   [NO RESULTS]")
    
    return matches

def test_degradation():
    """Test query degradation invariant"""
    print("\n\n" + "#" * 80)
    print("DEGRADATION TEST: Longer queries must not eliminate valid results")
    print("#" * 80)
    
    queries = [
        "quando",
        "quando saliro",
        "quando saliro su",
        "quando saliro su nel",
        "quando saliro su nel ciel",
        "quando saliro su nel ciel signor",
    ]
    
    all_results = {}
    
    for query in queries:
        results = simulate_search(query)
        all_results[query] = [r["pdf_name"] for r in results]
    
    # Verify invariant
    print("\n\n" + "=" * 80)
    print("INVARIANT VERIFICATION")
    print("=" * 80)
    
    violations = 0
    for i in range(len(queries) - 1):
        short_query = queries[i]
        long_query = queries[i + 1]
        
        short_results = set(all_results[short_query])
        long_results = set(all_results[long_query])
        
        # Long results must be subset of short results
        is_subset = long_results.issubset(short_results)
        
        if short_results and not long_results:
            print(f"\n[FAIL] '{short_query}' finds results, '{long_query}' finds NONE")
            print(f"       Short results: {short_results}")
            print(f"       Long results: {long_results}")
            violations += 1
        elif is_subset:
            print(f"[OK]   '{short_query}' -> {len(short_results)} results")
            print(f"       '{long_query}' -> {len(long_results)} results (subset: OK)")
        else:
            print(f"[WARN] '{long_query}' finds results not in '{short_query}'")
            print(f"       Short: {short_results}")
            print(f"       Long: {long_results}")
            print(f"       Extra in long: {long_results - short_results}")
    
    print("\n" + "=" * 80)
    if violations == 0:
        print("INVARIANT CHECK PASSED")
    else:
        print(f"INVARIANT CHECK FAILED: {violations} violation(s)")
    print("=" * 80)

def test_normalization_details():
    """Test normalization of specific text"""
    print("\n\n" + "#" * 80)
    print("NORMALIZATION DETAILS TEST")
    print("#" * 80)
    
    test_texts = [
        "Quando salirò su nel ciel Signor",
        "quando saliro' su nel ciel signor",
        "l'incertezza è nel cuor",
        "l incertezza e nel cuor",
        "l' incertezza e nel cuor",
    ]
    
    for text in test_texts:
        print(f"\nOriginal: '{text}'")
        normalized = normalize_search_query(text)
        print(f"Normalized: '{normalized}'")
        tokens = _tokenize_text(normalized)
        print(f"Tokens: {tokens}")

if __name__ == "__main__":
    test_normalization_details()
    test_degradation()
