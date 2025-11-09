# app.py
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import streamlit as st

st.set_page_config(page_title="Quiz Hub", page_icon="🧠", layout="centered")

QUIZ_DIR = Path("quizzes")

# ----------------- Loader & Validator -----------------
def load_quiz_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    validate_quiz_data(data, path.name)
    return data

def validate_quiz_data(data: Dict[str, Any], name: str) -> None:
    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError(f"{name}: must contain a 'questions' list.")
    for i, q in enumerate(data["questions"], start=1):
        if "id" not in q or "type" not in q or "prompt" not in q:
            raise ValueError(f"{name} Q{i}: missing 'id'/'type'/'prompt'.")
        t = q["type"]
        if t == "single_choice":
            if "choices" not in q or "answer" not in q or not isinstance(q["answer"], int):
                raise ValueError(f"{name} Q{i} single_choice needs 'choices' + integer 'answer'.")
            if q["answer"] < 0 or q["answer"] >= len(q["choices"]):
                raise ValueError(f"{name} Q{i}: 'answer' index out of range.")
        elif t == "multi_select":
            if "choices" not in q or "answer" not in q or not isinstance(q["answer"], list):
                raise ValueError(f"{name} Q{i} multi_select needs 'choices' + list 'answer'.")
            for idx in q["answer"]:
                if not isinstance(idx, int) or idx < 0 or idx >= len(q["choices"]):
                    raise ValueError(f"{name} Q{i}: multi-select index {idx} out of range.")
        elif t == "true_false":
            if "answer" not in q or not isinstance(q["answer"], bool):
                raise ValueError(f"{name} Q{i} true_false needs boolean 'answer'.")
        elif t == "short_answer":
            if "answer_text" not in q or not isinstance(q["answer_text"], list) or not q["answer_text"]:
                raise ValueError(f"{name} Q{i} short_answer needs non-empty list 'answer_text'.")
        else:
            raise ValueError(f"{name} Q{i}: unknown type '{t}'.")

def list_quizzes() -> List[Tuple[str, Path, Optional[str]]]:
    """Return [(label, path, title_from_meta)] sorted by label."""
    QUIZ_DIR.mkdir(parents=True, exist_ok=True)
    items: List[Tuple[str, Path, Optional[str]]] = []
    for p in sorted(QUIZ_DIR.glob("*.json")):
        title = None
        try:
            with open(p, "r", encoding="utf-8") as f:
                meta = json.load(f).get("meta", {})
                title = meta.get("title")
        except Exception:
            title = None
        label = title or p.stem.replace("_", " ").title()
        items.append((label, p, title))
    return items

# ----------------- State -----------------
def init_state():
    if "quiz_path" not in st.session_state:
        st.session_state.quiz_path = None
    if "order" not in st.session_state:
        st.session_state.order = []
    if "idx" not in st.session_state:
        st.session_state.idx = 0
    if "score" not in st.session_state:
        st.session_state.score = 0

def reset_run():
    st.session_state.idx = 0
    st.session_state.score = 0
    # clear input widgets from previous run
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(("r_", "m_", "t_", "s_")):
            del st.session_state[k]

# ----------------- UI helpers -----------------
def normalize(s: str) -> str:
    return " ".join(s.lower().split())

def render_question(q: Dict[str, Any]):
    st.subheader(q["prompt"])
    t = q["type"]
    if t in ("single_choice", "multi_select"):
        choices = q.get("choices", [])
        if t == "single_choice":
            return st.radio("Choose one:", choices, index=None, key=f"r_{q['id']}")
        else:
            return st.multiselect("Choose all that apply:", choices, key=f"m_{q['id']}")
    elif t == "true_false":
        return st.radio("True or False?", ["True", "False"], index=None, key=f"t_{q['id']}")
    elif t == "short_answer":
        return st.text_input("Your answer", key=f"s_{q['id']}")

