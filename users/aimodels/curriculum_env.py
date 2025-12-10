# users/aimodels/curriculum_env.py
from typing import Tuple

# Keep this in sync with what you expose in the UI / DB
LANGS  = ["python", "java", "cpp", "javascript"]  # order matters
LEVELS = ["Beginner", "Intermediate", "Advanced"]  # strict order

# Discrete actions
A_REPEAT, A_NEXT_LEVEL, A_NEXT_LANGUAGE = 0, 1, 2
ACTIONS = [A_REPEAT, A_NEXT_LEVEL, A_NEXT_LANGUAGE]

def state_index(lang: str, lvl: str) -> int:
    """Map (language, level) -> integer state id."""
    li = LANGS.index(lang.lower())
    lv = LEVELS.index(lvl.capitalize())
    return li * len(LEVELS) + lv

def index_state(s: int) -> Tuple[str, str]:
    """Map integer state id -> (language, level)."""
    li = s // len(LEVELS)
    lv = s % len(LEVELS)
    return LANGS[li], LEVELS[lv]

def next_state(lang: str, lvl: str, action: int) -> Tuple[str, str]:
    """Transition logic with product constraints baked in."""
    li = LANGS.index(lang.lower())
    lv = LEVELS.index(lvl.capitalize())

    if action == A_REPEAT:
        return lang, lvl

    if action == A_NEXT_LEVEL:
        if lv < len(LEVELS) - 1:
            return lang, LEVELS[lv + 1]
        # already Advanced → cannot go higher
        return lang, lvl

    if action == A_NEXT_LANGUAGE:
        # switch language only from Advanced
        if lv == len(LEVELS) - 1 and li < len(LANGS) - 1:
            return LANGS[li + 1], "Beginner"
        # otherwise illegal; keep same
        return lang, lvl

    # default safe
    return lang, lvl