# app.py
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import streamlit as st

# PDF certificate
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors

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
            if (
                "choices" not in q
                or "answer" not in q
                or not isinstance(q["answer"], int)
            ):
                raise ValueError(
                    f"{name} Q{i} single_choice needs 'choices' + integer 'answer'."
                )
            if q["answer"] < 0 or q["answer"] >= len(q["choices"]):
                raise ValueError(f"{name} Q{i}: 'answer' index out of range.")
        elif t == "multi_select":
            if (
                "choices" not in q
                or "answer" not in q
                or not isinstance(q["answer"], list)
            ):
                raise ValueError(
                    f"{name} Q{i} multi_select needs 'choices' + list 'answer'."
                )
            for idx in q["answer"]:
                if not isinstance(idx, int) or idx < 0 or idx >= len(q["choices"]):
                    raise ValueError(
                        f"{name} Q{i}: multi-select index {idx} out of range."
                    )
        elif t == "true_false":
            if "answer" not in q or not isinstance(q["answer"], bool):
                raise ValueError(f"{name} Q{i} true_false needs boolean 'answer'.")
        elif t == "short_answer":
            if (
                "answer_text" not in q
                or not isinstance(q["answer_text"], list)
                or not q["answer_text"]
            ):
                raise ValueError(
                    f"{name} Q{i} short_answer needs non-empty list 'answer_text'."
                )
        else:
            raise ValueError(f"{name} Q{i}: unknown type '{t}'.")


def list_quizzes() -> List[Tuple[str, Path, Optional[str]]]:
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
    defaults = {
        "quiz_path": None,
        "order": [],
        "idx": 0,
        "score": 0,
        "attempts": [],
        "graded_current": False,
        "allow_next": False,
        "student_name": "",  # NEW
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_run():
    st.session_state.idx = 0
    st.session_state.score = 0
    st.session_state.attempts = []
    st.session_state.graded_current = False
    st.session_state.allow_next = False
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(("r_", "m_", "t_", "s_")):
            del st.session_state[k]


# ----------------- Helpers -----------------
def normalize(s: str) -> str:
    return " ".join(s.lower().split())


def user_value_to_text(q: Dict[str, Any], user_value) -> str:
    t = q["type"]
    if t == "single_choice":
        return "" if user_value is None else str(user_value)
    if t == "multi_select":
        return ", ".join(user_value) if user_value else ""
    if t == "true_false":
        return "" if user_value is None else str(user_value)
    if t == "short_answer":
        return user_value or ""
    return ""


def correct_answer_text(q: Dict[str, Any]) -> str:
    t = q["type"]
    if t == "single_choice":
        return q["choices"][q["answer"]]
    if t == "multi_select":
        return ", ".join(q["choices"][i] for i in q["answer"])
    if t == "true_false":
        return "True" if q["answer"] else "False"
    if t == "short_answer":
        return ", ".join(q["answer_text"])
    return ""


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
        return st.radio(
            "True or False?", ["True", "False"], index=None, key=f"t_{q['id']}"
        )
    elif t == "short_answer":
        return st.text_input("Your answer", key=f"s_{q['id']}")


def check_question(q: Dict[str, Any], user_value) -> Optional[bool]:
    t = q["type"]
    if t == "single_choice":
        if user_value is None:
            st.warning("Select an option.")
            return None
        idx = q["choices"].index(user_value)
        ok = idx == q["answer"]
    elif t == "multi_select":
        if not user_value:
            st.warning("Select at least one option.")
            return None
        chosen = {q["choices"].index(x) for x in user_value}
        ok = chosen == set(q["answer"])
    elif t == "true_false":
        if user_value is None:
            st.warning("Select True or False.")
            return None
        chosen = user_value == "True"
        ok = chosen == q["answer"]
    elif t == "short_answer":
        if not user_value:
            st.warning("Type an answer.")
            return None
        ok = normalize(user_value) in {normalize(a) for a in q["answer_text"]}
    else:
        return None

    if ok:
        st.success("✅ Correct!")
    else:
        st.error(f"❌ Not quite. Correct: **{correct_answer_text(q)}**")

    if q.get("explanation"):
        with st.expander("Why?"):
            st.write(q["explanation"])
    return ok


def record_attempt(q: Dict[str, Any], user_value, ok: bool):
    if st.session_state.graded_current:
        return
    st.session_state.attempts.append(
        {
            "id": q["id"],
            "prompt": q["prompt"],
            "type": q["type"],
            "user_answer": user_value_to_text(q, user_value),
            "correct_answer": correct_answer_text(q),
            "is_correct": ok,
            "explanation": q.get("explanation", ""),
        }
    )
    st.session_state.graded_current = True


# ----------------- Certificate (PDF) -----------------
def build_certificate_pdf(
    student_name: str, quiz_title: str, score: int, total: int
) -> bytes:
    """Return PDF bytes for a simple certificate."""
    if not student_name.strip():
        student_name = "Student"
    if not quiz_title.strip():
        quiz_title = "Quiz"

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Border
    margin = 1.5 * cm
    c.setStrokeColor(colors.HexColor("#444444"))
    c.setLineWidth(3)
    c.rect(margin, margin, width - 2 * margin, height - 2 * margin)

    # Header
    c.setFillColor(colors.HexColor("#222222"))
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 3 * cm, "Certificate of Achievement")

    # Subheader line
    c.setStrokeColor(colors.HexColor("#888888"))
    c.setLineWidth(1)
    c.line(width / 2 - 5 * cm, height - 3.4 * cm, width / 2 + 5 * cm, height - 3.4 * cm)

    # Body
    c.setFillColor(colors.HexColor("#333333"))
    c.setFont("Helvetica", 14)
    text_y = height - 6 * cm
    c.drawCentredString(width / 2, text_y, "This is to certify that")
    text_y -= 1.0 * cm

    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(colors.HexColor("#000000"))
    c.drawCentredString(width / 2, text_y, student_name)
    text_y -= 1.4 * cm

    c.setFont("Helvetica", 14)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawCentredString(width / 2, text_y, "has successfully completed the quiz")
    text_y -= 1.0 * cm

    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(colors.HexColor("#000000"))
    c.drawCentredString(width / 2, text_y, quiz_title)
    text_y -= 1.2 * cm

    c.setFont("Helvetica", 14)
    c.setFillColor(colors.HexColor("#333333"))
    c.drawCentredString(width / 2, text_y, f"Score: {score} / {total}")
    text_y -= 1.2 * cm

    # Footer
    c.setFont("Helvetica-Oblique", 10)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawCentredString(
        width / 2, 2.2 * cm, "Generated by Hostel Learning Hub • Streamlit"
    )

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


