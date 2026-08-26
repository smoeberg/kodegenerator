"""DOR Web Dashboard - Visual Governance & Admin Management Interface."""

import json
import os
import sqlite3

import pandas as pd
import streamlit as st

from dashboard.catalog import STANDARD_CAPABILITIES, STANDARD_ROLES
from dashboard.security import admin_password, encrypt_secret

try:
    from dashboard.decision_cockpit import render_decision_cockpit
except ImportError:
    render_decision_cockpit = None

try:
    from dashboard.workflow_cockpit import render_workflow_cockpit
except ImportError:
    render_workflow_cockpit = None

st.set_page_config(
    page_title="DOR - Controller & Digital Employee Management",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Authentication Check ---
ADMIN_PASSWORD = admin_password()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("⚡ Digital Organization Runtime (DOR) Dashboard")
    st.subheader("🔐 Autentificering Påkrævet")
    pwd = st.text_input(
        "Indtast Dashboard Admin Adgangskode",
        type="password",
        help="Konfigureres med DOR_ADMIN_PASSWORD.",
    )
    if st.button("Log ind"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("⚠️ Forkert adgangskode.")
    st.stop()

st.title("⚡ Digital Organization Runtime (DOR) Dashboard")

DB_PATH = os.getenv("DOR_DB_PATH", "dor_runtime.db")


def get_connection():
    if not os.path.exists(DB_PATH):
        return None
    return sqlite3.connect(DB_PATH)


# --- Sidebar Navigation ---
st.sidebar.title("Navigation")
menu = st.sidebar.radio(
    "Vælg Sektion",
    [
        "🚀 System Generator & Workflow",
        "🎛️ Decision Cockpit (HITL)",
        "Overblik & Systemtilstand",
        "Digitale Medarbejdere (Agenter)",
        "Opret Ny Agent (Wizard)",
        "Afdelinger & Teams",
        "Opgaver (Tasks)",
        "Audit Log & Hændelser",
    ],
)

if st.sidebar.button("Log ud"):
    st.session_state.authenticated = False
    st.rerun()

conn = get_connection()

# --- Sektion: System Generator & Workflow ---
if menu == "🚀 System Generator & Workflow":
    if render_workflow_cockpit is not None:
        render_workflow_cockpit()
    else:
        st.error("`dashboard.workflow_cockpit` kunne ikke importeres.")

# --- Sektion: Decision Cockpit ---
elif menu == "🎛️ Decision Cockpit (HITL)":
    if render_decision_cockpit is not None:
        render_decision_cockpit()
    else:
        st.warning(
            "`dashboard.decision_cockpit` er ikke tilgængelig. "
            "Brug System Generator eller Opgaver indtil modulet er på plads."
        )

# --- Sektion: Overblik & Systemtilstand ---
elif menu == "Overblik & Systemtilstand":
    st.subheader("Systemoversigt")
    if not conn:
        st.warning(
            f"Databasefilen '{DB_PATH}' blev ikke fundet. "
            "Kør systemet først for at initialisere data."
        )
    else:
        col1, col2, col3, col4 = st.columns(4)
        try:
            agent_count = pd.read_sql("SELECT COUNT(*) as c FROM agents", conn).iloc[0]["c"]
            dept_count = pd.read_sql("SELECT COUNT(*) as c FROM departments", conn).iloc[0]["c"]
            task_count = pd.read_sql("SELECT COUNT(*) as c FROM tasks", conn).iloc[0]["c"]
            event_count = pd.read_sql("SELECT COUNT(*) as c FROM event_log", conn).iloc[0]["c"]

            col1.metric("Aktive Agenter", agent_count)
            col2.metric("Afdelinger", dept_count)
            col3.metric("Opgaver I Alt", task_count)
            col4.metric("Audit Hændelser", event_count)
        except Exception as e:
            st.error(f"Fejl ved indlæsning af metrikker: {e}")

# --- Sektion: Digitale Medarbejdere ---
elif menu == "Digitale Medarbejdere (Agenter)":
    st.subheader("Oversigt over Digitale Medarbejdere")
    if conn:
        try:
            query = """
            SELECT
                a.agent_id,
                a.name,
                a.role,
                a.department_id,
                d.name as department_name,
                a.status,
                a.is_active,
                a.created_at
            FROM agents a
            LEFT JOIN departments d ON a.department_id = d.department_id
            """
            agents_df = pd.read_sql(query, conn)
            st.dataframe(agents_df, use_container_width=True)
        except Exception as e:
            st.error(f"Kunne ikke hente agenter: {e}")

# --- Sektion: Opret Ny Agent (Wizard) ---
elif menu == "Opret Ny Agent (Wizard)":
    st.subheader("Opret Ny Digital Medarbejder")
    st.info(
        "Brug denne guide til at registrere og konfigurere en ny AI-agent "
        "med passende rolle og sikkerhedsbegrænsninger."
    )

    with st.form("create_agent_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Agent Navn / Alias", placeholder="f.eks. CodeReviewer-Alpha")
            role_options = list(STANDARD_ROLES.keys())
            selected_role = st.selectbox("Vælg Rolle (Skabelon)", role_options)

        with col2:
            model_name = st.selectbox(
                "Underliggende AI Model",
                ["claude-3-7-sonnet", "claude-3-5-sonnet", "gpt-4o", "mistral-large", "custom"],
            )
            status = st.selectbox("Initial Status", ["active", "idle", "disabled"])

        st.markdown("### Standard Rettigheder & Evner")
        default_caps = STANDARD_ROLES.get(selected_role, [])
        selected_caps = st.multiselect(
            "Tilknyttede Capabilities", STANDARD_CAPABILITIES, default=default_caps
        )

        submitted = st.form_submit_button("Opret Agent")
        if submitted:
            st.success(f"Agent '{name}' oprettet med rollen '{selected_role}'!")

# --- Sektion: Afdelinger & Teams ---
elif menu == "Afdelinger & Teams":
    st.subheader("Afdelingsstruktur")
    if conn:
        try:
            depts_df = pd.read_sql("SELECT * FROM departments", conn)
            st.dataframe(depts_df, use_container_width=True)
        except Exception as e:
            st.error(f"Kunne ikke hente afdelinger: {e}")

# --- Sektion: Opgaver ---
elif menu == "Opgaver (Tasks)":
    st.subheader("Opgaveliste & Workflow Status")
    if conn:
        try:
            tasks_df = pd.read_sql(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100", conn
            )
            st.dataframe(tasks_df, use_container_width=True)
        except Exception as e:
            st.error(f"Kunne ikke hente opgaver: {e}")

# --- Sektion: Audit Log & Hændelser ---
elif menu == "Audit Log & Hændelser":
    st.subheader("Uforanderlig Audit & Event Log")
    if conn:
        try:
            events_df = pd.read_sql(
                "SELECT * FROM event_log ORDER BY timestamp DESC LIMIT 200", conn
            )
            st.dataframe(events_df, use_container_width=True)
        except Exception as e:
            st.error(f"Kunne ikke hente event log: {e}")
