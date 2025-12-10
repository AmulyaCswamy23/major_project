import streamlit as st
import time, json, requests, re
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import chromadb

# ---------------- CONFIG -----------------
PDF_PATH = "/Users/amulyakc/Desktop/eduweb/users/aimodels/c_textbook.pdf"
OLLAMA_URL = "http://localhost:11434/api/generate"
DJANGO_URL = "http://127.0.0.1:8000/api/save_test/"
TIME_LIMIT = 10 * 60
LEVEL = "Beginner"

st.set_page_config(page_title="EduWeb AI Test", page_icon="🧠")

# ---------------- PDF UTIL -----------------
def extract_pdf_text(path):
    reader = PdfReader(path)
    return "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])

def split_sentences(text): 
    return re.split(r'(?<=[.!?]) +', text)

def make_chunks(text, size=400):
    chunks, curr = [], ""
    for sent in split_sentences(text):
        if len(curr) + len(sent) < size:
            curr += " " + sent
        else:
            chunks.append(curr.strip()); curr = sent
    if curr: chunks.append(curr.strip())
    return chunks

# ---------------- DB / Embeddings -----------------
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

chroma_client = chromadb.PersistentClient(path="rag_store")
try:
    collection = chroma_client.get_collection("mcq_bank")
except:
    collection = chroma_client.create_collection("mcq_bank")

# ---------------- STATE -----------------
if "started" not in st.session_state: st.session_state.started = False
if "questions" not in st.session_state: st.session_state.questions = []
if "answers" not in st.session_state: st.session_state.answers = {}
if "hints" not in st.session_state: st.session_state.hints = 0
if "start_time" not in st.session_state: st.session_state.start_time = None
if "submitted" not in st.session_state: st.session_state.submitted = False

# ---------------- HEADER -----------------
st.title("🧠 EduWeb AI Test — Beginner Level")

topic = st.text_input("📘 Enter Topic", "Pointers in C")
language = st.selectbox("💻 Language", ["C", "Python", "Java", "C++"])

# ---------------- START TEST -----------------
if st.button("🚀 Generate MCQs & Start Test"):

    st.info("📚 Loading content...")
    text = extract_pdf_text(PDF_PATH)
    chunks = make_chunks(text)

    # reset chroma store
    try: collection.delete(where={})
    except: pass

    collection.add(
        documents=chunks,
        embeddings=embedder.encode(chunks).tolist(),
        ids=[str(i) for i in range(len(chunks))]
    )

    query = embedder.encode([topic]).tolist()
    docs = collection.query(query_embeddings=query, n_results=5)
    context = " ".join(docs["documents"][0])

    prompt = f"""
Generate exactly 5 beginner MCQs on topic '{topic}'.

Output valid JSON array ONLY:
[
 {{"q":"Question?","options":["A","B","C","D"],"answer":"A"}}
]

Context:
{context}
"""

    resp = requests.post(OLLAMA_URL, json={"model":"phi3:mini","prompt":prompt}, stream=True)

    raw = ""
    for line in resp.iter_lines():
        if line:
            try: raw += json.loads(line.decode())["response"]
            except: pass

    # cleanup
    raw = raw.replace("```json","").replace("```","").strip()

    # regex extract JSON array
    match = re.search(r"\[\s*{(.|\n)*}\s*\]", raw)
    if not match:
        st.error("❌ Could not parse model output. Raw:")
        st.code(raw)
        st.stop()

    json_text = match.group(0)
    json_text = re.sub(r",\s*]", "]", json_text)  # remove trailing comma

    st.session_state.questions = json.loads(json_text)

    st.session_state.start_time = time.time()
    st.session_state.started = True
    st.rerun()

# ---------------- TEST MODE -----------------
if st.session_state.started and not st.session_state.submitted:

    remaining = TIME_LIMIT - int(time.time() - st.session_state.start_time)
    st.warning(f"⏳ Time Left: {remaining//60:02}:{remaining%60:02}")

    if remaining <= 0:
        st.session_state.submitted = True
        st.rerun()

    for i, q in enumerate(st.session_state.questions):
        st.subheader(f"Q{i+1}: {q['q']}")
        selection = st.radio("", q["options"], key=f"q{i}")
        st.session_state.answers[i] = selection

        if st.button(f"💡 Hint Q{i+1}", key=f"h{i}"):
            st.session_state.hints += 1
            hint = requests.post(
                OLLAMA_URL,
                json={"model":"phi3:mini","prompt":f"Give short hint: {q['q']}"}
            ).json().get("response","")
            st.info(f"Hint: {hint}")

    if st.button("✅ Submit Test"):
        st.session_state.submitted = True
        st.rerun()

# ---------------- RESULTS -----------------
if st.session_state.submitted:
    correct = sum(
        1 for i, q in enumerate(st.session_state.questions)
        if st.session_state.answers.get(i) == q["answer"]
    )

    total = len(st.session_state.questions)
    score = round((correct/total)*100)

    st.success(f"🏆 Score: {score}% ({correct}/{total}) | 💡 Hints: {st.session_state.hints}")

    payload = {
        "username": "demo-user",
        "language": language,
        "difficulty": LEVEL,
        "score": score,
        "hints_used": st.session_state.hints,
        "time_taken": int(time.time() - st.session_state.start_time)
    }

    try:
        requests.post(DJANGO_URL, json=payload)
        st.info("✅ Saved to Django database")
    except:
        st.warning("⚠️ Backend offline, not saved")

    st.balloons()
    st.write("Refresh to restart test.")