"""Keep visitor files private to a Streamlit session; bound shared API usage."""
import hashlib
import io
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st


def session_directory():
    if "_private_directory" not in st.session_state:
        st.session_state["_private_directory"] = tempfile.TemporaryDirectory(prefix="sheep-session-")
    return Path(st.session_state["_private_directory"].name)


class SessionFile(os.PathLike):
    def __init__(self, name):
        self.name = name

    def __fspath__(self):
        return str(session_directory() / self.name)

    def exists(self):
        return Path(self).exists()

    def read_text(self, **kwargs):
        return Path(self).read_text(**kwargs)

    def write_text(self, text, **kwargs):
        return Path(self).write_text(text, **kwargs)

    def open(self, *args, **kwargs):
        return Path(self).open(*args, **kwargs)


def persist_upload(kind, widget_key):
    upload = st.session_state.get(widget_key)
    if upload is None:
        st.session_state.pop("_source_" + kind, None)
    else:
        st.session_state["_source_" + kind] = (upload.name, upload.getvalue())


def saved_upload(kind):
    value = st.session_state.get("_source_" + kind)
    if not value:
        return None
    stream = io.BytesIO(value[1])
    stream.name = value[0]
    return stream


def source_version():
    digest = hashlib.sha256()
    for kind in ("survey", "materials"):
        digest.update(kind.encode())
        value = st.session_state.get("_source_" + kind)
        digest.update(value[1] if value else b"bundled-demo-v1")
    return digest.hexdigest()


def setting(name, default=""):
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default


def reserve_api_call():
    """Atomic, shared daily cap. Failed requests also consume a slot."""
    daily_limit = int(setting("AI_DAILY_CALL_LIMIT", "40"))
    session_limit = int(setting("AI_SESSION_CALL_LIMIT", "8"))
    used = st.session_state.get("_api_calls", 0)
    if used >= session_limit:
        raise RuntimeError("本次体验的 AI 调用次数已用完，仍可浏览看板和生成基础版策略。")
    database = Path(tempfile.gettempdir()) / "sheep-public-api-quota-v1.sqlite3"
    with sqlite3.connect(database, timeout=10) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.execute("BEGIN IMMEDIATE")
        today = date.today().isoformat()
        connection.execute("INSERT OR IGNORE INTO quota VALUES (?, 0)", (today,))
        count = connection.execute("SELECT calls FROM quota WHERE day = ?", (today,)).fetchone()[0]
        if count >= daily_limit:
            raise RuntimeError("今日共享 AI 体验额度已用完，请使用基础版策略或稍后再试。")
        connection.execute("UPDATE quota SET calls = calls + 1 WHERE day = ?", (today,))
    st.session_state["_api_calls"] = used + 1
