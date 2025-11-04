from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

import json, os, re, time, requests
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import chromadb

from .models import TestResult


# -------------- AUTH VIEWS -----------------

def signup_view(request):
    from .forms import SignUpForm
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password1'])
            user.save()
            messages.success(request, "Account created! Login now.")
            return redirect('login')
        messages.error(request, "Fix form errors.")
    else:
        form = SignUpForm()
    return render(request, 'users/signup.html', {'form': form})


def login_view(request):
    if request.method == "POST":
        user = authenticate(request,
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        if user:
            login(request, user)
            return redirect('dashboard')
        messages.error(request, "Invalid credentials.")
    return render(request, 'users/login.html')


@login_required(login_url='login')
def dashboard_view(request):
    return render(request, 'index.html', {"user": request.user})


def logout_view(request):
    logout(request)
    messages.info(request, "Logged out.")
    return redirect('login')


# ---------------- STREAMLIT REDIRECT ------------------

@login_required(login_url='login')
def take_test(request):
    if request.method == "POST":
        lang = request.POST.get("language")
        level = request.POST.get("difficulty")

        username = request.user.username
        streamlit_url = f"http://localhost:8501/?user={username}&lang={lang}&level={level}"

        return redirect(streamlit_url)

    return render(request, 'users/take_test.html')


# ---------------- RAG MCQ GENERATOR API ----------------

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


def split_into_chunks(text, chunk_size=500):
    sentences = split_sentences(text)
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) < chunk_size:
            current += " " + s
        else:
            chunks.append(current.strip())
            current = s
    if current:
        chunks.append(current)
    return chunks


def generate_questions(request):
    topic = request.GET.get("topic", "Python beginner")

    prompt = f"""
You are an exam MCQ generator.

Generate exactly 5 MCQs on: {topic}

RULES:
- Strictly return valid JSON ONLY.
- No explanations, no extra text.
- Each question must have exactly 4 options.
- "answer" must be one of the options.

FORMAT STRICTLY LIKE THIS:
[
  {{
    "question": "Your question?",
    "options": ["opt1", "opt2", "opt3", "opt4"],
    "answer": "opt2"
  }}
]
"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "phi3:mini", "prompt": prompt},
            timeout=60
        )

        raw = response.text.strip()

        # --- Try direct JSON load first ---
        try:
            return JsonResponse(json.loads(raw), safe=False)
        except:
            pass

        # --- Extract JSON bracket and repair ---
        try:
            start = raw.index("[")
            end = raw.rindex("]") + 1
            cleaned = raw[start:end]

            # Fix common JSON mistakes
            cleaned = cleaned.replace("\n", "")
            cleaned = cleaned.replace(",]", "]")
            cleaned = cleaned.replace(", }", "}")
            cleaned = cleaned.replace("} ,", "},")

            return JsonResponse(json.loads(cleaned), safe=False)
        except:
            pass

        # ✅ Final fallback safety — but better messages
        fallback = [
            {
                "question": f"Fallback question: What language is used in this test?",
                "options": ["Python", "Java", "C++", "Javascript"],
                "answer": "Python"
            }
        ]
        return JsonResponse(fallback, safe=False)

    except Exception as e:
        return JsonResponse(
            [{"error": f"AI server error: {str(e)}"}],
            safe=False,
            status=500
        )

from django.http import JsonResponse
import requests
import json

def api_questions(request):
    topic = request.GET.get("topic", "python-beginner")

    prompt = f"""
    Generate 5 beginner MCQs in {topic.split('-')[0]} language.
    Each question must have 4 options and one correct answer.
    Format:
    Q: question
    A) option
    B) option
    C) option
    D) option
    Correct: A/B/C/D
    """

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "phi3:mini", "prompt": prompt},
        stream=True
    )

    text = ""
    for chunk in response.iter_lines():
        if chunk:
            try:
                data = json.loads(chunk.decode())
                if "response" in data:
                    text += data["response"]
            except:
                continue

    # Parse questions roughly
    blocks = [b for b in text.split("\n\n") if b.strip()]
    questions = []
    for b in blocks:
        lines = [l.strip() for l in b.split("\n") if l.strip()]
        if len(lines) >= 6:
            q = lines[0].replace("Q:", "").strip()
            opts = [o[3:].strip() for o in lines[1:5]]  # remove A), B) etc.
            ans = lines[-1].replace("Correct:", "").strip()
            questions.append({"question": q, "options": opts, "answer": ans})

    return JsonResponse(questions, safe=False)
# ---------------- HINT API ------------------

@csrf_exempt
def hint_api(request):
    data = json.loads(request.body)
    question = data.get("question", "")

    r = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "phi3:mini", "prompt": f"Give a 1-line hint for: {question}"}
    )
    return JsonResponse({"hint": r.text.strip()})


# ---------------- SUBMIT TEST API ------------------

@csrf_exempt
def submit_test_api(request):
    data = json.loads(request.body)

    TestResult.objects.create(
        user=User.objects.get(username=data["username"]),
        language=data["language"],
        score=data["score"],
        hints_used=data["hints_used"],
        time_elapsed=data["time"]
    )

    return JsonResponse({"status": "saved"})


# ---------------- USER INFO ------------------

@login_required(login_url='login')
def get_user_info(request):
    user = request.user
    results = TestResult.objects.filter(user=user).values()

    return JsonResponse({
        "username": user.username,
        "results": list(results)
    })