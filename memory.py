import os
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Google Gemini Embedding Function (Zero Local RAM consumption)
class GeminiEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return [[0.0] * 768 for _ in input]
        
        genai.configure(api_key=api_key)
        embeddings = []
        for text in input:
            try:
                res = genai.embed_content(
                    model="models/text-embedding-004",
                    content=text,
                    task_type="retrieval_document"
                )
                embeddings.append(res['embedding'])
            except Exception as e:
                print(f"[Embedding Error]: {e}")
                embeddings.append([0.0] * 768)
        return embeddings

# Initialize In-Memory ChromaDB Client with Gemini Embeddings
embedding_fn = GeminiEmbeddingFunction()
client = chromadb.Client()

collection = client.get_or_create_collection(
    name="sre_incident_memory",
    embedding_function=embedding_fn
)

def search_similar_incident(error_log: str, language: str, top_k: int = 1) -> str:
    """Error log ke semantic meaning ke base par past verified fix dhoondhta hai."""
    try:
        if collection.count() == 0:
            return ""

        results = collection.query(
            query_texts=[error_log],
            n_results=top_k,
            where={"language": language}
        )

        if results and results["documents"] and len(results["documents"][0]) > 0:
            return results["documents"][0][0]
    except Exception as e:
        print(f"[Vector DB Query Safe Fallback]: {e}")
    return ""

def store_incident(error_log: str, verified_patch: str, language: str):
    """Naye pass huye code fix ko Vector DB mein save karta hai."""
    try:
        doc_content = f"ERROR CONTEXT:\n{error_log}\n\nVERIFIED PATCH:\n{verified_patch}"
        doc_id = f"inc_{collection.count() + 1}"
        
        collection.add(
            documents=[doc_content],
            metadatas=[{"language": language}],
            ids=[doc_id]
        )
        print(f"[Vector DB]: Successfully saved {doc_id} with Gemini Embeddings.")
    except Exception as e:
        print(f"[Vector DB Save Safe Fallback]: {e}")