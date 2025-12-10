# users/aimodels/rag_model.py
import os, re, json, time, math, unicodedata
import numpy as np
from typing import List, Dict, Optional, Tuple
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer
import requests

# =========================================================
# CONFIG
# =========================================================
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
OLLAMA_URL = "http://localhost:11434/api/generate"

TEXTBOOKS = {
    "python": "/Users/amulyakc/Desktop/eduweb/users/aimodels/python_textbook.pdf",
    "c":      "/Users/amulyakc/Desktop/eduweb/users/aimodels/c_textbook.pdf",
    "cpp":    "/Users/amulyakc/Desktop/eduweb/users/aimodels/cpp_textbook.pdf",
    "java":   "/Users/amulyakc/Desktop/eduweb/users/aimodels/java_textbook.pdf",
}

# Loose normalization so even "C++ Beginner", "C language", etc. work
def normalize_language(language: str) -> str:
    s = (language or "").strip().lower()
    s = re.sub(r"\s+", " ", s)

    if "python" in s:
        return "python"

    # make sure javascript doesn't get caught
    if "java" in s and "script" not in s:
        return "java"

    if "c++" in s or "cpp" in s or "c plus plus" in s:
        return "cpp"

    # plain C (but not C++)
    if re.search(r"\bc language\b", s) or re.fullmatch(r"c", s):
        return "c"

    return s


# =========================================================
# UTILS
# =========================================================
def _clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def read_pdf(path: str) -> str:
    reader = PdfReader(path)
    pages = []
    for p in reader.pages:
        t = p.extract_text() or ""
        if t.strip():
            pages.append(_clean(t))
    return "\n".join(pages)


def level_chunk_params(level: str) -> Tuple[int, int]:
    level = (level or "beginner").lower()
    if level.startswith("beg"):
        return 600, 420
    if level.startswith("int"):
        return 900, 620
    return 1200, 800


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def make_chunks(text: str, chunk_size: int, stride: int) -> List[str]:
    sents = split_sentences(text)
    chunks, cur, cur_len = [], [], 0

    for s in sents:
        if cur_len + len(s) <= chunk_size:
            cur.append(s)
            cur_len += len(s) + 1
        else:
            chunks.append(" ".join(cur).strip())

            slide_len = max(1, len(cur) - (stride // 50))
            cur = cur[slide_len:]
            cur_len = sum(len(x) + 1 for x in cur)

            cur.append(s)
            cur_len += len(s) + 1

    if cur:
        chunks.append(" ".join(cur).strip())

    return [c for c in chunks if len(c) > 150]


def softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x)
    ex = np.exp(x)
    return ex / (ex.sum() + 1e-12)


# =========================================================
# INDEXER
# =========================================================
class SmartIndex:
    def __init__(self, base: str, embedder: SentenceTransformer):
        self.base = base
        self.embedder = embedder
        self.chunks: List[str] = []
        self.tfidf = None
        self.tfidf_mat = None
        self.emb_mat = None

    def build(self, chunks: List[str]):
        print(f"[RAG] Building index at base={self.base} with {len(chunks)} chunks")
        self.chunks = chunks

        self.tfidf = TfidfVectorizer(min_df=1, max_df=0.92, ngram_range=(1, 2))
        self.tfidf_mat = self.tfidf.fit_transform(chunks)

        embs = self.embedder.encode(chunks, convert_to_numpy=True, normalize_embeddings=True)
        self.emb_mat = embs.astype("float32")

        self._persist()

    def _persist(self):
        os.makedirs(os.path.dirname(self.base), exist_ok=True)
        print(f"[RAG] Persisting index files with base={self.base}")

        with open(self.base + "_chunks.txt", "w") as f:
            for c in self.chunks:
                f.write(c.replace("\n", " ") + "\n")

        np.savez_compressed(
            self.base + "_tfidf.npz",
            data=self.tfidf_mat.data,
            indices=self.tfidf_mat.indices,
            indptr=self.tfidf_mat.indptr,
            shape=self.tfidf_mat.shape,
        )

        with open(self.base + "_vocab.json", "w") as f:
            json.dump(self.tfidf.vocabulary_, f)

        np.save(self.base + "_emb.npy", self.emb_mat)

    def load(self) -> bool:
        try:
            print(f"[RAG] Trying to load index base={self.base}")
            with open(self.base + "_chunks.txt") as f:
                self.chunks = [ln.strip() for ln in f]

            tf = np.load(self.base + "_tfidf.npz")
            from scipy.sparse import csr_matrix
            self.tfidf_mat = csr_matrix(
                (tf["data"], tf["indices"], tf["indptr"]), shape=tf["shape"]
            )

            with open(self.base + "_vocab.json") as f:
                vocab = json.load(f)
            self.tfidf = TfidfVectorizer(vocabulary=vocab)

            self.emb_mat = np.load(self.base + "_emb.npy")

            print(f"[RAG] Loaded index base={self.base} (chunks={len(self.chunks)})")
            return True
        except Exception as e:
            print(f"[RAG] Failed to load index base={self.base}: {e}")
            return False

    def query(self, q: str, k: int = 6, alpha: float = 0.55):
        q_tfidf = self.tfidf.transform([q]).toarray()[0]
        sim_tfidf = self.tfidf_mat.dot(q_tfidf)

        q_emb = self.embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)[0]
        sim_emb = self.emb_mat @ q_emb

        st = softmax(sim_tfidf)
        se = softmax(sim_emb)
        blend = alpha * st + (1 - alpha) * se

        topk = np.argsort(-blend)[:k]
        return [(i, float(blend[i])) for i in topk]


