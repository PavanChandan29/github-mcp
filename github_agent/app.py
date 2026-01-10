import streamlit as st
import asyncio
import os
from agent import agent, CONFIG

# =========================
# Page Config
# =========================
st.set_page_config(
    page_title="CodeSense",
    layout="wide"
)

# =========================
# Light Grey + Olive Theme
# =========================
st.markdown("""
<style>

/* App background */
.stApp {
    background-color: #f2f3f5;
    color: #1f2328;
    font-family: "Inter", "Segoe UI", sans-serif;
}

/* Centered title */
h1 {
    text-align: center;
    color: #1f2328;
    font-weight: 700;
    margin-bottom: 1.2rem;
}

/* Settings button */
button[data-testid="baseButton-secondary"] {
    background-color: #e6e8eb !important;
    border: 2px solid #6b8e23 !important;
    border-radius: 10px !important;
    padding: 6px 10px !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
}

/* Settings icon → DARK GREY */
button[data-testid="baseButton-secondary"],
button[data-testid="baseButton-secondary"] span,
button[data-testid="baseButton-secondary"] span span {
    color: #5a5a5a !important;
}

/* Settings panel */
.stExpander {
    background-color: #e6e8eb !important;
    border: 1px solid #d0d7de !important;
    border-radius: 12px;
    padding: 10px;
}

/* Chat message card */
.chat-message {
    background-color: #ffffff;
    border: 1px solid #d0d7de;
    color: #1f2328;
    padding: 14px 16px;
    border-radius: 12px;
    margin-bottom: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    line-height: 1.5;
}

/* User message */
.user-message {
    border-left: 5px solid #6b8e23;
}

/* Assistant message */
.assistant-message {
    border-left: 5px solid #5a5a5a;
}

/* Inputs */
textarea, input {
    background-color: #ffffff !important;
    color: #1f2328 !important;
    border: 1px solid #d0d7de !important;
    border-radius: 10px !important;
    padding: 10px !important;
}

/* Buttons */
button {
    background-color: #e6e8eb !important;
    color: #1f2328 !important;
    border: 1px solid #6b8e23 !important;
    border-radius: 10px !important;
    padding: 8px 14px !important;
    font-weight: 500;
    transition: all 0.15s ease-in-out;
}

button:hover {
    background-color: #eef1ea !important;
    color: #1f2328 !important;
    transform: translateY(-1px);
}

/* Success / info */
.stSuccess, .stInfo {
    color: #6b8e23 !important;
}

/* Chat input spacing */
.stChatInputContainer {
    padding-top: 12px;
}

/* REMOVE Send icon completely */
.stChatInput button,
.stChatInput svg {
    display: none !important;
}

</style>
""", unsafe_allow_html=True)

# =========================
# Session State
# =========================
if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'git_username' not in st.session_state:
    st.session_state.git_username = ""

if 'git_token' not in st.session_state:
    st.session_state.git_token = ""

if 'show_settings' not in st.session_state:
    st.session_state.show_settings = False

if 'settings_saved' not in st.session_state:
    st.session_state.settings_saved = False

if 'llm_model' not in st.session_state:
    st.session_state.llm_model = CONFIG["llm"].get("model", "gpt-4")

if 'last_repo' not in st.session_state:
    st.session_state.last_repo = None

if 'last_repo_user' not in st.session_state:
    st.session_state.last_repo_user = None

# =========================
# Settings Button
# =========================
with st.container():
    col1, col2 = st.columns([1, 20])
    with col1:
        if st.button("⚙️", key="settings_btn", help="Settings"):
            st.session_state.show_settings = not st.session_state.show_settings

# =========================
# Settings Panel
# =========================
if st.session_state.show_settings:
    with st.expander("Settings", expanded=True):

        git_username = st.text_input("Git Username", value=st.session_state.git_username)
        git_token = st.text_input("Git Token", value=st.session_state.git_token, type="password")

        st.text_input("Current LLM Model", value=st.session_state.llm_model, disabled=True)

        col_reset, col_ok = st.columns(2)

        with col_reset:
            if st.button("Reset"):
                st.session_state.git_username = ""
                st.session_state.git_token = ""
                st.session_state.settings_saved = False
                st.rerun()

        with col_ok:
            if st.button("OK", disabled=st.session_state.settings_saved):
                if git_username and git_token:
                    st.session_state.git_username = git_username
                    st.session_state.git_token = git_token
                    st.session_state.settings_saved = True
                    st.success("Settings saved!")
                    st.rerun()
                else:
                    st.info("Please fill in both Username and Token")

# =========================
# Helpers
# =========================
def has_credentials():
    return bool(st.session_state.git_username and st.session_state.git_token)

# =========================
# Title
# =========================
st.markdown("<h1>CodeSense 🤖</h1>", unsafe_allow_html=True)

# =========================
# Chat History
# =========================
for message in st.session_state.messages:
    role = message["role"]
    css_class = "user-message" if role == "user" else "assistant-message"

    st.markdown(
        f'<div class="chat-message {css_class}">{message["content"]}</div>',
        unsafe_allow_html=True
    )

# =========================
# Chat Input
# =========================
if prompt := st.chat_input("Press Enter to send • Shift+Enter for a new line"):

    st.session_state.messages.append({"role": "user", "content": prompt})

    if not has_credentials():
        response = "Please configure your GitHub username and token in Settings."
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()

    else:
        with st.spinner("Thinking..."):
            try:
                os.environ["GITHUB_TOKEN"] = st.session_state.git_token

                conversation_history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                ]

                initial_state = {
                    "question": prompt,
                    "username": st.session_state.git_username,
                    "conversation_history": conversation_history,
                    "last_repo": st.session_state.last_repo,
                    "last_repo_user": st.session_state.last_repo_user,
                    "tool_name": None,
                    "tool_args": None,
                    "tool_result": None,
                    "final_answer": None,
                }

                result = asyncio.run(agent.ainvoke(initial_state))
                response = result.get("final_answer", "Sorry, I couldn't generate a response.")

                if result.get("last_repo"):
                    st.session_state.last_repo = result.get("last_repo")
                    st.session_state.last_repo_user = result.get("last_repo_user")

            except Exception as e:
                response = f"Error: {str(e)}"

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()