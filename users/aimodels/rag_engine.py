import re
import chromadb
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import requests
import json

# Initialize Chroma and embedder once
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
chroma_client = chromadb.Client()
try:
    collection = chroma_client.get_collection("c_textbook")
except:
    collection = chroma_client.create_collection("c_textbook")

def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    return "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])

def split_sentences(text):
    return re.split(r'(?<=[.!?]) +', text)

def split_into_chunks(text, chunk_size=500, overlap=50):
    sentences = split_sentences(text)
    chunks, current = [], ""
    for idx, s in enumerate(sentences):
        if len(current) + len(s) <= chunk_size:
            current += " " + s
        else:
            chunks.append(current.strip())
            current = " ".join(sentences[max(0, idx-2):idx]) + " " + s
    if current:
        chunks.append(current.strip())
    return chunks

def index_pdf(pdf_path):
    text = extract_text_from_pdf(pdf_path)
    chunks = split_into_chunks(text)
    embeddings = embedder.encode(chunks).tolist()
    collection.add(documents=chunks, embeddings=embeddings, ids=[str(i) for i in range(len(chunks))])
    return len(chunks)

def generate_mcqs(topic, n_results=5):
    query_emb = embedder.encode([topic]).tolist()
    results = collection.query(query_embeddings=query_emb, n_results=n_results)
    context = " ".join(results["documents"][0])

    prompt = f"""
    Generate 5 multiple-choice questions (MCQs) on the topic '{topic}' using the following text.
    Each question should have 4 distinct options and the correct answer clearly marked as 'Answer:'.

    Context:
    {context}
    """

    payload = {"model": "phi3", "prompt": prompt}
    response = requests.post("http://localhost:11434/api/generate", json=payload, stream=True)

    result_text = ""
    for chunk in response.iter_lines():
        if chunk:
            try:
                data = json.loads(chunk.decode("utf-8"))
                if "response" in data:
                    result_text += data["response"]
            except json.JSONDecodeError:
                result_text += chunk.decode("utf-8")

    return result_text.strip()