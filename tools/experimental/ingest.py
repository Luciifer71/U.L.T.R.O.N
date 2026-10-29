import os
from pathlib import Path
import chromadb
from ollama import Client

# Initialize ChromaDB persistent storage and Ollama Client
ROOT = Path(__file__).resolve().parents[2]
chroma_client = chromadb.PersistentClient(path=str(ROOT / "chroma_db"))
collection = chroma_client.get_or_create_collection(name="ultron_knowledge")
ollama_client = Client()

KNOWLEDGE_DIR = str(ROOT / "knowledge_base")


def get_embedding(text: str) -> list:
    """Generates a vector embedding using Ollama nomic-embed-text."""
    response = ollama_client.embed(model="nomic-embed-text", input=text)
    return response["embeddings"][0]


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list:
    """Splits long document text into overlapping segments."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunks.append(" ".join(words[i : i + chunk_size]))
    return chunks


def ingest_files():
    if not os.path.exists(KNOWLEDGE_DIR):
        os.makedirs(KNOWLEDGE_DIR)
        print(
            f"[INGEST] Created '{KNOWLEDGE_DIR}' directory. Put your text,"
            " markdown, or code files there and re-run."
        )
        return

    doc_counter = 0
    valid_exts = (".txt", ".md", ".py", ".json", ".csv", ".log")

    for root, _, files in os.walk(KNOWLEDGE_DIR):
        for file in files:
            if file.endswith(valid_exts):
                file_path = os.path.join(root, file)
                print(f"[INGESTING]: {file_path}")

                try:
                    with open(
                        file_path, "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        content = f.read()

                    chunks = chunk_text(content)
                    for idx, chunk in enumerate(chunks):
                        if not chunk.strip():
                            continue
                        embedding = get_embedding(chunk)
                        collection.upsert(
                            documents=[chunk],
                            embeddings=[embedding],
                            metadatas=[{"source": file, "chunk_id": idx}],
                            ids=[f"doc_{doc_counter}_{idx}"],
                        )
                    doc_counter += 1
                except Exception as e:
                    print(f"[ERROR]: Failed to process {file_path}: {e}")

    print(
        f"[INGEST COMPLETE]: Indexing finished. Stored in vector database"
        f" './chroma_db'."
    )


if __name__ == "__main__":
    ingest_files()