"""
Secret/config resolution for ANTHROPIC_API_KEY and ANTHROPIC_MODEL.

Resolution order: a per-browser-session key the user entered in the app UI
(st.session_state), then the OS environment (populated by python-dotenv's
load_dotenv() from a .env file, or a real env var), then Streamlit Cloud's
st.secrets, then default. The env-then-secrets order is unchanged from
before the session-key feature existed — local and hosted app-owner-key
behavior is identical either way. The session-state check is new (app/main.py's
gear-icon popover) and is checked first so a user-supplied session key
overrides an app-owner key for the rest of that browser session.

The session-state and st.secrets accesses are both wrapped in try/except:
st.session_state/st.secrets raise outside a running Streamlit script (e.g.
in tests or a plain CLI run, or with no .streamlit/secrets.toml present,
the normal state for local development) — none of that may ever crash a
local run or the test suite.
"""

import os


def get_secret(name: str, default: str = "") -> str:
    """Resolve a secret: session key, then OS environment variable, then Streamlit secrets, then default."""
    try:
        import streamlit as st
        val = st.session_state.get(name)
        if val:
            return val
    except Exception:
        pass
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default
