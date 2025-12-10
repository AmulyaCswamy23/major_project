import json, re

def ultra_extract_mcqs(raw_text: str):
    """
    Extracts and cleans MCQs from ANY LLM output.
    Fully bulletproof version.
    """

    if not raw_text:
        return []

    text = raw_text

    # --- 1. REMOVE markdown fences ---
    text = text.replace("```json", "").replace("```", "").replace("```JSON", "")
    text = text.replace("```", "")

    # --- 2. FIND JSON BLOCK ANYWHERE ---
    json_block = None
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        json_block = match.group(0)
    else:
        # No array found → look for single object { ... }
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            json_block = "[" + match.group(0) + "]"
        else:
            json_block = "[]"

    # --- 3. CLEAN JSON ---
    clean = (
        json_block
        .replace(",]", "]")
        .replace(", }", "}")
        .replace(",}", "}")
        .replace("} ,", "},")
    )

    # --- 4. SAFE PARSE ---
    try:
        parsed = json.loads(clean)
    except:
        parsed = []

    # --- 5. CLEAN STRUCTURE ---
    fixed = []
    for q in parsed:
        if not isinstance(q, dict):
            continue

        question = str(q.get("question", "")).strip()
        options  = q.get("options", [])
        answer   = str(q.get("answer", "")).strip()

        # Fix missing question
        if not question:
            continue

        # Normalize options
        if not isinstance(options, list):
            options = []

        # Convert all options to strings
        options = [str(o).strip() for o in options]

        # Remove empty / duplicate options
        uniq = []
        for o in options:
            if o and o not in uniq:
                uniq.append(o)

        options = uniq[:4]

        # If fewer than 4 options → fill placeholders
        while len(options) < 4:
            options.append(f"Option {len(options)+1}")

        # Fix alphabetic answers A/B/C/D
        up = answer.upper()
        if up in {"A", "B", "C", "D"}:
            idx = {"A":0, "B":1, "C":2, "D":3}[up]
            answer = options[idx]

        # If answer still invalid → set option 1
        if answer not in options:
            answer = options[0]

        fixed.append({
            "question": question,
            "options": options,
            "answer": answer
        })

    return fixed