# =========================================================
# PROMPT BUILDER
# =========================================================
def build_prompt(language: str, level: str, context: str, count: int):
    return f"""
Generate exactly {count} {level}-level MCQs for {language} strictly from this context:

\"\"\"{context}\"\"\"

Rules:
- Only facts from context
- No hallucination
- JSON only
- 4 options
- answer must be one of the options
"""


# =========================================================
# OLLAMA CALLER
# =========================================================
def call_ollama_json(prompt: str, model: str) -> str:
    r = requests.post(OLLAMA_URL, json={"model": model, "prompt": prompt}, stream=True)
    r.raise_for_status()

    buf = ""
    for line in r.iter_lines():
        if not line:
            continue
        try:
            buf += json.loads(line.decode()).get("response", "")
        except:
            buf += line.decode(errors="ignore")
    return buf


# =========================================================
# JSON EXTRACTOR
# =========================================================
def extract_json_array(text: str):
    cleaned = re.sub(r"```(json)?", "", text, flags=re.I).replace("```", "").strip()
    m = re.search(r"\[.*?\]", cleaned, re.DOTALL)
    if not m:
        raise ValueError("No JSON array found")
    block = m.group(0)

    block = re.sub(r",\s*}", "}", block)
    block = re.sub(r",\s*]", "]", block)

    data = json.loads(block)

    out = []
    for x in data:
        q = x.get("question")
        opts = x.get("options", [])
        ans = x.get("answer")

        if q and isinstance(opts, list) and len(opts) >= 4 and ans:
            out.append({
                "question": _clean(q),
                "options": [str(o) for o in opts[:4]],
                "answer": str(ans).strip()
            })

    return out[:5]


# =========================================================
# RAG ENGINE
# =========================================================
class SmartRAGMCQ:
    def __init__(self):
        print("[RAG] Initializing embedder", MODEL_NAME)
        self.embedder = SentenceTransformer(MODEL_NAME)

    def ensure_index(self, language: str, level: str) -> SmartIndex:
        lang_norm = normalize_language(language)
        level_norm = (level or "beginner").strip().lower().split()[0]

        print(f"[RAG] ensure_index: requested language='{language}', "
              f"normalized='{lang_norm}', level='{level}'")

        pdf_path = TEXTBOOKS.get(lang_norm)
        if not pdf_path or not os.path.exists(pdf_path):
            raise FileNotFoundError(
                f"No textbook found for language='{language}' normalized='{lang_norm}'"
            )

        base = os.path.join(os.path.dirname(pdf_path), f"{lang_norm}_{level_norm}")
        idx = SmartIndex(base, self.embedder)

        if idx.load():
            if idx.tfidf_mat is not None and idx.emb_mat is not None and len(idx.chunks) > 0:
                return idx
            print("[RAG] Incomplete index detected, rebuilding…")

        text = read_pdf(pdf_path).strip()
        if not text:
            raise ValueError(f"Empty PDF: {pdf_path}")

        chunk_size, stride = level_chunk_params(level)
        chunks = make_chunks(text, chunk_size, stride)

        if not chunks:
            raise ValueError(f"No chunks generated from PDF: {pdf_path}")

        unique = list(dict.fromkeys(chunks))
        idx.build(unique)
        return idx

    def retrieve(self, idx: SmartIndex, query: str, k: int = 6) -> str:
        hits = idx.query(query, k=k)
        return "\n\n".join([idx.chunks[i] for i, _ in hits])

    def generate_mcqs(self, language: str, level: str, n: int = 5,
                      topic_hint: Optional[str] = None,
                      model: str = "qwen2.5:3b-instruct"):

        idx = self.ensure_index(language, level)

        query = f"{language} {level}"
        if topic_hint:
            query += f" {topic_hint}"

        ctx = self.retrieve(idx, query)

        prompt = build_prompt(language, level, ctx, count=n)
        raw = call_ollama_json(prompt, model)

        try:
            return extract_json_array(raw)
        except Exception:
            repair_prompt = f"""
Fix JSON. Return only JSON array:
{raw}
"""
            fixed = call_ollama_json(repair_prompt, model)
            return extract_json_array(fixed)