import streamlit as st
import asyncio
import os
import requests

# Try importing local agent (only works in local mode)
try:
    from agent import agent, CONFIG
    LOCAL_AGENT_AVAILABLE = True
except:
    LOCAL_AGENT_AVAILABLE = False


# =========================
# Mode Configuration
# =========================
DEPLOY_MODE = os.getenv("DEPLOY_MODE", "local")  # local | cloud
API_BASE = os.getenv("API_BASE", "")

# =========================
# Page Config
# =========================
st.set_page_config(page_title="CodeSense", layout="wide")

# =========================
# Theme
# =========================
st.markdown("""
<style>
.stApp { background-color: #f2f3f5; color: #1f2328; font-family: Inter, Segoe UI, sans-serif; }
h1 { text-align: center; color: #1f2328; font-weight: 700; margin-bottom: 1.2rem; }
button { background-color: #e6e8eb !important; color: #1f2328 !important;
         border: 1px solid #6b8e23 !important; border-radius: 10px !important;
         padding: 8px 14px !important; }
.chat-message { background-color: #ffffff; border: 1px solid #d0d7de;
                padding: 14px 16px; border-radius: 12px; margin-bottom: 14px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.user-message { border-left: 5px solid #6b8e23; }
.assistant-message { border-left: 5px solid #5a5a5a; }
textarea, input { background-color: #ffffff !important; color: #1f2328 !important;
                  border: 1px solid #d0d7de !important; border-radius: 10px !important; }
.stChatInput button, .stChatInput svg { display: none !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# Session State
# =========================
for key, default in {
    "messages": [],
    "git_username": "",
    "git_token": "",
    "show_settings": False,
    "settings_saved": False,
    "last_repo": None,
    "last_repo_user": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# =========================
# Settings Button
# =========================
with st.container():
    col1, _ = st.columns([1, 20])
    with col1:
        if st.button("⚙️", help="Settings"):
            st.session_state.show_settings = not st.session_state.show_settings

# =========================
# Settings Panel
# =========================
if st.session_state.show_settings:
    with st.expander("Settings", expanded=True):

        git_username = st.text_input("GitHub Username", value=st.session_state.git_username)
        git_token = st.text_input("GitHub Token", value=st.session_state.git_token, type="password")

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
                    st.info("Please fill in both fields")

# =========================
# Helpers
# =========================
def has_credentials():
    return bool(st.session_state.git_username and st.session_state.git_token)

def call_cloud_ingest():
    requests.post(
        f"{API_BASE}/ingest",
        json={
            "username": st.session_state.git_username,
            "github_token": st.session_state.git_token
        },
        timeout=60
    )

def call_cloud_query(prompt):
    res = requests.post(
        f"{API_BASE}/query",
        json={
            "username": st.session_state.git_username,
            "question": prompt
        },
        timeout=60
    )
    return res.json().get("answer", "No response")

def call_local_agent(prompt):
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

    if result.get("last_repo"):
        st.session_state.last_repo = result.get("last_repo")
        st.session_state.last_repo_user = result.get("last_repo_user")

    return result.get("final_answer", "No response")


# =========================
# Title
# =========================
st.markdown("<h1>CodeSense 🤖</h1>", unsafe_allow_html=True)

# =========================
# Chat History
# =========================
for message in st.session_state.messages:
    css = "user-message" if message["role"] == "user" else "assistant-message"
    st.markdown(f'<div class="chat-message {css}">{message["content"]}</div>',
                unsafe_allow_html=True)

# =========================
# Chat Input
# =========================
if prompt := st.chat_input("Press Enter to send • Shift+Enter for new line"):

    st.session_state.messages.append({"role": "user", "content": prompt})

    if not has_credentials():
        response = "Please configure your GitHub username and token in Settings."
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()

    with st.spinner("Thinking..."):
        try:
            # ---------- INGEST ----------
            if DEPLOY_MODE == "cloud":
                call_cloud_ingest()
            else:
                os.environ["GITHUB_TOKEN"] = st.session_state.git_token

            # ---------- QUERY ----------
            if DEPLOY_MODE == "cloud":
                response = call_cloud_query(prompt)
            else:
                if not LOCAL_AGENT_AVAILABLE:
                    response = "Local agent not available."
                else:
                    response = call_local_agent(prompt)

        except Exception as e:
            response = f"Error: {str(e)}"

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()