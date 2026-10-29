import hashlib
import os

import chromadb
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

CHROMA_DATA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
collection = client.get_or_create_collection(name="sre_incident_memory", metadata={"hnsw:space": "cosine"})
ACTIVE_EMBED_MODEL = None


def get_embedding(text: str) -> list[float] | None:
    """Text (Error Logs) ko numbers (Vectors) mein convert karta hai Gemini ka use karke."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not text.strip():
        return None
        
    try:
        genai.configure(api_key=api_key)
        global ACTIVE_EMBED_MODEL
        if ACTIVE_EMBED_MODEL is None:
            models = [m.name for m in genai.list_models() if "embedContent" in m.supported_generation_methods]
            preferences = ["models/text-embedding-004", "models/embedding-001"]
            ACTIVE_EMBED_MODEL = next((m for m in preferences if m in models), models[0] if models else None)
            
        if not ACTIVE_EMBED_MODEL:
            return None
            
        result = genai.embed_content(model=ACTIVE_EMBED_MODEL, content=text, task_type="retrieval_query")
        embedding = result.get("embedding")
        return embedding if isinstance(embedding, list) and embedding else None
        
    except Exception as exc:
        print(f"[Warning] Embedding unavailable; semantic memory skipped. Error: {exc}")
        return None


def search_similar_incident(error_log: str, language: str) -> dict:
    try:
        if collection.count() == 0:
            return {"found": False, "patch": "", "rca": ""}
            
        vector = get_embedding(error_log)
        if vector is None:
            return {"found": False, "patch": "", "rca": ""}
            
        results = collection.query(query_embeddings=[vector], n_results=1, where={"language": language.lower()})
        
        if results and results.get("ids") and results["ids"][0]:
            distance = results["distances"][0][0]
            if distance < 0.15:
                meta = results["metadatas"][0][0]
                print(f"[Memory] Found a similar past incident for {language}!")
                return {"found": True, "patch": meta.get("verified_patch", ""), "rca": meta.get("rca", "")}
                
    except Exception as exc:
        print(f"[Memory Search Warning] {exc}")
        
    return {"found": False, "patch": "", "rca": ""}


def store_incident(error_log: str, verified_patch: str, language: str, rca: str = "") -> None:
    try:
        vector = get_embedding(error_log)
        if vector is None:
            print("[Memory] Skipped storing incident because Gemini Embeddings are unavailable.")
            return
            
        incident_id = hashlib.sha256(f"{language.lower()}\0{error_log}".encode("utf-8")).hexdigest()
        
        collection.upsert(
            ids=[incident_id], 
            embeddings=[vector], 
            documents=[error_log], 
            metadatas=[{"language": language.lower(), "verified_patch": verified_patch, "rca": rca}]
        )
        print(f"[Memory] Success! Stored fixed {language} bug in ChromaDB for future reference.")
        
    except Exception as exc:
        print(f"[Memory Store Warning] {exc}")