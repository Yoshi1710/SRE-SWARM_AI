import os
import chromadb
from chromadb.config import Settings

DB_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
client = chromadb.PersistentClient(path=DB_DIR)

# SRE Incidents collection
collection = client.get_or_create_collection(
    name="sre_incident_memory",
    metadata={"description": "Stores resolved stack traces and verified code patches"}
)

def search_similar_incident(error_log: str, language: str, top_k: int = 1) -> str:
    try:
        count = collection.count()
        if count == 0:
            return ""

        results = collection.query(
            query_texts=[error_log],
            n_results=min(top_k, count),
            where={"language": language}
        )

        if results and results["documents"] and len(results["documents"][0]) > 0:
            past_record = results["documents"][0][0]
            distance = results["distances"][0][0] if "distances" in results else 1.0
            
            if distance < 0.6:
                return past_record
    except Exception as e:
        print(f"[Vector DB Query Warning]: {e}")
    return ""

def store_incident(error_log: str, verified_patch: str, language: str):
    try:
        doc_content = f"ERROR CONTEXT:\n{error_log}\n\nVERIFIED PATCH:\n{verified_patch}"
        doc_id = f"inc_{collection.count() + 1}"
        
        collection.add(
            documents=[doc_content],
            metadatas=[{"language": language}],
            ids=[doc_id]
        )
        print(f"[Vector DB]: Saved incident {doc_id} to vector memory.")
    except Exception as e:
        print(f"[Vector DB Save Error]: {e}")