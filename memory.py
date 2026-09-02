import os
import hashlib
import random
import chromadb
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

CHROMA_DATA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
client = chromadb.PersistentClient(path=CHROMA_DATA_PATH)
collection = client.get_or_create_collection(
    name="sre_incident_memory",
    metadata={"hnsw:space": "cosine"}
)

ACTIVE_EMBED_MODEL = None

def get_best_embedding_model() -> str:
    global ACTIVE_EMBED_MODEL
    if ACTIVE_EMBED_MODEL:
        return ACTIVE_EMBED_MODEL

    try:
        models = [
            m.name for m in genai.list_models()
            if "embedContent" in m.supported_generation_methods
        ]
        print(f"[ChromaDB Discovery]: Available embedding models: {models}")
        for pref in ["models/text-embedding-004", "models/embedding-001"]:
            if pref in models:
                ACTIVE_EMBED_MODEL = pref
                return ACTIVE_EMBED_MODEL
        if models:
            ACTIVE_EMBED_MODEL = models[0]
            return ACTIVE_EMBED_MODEL
    except Exception as e:
        print(f"[Embedding Discovery Error]: {e}")

    ACTIVE_EMBED_MODEL = "models/text-embedding-004"
    return ACTIVE_EMBED_MODEL

def generate_local_embedding(text: str, dim: int = 768) -> list[float]:
    """Crash-proof deterministic fallback vector."""
    seed = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dim)]

def get_embedding(text: str) -> list[float]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return generate_local_embedding(text)

    genai.configure(api_key=api_key)
    model_name = get_best_embedding_model()

    try:
        res = genai.embed_content(
            model=model_name,
            content=text,
            task_type="retrieval_document"
        )
        return res.get("embedding", [])
    except Exception:
        try:
            res = genai.embed_content(
                model="models/embedding-001",
                content=text
            )
            return res.get("embedding", [])
        except Exception:
            # Local fallback so server NEVER returns 500
            return generate_local_embedding(text)

def search_similar_incident(error_log: str, language: str) -> dict:
    try:
        if collection.count() == 0:
            return {"found": False, "patch": "", "rca": ""}

        query_emb = get_embedding(error_log)
        results = collection.query(
            query_embeddings=[query_emb],
            n_results=1,
            where={"language": language.lower()}
        )

        if results and results["ids"] and len(results["ids"][0]) > 0:
            distance = results["distances"][0][0]
            if distance < 0.15:
                metadata = results["metadatas"][0][0]
                print(f"[ChromaDB Cache Hit]: Found patch with distance {distance:.4f}")
                return {
                    "found": True,
                    "patch": metadata.get("verified_patch", ""),
                    "rca": metadata.get("rca", "Retrieved from persistent cache.")
                }
    except Exception as e:
        print(f"[ChromaDB Search Error]: {e}")

    return {"found": False, "patch": "", "rca": ""}

def store_incident(error_log: str, verified_patch: str, language: str, rca: str = ""):
    try:
        emb = get_embedding(error_log)
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
        print(f"[ChromaDB]: Saved fix {doc_id[:8]} to disk.")
    except Exception as e:
        print(f"[ChromaDB Store Warning]: {e}")