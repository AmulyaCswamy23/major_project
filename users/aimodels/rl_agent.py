# users/aimodels/rl_agent.py
import os
import json
import numpy as np

# =========================================================
# CONFIG
# =========================================================

# Keep lowercase language names to avoid mismatch
LANGS = ["python", "java", "cpp"]
LEVELS = ["Beginner", "Intermediate", "Advanced"]

ACTIONS = {
    0: "repeat_level",
    1: "next_level",
    2: "next_language",
}

ALPHA = 0.3     # learning rate
GAMMA = 0.8     # discount factor
EPSILON = 0.15  # small exploration chance

# Q-table file on disk (same folder as this file, fallback to CWD if needed)
try:
    BASE_DIR = os.path.dirname(__file__)
except NameError:
    BASE_DIR = os.getcwd()

Q_PATH = os.path.join(BASE_DIR, "qtable.json")


# =========================================================
# NORMALIZATION HELPERS
# =========================================================

def normalize_language(language: str) -> str:
    """
    Normalize language string:
    - strip spaces
    - lowercase
    - must be in LANGS
    """
    lang = language.strip().lower()
    if lang not in LANGS:
        raise ValueError(f"Unknown language: {language!r} (normalized to {lang!r})")
    return lang


def normalize_level(level: str) -> str:
    """
    Normalize level string:
    - strip spaces
    - lowercase
    - map to one of: 'Beginner', 'Intermediate', 'Advanced'
    """
    lvl_clean = level.strip().lower()
    mapping = {
        "beginner": "Beginner",
        "intermediate": "Intermediate",
        "advanced": "Advanced",
    }
    if lvl_clean not in mapping:
        raise ValueError(f"Unknown level: {level!r} (normalized to {lvl_clean!r})")
    return mapping[lvl_clean]


# =========================================================
# STATE <-> ID
# =========================================================

def state_to_id(language: str, level: str) -> int:
    """
    Map (language, level) -> integer state id.
    language: case-insensitive, must be in LANGS
    level: case-insensitive, must map to LEVELS
    """
    language = normalize_language(language)
    level = normalize_level(level)

    li = LANGS.index(language)
    lj = LEVELS.index(level)
    return li * len(LEVELS) + lj


def id_to_state(sid: int):
    """
    Map integer state id -> (language, level)
    """
    num_levels = len(LEVELS)
    lang_i = sid // num_levels
    lvl_i = sid % num_levels
    return LANGS[lang_i], LEVELS[lvl_i]


def next_state(language: str, level: str, action_idx: int):
    """
    Pure transition function (no randomness).
    Given current (language, level) and chosen action index,
    return the next (language, level).
    """
    language = normalize_language(language)
    level = normalize_level(level)

    lang_i = LANGS.index(language)
    lvl_i = LEVELS.index(level)

    act = ACTIONS.get(action_idx, "repeat_level")

    if act == "repeat_level":
        # stay in the same state
        return language, level

    if act == "next_level":
        # move to next level if possible, else stay
        if lvl_i < len(LEVELS) - 1:
            return language, LEVELS[lvl_i + 1]
        return language, level

    if act == "next_language":
        # only allow jumping language if currently at Advanced
        if lvl_i == len(LEVELS) - 1 and lang_i < len(LANGS) - 1:
            # move to next language, Beginner level
            return LANGS[lang_i + 1], LEVELS[0]
        # otherwise stay
        return language, level

    # fallback
    return language, level


# =========================================================
# Q-TABLE PERSISTENCE
# =========================================================

def load_q():
    """
    Load Q-table from disk; if not present or invalid, create a fresh one.
    Shape: (num_states, num_actions) = (len(LANGS) * len(LEVELS), len(ACTIONS))
    """
    num_states = len(LANGS) * len(LEVELS)
    num_actions = len(ACTIONS)

    if os.path.exists(Q_PATH):
        try:
            with open(Q_PATH, "r") as f:
                data = json.load(f)
            arr = np.array(data.get("qtable", []), dtype=float)
            if arr.shape == (num_states, num_actions):
                return arr
            else:
                # shape mismatch; reinit
                print("Q-table shape mismatch, reinitializing.")
        except Exception as e:
            # any error => fresh init
            print(f"Failed to load Q-table ({e}), reinitializing.")

    # fresh Q-table
    q = np.zeros((num_states, num_actions), dtype=float)
    save_q(q)
    return q