def check_question(q: Dict[str, Any], user_value) -> bool:
    t = q["type"]
    if t == "single_choice":
        if user_value is None:
            st.warning("Select an option.")
            return False
        idx = q["choices"].index(user_value)
        ok = (idx == q["answer"])
    elif t == "multi_select":
        if not user_value:
            st.warning("Select at least one option.")
            return False
        chosen = {q["choices"].index(x) for x in user_value}
        ok = (chosen == set(q["answer"]))
    elif t == "true_false":
        if user_value is None:
            st.warning("Select True or False.")
            return False
        chosen = (user_value == "True")
        ok = (chosen == q["answer"])
    elif t == "short_answer":
        if not user_value:
            st.warning("Type an answer.")
            return False
        ok = normalize(user_value) in {normalize(a) for a in q["answer_text"]}

    if ok:
        st.success("✅ Correct!")
    else:
        # Build correct text
        if t == "single_choice":
            correct = q["choices"][q["answer"]]
        elif t == "multi_select":
            correct = ", ".join(q["choices"][i] for i in q["answer"])
        elif t == "true_false":
            correct = "True" if q["answer"] else "False"
        else:
            correct = ", ".join(q["answer_text"])
        st.error(f"❌ Not quite. Correct: **{correct}**")

    if q.get("explanation"):
        with st.expander("Why?"):
            st.write(q["explanation"])
    return ok

def show_results(total: int):
    st.write("---")
    st.subheader("Results")
    st.metric("Score", f"{st.session_state.score} / {total}")
    st.balloons()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔁 Restart This Quiz"):
            reset_run()
            st.rerun()
    with col2:
        if st.button("🏠 Back to Quiz Selection"):
            reset_run()
            st.session_state.quiz_path = None
            st.rerun()

# ----------------- Main -----------------
def main():
    init_state()
    st.title("🧠 Quiz Hub")

    # If no quiz chosen yet, show picker
    if not st.session_state.quiz_path:
        st.subheader("Choose a quiz")
        items = list_quizzes()
        if not items:
            st.info("No quizzes found. Add *.json files to the 'quizzes' folder.")
            return

        labels = [lbl for (lbl, _p, _t) in items]
        choice = st.selectbox("Available quizzes", labels, index=0)
        if st.button("Start"):
            path = dict(items)[choice] if isinstance(items, dict) else items[labels.index(choice)][1]
            st.session_state.quiz_path = str(path)
            reset_run()
            st.rerun()

        # Preview selected meta
        idx = labels.index(choice)
        meta_path = items[idx][1]
        try:
            data = load_quiz_json(meta_path)
            meta = data.get("meta", {})
            st.caption(f"**Title:** {meta.get('title', meta_path.stem)}  |  **Subject:** {meta.get('subject','—')}  |  **Questions:** {len(data.get('questions', []))}")
        except Exception as e:
            st.error(f"Error reading quiz: {e}")
        return

    # A quiz is selected
    try:
        data = load_quiz_json(Path(st.session_state.quiz_path))
    except Exception as e:
        st.error(f"Failed to load quiz: {e}")
        st.session_state.quiz_path = None
        return

    questions: List[Dict[str, Any]] = data["questions"]
    total = len(questions)
    if total == 0:
        st.warning("This quiz has no questions.")
        if st.button("Back"):
            st.session_state.quiz_path = None
        return

    # Progress
    st.caption(f"{data.get('meta', {}).get('title', Path(st.session_state.quiz_path).stem)}")
    st.progress(st.session_state.idx / total)
    st.caption(f"Question {st.session_state.idx + 1} of {total}")

    # Finished?
    if st.session_state.idx >= total:
        show_results(total)
        return

    q = questions[st.session_state.idx]
    user_value = render_question(q)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Check"):
            if check_question(q, user_value):
                st.session_state.score += 1
    with col2:
        if st.button("Next"):
            st.session_state.idx += 1
            st.rerun()

if __name__ == "__main__":
    main()
