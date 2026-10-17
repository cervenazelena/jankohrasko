"""Jednorazové naindexovanie dokumentov do RAG indexu (bez bežiaceho servera).

Použitie:
    python index_pdfs.py "$RAG_DOCS/*.pdf"
    python index_pdfs.py subor1.pdf subor2.txt

Reuse funkcií z rag_service.py. Index sa uloží do RAG_INDEX_DIR (default ./rag_index).
Na TUKE beží embedder na CPU (RAG_DEVICE=cpu) — pre jednorazové indexovanie stačí;
pri veľkom korpuse zváž RAG_DEVICE=cuda na dočasnom GPU jobe.
"""
import sys
import rag_service as rag

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Použitie: python index_pdfs.py <cesta/glob> [...]")
        sys.exit(1)
    rag._load_index()
    res = rag.index_paths(sys.argv[1:])
    print("=== HOTOVO ===")
    print(f"Naindexovaných chunkov: {res['indexed_chunks']}, index spolu: {res['total']}")
    # rýchly self-test
    if res["total"] > 0:
        print("\n--- self-test dotazu ---")
        for r in rag.search("o čom je tento text", k=3):
            print(f"  [{r['score']:.2f}] {r['source']} #{r['chunk_id']}: {r['text'][:100]}")
