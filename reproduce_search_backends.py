from duckduckgo_search import DDGS

def search_web(query: str, backend: str = "api"):
    print(f"\nSearching for: '{query}' with backend='{backend}'")
    try:
        results = []
        with DDGS() as ddgs:
            # Try specific backend
            for r in ddgs.text(query, max_results=5, backend=backend):
                print(f"Found: {r['title']}")
                results.append(r)
        
        if not results:
            print(f"No results found with backend='{backend}'.")
        else:
            print(f"Successfully found {len(results)} results.")
            
    except Exception as e:
        print(f"Error searching web with backend='{backend}': {e}")

if __name__ == "__main__":
    Backends = ["api", "html", "lite"]
    for b in Backends:
        search_web("python release date", backend=b)
