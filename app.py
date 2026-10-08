import os
import re
import json
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st
from sarvamai import SarvamAI

# ============================================================
# MAPMYFUTURE - AI CAREER PLANNER FOR HIGH SCHOOL STUDENTS
# ============================================================

st.set_page_config(page_title="MapMyFuture", layout="wide")

API_KEY = None

try:
    API_KEY = st.secrets.get("SARVAM_API_KEY")
except Exception:
    API_KEY = None

if not API_KEY:
    API_KEY = os.getenv("SARVAM_API_KEY")

if not API_KEY:
    st.error("Sarvam API key not found.")
    st.info("For Streamlit Cloud, add SARVAM_API_KEY in App Settings → Secrets. For local use, set SARVAM_API_KEY as an environment variable.")
    st.stop()

client = SarvamAI(api_subscription_key=API_KEY)
MODEL = "sarvam-105b"
DB_NAME = "mapmyfuture_v2.db"


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_database():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT,
            stream TEXT,
            career TEXT,
            plan_json TEXT,
            meta_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_database()


def save_plan(meta, plan):
    conn = get_connection()
    conn.execute(
        "INSERT INTO plans (student_name, stream, career, plan_json, meta_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            meta["name"],
            meta["stream"],
            meta["career"],
            json.dumps(plan),
            json.dumps(meta),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()


def get_plans():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM plans ORDER BY id DESC", conn)
    conn.close()
    return df


# ============================================================
# AI CORE HELPERS
# ============================================================

def ask_text(prompt, think=False):
    response = client.chat.completions(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        reasoning_effort="low" if think else None,
    )
    text = response.choices[0].message.content or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def extract_json(text):
    text = text.replace("```json", "").replace("```", "")
    start, end = text.find("{"), text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(
            "The AI reply did not contain JSON. Raw reply was: "
            + repr(text[:300])
        )

    return json.loads(text[start:end + 1])


def ask_json(prompt, tries=3):
    last_error = None

    for _ in range(tries):
        try:
            return extract_json(ask_text(prompt))
        except Exception as e:
            last_error = e

    raise last_error


# ============================================================
# AI FEATURE 1: CAREER PLAN
# ============================================================

PLAN_SCHEMA = """
{
  "paths": [
    {
      "name": "short path name",
      "years": 4,
      "steps": [
        "Class 11: stream",
        "undergraduate degree",
        "exam or training",
        "dream career"
      ],
      "cost": {
        "tuition": 0,
        "accommodation": 0,
        "materials": 0
      },
      "colleges": [
        "college 1",
        "college 2",
        "college 3"
      ],
      "entry": "entrance exams and typical eligibility",
      "timeline": "when to apply",
      "alt": {
        "steps": [
          "Class 11: stream",
          "backup degree",
          "bridge step",
          "same or similar career"
        ],
        "note": "why this backup route works"
      }
    }
  ]
}
"""


def generate_plan(stream, interests, career, marks, change=""):
    situation = ""

    if change:
        situation = (
            f"IMPORTANT: The student's situation has changed: {change}\n"
            "Re-plan with realistic routes that fit this new situation.\n\n"
        )

    prompt = (
        "You are MapMyFuture AI, a career counsellor for Indian high school students.\n\n"
        f"Stream of interest: {stream}\n"
        f"Interests: {interests}\n"
        f"Dream career: {career}\n"
        f"Expected marks (%): {marks}\n\n"
        + situation
        + "Create 2 or 3 distinct pathways from Class 11 to this dream career.\n"
        "Each path must have exactly 4 steps and a backup route (alt) in case the "
        "student misses a cut-off or changes their mind.\n"
        "Costs are TOTAL estimates in Indian Rupees (INR) over the whole course, "
        "as plain integers.\n"
        "Only mention real, well-known colleges, exams and degrees. If unsure about "
        "a detail, keep it general.\n\n"
        "Return ONLY valid JSON in exactly this format, with no extra text:\n"
        + PLAN_SCHEMA
    )

    plan = ask_json(prompt)

    if not plan.get("paths"):
        raise ValueError("The AI did not return any pathways.")

    return plan


# ============================================================
# AI FEATURE 1B: SPECIFIC COLLEGES & UNIVERSITIES
# ============================================================

COLLEGE_SCHEMA = """
{
  "india": [
    {
      "name": "full official college or university name",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    },
    {
      "name": "full official college or university name",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    },
    {
      "name": "full official college or university name",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    }
  ],
  "abroad": [
    {
      "name": "full official college or university name",
      "country": "country",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    },
    {
      "name": "full official college or university name",
      "country": "country",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    },
    {
      "name": "full official college or university name",
      "country": "country",
      "course": "relevant course or degree",
      "reason": "short reason why it fits the career"
    }
  ]
}
"""


def generate_colleges(career, stream, interests, path):
    prompt = (
        "You are an expert university and college counsellor.\n\n"
        f"Student stream: {stream}\n"
        f"Student interests: {interests}\n"
        f"Dream career: {career}\n"
        f"Selected pathway: {path.get('name')}\n"
        f"Path steps: {path.get('steps')}\n\n"

        "Recommend EXACTLY 3 specific, real colleges or universities in India "
        "and EXACTLY 3 specific, real universities or colleges abroad.\n\n"

        "IMPORTANT RULES:\n"
        "1. Give the FULL and SPECIFIC official name of every institution.\n"
        "2. Never write generic names such as 'top college', 'good university', "
        "'reputed college', 'college 1', 'college 2', or 'college 3'.\n"
        "3. Every institution must actually offer a relevant course for the "
        "student's career.\n"
        "4. For India, give exactly 3 institutions.\n"
        "5. For abroad, give exactly 3 institutions.\n"
        "6. For abroad, include the country.\n"
        "7. Use real institutions only. Do not invent universities.\n"
        "8. Give a relevant degree/course for each institution.\n"
        "9. Keep the reason short and useful for a Class 11 student.\n"
        "10. Do not use placeholders.\n"
        "11. Do not return generic descriptions instead of institution names.\n\n"

        "Return ONLY valid JSON in exactly this format, with no extra text:\n"
        + COLLEGE_SCHEMA
    )

    result = ask_json(prompt)

    if not result.get("india"):
        raise ValueError("AI did not return Indian colleges.")

    if not result.get("abroad"):
        raise ValueError("AI did not return abroad universities.")

    return result


# ============================================================
# AI FEATURE 2: SCHOLARSHIP MATCHER
# ============================================================

SCH_SCHEMA = """
{
  "scholarships": [
    {
      "name": "scholarship name",
      "provider": "who offers it",
      "amount_per_year": 0,
      "eligibility": "short eligibility summary",
      "how_to_apply": "short how-to-apply note"
    }
  ]
}
"""


def match_scholarships(meta, path):
    prompt = (
        "You are a financial-aid advisor for Indian students.\n\n"
        f"Student marks: {meta['marks']}%\n"
        f"Family income: Rs. {meta['income']} lakh per year\n"
        f"Category: {meta['category']}\n"
        f"Planned course path: {path.get('name')} - steps: {path.get('steps')}\n\n"
        "List up to 5 REAL, well-known scholarships, fee waivers or education loan "
        "schemes in India this student could realistically apply for "
        "(government, university or private).\n"
        "Do not invent schemes. Give amount_per_year as a conservative integer in INR "
        "(use 0 if it is not a fixed amount).\n\n"
        "Return ONLY valid JSON in exactly this format, with no extra text:\n"
        + SCH_SCHEMA
    )

    return ask_json(prompt).get("scholarships", [])


# ============================================================
# AI FEATURE 3: DAY-IN-THE-LIFE SIMULATION
# ============================================================

def new_scenario(career):
    prompt = (
        f"Create a short, realistic day-in-the-life work scenario for a person "
        f"working as: {career}.\n"
        "It should take about 2 minutes to answer, with no jargon, suitable for a "
        "Class 11 student, and there should be no single obviously correct answer.\n\n"
        'Return ONLY valid JSON: {"scenario": "the situation and the question", '
        '"skill_tested": "main skill this tests"}'
    )

    return ask_json(prompt)


def evaluate_answer(career, scenario, answer):
    prompt = (
        f"A Class 11 student is trying a mini job simulation for: {career}.\n\n"
        f"Scenario: {scenario}\n"
        f"Student's answer: {answer}\n\n"
        "Evaluate kindly but honestly.\n"
        "Return ONLY valid JSON in exactly this format:\n"
        '{"score": 7, "feedback": "what they did well and what to improve", '
        '"what_a_pro_would_do": "short professional approach", '
        '"fit_comment": "one line on whether this suggests they may enjoy this career"}\n'
        "score is an integer from 1 to 10."
    )

    return ask_json(prompt)


# ============================================================
# AI FEATURE 4: COUNSELLOR CHAT
# ============================================================

def counsellor_reply(history, question, meta, plan):
    context = "No plan generated yet."

    if meta and plan:
        brief = [
            {
                "name": p.get("name"),
                "steps": p.get("steps"),
                "cost": p.get("cost"),
            }
            for p in plan.get("paths", [])
        ]

        context = (
            f"Student: {meta.get('name')}, "
            f"stream: {meta.get('stream')}, "
            f"dream career: {meta.get('career')}, "
            f"marks: {meta.get('marks')}%.\n"
            f"Their generated pathways: {json.dumps(brief)}"
        )

    transcript = ""

    for m in history[-8:]:
        who = "Student" if m["role"] == "user" else "Counsellor"
        transcript += f"{who}: {m['content']}\n"

    prompt = (
        "You are MapMyFuture AI Counsellor, a warm, honest career counsellor for "
        "Indian high school students.\n"
        "Rules: be practical and encouraging, never invent exact cut-offs or fees "
        "(tell the student to confirm on official websites), keep answers short and "
        "clear, and reply in the same language the student writes in "
        "(English, Hindi or another Indian language).\n\n"
        f"Student context:\n{context}\n\n"
        f"Conversation so far:\n{transcript}\n"
        f"Student: {question}\n"
        "Counsellor:"
    )

    return ask_text(prompt)


# ============================================================
# AI FEATURE 5: CAREER INTEREST QUIZ  (NEW)
# ============================================================

QUIZ_SCHEMA = """
{
  "questions": [
    {
      "question": "a short, friendly question about the student's interests or style",
      "options": ["option A", "option B", "option C", "option D", "option E"]
    }
  ]
}
"""

QUIZ_RESULT_SCHEMA = """
{
  "summary": "2 sentences describing the student's interests and strengths",
  "careers": [
    {
      "name": "career name",
      "stream": "Arts, Science or Commerce",
      "why": "one or two sentences linking this career to their answers",
      "next_step": "one practical thing to do this month"
    }
  ]
}
"""


def generate_quiz():
    prompt = (
        "You are a career counsellor for Indian Class 10 and Class 11 students.\n\n"
        "Create a fun career interest quiz of EXACTLY 30 multiple-choice questions.\n"
        "Rules:\n"
        "1. Questions cover interests, favourite school subjects, working style "
        "(alone or in a team), problem-solving style, and what the student enjoys "
        "doing in free time.\n"
        "2. Each question has EXACTLY 5 short options.\n"
        "3. There are no right or wrong answers.\n"
        "4. Use simple English that a 15-year-old understands.\n"
        "5. Do not mention specific careers in the questions.\n\n"
        "Return ONLY valid JSON in exactly this format, with no extra text:\n"
        + QUIZ_SCHEMA
    )

    result = ask_json(prompt)

    if not result.get("questions"):
        raise ValueError("The AI did not return any quiz questions.")

    # Keep the quiz at exactly 30 questions even if the AI returns extra questions.
    result["questions"] = result["questions"][:30]

    if len(result["questions"]) != 30:
        raise ValueError("The AI did not return exactly 30 quiz questions.")

    return result


def analyse_quiz(questions, picked):
    qa = ""

    for i, q in enumerate(questions):
        qa += f"Q{i + 1}. {q.get('question', '')}\nAnswer: {picked[i]}\n\n"

    prompt = (
        "You are a career counsellor for Indian high school students.\n\n"
        "A student took a career interest quiz. Here are the questions and "
        "their answers:\n\n"
        + qa
        + "Based ONLY on these answers, suggest EXACTLY 3 careers that fit this "
        "student and the Indian stream (Arts, Science or Commerce) usually needed "
        "for each.\n"
        "Be encouraging and practical. Do not promise outcomes.\n\n"
        "Return ONLY valid JSON in exactly this format, with no extra text:\n"
        + QUIZ_RESULT_SCHEMA
    )

    result = ask_json(prompt)

    if not result.get("careers"):
        raise ValueError("The AI did not return any career suggestions.")

    return result


# ============================================================
# HELPERS
# ============================================================

def to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def inr(n):
    return "Rs. {:,}".format(int(n))


def build_dot(plan, selected, use_alt):
    def esc(t):
        return str(t).replace('"', "'").replace("\\", "")

    lines = [
        "digraph G {",
        "rankdir=LR;",
        'node [shape=box, style="rounded,filled", fillcolor="#eef2ff", '
        'color="#4f46e5", fontname="Helvetica"];',
        'edge [color="#9aa3b8"];',
        'you [label="You", shape=circle, fillcolor="#4f46e5", fontcolor="white"];',
    ]

    for i, p in enumerate(plan["paths"]):
        steps = None

        if use_alt:
            steps = (p.get("alt") or {}).get("steps")

        steps = steps or p.get("steps", [])

        base = "#c7d2fe" if i == selected else "#eef2ff"
        path_name = esc(p.get("name", ""))
        prev = "you"

        for j, s in enumerate(steps):
            nid = f"p{i}s{j}"
            fill = "#dcfce7" if j == len(steps) - 1 else base

            lines.append(
                f'{nid} [label="{esc(s)}", fillcolor="{fill}"];'
            )

            if j == 0:
                lines.append(
                    f'{prev} -> {nid} [label="{path_name}"];'
                )
            else:
                lines.append(f"{prev} -> {nid};")

            prev = nid

    lines.append("}")

    return "\n".join(lines)


def reset_plan_state():
    st.session_state["sch"] = {}
    st.session_state["scenario"] = None
    st.session_state["eval"] = None


def plan_this_career(career_name, stream_name):
    # Runs when the "Plan this career" button is clicked on the quiz page.
    st.session_state["next_page"] = "Plan My Future"
    st.session_state["career_input"] = career_name

    for option in ["Arts", "Science", "Commerce"]:
        if option.lower() in str(stream_name).lower():
            st.session_state["stream_input"] = option
            break


# ============================================================
# SIDEBAR
# ============================================================

# Handle navigation requested by buttons before the sidebar radio.
if "next_page" in st.session_state:
    st.session_state["page_selector"] = st.session_state.pop("next_page")

with st.sidebar:
    st.markdown("# MapMyFuture")
    st.caption("See your whole journey, not just the next step.")
    st.divider()

    page = st.radio(
        "Navigation",
        ["Plan My Future", "Career Quiz", "AI Counsellor", "Saved Plans", "About"],
        key="page_selector",
    )

    st.divider()
    st.caption("Powered by Sarvam AI")


# ============================================================
# PAGE: PLAN MY FUTURE
# ============================================================

if page == "Plan My Future":

    st.title("MapMyFuture")
    st.write(
        "Tell us your interests. We will map the path from Class 11 to your dream career."
    )
    st.divider()

    # Small option added without changing the existing app layout.
    def open_career_quiz():
        st.session_state["next_page"] = "Career Quiz"

    if st.button(
        "Not sure about your career? Take the Career Quiz",
        on_click=open_career_quiz,
    ):
        st.rerun()

    with st.form("plan_form"):

        name = st.text_input(
            "Your name",
            placeholder="Example: Aryan",
        )

        c1, c2 = st.columns(2)

        with c1:
            stream = st.selectbox(
                "Stream of interest",
                ["Arts", "Science", "Commerce", "Not sure yet"],
                key="stream_input",
            )

        with c2:
            career = st.text_input(
                "Dream career",
                placeholder="Example: Teacher, Software Engineer, CA",
                key="career_input",
            )

        interests = st.text_area(
            "What do you enjoy?",
            placeholder=(
                "Example: I like explaining things to friends and reading history."
            ),
            height=100,
        )

        c3, c4, c5 = st.columns(3)

        with c3:
            marks = st.number_input(
                "Expected marks (%)",
                0,
                100,
                85,
            )

        with c4:
            income = st.number_input(
                "Family income (Rs. lakh / year)",
                0.0,
                100.0,
                4.0,
                step=0.5,
            )

        with c5:
            category = st.selectbox(
                "Category",
                ["General", "OBC", "SC", "ST", "EWS"],
            )

        submitted = st.form_submit_button("Generate my map")

    if submitted:

        if not name or not career:
            st.warning("Please fill in your name and dream career.")

        else:

            with st.spinner("MapMyFuture AI is planning your journey..."):

                try:
                    st.session_state["plan"] = generate_plan(
                        stream,
                        interests,
                        career,
                        marks,
                    )

                    st.session_state["meta"] = {
                        "name": name,
                        "stream": stream,
                        "career": career,
                        "interests": interests,
                        "marks": marks,
                        "income": income,
                        "category": category,
                    }

                    reset_plan_state()

                except Exception as e:
                    st.error(
                        "Something went wrong while generating your plan. Please try again."
                    )
                    st.code(str(e))

    # ========================================================
    # RESULTS
    # ========================================================

    if "plan" in st.session_state:

        plan = st.session_state["plan"]
        meta = st.session_state["meta"]
        paths = plan["paths"]

        st.divider()

        st.header(
            f"{meta['name']}'s journey to: {meta['career']}"
        )

        top1, top2 = st.columns([3, 1])

        with top1:

            names = [
                p.get("name", f"Path {i + 1}")
                for i, p in enumerate(paths)
            ]

            chosen = st.radio(
                "Choose a pathway to explore",
                names,
                horizontal=True,
            )

        with top2:

            use_alt = st.toggle(
                "I missed the cut-off / changed my mind"
            )

        idx = names.index(chosen)
        path = paths[idx]

        # ====================================================
        # CAREER MAP
        # ====================================================

        st.subheader("Your career map")

        st.graphviz_chart(
            build_dot(plan, idx, use_alt)
        )

        if use_alt:
            st.warning(
                "Backup route: "
                + (path.get("alt") or {}).get(
                    "note",
                    "Alternative path shown.",
                )
            )

        # ====================================================
        # COST + COLLEGES
        # ====================================================

        cost = path.get("cost", {})

        tuition = to_int(cost.get("tuition"))
        stay = to_int(cost.get("accommodation"))
        books = to_int(cost.get("materials"))

        total = tuition + stay + books
        years = to_int(path.get("years")) or 1

        left, right = st.columns(2)

        with left:

            st.subheader("Total Cost of the Dream")

            st.metric(
                f"Over {years} years",
                inr(total),
            )

            chart_df = pd.DataFrame(
                {"INR": [tuition, stay, books]},
                index=[
                    "Tuition",
                    "Accommodation",
                    "Materials",
                ],
            )

            st.bar_chart(chart_df)

            st.caption(
                "AI estimates. Always confirm fees on the college website."
            )

        with right:

            st.subheader("Colleges and entry")

            for c in path.get("colleges", []):
                st.write("- " + str(c))

            st.write(
                "**Entry:** "
                + str(
                    path.get(
                        "entry",
                        "Check official websites.",
                    )
                )
            )

            st.write(
                "**Timeline:** "
                + str(
                    path.get(
                        "timeline",
                        "Check official websites.",
                    )
                )
            )

        # ====================================================
        # SPECIFIC COLLEGE & UNIVERSITY RECOMMENDATIONS
        # ====================================================

        st.subheader("🎓 Specific Colleges & Universities")

        st.write(
            "Get specific college and university names in India and abroad "
            "that match this career pathway."
        )

        college_cache = st.session_state.setdefault(
            "college_recommendations",
            {},
        )

        college_key = (
            f"{meta['career']}|"
            f"{path.get('name')}|"
            f"{meta.get('stream')}|"
            f"{meta.get('interests', '')}"
        )

        if st.button(
            "Find specific colleges & universities",
            key=f"find_colleges_{idx}",
        ):

            with st.spinner(
                "Finding suitable colleges in India and abroad..."
            ):

                try:

                    college_cache[college_key] = generate_colleges(
                        meta["career"],
                        meta["stream"],
                        meta.get("interests", ""),
                        path,
                    )

                except Exception as e:

                    st.error(
                        "Could not find college recommendations. Please try again."
                    )

                    st.code(str(e))

        college_data = college_cache.get(college_key)

        if college_data:

            # =================================================
            # INDIA
            # =================================================

            st.markdown("### 🇮🇳 India")

            india_colleges = college_data.get(
                "india",
                [],
            )

            for college in india_colleges:

                st.markdown(
                    f"**🎓 {college.get('name', 'University name unavailable')}**"
                )

                st.write(
                    f"**Course:** "
                    f"{college.get('course', 'Relevant course')}"
                )

                st.write(
                    f"**Why:** "
                    f"{college.get('reason', '-')}"
                )

                st.divider()

            # =================================================
            # ABROAD
            # =================================================

            st.markdown("### 🌍 Abroad")

            abroad_colleges = college_data.get(
                "abroad",
                [],
            )

            for university in abroad_colleges:

                st.markdown(
                    f"**🌎 {university.get('name', 'University name unavailable')}**"
                )

                st.write(
                    f"**Country:** "
                    f"{university.get('country', '-')}"
                )

                st.write(
                    f"**Course:** "
                    f"{university.get('course', 'Relevant course')}"
                )

                st.write(
                    f"**Why:** "
                    f"{university.get('reason', '-')}"
                )

                st.divider()

            st.caption(
                "AI-generated recommendations. Always verify courses, eligibility, "
                "admission requirements and fees on the institution's official website."
            )

        # ====================================================
        # AI SCHOLARSHIP MATCHER
        # ====================================================

        st.subheader("AI Scholarship Matcher")

        cache = st.session_state.setdefault(
            "sch",
            {},
        )

        key = (
            f"{meta['career']}|"
            f"{path.get('name')}|"
            f"{meta['marks']}|"
            f"{meta['income']}|"
            f"{meta['category']}"
        )

        if st.button("Find scholarships with AI"):

            with st.spinner(
                "Searching for aid options that fit your profile..."
            ):

                try:

                    cache[key] = match_scholarships(
                        meta,
                        path,
                    )

                except Exception as e:

                    st.error(
                        "Could not fetch scholarships. Please try again."
                    )

                    st.code(str(e))

        items = cache.get(key)

        if items:

            saving = 0

            for s in items:

                amt = to_int(
                    s.get("amount_per_year")
                )

                saving += amt * years

                amount_text = (
                    inr(amt) + " / year"
                    if amt
                    else "amount varies"
                )

                st.markdown(
                    f"**{s.get('name', 'Scholarship')}** "
                    f"({s.get('provider', '')}) - {amount_text}\n\n"
                    f"Eligibility: {s.get('eligibility', '-')}\n\n"
                    f"How to apply: {s.get('how_to_apply', '-')}"
                )

            saving = min(
                total,
                saving,
            )

            st.info(
                f"Estimated cost after aid, if you win all of them: "
                f"{inr(total - saving)} "
                f"(saves {inr(saving)})"
            )

            st.caption(
                "AI suggestions. Verify every scheme on its official website before applying."
            )

        # ====================================================
        # AI SIMULATION
        # ====================================================

        st.subheader(
            "Day-in-the-life mini simulation"
        )

        if st.button("Give me a scenario"):

            with st.spinner(
                "Creating a scenario..."
            ):

                try:

                    st.session_state["scenario"] = new_scenario(
                        meta["career"]
                    )

                    st.session_state["eval"] = None
                    st.session_state["sim_answer"] = ""

                except Exception as e:

                    st.error(
                        "Could not create a scenario. Please try again."
                    )

                    st.code(str(e))

        sc = st.session_state.get(
            "scenario"
        )

        if sc:

            st.write(
                sc.get(
                    "scenario",
                    "",
                )
            )

            st.caption(
                "Skill tested: "
                + str(
                    sc.get(
                        "skill_tested",
                        "",
                    )
                )
            )

            answer = st.text_area(
                "What would you do?",
                key="sim_answer",
                height=100,
            )

            if st.button("Get AI feedback"):

                if not answer.strip():

                    st.warning(
                        "Write your answer first."
                    )

                else:

                    with st.spinner(
                        "AI is reviewing your answer..."
                    ):

                        try:

                            st.session_state["eval"] = evaluate_answer(
                                meta["career"],
                                sc.get(
                                    "scenario",
                                    "",
                                ),
                                answer,
                            )

                        except Exception as e:

                            st.error(
                                "Could not evaluate your answer. Please try again."
                            )

                            st.code(str(e))

            ev = st.session_state.get(
                "eval"
            )

            if ev:

                st.metric(
                    "Your score",
                    f"{to_int(ev.get('score'))}/10",
                )

                st.success(
                    str(
                        ev.get(
                            "feedback",
                            "",
                        )
                    )
                )

                st.info(
                    "A professional would: "
                    + str(
                        ev.get(
                            "what_a_pro_would_do",
                            "",
                        )
                    )
                )

                st.write(
                    "**Do you fit this career?** "
                    + str(
                        ev.get(
                            "fit_comment",
                            "",
                        )
                    )
                )

        # ====================================================
        # AI RE-ROUTE
        # ====================================================

        st.subheader(
            "Plans change? Let AI re-route you"
        )

        change = st.text_input(
            "What changed?",
            placeholder=(
                "Example: I scored only 65% in Class 10 "
                "and my family can spend less."
            ),
        )

        if st.button("Re-route my map"):

            if not change.strip():

                st.warning(
                    "Tell us what changed first."
                )

            else:

                with st.spinner(
                    "Re-planning your journey..."
                ):

                    try:

                        st.session_state["plan"] = generate_plan(
                            meta["stream"],
                            meta.get("interests", ""),
                            meta["career"],
                            meta["marks"],
                            change,
                        )

                        reset_plan_state()
                        st.rerun()

                    except Exception as e:

                        st.error(
                            "Could not re-route. Please try again."
                        )

                        st.code(str(e))

        st.divider()

        if st.button("Save this plan"):

            save_plan(
                meta,
                plan,
            )

            st.success(
                "Plan saved!"
            )


# ============================================================
# PAGE: CAREER QUIZ  (NEW)
# ============================================================

elif page == "Career Quiz":

    st.title("Career Interest Quiz")

    st.write(
        "Not sure what you want to be? Answer 30 quick questions and get career "
        "ideas that match your interests. There are no right or wrong answers."
    )

    if st.button("Start a new quiz"):

        with st.spinner("Creating your quiz..."):

            try:

                # clear old answers so the new quiz starts fresh
                for k in list(st.session_state.keys()):
                    if k.startswith("quiz_q_"):
                        del st.session_state[k]

                st.session_state["quiz"] = generate_quiz()
                st.session_state["quiz_result"] = None

            except Exception as e:

                st.error("Could not create the quiz. Please try again.")
                st.code(str(e))

    quiz = st.session_state.get("quiz")

    if quiz:

        questions = quiz.get("questions", [])[:30]

        with st.form("quiz_form"):

            picked = []

            for i, q in enumerate(questions):

                picked.append(
                    st.radio(
                        f"{i + 1}. {q.get('question', '')}",
                        q.get("options", []),
                        index=None,
                        key=f"quiz_q_{i}",
                    )
                )

            done = st.form_submit_button("See my results")

        if done:

            if any(p is None for p in picked):

                st.warning("Please answer every question first.")

            else:

                with st.spinner("Finding careers that fit you..."):

                    try:

                        st.session_state["quiz_result"] = analyse_quiz(
                            questions,
                            picked,
                        )

                    except Exception as e:

                        st.error(
                            "Could not analyse your answers. Please try again."
                        )

                        st.code(str(e))

    result = st.session_state.get("quiz_result")

    if result:

        st.divider()

        st.header("Your results")

        st.write(result.get("summary", ""))

        for n, c in enumerate(result.get("careers", [])):

            st.markdown(
                f"### {c.get('name', 'Career')}"
            )

            st.write(
                f"**Usual stream:** {c.get('stream', '-')}"
            )

            st.write(
                f"**Why it fits you:** {c.get('why', '-')}"
            )

            st.write(
                f"**Try this month:** {c.get('next_step', '-')}"
            )

            st.button(
                "Plan this career",
                key=f"plan_career_{n}",
                on_click=plan_this_career,
                args=(c.get("name", ""), c.get("stream", "")),
            )

            st.divider()

        st.info(
            "Like one of these careers? Click 'Plan this career' to jump to "
            "'Plan My Future' with it already filled in, then fill in your "
            "name and marks to see the full map."
        )

        st.caption(
            "This quiz is a starting point, not a verdict. Talk to your parents, "
            "teachers and school counsellor too."
        )


# ============================================================
# PAGE: AI COUNSELLOR
# ============================================================

elif page == "AI Counsellor":

    st.title("AI Career Counsellor")

    st.write(
        "Ask anything about streams, colleges, exams, fees or careers. "
        "You can write in English or an Indian language."
    )

    if "plan" not in st.session_state:

        st.info(
            "Tip: generate a plan first, so the counsellor knows your goals."
        )

    chat = st.session_state.setdefault(
        "chat",
        [],
    )

    for m in chat:

        with st.chat_message(
            m["role"]
        ):

            st.write(
                m["content"]
            )

    question = st.chat_input(
        "Example: Which is better for me, BCA or B.Tech?"
    )

    if question:

        chat.append(
            {
                "role": "user",
                "content": question,
            }
        )

        with st.spinner(
            "Counsellor is thinking..."
        ):

            try:

                reply = counsellor_reply(
                    chat[:-1],
                    question,
                    st.session_state.get("meta"),
                    st.session_state.get("plan"),
                )

            except Exception as e:

                reply = (
                    "Sorry, I could not answer right now. "
                    "Please try again. ("
                    + str(e)
                    + ")"
                )

        chat.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        st.rerun()

    if chat and st.button("Clear chat"):

        st.session_state["chat"] = []

        st.rerun()


# ============================================================
# PAGE: SAVED PLANS
# ============================================================

elif page == "Saved Plans":

    st.title("Saved Plans")

    plans = get_plans()

    if len(plans) == 0:

        st.info(
            "No plans saved yet."
        )

    else:

        for _, row in plans.iterrows():

            with st.expander(
                f"{row['student_name']} - "
                f"{row['career']} "
                f"({row['created_at']})"
            ):

                st.write(
                    f"**Stream:** {row['stream']}"
                )

                if st.button(
                    "Open this plan",
                    key=f"open_{row['id']}",
                ):

                    st.session_state["plan"] = json.loads(
                        row["plan_json"]
                    )

                    st.session_state["meta"] = json.loads(
                        row["meta_json"]
                    )

                    reset_plan_state()

                    st.success(
                        "Loaded. Go to 'Plan My Future' to see it."
                    )


# ============================================================
# PAGE: ABOUT
# ============================================================

elif page == "About":

    st.title("About MapMyFuture")

    st.markdown("""
MapMyFuture is an AI-powered visual career-planning app for high school students.
Most students only think about the next step, such as which stream to choose after
Class 10. MapMyFuture helps you see your **whole journey**: from Class 11, through
college and entrance exams, all the way to your dream career, along with what it
may cost and how you can reduce that cost.

### Who is it for?
- Students in Class 10 to Class 12 who are choosing a stream or a career
- Students who are not sure what they want to do yet
- Parents and teachers who want a simple way to discuss options with a student

### How to use it
1. **Not sure about your career?** Open **Career Quiz**, answer 30 quick questions,
   and get 3 career ideas that match your interests.
2. **Know your dream career?** Go to **Plan My Future**, fill in your details,
   and click **Generate my map**.
3. Explore the pathways, costs, colleges, scholarships and the mini simulation.
4. Ask any follow-up question in **AI Counsellor**.
5. Click **Save this plan** to open it again later from **Saved Plans**.

### What each feature does
- **Career map:** A visual mind map of 2 to 3 different pathways from Class 11 to
  your dream career. Each pathway has a backup route you can switch on if you miss
  a cut-off or change your mind.
- **Total Cost of the Dream:** An estimate of tuition, accommodation and study
  materials over the whole course, shown with a chart.
- **Colleges and entry:** The entrance exams, typical eligibility and when to apply
  for each pathway.
- **Specific colleges and universities:** Named colleges in India and universities
  abroad that offer a course for your career, with the course and a short reason.
- **Career Quiz:** A short interest quiz that suggests careers, the usual stream
  for each, and one thing to try this month. A "Plan this career" button takes you
  straight to the planner.
- **AI Scholarship Matcher:** Scholarships, fee waivers and education loan schemes
  that may suit your marks, family income and category, plus an estimate of your
  cost after aid.
- **Day-in-the-life simulation:** A short real-world work scenario for your career.
  You write what you would do and get a score, feedback and what a professional
  would do, so you can test whether you may enjoy the career.
- **Re-route my map:** Tell the app what changed, for example lower marks or less
  money, and it plans new routes that fit your new situation.
- **AI Counsellor:** A chat assistant that knows your plan. You can write in
  English, Hindi or another Indian language and it replies in the same language.
- **Saved Plans:** Keep your plans and come back to them any time.

### Please remember
- All results are generated by AI. Costs, fees, cut-offs, scholarships and course
  details are **estimates** and can be out of date or wrong.
- **Always confirm** details on the official website of the college, exam body or
  scholarship provider before you make a decision or apply.
- This app is a guide to help you think and plan. It is not a replacement for
  advice from your parents, teachers and school counsellor.

### Your data
- Plans you save, including your name, stream, dream career, marks, family income
  and category, are stored in a database file on the computer running the app.
- The career quiz answers are not saved.
- Your inputs are sent to Sarvam AI to generate the results.

### Technology
**Python + Streamlit + Sarvam AI + SQLite + Pandas**
""")