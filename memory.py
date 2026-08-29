import os
import math
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# In-Memory Vector Store
INCIDENT_MEMORY = []

def get_embedding(text: str) -> list[float]:
    """Gemini API se text ka mathematical embedding vector nikalta hai."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    try:
        genai.configure(api_key=api_key)
        res = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_document"
        )
        return res.get("embedding", [])
    except Exception as e:
        print(f"[Embedding Warning]: {e}")
        return []

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Do error vectors ke beech ka semantic angle (similarity score) calculate karta hai."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)

def search_similar_incident(error_log: str, language: str, similarity_threshold: float = 0.70) -> str:
    """Vector memory search: Past verified incident fix retrieve karta hai."""
    try:
        query_emb = get_embedding(error_log)
        if not query_emb or len(INCIDENT_MEMORY) == 0:
            return ""
        
        best_match = None
        best_score = -1.0
        
        for item in INCIDENT_MEMORY:
            if item.get("language", "").lower() == language.lower():
                score = cosine_similarity(query_emb, item["embedding"])
                if score > best_score and score >= similarity_threshold:
                    best_score = score
                    best_match = item
                    
        if best_match:
            print(f"[Vector DB]: High similarity match found ({best_score:.2f})!")
            return f"PAST ERROR:\n{best_match['error_log']}\n\nVERIFIED FIX:\n{best_match['verified_patch']}"
    except Exception as e:
        print(f"[Vector DB Safe Fallback]: {e}")
    return ""

def store_incident(error_log: str, verified_patch: str, language: str):
    """Naye pass huye solution ko vector memory mein save karta hai."""
    try:
        emb = get_embedding(error_log)
        if not emb:
            return
        doc_id = f"inc_{len(INCIDENT_MEMORY) + 1}"
        INCIDENT_MEMORY.append({
            "id": doc_id,
            "error_log": error_log,
            "verified_patch": verified_patch,
            "language": language,
            "embedding": emb
        })
        print(f"[Vector DB]: Saved {doc_id} to semantic memory.")
    except Exception as e:
        print(f"[Vector DB Save Warning]: {e}")