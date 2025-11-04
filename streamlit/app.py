import streamlit as st
import time
import requests
import json

st.set_page_config(page_title="EduWeb Test", page_icon="🧠", layout="centered")

# ✅ Read query params
params = st.query_params
username = params.get("user", [""])[0]
language = params.get("lang", [""])[0]
difficulty = params.get("level", [""])[0]

BACKEND_URL = "http://127.0.0.1:8000"  # Django server

st.title(" EduWeb Test Platform")
st.write(f"**User:** {username}  |  **Language:** {language.upper()} |  **Level:** {difficulty}")

# Session state variables
if "questions" not in st.session_state:
    st.session_state.questions = []
if "current" not in st.session_state:
    st.session_state.current = 0
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "hints_used" not in st.session_state:
    st.session_state.hints_used = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()

# ✅ Fetch questions from Django
def fetch_questions():
    with st.spinner("⌛ Fetching questions..."):
        res = requests.get(f"{BACKEND_URL}/api/questions/?topic={language}-{difficulty}")
        st.session_state.questions = res.json()

if not st.session_state.questions:
    fetch_questions()

questions = st.session_state.questions
current = st.session_state.current

if not questions:
    st.error(" No questions received from API")
    st.stop()

q = questions[current]

# ✅ Timer UI
elapsed = int(time.time() - st.session_state.start_time)
remaining = max(0, 600 - elapsed)
st.progress(remaining / 600)
st.write(f"⏳ **Time Left:** {remaining//60}:{remaining%60:02d}")

if remaining <= 0:
    st.warning("⏱️ Time up! Auto submitting...")
    st.session_state.auto_submit = True

# ✅ Show Question
st.subheader(f"Question {current+1} / {len(questions)}")
st.write(q["question"])

# ✅ Options
choices = q["options"]
selected = st.radio("Choose answer:", choices, key=f"answer_{current}")

if selected:
    st.session_state.answers[current] = selected

# ✅ Hint Button
def get_hint():
    st.session_state.hints_used += 1
    st.session_state.show_hint = True
    res = requests.post(f"{BACKEND_URL}/api/hint", json={"question": q["question"]})
    st.session_state.current_hint = res.json().get("hint", "No hint available")
    st.session_state.hint_time = time.time()

if st.button("💡 Show Hint"):
    get_hint()

# ✅ Display hint for 10 seconds
if st.session_state.get("show_hint", False):
    if time.time() - st.session_state.hint_time < 10:
        st.info("💡 Hint: " + st.session_state.get("current_hint", ""))
    else:
        st.session_state.show_hint = False

# ✅ Navigation buttons
col1, col2, col3 = st.columns(3)
if col1.button("⬅️ Previous") and current > 0:
    st.session_state.current -= 1
    st.rerun()

if col2.button("➡️ Next") and current < len(questions)-1:
    st.session_state.current += 1
    st.rerun()

# ✅ Submit Handler
def submit_test():
    correct = sum(1 for i, ans in st.session_state.answers.items() if ans == questions[i]["answer"])
    incorrect = len(questions) - correct
    score = (correct / len(questions)) * 100
    total_time = int(time.time() - st.session_state.start_time)

    payload = {
        "username": username,
        "language": language,
        "difficulty": difficulty,
        "score": score,
        "correct": correct,
        "incorrect": incorrect,
        "hints_used": st.session_state.hints_used,
        "time": total_time
    }

    requests.post(f"{BACKEND_URL}/api/submit", json=payload)

    st.success(f"✅ Test Completed! Score: {score:.2f}%")
    st.write(f"✔️ Correct: {correct}")
    st.write(f"❌ Incorrect: {incorrect}")
    st.write(f"💡 Hints Used: {st.session_state.hints_used}")
    st.write(f"⏱️ Time Taken: {total_time}s")
    st.stop()

if col3.button("✅ Submit Test") or st.session_state.get("auto_submit", False):
    submit_test()