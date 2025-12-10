# ======================================================
# ✅ IMPORTS
# ======================================================

from django.shortcuts import render, redirect, resolve_url
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Avg, Count
from django.utils import timezone
from datetime import date, timedelta
import requests, json, re
from pydantic import BaseModel, RootModel, Field, validator
from typing import List

from django.template.loader import render_to_string
from django.utils.html import escape

from .models import (
    Profile,
    TestResult,
    UserPath,
    UserBadge,
    LANG_ORDER,
    LEVELS,
)

# Optional PDF dependency (graceful fallback)
try:
    from xhtml2pdf import pisa
    HAS_PDF = True
except Exception:
    HAS_PDF = False

# RL agent import — tolerant if missing
try:
    from users.aimodels.rl_agent import compute_next_step
except Exception:
    compute_next_step = None  # fallback to rule-based if RL not available


# ======================================================
# ✅ HOME / DASHBOARD / AUTH
# ======================================================

@login_required(login_url="login")
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def home_view(request):
    return render(request, "index.html")


def login_view(request):
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user:
            login(request, user)
            return render(request, "index.html")   # go to index/home after login
        messages.error(request, "Invalid credentials.")
    return render(request, "users/login.html")


def signup_view(request):
    from .forms import SignUpForm

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password1"])
            user.save()
            messages.success(request, "Account created! Login now.")
            return redirect("login")
        messages.error(request, "Fix errors.")
    else:
        form = SignUpForm()
    return render(request, "users/signup.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required(login_url="login")
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def dashboard_view(request):
    user = request.user

    # Ensure related objects exist
    path, _ = UserPath.objects.get_or_create(user=user)
    profile, _ = Profile.objects.get_or_create(user=user)

    # Stats
    tests_total = TestResult.objects.filter(user=user).count()
    avg_score_q = TestResult.objects.filter(user=user).aggregate(avg=Avg("score"))
    avg_score = round((avg_score_q["avg"] or 0.0), 1)

    today = timezone.localdate()
    tests_today = TestResult.objects.filter(
        user=user, created_at__date=today
    ).count()

    # Badges and learned languages (with level)
    badges = UserBadge.objects.filter(user=user).order_by("-awarded_at")
    legend_badges = badges.filter(level__iexact="Legend").count()
    learned = [{"language": b.language, "level": b.level} for b in badges]

    # Does user have Legend for current language?
    has_legend_for_current = UserBadge.objects.filter(
        user=user, language=path.current_language, level__iexact="Legend"
    ).exists()

    # Recent results
    recent = TestResult.objects.filter(user=user).order_by("-created_at")[:6]

    context = {
        "current_language": path.current_language,
        "current_level": path.current_level,
        "tests_total": tests_total,
        "tests_today": tests_today,
        "avg_score": avg_score,
        "legend_badges": legend_badges,
        "learned_languages": learned,
        "recent_results": recent,
        "has_legend_for_current": has_legend_for_current,
        "profile": profile,
        "path": path,
    }

    return render(request, "users/dashboard.html", context)


# ======================================================
# ✅ TEST FLOW (CHOOSE LANGUAGE + START TEST PAGE)
# ======================================================

from .models import UserPath, UserBadge, LANG_ORDER, LEVELS  # ensure present


@login_required(login_url="login")
@require_http_methods(["GET", "POST"])
def take_test(request):
    """
    Any user can choose the language.
    - They cannot choose difficulty.
    - Whenever they switch language, it starts at Beginner.
    - Still respects 1-test-per-day lock.
    """
    path, _ = UserPath.objects.get_or_create(user=request.user)

    # 1-test-per-day lock
    today = timezone.localdate()
    if path.last_test_date == today:
        return render(
            request,
            "users/test_locked.html",
            {
                "current_language": path.current_language,
                "current_level": path.current_level,
            },
        )

    # All languages user can choose from (including Python)
    available_langs = list(LANG_ORDER)  # e.g. ["python", "java", "cpp"]

    if request.method == "POST":
        chosen_lang = (request.POST.get("language") or "").lower()

        if chosen_lang not in LANG_ORDER:
            messages.error(request, "Invalid language selected.")
            return redirect("take_test")

        # whenever user chooses a language, start from Beginner
        path.current_language = chosen_lang
        path.current_level = "Beginner"
        path.save(update_fields=["current_language", "current_level"])

        return redirect("start_test_page")

    # GET → render form
    return render(
        request,
        "users/take_test.html",
        {
            "current_language": path.current_language,
            "current_level": path.current_level,
            "available_languages": available_langs,
            "can_choose_language": True,  # if your template checks this
        },
    )


@login_required(login_url="login")
def start_test_page(request):
    path, _ = UserPath.objects.get_or_create(user=request.user)
    locked = path.is_locked()
    remaining_unlock = path.locked_until if locked else None

    # Also compute daily limit status
    today = timezone.localdate()
    tests_today = path.tests_taken_today if path.last_test_date == today else 0
    can_take = (not locked) and tests_today < 1

    return render(
        request,
        "users/test_page.html",
        {
            "language": path.current_language,
            "difficulty": path.current_level,
            "locked": locked,
            "locked_until": remaining_unlock,
            "can_take": can_take,
        },
    )


# ======================================================
# ✅ USER INFO (for header pill)
# ======================================================

@login_required
def get_user_info(request):
    return JsonResponse({"username": request.user.username})


# ======================================================
# ✅ LLM SETTINGS / MCQ STRUCTS
# ======================================================

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MCQ_MODEL = "qwen2.5:3b-instruct"
HINT_MODEL = "phi3:mini"


class MCQ(BaseModel):
    question: str
    options: List[str] = Field(..., min_items=4, max_items=4)
    answer: str

    @validator("answer")
    def normalize_answer(cls, v, values):
        opts = values.get("options", [])
        if v in opts:
            return v

        letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
        if v.upper() in letter_map:
            idx = letter_map[v.upper()]
            if idx < len(opts):
                return opts[idx]

        return opts[0] if opts else v


class MCQList(RootModel[List[MCQ]]):
    @validator("root")
    def must_be_five(cls, v):
        if len(v) != 5:
            raise ValueError("Must return exactly 5 MCQs")
        return v


def build_prompt(language, level):
    return f"""
Generate EXACTLY 5 MCQs for {language} ({level} level).

STRICT RULES:
- Output ONLY a JSON array.
- NO markdown.
- NO text before or after JSON.
- Each question MUST have 4 options.
- Answer must be EXACT TEXT of correct option.

Correct format:
[
  {{
    "question": "Which operator is exponentiation in Python?",
    "options": ["**","*","^","//"],
    "answer": "**"
  }}
]
""".strip()


def extract_json_array(text):
    cleaned = text.replace("```json", "").replace("```", "").strip()

    # 1) direct array
    match = re.search(r"\[\s*{[\s\S]*?}\s*\]", cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    # 2) {"questions": [...]}
    match2 = re.search(r'"questions"\s*:\s*(\[\s*{[\s\S]*?}\s*\])', cleaned)
    if match2:
        try:
            return json.loads(match2.group(1))
        except Exception:
            pass

    # 3) a single object
    match3 = re.search(r"{[\s\S]*?}", cleaned)
    if match3:
        try:
            obj = json.loads(match3.group(0))
            return [obj]
        except Exception:
            pass

    raise ValueError("No valid JSON array found")


def generate_mcqs(language, level):
    prompt = build_prompt(language, level)
    collected: List[MCQ] = []

    for attempt in range(10):
        try:
            res = requests.post(
                OLLAMA_URL,
                json={
                    "model": MCQ_MODEL,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                },
                timeout=40,
            ).json()

            raw = res.get("response", "").strip()

            print("\n" + "=" * 80)
            print(f"🔵 RAW OUTPUT (Attempt {attempt+1}):")
            print(raw)
            print("=" * 80 + "\n")

            # Try as object
            try:
                obj = json.loads(raw)
                mcq = MCQ.parse_obj(obj)
                collected.append(mcq)
            except Exception:
                # Try as array
                try:
                    arr = extract_json_array(raw)
                    validated = MCQList.parse_obj(arr)
                    print("✅ VALID 5 MCQs GENERATED IN ONE SHOT")
                    return validated.root
                except Exception:
                    pass

            if len(collected) == 5:
                print("✅ Collected 5 MCQs after multiple attempts")
                return collected

        except Exception as e:
            print(f"[MCQ ERROR Attempt {attempt+1}]: {e}")

    print("❌ MCQ FALLBACK USED")
    return fallback_mcqs()


def fallback_mcqs():
    return [
        {
            "question": "What is Python?",
            "options": ["Language", "Snake", "IDE", "Game"],
            "answer": "Language",
        },
        {
            "question": "Which keyword starts a loop?",
            "options": ["for", "print", "int", "loop"],
            "answer": "for",
        },
        {
            "question": "Assignment operator?",
            "options": ["=", "==", "+=", "<-"],
            "answer": "=",
        },
        {
            "question": "Python extension?",
            "options": [".py", ".java", ".c", ".js"],
            "answer": ".py",
        },
        {
            "question": "RAM stores?",
            "options": ["Temporary data", "Music", "Games", "Videos"],
            "answer": "Temporary data",
        },
    ]


# ======================================================
# ✅ MCQ / HINT / SUBMIT APIs
# ======================================================

@csrf_exempt
@login_required
def api_questions(request):
    lang = request.GET.get("lang", "python")
    level = request.GET.get("level", "Beginner")

    mcqs = generate_mcqs(lang, level)
    out = [q.dict() if not isinstance(q, dict) else q for q in mcqs]

    return JsonResponse(out, safe=False)


@csrf_exempt
@login_required
def hint_api(request):
    try:
        body = json.loads(request.body)
        question = body.get("question", "")

        res = requests.post(
            OLLAMA_URL,
            json={
                "model": HINT_MODEL,
                "prompt": f"Give a short 1-line hint for: {question}",
                "stream": False,
            },
        ).json()

        return JsonResponse({"hint": res.get("response", "").strip()})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@login_required(login_url="login")
@require_POST
def submit_test_api(request):
    """
    Save test result, update user path and badges, return next step info.
    """
    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    user = request.user

    # 0) Hard lock: 1 test per day per user
    path, _ = UserPath.objects.get_or_create(user=user)
    today = timezone.localdate()
    if path.last_test_date == today and (path.tests_taken_today or 0) >= 1:
        return JsonResponse(
            {
                "status": "locked",
                "message": "You have already taken today’s test. Please come back tomorrow.",
            },
            status=403,
        )

    # sanitize incoming fields
    language_raw = (data.get("language") or "python")
    difficulty_raw = (data.get("difficulty") or "Beginner")

    language = str(language_raw).lower()
    difficulty = str(difficulty_raw).capitalize()

    try:
        score = int(data.get("score", 0))
    except Exception:
        score = 0

    try:
        hints_used = int(data.get("hints_used", 0))
    except Exception:
        hints_used = 0

    try:
        time_taken = int(data.get("time_taken", 0))
    except Exception:
        time_taken = 0

    # 1) Save test result
    TestResult.objects.create(
        user=user,
        language=language,
        difficulty=difficulty,
        score=score,
        hints_used=hints_used,
        time_elapsed=time_taken,
    )

    # 2) Ensure profile exists
    try:
        profile, _ = Profile.objects.get_or_create(user=user)
    except Exception:
        profile = None

    # 3) Bookkeeping: enforce 1 test/day
    today = timezone.localdate()
    if path.last_test_date == today:
        path.tests_taken_today = min((path.tests_taken_today or 0) + 1, 2)
    else:
        path.tests_taken_today = 1
        path.last_test_date = today

    path.save(update_fields=["last_test_date", "tests_taken_today"])

    # 4) Decide next_level and next_language
    next_language = language
    next_level = difficulty
    rl_used = False

    if compute_next_step:
        try:
            rl_res = compute_next_step(
                score=score,
                hints=hints_used,
                current_language=language,
                current_level=difficulty,
            )
            if isinstance(rl_res, (list, tuple)) and len(rl_res) >= 2:
                cand_lang, cand_level = rl_res[0], rl_res[1]
                if isinstance(cand_lang, str) and isinstance(cand_level, str):
                    next_language = cand_lang.lower()
                    next_level = cand_level.capitalize()
                    rl_used = True
            elif isinstance(rl_res, dict):
                cand_lang = rl_res.get("language")
                cand_level = rl_res.get("level")
                if cand_lang:
                    next_language = str(cand_lang).lower()
                if cand_level:
                    next_level = str(cand_level).capitalize()
                rl_used = True
        except Exception as e:
            print("RL agent error:", e)
            rl_used = False

    if not rl_used:
        # rule-based progression
        try:
            cur_index = LEVELS.index(difficulty)
        except ValueError:
            cur_index = 0

        if score >= 85 and hints_used < 2:
            if cur_index < len(LEVELS) - 1:
                next_level = LEVELS[cur_index + 1]
            else:
                next_level = LEVELS[-1]
        elif score >= 70 and hints_used < 2:
            if cur_index < len(LEVELS) - 1:
                next_level = LEVELS[cur_index + 1]
            else:
                next_level = LEVELS[-1]
        elif score > 60 and hints_used == 0:
            if cur_index < len(LEVELS) - 1:
                next_level = LEVELS[cur_index + 1]
        else:
            next_level = LEVELS[cur_index]

        next_language = language

    # 5) Legend badge logic: when user completes Python Advanced well
    can_choose_next_language = False
    if (
        language == "python"
        and difficulty == "Advanced"
        and score >= 85
        and hints_used < 2
    ):
        badge, created = UserBadge.objects.get_or_create(
            user=user,
            language="python",
            level="Legend",
        )
        blist = path.badge_languages or []
        if "python" not in blist:
            blist.append("python")
            path.badge_languages = blist

        path.legend_badges = (path.legend_badges or 0) + (1 if created else 0)
        can_choose_next_language = True

    # 6) Update current path state
    path.current_language = next_language
    path.current_level = next_level
    path.save()

    # 7) Optionally update profile stats
    if profile:
        try:
            profile.total_tests_taken = profile.total_tests_taken + 1
            all_scores = TestResult.objects.filter(user=user).values_list(
                "score", flat=True
            )
            avg = sum(all_scores) / len(all_scores) if all_scores else score
            profile.average_score = avg
            profile.save(update_fields=["total_tests_taken", "average_score"])
        except Exception:
            pass

    # 8) If RL kept user on same level → revision topics
    repeat_level = next_language == language and next_level == difficulty
    revision_topics = get_revision_topics(language, difficulty) if repeat_level else []

    # 9) Respond with JSON
    return JsonResponse(
        {
            "status": "saved",
            "next_language": next_language,
            "next_level": next_level,
            "can_choose_next_language": can_choose_next_language,
            "repeat_level": repeat_level,
            "revision_topics": revision_topics,
            "message": (
                "Legend unlocked! Choose your next language from the dashboard."
                if can_choose_next_language
                else (
                    "Please revise the suggested topics and take the test again tomorrow."
                    if repeat_level
                    else "Progress saved."
                )
            ),
        }
    )


# ======================================================
# ✅ TEST RESULT PAGE + LEGEND FLAG
# ======================================================

def compute_can_choose_next_language(
    user, language: str, difficulty: str, score: int, hints: int
) -> str:
    """
    Return "true" or "false" (string) to match template check:
      {% if can_choose_next_language == "true" %}
    """
    try:
        lang = (language or "").lower()
        diff = (difficulty or "").capitalize()
        sc = int(score or 0)
        h = int(hints or 0)
    except Exception:
        return "false"

    if lang == "python" and diff == "Advanced" and sc >= 85 and h < 2:
        return "true"
    return "false"


@login_required
def test_result_page(request):
    score = request.GET.get("score")
    correct = request.GET.get("correct")
    total = request.GET.get("total")
    hints = request.GET.get("hints")
    time_taken = request.GET.get("time")
    language = request.GET.get("language")
    difficulty = request.GET.get("difficulty")

    next_language = request.GET.get("next_language", "")
    next_level = request.GET.get("next_level", "")

    topics_raw = request.GET.get("topics")
    try:
        revision_topics = json.loads(topics_raw) if topics_raw else []
    except Exception:
        revision_topics = []

    can_choose = request.GET.get("can_choose_next_language")
    if can_choose is None:
        can_choose = compute_can_choose_next_language(
            request.user,
            language,
            difficulty,
            score or 0,
            hints or 0,
        )

    return render(
        request,
        "users/test_result.html",
        {
            "score": score,
            "correct": correct,
            "total": total,
            "hints": hints,
            "time": time_taken,
            "language": language,
            "difficulty": difficulty,
            "next_language": next_language,
            "next_level": next_level,
            "can_choose_next_language": can_choose,
            "revision_topics": revision_topics,
        },
    )


# ======================================================
# ✅ ROADMAP KNOWLEDGE BASE + REVISION TOPICS
# ======================================================

RESOURCE_CATALOG = {
    "python": {
        "Beginner": {
            "topics": ["Syntax & I/O", "Data Types", "Control Flow", "Functions"],
            "youtube": [
                (
                    "Python Full Course (freeCodeCamp)",
                    "https://www.youtube.com/watch?v=rfscVS0vtbw",
                ),
                (
                    "Core Basics Playlist",
                    "https://www.youtube.com/watch?v=kqtD5dpn9C8",
                ),
            ],
            "hackerrank": "https://www.hackerrank.com/domains/python",
            "udemy": [
                (
                    "Complete Python Bootcamp",
                    "https://www.udemy.com/course/complete-python-bootcamp/",
                ),
            ],
        },
        "Intermediate": {
            "topics": [
                "OOP",
                "Modules & Packages",
                "File I/O & Errors",
                "Virtualenv & Packaging",
            ],
            "youtube": [
                (
                    "OOP in Python (Corey Schafer)",
                    "https://www.youtube.com/watch?v=JeznW_7DlB0",
                ),
            ],
            "hackerrank": "https://www.hackerrank.com/domains/python",
            "udemy": [
                (
                    "Intermediate/Advanced Python",
                    "https://www.udemy.com/course/advanced-python/",
                ),
            ],
        },
        "Advanced": {
            "topics": ["Iterators/Generators", "Decorators", "Asyncio", "Testing & Tooling"],
            "youtube": [
                (
                    "Generators/Decorators (Corey Schafer)",
                    "https://www.youtube.com/watch?v=FsAPt_9Bf3U",
                ),
            ],
            "hackerrank": "https://www.hackerrank.com/domains/python",
            "udemy": [
                (
                    "Advanced Python Concepts",
                    "https://www.udemy.com/course/advanced-python-concepts/",
                ),
            ],
        },
    },
    "java": {
        "Beginner": {
            "topics": ["Syntax & Types", "Control Flow", "Methods", "Arrays & Strings"],
            "youtube": [
                (
                    "Java for Beginners",
                    "https://www.youtube.com/watch?v=eIrMbAQSU34",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/java",
            "udemy": [
                (
                    "Java Programming Masterclass",
                    "https://www.udemy.com/course/java-the-complete-java-developer-course/",
                )
            ],
        },
        "Intermediate": {
            "topics": ["OOP Deep Dive", "Collections", "Exceptions & IO", "Generics"],
            "youtube": [
                (
                    "Java Collections",
                    "https://www.youtube.com/watch?v=jM8GQnE2Fng",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/java",
            "udemy": [
                (
                    "Java Mastery",
                    "https://www.udemy.com/course/java-the-complete-java-developer-course/",
                )
            ],
        },
        "Advanced": {
            "topics": [
                "Streams",
                "Concurrency",
                "JVM/GC",
                "Testing & Build (Maven/Gradle)",
            ],
            "youtube": [
                (
                    "Java Concurrency",
                    "https://www.youtube.com/watch?v=7p3Wx2oZ9YI",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/java",
            "udemy": [
                (
                    "Modern Java",
                    "https://www.udemy.com/course/modern-java-learn-java-8-features-by-coding-it/",
                )
            ],
        },
    },
    "cpp": {
        "Beginner": {
            "topics": ["Syntax & IO", "Variables/Types", "Control Flow", "Functions"],
            "youtube": [
                (
                    "C++ Tutorial",
                    "https://www.youtube.com/watch?v=vLnPwxZdW4Y",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/cpp",
            "udemy": [
                (
                    "Beginning C++",
                    "https://www.udemy.com/course/beginning-c-plus-plus-programming/",
                )
            ],
        },
        "Intermediate": {
            "topics": ["OOP", "STL Basics", "Pointers/Refs", "Files & Exceptions"],
            "youtube": [
                (
                    "STL in C++",
                    "https://www.youtube.com/watch?v=PocJ5jXv8No",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/cpp",
            "udemy": [
                (
                    "C++ Masterclass",
                    "https://www.udemy.com/course/beginning-c-plus-plus-programming/",
                )
            ],
        },
        "Advanced": {
            "topics": ["Templates", "Move Semantics", "Concurrency", "CMake & Tooling"],
            "youtube": [
                (
                    "C++ Advanced",
                    "https://www.youtube.com/watch?v=1OEu9C51K2A",
                )
            ],
            "hackerrank": "https://www.hackerrank.com/domains/cpp",
            "udemy": [
                (
                    "Advanced C++",
                    "https://www.udemy.com/course/advanced-c-programming/",
                )
            ],
        },
    },
    "c": {
    "Beginner": {
        "topics": [
            "Syntax & Structure",
            "Variables & Data Types",
            "Control Flow (if/else, loops)",
            "Functions & Scope"
        ],
        "youtube": [
            ("C Programming Full Course — freeCodeCamp", "https://www.youtube.com/watch?v=KJgsSFOSQv0"),
            ("Basics of C Programming — Jenny’s Lectures", "https://www.youtube.com/watch?v=ZSPZob_1TOk"),
        ],
        "hackerrank": "https://www.hackerrank.com/domains/c",
        "udemy": [
            ("C Programming For Beginners — Master the C Language", "https://www.udemy.com/course/c-programming-for-beginners-/"),
        ],
    },

    "Intermediate": {
        "topics": [
            "Pointers & Memory",
            "Arrays & Strings",
            "Structures & Unions",
            "File Handling"
        ],
        "youtube": [
            ("Pointers Explained — CodeWithHarry", "https://www.youtube.com/watch?v=_s6wuxk2PtM"),
            ("Structures & Unions — Neso Academy", "https://www.youtube.com/watch?v=UmnCZ7-9yDY"),
        ],
        "hackerrank": "https://www.hackerrank.com/domains/c",
        "udemy": [
            ("Mastering C Pointers", "https://www.udemy.com/course/pointers-in-c-programming/"),
        ],
    },

    "Advanced": {
        "topics": [
            "Dynamic Memory Allocation",
            "Data Structures Implementation",
            "Preprocessor & Compilation Process",
            "Debugging & Build Tools"
        ],
        "youtube": [
            ("Memory Allocation Deep Dive", "https://www.youtube.com/watch?v=6DnFYxD2z8E"),
            ("Makefile & Compiler Tooling", "https://www.youtube.com/watch?v=DtGrdB8wS0E"),
        ],
        "hackerrank": "https://www.hackerrank.com/domains/c",
        "udemy": [
            ("Advanced C Programming — Data Structures & Pointers", "https://www.udemy.com/course/mastering-data-structures-using-c-programming-language/"),
        ],
    },
},
}

ROADMAP_LANGS = ["python", "java", "cpp","C"]
ROADMAP_LEVELS = ["Beginner", "Intermediate", "Advanced"]


def build_4_week_plan(language: str, level: str):
    """Simple deterministic 4-week plan with day locks + resources."""
    lang = language.lower()
    level_cap = level.capitalize()
    node = RESOURCE_CATALOG.get(lang, {}).get(level_cap)
    if not node:
        return {
            "weeks": [],
            "language": lang,
            "level": level_cap,
            "err": "Unsupported pair.",
        }

    topics = node["topics"]
    today = date.today()

    weeks = []
    for w in range(4):
        start = today + timedelta(days=7 * w)
        end = start + timedelta(days=6)
        topic = topics[w % len(topics)]
        weeks.append(
            {
                "title": f"Week {w+1}: {topic}",
                "start": start.strftime("%d %b %Y"),
                "end": end.strftime("%d %b %Y"),
                "milestones": [
                    f"Learn: {topic}",
                    "Daily practice: 30–45 mins (min 1 HackerRank problem/day)",
                    "Create summary notes & 1 mini exercise",
                ],
                "lock_next_test_until": (end + timedelta(days=1)).strftime(
                    "%d %b %Y"
                ),
            }
        )

    return {
        "language": lang,
        "level": level_cap,
        "youtube": node["youtube"],
        "hackerrank": node["hackerrank"],
        "udemy": node["udemy"],
        "weeks": weeks,
    }


def get_revision_topics(language: str, level: str):
    lang = (language or "").lower()
    lvl = (level or "").capitalize()
    node = RESOURCE_CATALOG.get(lang, {}).get(lvl, {})
    return node.get("topics", [])


@login_required(login_url="login")
@require_http_methods(["GET"])
def roadmap_form(request):
    return render(
        request,
        "users/roadmap_form.html",
        {
            "langs": ROADMAP_LANGS,
            "levels": ROADMAP_LEVELS,
        },
    )


@login_required(login_url="login")
@require_http_methods(["POST"])
def roadmap_generate(request):
    language = request.POST.get("language", "python")
    level = request.POST.get("level", "Beginner")

    plan = build_4_week_plan(language, level)
    html = render_to_string("users/roadmap.html", {"plan": plan})

    return HttpResponse(html)


@csrf_exempt
@login_required(login_url="login")
@require_http_methods(["POST"])
def roadmap_pdf(request):
    """Render roadmap as PDF. Falls back to HTML if xhtml2pdf missing."""
    language = request.POST.get("language", "python")
    level = request.POST.get("level", "Beginner")
    plan = build_4_week_plan(language, level)

    html = render_to_string("users/roadmap_pdf.html", {"plan": plan})

    if not HAS_PDF:
        # Fallback: show printable HTML with a note.
        return HttpResponse(html)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="roadmap_{language}_{level}.pdf"'
    pisa.CreatePDF(html, dest=response)  # type: ignore
    return response

# ======================================================
# ✅ LANGUAGE CHOICE VIEWS
# ======================================================

@login_required
def choose_next_language(request):
    """After Legend, user picks next language — but cannot take test today."""
    if request.method == "POST":
        lang = request.POST.get("language")
        if not lang:
            messages.error(request, "Please choose a language.")
            return redirect("choose_next_language")

        path, _ = UserPath.objects.get_or_create(user=request.user)
        path.current_language = lang.lower()
        path.current_level = "Beginner"
        # DO NOT reset test lock here — user must wait until tomorrow
        path.save()

        messages.success(
            request,
            "Next language selected! Please review the roadmap before taking the first test.",
        )
        return redirect("roadmap_form")

    # available languages except python
    options = [l for l in LANG_ORDER if l != "python"]

    return render(
        request,
        "users/choose_next_language.html",
        {"languages": options},
    )


@login_required
def choose_preferred_language_page(request):
    """
    User can pick a preferred language; always starts at Beginner.
    This is independent of Legend badge — it's a preference chooser.
    """
    if request.method == "POST":
        lang = request.POST.get("language")
        if not lang:
            messages.error(request, "Choose a language.")
            return redirect("choose_preferred_language")

        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.preferred_language = lang.lower()
        profile.save()

        path, _ = UserPath.objects.get_or_create(user=request.user)
        path.current_language = lang.lower()
        path.current_level = "Beginner"
        path.save()

        messages.success(
            request,
            "Preference saved — you'll be unlocked after cooldown.",
        )
        return redirect("dashboard")

    languages_local = ["python", "java", "cpp", "c"]
    path, _ = UserPath.objects.get_or_create(user=request.user)

    return render(
        request,
        "users/choose_preferred_language.html",
        {
            "languages": languages_local,
            "current_language": path.current_language,
        },
    )