def save_q(q):
    """
    Save Q-table to disk as JSON.
    """
    obj = {"qtable": q.tolist()}
    with open(Q_PATH, "w") as f:
        json.dump(obj, f, indent=2)


Q = load_q()


# =========================================================
# REWARD POLICY
# =========================================================

def get_reward(score: int, hints: int) -> float:
    """
    Reward function based purely on quiz performance and hint usage.
    Higher score + fewer hints -> higher reward.
    Negative reward encourages not moving forward when performance is poor.
    """
    score = int(score)
    hints = int(hints)

    # highest priority
    if score > 85 and hints < 2:
        return +10.0
    if score > 70 and hints < 2:
        return +5.0
    if score > 60 and hints == 0:
        return +5.0
    # penalty to discourage moving forward on low performance
    return -5.0


# =========================================================
# PUBLIC API
# =========================================================

def compute_next_step(score: int, hints: int, current_language: str, current_level: str):
    """
    Decide the next (language, level) based on quiz results and current state.

    Args:
        score: int quiz score (0–100)
        hints: int number of hints used
        current_language: e.g. "python", "Python", " PYTHON "
        current_level: e.g. "Beginner", "beginner", " BEGINNER "

    Returns:
        (next_language, next_level)  # both strings
        - next_language is lowercase
        - next_level is one of "Beginner", "Intermediate", "Advanced"

    Side effects:
        - updates the Q-table online using Q-learning
        - persists Q-table to disk

    Behaviour tweak:
    - If reward is positive (student did well) and the RL policy chose
      "repeat_level", we override it to move forward:
        * to "next_level" if not yet Advanced
        * to "next_language" if at Advanced and not in the last language
      This prevents the agent from getting stuck at Beginner in cpp or
      any other language when the student is clearly ready to progress.
    """
    global Q

    # normalize inputs
    current_language = normalize_language(current_language)
    current_level = normalize_level(current_level)

    # map to state id
    s = state_to_id(current_language, current_level)

    # epsilon-greedy action selection
    if np.random.rand() < EPSILON:
        # exploration: random action
        action = int(np.random.randint(len(ACTIONS)))
    else:
        # exploitation: best known action
        action = int(np.argmax(Q[s]))

    # compute immediate reward from performance
    reward = get_reward(score, hints)

    # ---------- CURRICULUM SAFETY OVERRIDE ----------
    # If the student did well (reward > 0) but RL chose "repeat_level",
    # force progression to avoid getting stuck.
    act_name = ACTIONS[action]
    lang_i = LANGS.index(current_language)
    lvl_i = LEVELS.index(current_level)

    if reward > 0 and act_name == "repeat_level":
        # If not yet at the highest level, go to the next level.
        if lvl_i < len(LEVELS) - 1:
            action = 1  # "next_level"
        else:
            # At Advanced: if not last language, go to next language.
            if lang_i < len(LANGS) - 1:
                action = 2  # "next_language"
            # If already at last language & Advanced, we keep them there.
        act_name = ACTIONS[action]
    # ---------- END OVERRIDE ----------

    # compute next state and id using the (possibly overridden) action
    next_lang, next_lvl = next_state(current_language, current_level, action)
    s2 = state_to_id(next_lang, next_lvl)

    # Q-learning update
    old_q = Q[s, action]
    Q[s, action] = old_q + ALPHA * (
        reward + GAMMA * float(np.max(Q[s2])) - old_q
    )

    # persist Q-table
    save_q(Q)

    # return normalized strings: language lowercase, level capitalized
    return next_lang.lower(), next_lvl