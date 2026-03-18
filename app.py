import os
os.environ["PYTHONUTF8"] = "1"

import re
import time
import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi

# ── API Key Rotation ─────────────────────────────────────────────────────────

def load_api_keys(path="api_keys.txt"):
    """Read non-empty lines from api_keys.txt — one key per line."""
    if not os.path.exists(path):
        st.error(f"'{path}' not found. Create it and add one Gemini API key per line.")
        st.stop()
    with open(path, "r") as f:
        keys = [line.strip() for line in f if line.strip()]
    if not keys:
        st.error(f"'{path}' is empty. Add at least one Gemini API key.")
        st.stop()
    return keys

def get_model():
    """Return a configured Gemini model using the current key."""
    keys = st.session_state["api_keys"]
    idx  = st.session_state["key_index"]
    genai.configure(api_key=keys[idx])
    return genai.GenerativeModel("gemini-2.5-flash")

def rotate_key():
    """Advance to the next key. Returns False if all keys exhausted."""
    keys     = st.session_state["api_keys"]
    next_idx = st.session_state["key_index"] + 1
    if next_idx >= len(keys):
        return False
    st.session_state["key_index"] = next_idx
    st.warning(f"⚠️ Rate limit hit — switched to API key {next_idx + 1} of {len(keys)}")
    return True

# ── Core helpers ─────────────────────────────────────────────────────────────

def extract_video_id(url):
    url = url.strip()
    patterns = [
        r"(?:v=)([0-9A-Za-z_-]{11})",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
        r"(?:shorts\/)([0-9A-Za-z_-]{11})",
        r"^([0-9A-Za-z_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_transcript(url):
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Could not extract video ID from URL.")
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join([s["text"] for s in transcript_list])
    except Exception:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id)
        return " ".join([s.text for s in transcript])

def query_gemini(transcript, prompt):
    """Call Gemini with automatic key rotation on ResourceExhausted / 429."""
    full_prompt = f"Here is the transcript of a YouTube video:\n\n{transcript}\n\n{prompt}"
    while True:
        try:
            model    = get_model()
            response = model.generate_content(full_prompt)
            return response.text
        except Exception as e:
            if "ResourceExhausted" in str(e) or "429" in str(e):
                if not rotate_key():
                    st.error("❌ All API keys have been rate limited. Please wait and try again later.")
                    st.stop()
                time.sleep(3)  # brief pause before retrying with new key
            else:
                raise e

# ── Parsers ──────────────────────────────────────────────────────────────────

def parse_quiz(raw):
    questions = []
    blocks = re.split(r'Q\d+:', raw)[1:]
    for block in blocks:
        lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 5:
            continue
        question = lines[0]
        options  = {}
        answer   = None
        for line in lines[1:]:
            m = re.match(r'^([A-D])[).]\s+(.*)', line)
            if m:
                options[m.group(1)] = m.group(2)
            ans = re.match(r'Answer:\s*([A-D])', line)
            if ans:
                answer = ans.group(1)
        if question and len(options) == 4 and answer:
            questions.append({"question": question, "options": options, "answer": answer})
    return questions

def parse_flashcards(raw):
    cards  = []
    blocks = re.split(r'CARD\s*\d+:', raw, flags=re.IGNORECASE)[1:]
    for block in blocks:
        parts = re.split(r'Back:', block, flags=re.IGNORECASE)
        if len(parts) == 2:
            front = re.sub(r'(?i)front:', '', parts[0]).strip()
            back  = parts[1].strip()
            if front and back:
                cards.append({"front": front, "back": back})
    return cards

# ── Prompts ───────────────────────────────────────────────────────────────────

SUMMARY_PROMPT = """
Based on this transcript:
1. Write a concise summary (4-6 sentences) of the entire video.
2. List the 8-10 most important key concepts as bullet points.
3. List 3-5 key takeaways the viewer should remember.
"""

QUIZ_PROMPT = """
Based on this transcript, generate exactly 12 multiple choice questions covering the most important concepts.
Format EVERY question exactly like this with no deviations:

Q1: <question text>
A) <option>
B) <option>
C) <option>
D) <option>
Answer: <correct letter only>

Q2: ...and so on up to Q12.
"""

FLASHCARD_PROMPT = """
Based on this transcript, generate exactly 10 flashcards for studying the key concepts.
Format EVERY flashcard exactly like this with no deviations:

CARD 1:
Front: <concept, term, or question>
Back: <clear concise explanation or answer>

CARD 2:
Front: ...
Back: ...

Continue for all 10 cards.
"""

