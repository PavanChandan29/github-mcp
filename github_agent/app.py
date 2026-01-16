import streamlit as st
import asyncio
import os
import requests
import time

# Try importing local agent (only works in local mode)
try:
    from agent import agent

    LOCAL_AGENT_AVAILABLE = True
except:
    LOCAL_AGENT_AVAILABLE = False

# =========================
# Mode Configuration
# =========================
DEPLOY_MODE = os.getenv("DEPLOY_MODE", "cloud")  # local | cloud
API_BASE = os.getenv("API_BASE", "http://44.198.180.55:8000")  # EC2 API

# =========================
# Page Config
# =========================
st.set_page_config(page_title="BitofGit", layout="wide")

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
.status-badge { 
    display: inline-block; 
    padding: 4px 12px; 
    border-radius: 12px; 
    font-size: 0.85em; 
    font-weight: 600;
    margin-left: 10px;
}
.status-pending { background-color: #fff3cd; color: #856404; }
.status-in-progress { background-color: #cce5ff; color: #004085; }
.status-completed { background-color: #d4edda; color: #155724; }
.status-failed { background-color: #f8d7da; color: #721c24; }
</style>
""", unsafe_allow_html=True)

# =========================
# Session State
# =========================
defaults = {
    "messages": [],
    "git_user_name": "",
    "git_token": "",
    "show_settings": False,
    "settings_saved": False,
    "ingested": False,
    "ingestion_status": None,  # NEW: Track ingestion status
    "last_repo": None,
    "last_repo_user": None,
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# =========================
# Helpers
# =========================
def has_credentials():
    return bool(st.session_state.git_user_name and st.session_state.git_token)


def check_ingestion_status():
    """Check the current ingestion status from the API"""
    try:
        r = requests.get(
            f"{API_BASE}/users/{st.session_state.git_user_name}",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            status = data.get("status", "not_found")
            return status
        return None
    except Exception as e:
        st.error(f"Failed to check status: {e}")
        return None


def call_cloud_ingest():
    """Trigger ingestion on EC2"""
    try:
        with st.spinner("🚀 Starting ingestion on EC2..."):
            r = requests.post(
                f"{API_BASE}/ingest",
                json={
                    "user_name": st.session_state.git_user_name,
                    "github_token": st.session_state.git_token
                },
                timeout=30
            )

            if r.status_code in [200, 202]:
                st.session_state.ingestion_status = "pending"
                st.success("✅ Ingestion started! Check EC2 logs for progress.")

                # Auto-refresh status after a short delay
                time.sleep(2)
                status = check_ingestion_status()
                if status:
                    st.session_state.ingestion_status = status

                return True
            else:
                st.error(f"❌ Ingestion failed: {r.text}")
                return False

    except Exception as e:
        st.error(f"❌ API ingest error: {e}")
        return False


def call_cloud_query(prompt):
    """Query the agent via EC2 API"""
    try:
        r = requests.post(
            f"{API_BASE}/query",
            json={
                "user_name": st.session_state.git_user_name,
                "question": prompt
            },
            timeout=120
        )
        return r.json().get("answer", "No response")
    except Exception as e:
        return f"API query error: {e}"


def call_local_agent(prompt):
    """Call local agent (when running locally)"""
    os.environ["GITHUB_TOKEN"] = st.session_state.git_token

    conversation_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
    ]

    initial_state = {
        "question": prompt,
        "username": st.session_state.git_user_name,
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
# Auto-refresh ingestion status every 10 seconds
# =========================
if st.session_state.ingestion_status in ["pending", "in_progress"]:
    # Auto-refresh status
    status = check_ingestion_status()
    if status and status != st.session_state.ingestion_status:
        st.session_state.ingestion_status = status
        st.rerun()

    # Auto-refresh UI every 10 seconds
    st.markdown(
        '<meta http-equiv="refresh" content="10">',
        unsafe_allow_html=True
    )

# =========================
# Settings Button + Status Badge
# =========================
with st.container():
    col1, col2, _ = st.columns([1, 3, 16])

    with col1:
        if st.button("⚙️", help="Settings"):
            st.session_state.show_settings = not st.session_state.show_settings

    with col2:
        # Show ingestion status badge
        if st.session_state.ingestion_status:
            status = st.session_state.ingestion_status
            status_colors = {
                "pending": "status-pending",
                "in_progress": "status-in-progress",
                "completed": "status-completed",
                "failed": "status-failed"
            }
            badge_class = status_colors.get(status, "status-pending")
            st.markdown(
                f'<span class="status-badge {badge_class}">{status.upper()}</span>',
                unsafe_allow_html=True
            )

# =========================
# Settings Panel
# =========================
if st.session_state.show_settings:
    with st.expander("Settings", expanded=True):

        git_user_name = st.text_input("GitHub Username", value=st.session_state.git_user_name)
        git_token = st.text_input("GitHub Token", value=st.session_state.git_token, type="password")

        # Show current status if available
        if st.session_state.ingestion_status:
            st.info(f"Current ingestion status: **{st.session_state.ingestion_status}**")

            # Refresh button
            if st.button("🔄 Refresh Status"):
                status = check_ingestion_status()
                if status:
                    st.session_state.ingestion_status = status
                    st.rerun()

        col_reset, col_ok = st.columns(2)

        with col_reset:
            if st.button("Reset"):
                st.session_state.git_user_name = ""
                st.session_state.git_token = ""
                st.session_state.settings_saved = False
                st.session_state.ingested = False
                st.session_state.ingestion_status = None
                st.rerun()

        with col_ok:
            # FIXED: Trigger ingestion immediately when OK is clicked
            if st.button("OK", disabled=st.session_state.settings_saved):
                if git_user_name and git_token:
                    st.session_state.git_user_name = git_user_name
                    st.session_state.git_token = git_token
                    st.session_state.settings_saved = True

                    # TRIGGER INGESTION NOW (if in cloud mode)
                    if DEPLOY_MODE == "cloud":
                        success = call_cloud_ingest()
                        if success:
                            st.session_state.ingested = True
                    else:
                        # Local mode
                        os.environ["GITHUB_TOKEN"] = st.session_state.git_token
                        st.session_state.ingested = True
                        st.success("Settings saved! (Local mode)")

                    st.rerun()
                else:
                    st.info("Please fill in both fields")

# =========================
# Title
# =========================
st.markdown("<h1>BitofGit 🤖</h1>", unsafe_allow_html=True)

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

    # Check if ingestion is needed (shouldn't happen if OK was clicked, but safety check)
    if not st.session_state.ingested and DEPLOY_MODE == "cloud":
        response = "⚠️ Please click OK in Settings to start ingestion first."
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()

    # 🔥 NEW: Check if ingestion is still running
    if DEPLOY_MODE == "cloud":
        current_status = check_ingestion_status()
        if current_status:
            st.session_state.ingestion_status = current_status

        if current_status in ["pending", "in_progress"]:
            response = f"⏳ Please wait! Your repositories are still being ingested.\n\n" \
                       f"**Current Status:** `{current_status}`\n\n" \
                       f"This usually takes 1-3 minutes depending on the number of repos. " \
                       f"You can check the status badge above or refresh it in Settings."
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

        elif current_status == "failed":
            response = "❌ Ingestion failed. Please check your credentials in Settings and try again."
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

        elif current_status == "not_found":
            response = "⚠️ No ingestion found. Please click OK in Settings to start ingestion."
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

    with st.spinner("Thinking..."):
        try:
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