# ----------------- Results UI -----------------
def show_results(meta: Dict[str, Any], total: int):
    st.write("---")
    st.subheader("Results")
    st.metric("Score", f"{st.session_state.score} / {total}")
    st.progress(st.session_state.score / max(total, 1))
    st.balloons()

    st.markdown("### Review — Questions & Solutions")
    for i, a in enumerate(st.session_state.attempts, start=1):
        ok = a["is_correct"]
        status = "✅" if ok else "❌"
        with st.expander(f"{status} Q{i}: {a['prompt']}", expanded=not ok):
            st.markdown(f"**Your answer:** {a['user_answer'] or '—'}")
            st.markdown(f"**Correct answer:** {a['correct_answer']}")
            if a.get("explanation"):
                st.markdown(f"**Explanation:** {a['explanation']}")

    student_name =st.session_state["student_name"]
    # --- Certificate PDF download ---
    quiz_title = (
        meta.get("title")
        or Path(st.session_state.quiz_path).stem.replace("_", " ").title()
    )
    pdf_bytes = build_certificate_pdf(
        student_name, quiz_title, st.session_state.score, total
    )
    st.download_button(
        "🎓 Download Certificate (PDF)",
        data=pdf_bytes,
        file_name=f"certificate_{student_name.replace(' ', '_')}_{quiz_title.replace(' ', '_')}.pdf",
        mime="application/pdf",
    )

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

    # Selection screen
    if not st.session_state.quiz_path:
        st.subheader("Choose a quiz")

        # Ask for student name here once
        student_name = st.text_input(
            "Your name (for certificate)", placeholder="e.g., Kajal Patil"
        )

        st.session_state["student_name"] = student_name

        items = list_quizzes()
        if not items:
            st.info("No quizzes found. Add *.json files to the 'quizzes' folder.")
            return

        labels = [lbl for (lbl, _p, _t) in items]
        choice = st.selectbox("Available quizzes", labels, index=0)
        if st.button("Start"):
            path = (
                dict(items)[choice]
                if isinstance(items, dict)
                else items[labels.index(choice)][1]
            )
            st.session_state.quiz_path = str(path)
            reset_run()
            st.session_state.allow_next = False
            st.rerun()

        idx = labels.index(choice)
        meta_path = items[idx][1]
        try:
            data = load_quiz_json(meta_path)
            meta = data.get("meta", {})
            st.caption(
                f"**Title:** {meta.get('title', meta_path.stem)}  |  "
                f"**Subject:** {meta.get('subject', '—')}  |  "
                f"**Questions:** {len(data.get('questions', []))}"
            )
        except Exception as e:
            st.error(f"Error reading quiz: {e}")
        return

    # Run a chosen quiz
    try:
        data = load_quiz_json(Path(st.session_state.quiz_path))
    except Exception as e:
        st.error(f"Failed to load quiz: {e}")
        st.session_state.quiz_path = None
        return

    meta = data.get("meta", {})
    questions: List[Dict[str, Any]] = data["questions"]
    total = len(questions)
    if total == 0:
        st.warning("This quiz has no questions.")
        if st.button("Back"):
            st.session_state.quiz_path = None
        return

    # Finished?
    if st.session_state.idx >= total:
        show_results(meta, total)
        return

    # Current question
    q = questions[st.session_state.idx]
    st.caption(f"{meta.get('title', Path(st.session_state.quiz_path).stem)}")
    st.progress(st.session_state.idx / total)
    st.caption(f"Question {st.session_state.idx + 1} of {total}")

    user_value = render_question(q)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Check"):
            graded = check_question(q, user_value)
            if graded is not None:
                if not st.session_state.graded_current:
                    if graded:
                        st.session_state.score += 1
                    record_attempt(q, user_value, graded)
                st.session_state.allow_next = True

    with col2:
        if st.button("Next ➡️", disabled=not st.session_state.allow_next):
            st.session_state.idx += 1
            st.session_state.graded_current = False
            st.session_state.allow_next = False
            st.rerun()


if __name__ == "__main__":
    main()
