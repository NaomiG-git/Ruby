from duckduckgo_search import DDGS

def search_web(query: str, max_results: int = 5):
    print(f"Searching for: {query}")
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                print(f"Found: {r['title']}")
                results.append(r)
        
        if not results:
            print("No results found.")
        else:
            print(f"Successfully found {len(results)} results.")
            
    except Exception as e:
        print(f"Error searching web: {e}")

if __name__ == "__main__":
    search_web("test search query")
