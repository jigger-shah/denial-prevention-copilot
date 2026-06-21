"""
Secret/config resolution for ANTHROPIC_API_KEY and ANTHROPIC_MODEL.

Local development reads these from the OS environment (populated by
python-dotenv's load_dotenv() from a .env file, or a real env var). Streamlit
Cloud exposes secrets via st.secrets instead. get_secret() checks the
environment variable first — so local behavior is completely unchanged — and
falls back to st.secrets only if the environment variable isn't set, which is
the Streamlit Cloud case.

No agent or rule-layer logic depends on this module having Streamlit
installed in a context where it can be imported safely: the st.secrets access
is wrapped in try/except because st.secrets raises if no
.streamlit/secrets.toml exists at all, which is the normal state for local
development and must never crash a local run.
"""

import os


def get_secret(name: str, default: str = "") -> str:
    """Resolve a secret: OS environment variable, then Streamlit secrets, then default."""
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default
