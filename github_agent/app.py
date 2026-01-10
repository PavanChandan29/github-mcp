import streamlit as st
import asyncio
import json
from pathlib import Path
from agent import agent, llm, CONFIG, AgentState

# Page config
st.set_page_config(
    page_title="GitHub MCP Agent",
    page_icon="🤖",
    layout="wide"
)

# Initialize session state
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

# Custom CSS for settings and chatbot
st.markdown("""
    <style>
    .settings-container {
        position: fixed;
        top: 10px;
        left: 10px;
        z-index: 1000;
        background: white;
        padding: 10px;
        border-radius: 5px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    
    .settings-box {
        background: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #d0d0d0;
        margin: 20px 0;
        max-width: 500px;
    }
    
    .fade-out {
        opacity: 0.3 !important;
        transition: opacity 0.5s;
    }
    
    button.faded-ok {
        opacity: 0.3 !important;
        transition: opacity 0.5s;
    }
    
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
    }
    
    .user-message {
        background-color: #e3f2fd;
        justify-content: flex-end;
    }
    
    .assistant-message {
        background-color: #f5f5f5;
        justify-content: flex-start;
    }
    </style>
""", unsafe_allow_html=True)

# Settings button (top left)
with st.container():
    col1, col2 = st.columns([1, 20])
    with col1:
        if st.button("⚙️", key="settings_btn", help="Settings"):
            st.session_state.show_settings = not st.session_state.show_settings

# Settings panel
if st.session_state.show_settings:
    with st.container():
        with st.expander("Settings", expanded=True):
            # Git Username
            git_username = st.text_input(
                "Git Username",
                value=st.session_state.git_username,
                key="settings_username"
            )
            
            # Git Token
            git_token = st.text_input(
                "Git Token",
                value=st.session_state.git_token,
                type="password",
                key="settings_token"
            )
            
            # Display current LLM model
            st.text_input(
                "Current LLM Model",
                value=st.session_state.llm_model,
                disabled=True,
                key="settings_model_display"
            )
            
            # Reset and OK buttons
            col_reset, col_ok, _ = st.columns([1, 1, 3])
            
            with col_reset:
                if st.button("Reset", key="reset_btn"):
                    st.session_state.git_username = ""
                    st.session_state.git_token = ""
                    st.session_state.settings_saved = False
                    st.rerun()
            
            with col_ok:
                ok_disabled = st.session_state.settings_saved
                
                # Apply fade CSS when settings are saved
                if ok_disabled:
                    st.markdown("""
                        <style>
                        button[data-baseweb="button"][aria-disabled="true"] {
                            opacity: 0.3 !important;
                            transition: opacity 0.5s ease-in-out;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                
                ok_clicked = st.button("OK", key="ok_btn", disabled=ok_disabled)
                if ok_clicked and not ok_disabled:
                    if git_username and git_token:
                        st.session_state.git_username = git_username
                        st.session_state.git_token = git_token
                        st.session_state.settings_saved = True
                        st.success("Settings saved!")
                        st.rerun()
                    else:
                        st.warning("Please fill in both Username and Token")

# Check if credentials are set
def has_credentials():
    return bool(st.session_state.git_username and st.session_state.git_token)

# Main chatbot interface
st.title("GitHub MCP Agent 🤖")

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Ask a question about GitHub repos..."):
    # Add user message to chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Check credentials
    if not has_credentials():
        response = "Seems like there's no gas in the car. Please pass the values in settings."
        with st.chat_message("assistant"):
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.rerun()
    else:
        # Process with agent
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Build conversation history from previous messages
                    conversation_history = []
                    for msg in st.session_state.messages[:-1]:  # Exclude current message
                        conversation_history.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                    
                    # Create initial state with username and conversation context
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
                    
                    # Run agent
                    result = asyncio.run(agent.ainvoke(initial_state))
                    response = result.get("final_answer", "Sorry, I couldn't generate a response.")
                    
                    # Update last_repo context from agent result
                    if result.get("last_repo"):
                        st.session_state.last_repo = result.get("last_repo")
                        st.session_state.last_repo_user = result.get("last_repo_user")
                    
                except Exception as e:
                    response = f"Error: {str(e)}"
                
                st.markdown(response)
        
        # Add assistant response to chat
        st.session_state.messages.append({"role": "assistant", "content": response})
        
        # Rerun to update the display
        st.rerun()