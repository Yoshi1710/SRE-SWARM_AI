import os
import chromadb
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Persistent disk storage - server restart par bhi data save rahega
CHROMA_DATA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
collection = client.get_or_create_collection(
    name="sre_incident_memory",
    metadata={"hnsw:space": "cosine"}
)

def get_embedding(text: str) -> list[float]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    
    genai.configure(api_key=api_key)
    
    # 1. Primary embedding model
    try:
        res = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_document"
        )
        return res.get("embedding", [])
    except Exception:
        pass

    # 2. Secondary fallback model agar primary 404 de
    try:
        res = genai.embed_content(
            model="models/embedding-001",
            content=text
        )
        return res.get("embedding", [])
    except Exception as e:
        print(f"[Embedding Error]: {e}")
        return []

def search_similar_incident(error_log: str, language: str) -> dict:
    """
    ChromaDB se similar incident dhoondhta hai.
    Agar similarity score high hai, toh verified patch return karega.
    """
    try:
        count = collection.count()
        if count == 0:
            return {"found": False, "patch": "", "rca": ""}

        query_emb = get_embedding(error_log)
        if not query_emb:
            return {"found": False, "patch": "", "rca": ""}

        results = collection.query(
            query_embeddings=[query_emb],
            n_results=1,
            where={"language": language.lower()}
        )

        if results and results["ids"] and len(results["ids"][0]) > 0:
            distance = results["distances"][0][0]
            # Cosine distance < 0.15 ka matlab 85%+ semantic similarity
            if distance < 0.15:
                metadata = results["metadatas"][0][0]
                print(f"[ChromaDB Cache Hit]: Found instant patch with distance {distance:.4f}")
                return {
                    "found": True,
                    "patch": metadata.get("verified_patch", ""),
                    "rca": metadata.get("rca", "Retrieved directly from ChromaDB verified cache.")
                }
    except Exception as e:
        print(f"[ChromaDB Query Error]: {e}")

    return {"found": False, "patch": "", "rca": ""}

def store_incident(error_log: str, verified_patch: str, language: str, rca: str = ""):
    """ChromaDB disk storage mein verified fix ko permanently save karta hai."""
    try:
        emb = get_embedding(error_log)
        if not emb:
            return

        import hashlib
        doc_id = hashlib.md5(f"{language}_{error_log}".encode()).hexdigest()

        collection.upsert(
            ids=[doc_id],
            embeddings=[emb],
            documents=[error_log],
            metadatas=[{
                "language": language.lower(),
                "verified_patch": verified_patch,
                "rca": rca
            }]
        )
        print(f"[ChromaDB]: Successfully stored fix for ID {doc_id[:8]} to disk.")
    except Exception as e:
        print(f"[ChromaDB Store Error]: {e}")