CONCEPT_MAP_PROMPT = """
Based on this transcript, produce a detailed concept map in plain text.
Format it like this:

[Main Topic]
├── [Subtopic 1]
│   ├── [Detail]
│   └── [Detail]
├── [Subtopic 2]
│   ├── [Detail]
│   └── [Detail]
└── [Subtopic 3]
    ├── [Detail]
    └── [Detail]

Include all major concepts and how they connect.
"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="Video Insight", page_icon="🎬", layout="wide")

    # Initialise key pool once per session
    if "api_keys" not in st.session_state:
        st.session_state["api_keys"]  = load_api_keys("api_keys.txt")
        st.session_state["key_index"] = 0

    st.markdown("""
    <style>
        .main { background-color: #0f1117; }
        .stTabs [data-baseweb="tab"] { font-size: 16px; font-weight: 600; }
        .card-box {
            background: #1e2130;
            border-radius: 16px;
            padding: 30px;
            text-align: center;
            font-size: 22px;
            font-weight: 500;
            min-height: 160px;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid #3a3f5c;
            margin-bottom: 12px;
        }
        .correct { background: #1a3a2a; border: 1px solid #2ecc71; border-radius: 10px; padding: 10px 16px; }
        .wrong   { background: #3a1a1a; border: 1px solid #e74c3c; border-radius: 10px; padding: 10px 16px; }
        .score-box {
            background: #1e2130;
            border-radius: 16px;
            padding: 24px;
            text-align: center;
            border: 1px solid #3a3f5c;
        }
    </style>
    """, unsafe_allow_html=True)

    st.title("Video Insight")
    st.caption("Paste a YouTube URL → Summary, Quiz, Flashcards & Concept Map powered by Gemini 2.5 Flash")

    # Key status indicator
    total_keys = len(st.session_state["api_keys"])
    cur_key    = st.session_state["key_index"] + 1
    st.info(f"🔑 Using API key {cur_key} of {total_keys}")

    url = st.text_input("Enter your YouTube Video URL", placeholder="https://www.youtube.com/watch?v=...")

    if st.button("Start Analyzing Video", use_container_width=True):
        if not url:
            st.error("Please enter a valid YouTube URL.")
            return

        with st.spinner("Fetching transcript..."):
            try:
                transcript = get_transcript(url)
            except Exception as e:
                st.error(f"Transcript fetch failed: {e}")
                return

        with st.expander("View Raw Transcript"):
            st.write(transcript)

        with st.spinner("Generating summary..."):
            summary = query_gemini(transcript, SUMMARY_PROMPT)
        with st.spinner("Generating quiz..."):
            quiz_raw = query_gemini(transcript, QUIZ_PROMPT)
        with st.spinner("Generating flashcards..."):
            flashcard_raw = query_gemini(transcript, FLASHCARD_PROMPT)
        with st.spinner("Generating concept map..."):
            concept_map = query_gemini(transcript, CONCEPT_MAP_PROMPT)

        st.session_state["summary"]      = summary
        st.session_state["quiz"]         = parse_quiz(quiz_raw)
        st.session_state["flashcards"]   = parse_flashcards(flashcard_raw)
        st.session_state["concept_map"]  = concept_map
        st.session_state["answers"]      = {}
        st.session_state["submitted"]    = False
        st.session_state["card_index"]   = 0
        st.session_state["card_flipped"] = False

    if "summary" not in st.session_state:
        return

    tab1, tab2, tab3, tab4 = st.tabs(["Summary", "Quiz", "Flashcards", "Concept Map"])

    with tab1:
        st.markdown(st.session_state["summary"])

    with tab2:
        quiz = st.session_state["quiz"]
        if not quiz:
            st.warning("Could not parse quiz. Try re-analyzing.")
        else:
            answers   = st.session_state.get("answers", {})
            submitted = st.session_state.get("submitted", False)

            for i, q in enumerate(quiz):
                st.markdown(f"**Q{i+1}: {q['question']}**")
                opts = [f"{k}) {v}" for k, v in q["options"].items()]

                if submitted:
                    chosen = answers.get(i)
                    for opt in opts:
                        letter = opt[0]
                        if letter == q["answer"]:
                            st.markdown(f'<div class="correct">{opt}</div>', unsafe_allow_html=True)
                        elif letter == chosen:
                            st.markdown(f'<div class="wrong">{opt}</div>', unsafe_allow_html=True)
                        else:
                            st.markdown(f"&nbsp;&nbsp;{opt}")
                else:
                    choice = st.radio(
                        label=f"q_{i}",
                        options=[o[0] for o in opts],
                        format_func=lambda x, opts=opts: next(o for o in opts if o[0] == x),
                        key=f"q_{i}",
                        label_visibility="collapsed"
                    )
                    answers[i] = choice
                    st.session_state["answers"] = answers

                st.divider()

            if not submitted:
                if st.button("Submit Quiz", use_container_width=True):
                    st.session_state["submitted"] = True
                    st.rerun()
            else:
                correct = sum(1 for i, q in enumerate(quiz) if answers.get(i) == q["answer"])
                total   = len(quiz)
                pct     = int(correct / total * 100)
                st.markdown(f"""
                <div class="score-box">
                    <h2>{"🎉" if pct >= 70 else "📚"} You scored {correct}/{total} ({pct}%)</h2>
                    <p>{"Great job!" if pct >= 70 else "Keep studying — you'll get there!"}</p>
                </div>
                """, unsafe_allow_html=True)
                if st.button("Retake Quiz", use_container_width=True):
                    st.session_state["submitted"] = False
                    st.session_state["answers"]   = {}
                    st.rerun()

    with tab3:
        cards = st.session_state.get("flashcards", [])
        if not cards:
            st.warning("Could not parse flashcards. Try re-analyzing.")
        else:
            idx     = st.session_state.get("card_index", 0)
            flipped = st.session_state.get("card_flipped", False)
            card    = cards[idx]

            st.markdown(f"**Card {idx+1} of {len(cards)}**")
            st.progress((idx + 1) / len(cards))

            content = card["back"] if flipped else card["front"]
            label   = "Answer" if flipped else "Concept"
            st.markdown(f'<div class="card-box">{label}<br><br>{content}</div>', unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Prev", use_container_width=True):
                    st.session_state["card_index"]   = max(0, idx - 1)
                    st.session_state["card_flipped"] = False
                    st.rerun()
            with c2:
                if st.button("Flip", use_container_width=True):
                    st.session_state["card_flipped"] = not flipped
                    st.rerun()
            with c3:
                if st.button("Next", use_container_width=True):
                    st.session_state["card_index"]   = min(len(cards) - 1, idx + 1)
                    st.session_state["card_flipped"] = False
                    st.rerun()

    with tab4:
        st.code(st.session_state["concept_map"], language="")

if __name__ == "__main__":
    main()