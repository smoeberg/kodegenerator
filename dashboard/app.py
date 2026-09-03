"""DOR Web Dashboard - Visual Governance & Admin Management Interface."""

import os
import sqlite3

import pandas as pd
import streamlit as st

from dashboard.catalog import STANDARD_CAPABILITIES, STANDARD_ROLES
from dashboard.security import admin_password
from services.runtime_configuration import validate_runtime_configuration

validate_runtime_configuration(role="dashboard")

try:
    from dashboard.decision_cockpit import render_decision_cockpit
except ImportError:
    render_decision_cockpit = None

try:
    from dashboard.workflow_cockpit import render_workflow_cockpit
except ImportError:
    render_workflow_cockpit = None

try:
    from dashboard.swarm_monitor import render_swarm_monitor
except ImportError:
    render_swarm_monitor = None

try:
    from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
except ImportError:
    render_multi_bot_control_plane = None

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
        "🧠 Multi-bot Control Plane",
        "🚀 System Generator & Workflow",
        "🤖 Swarm Fleet Monitor",
        "🎛️ Decision Cockpit (HITL)",
        "⚙️ Indstillinger & Integrationer",
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

# --- Sektion: Multi-bot Control Plane ---
if menu == "🧠 Multi-bot Control Plane":
    if render_multi_bot_control_plane is not None:
        render_multi_bot_control_plane()
    else:
        st.error("`dashboard.multi_bot_control_plane` kunne ikke importeres.")

# --- Sektion: System Generator & Workflow ---
elif menu == "🚀 System Generator & Workflow":
    if render_workflow_cockpit is not None:
        render_workflow_cockpit()
    else:
        st.error("`dashboard.workflow_cockpit` kunne ikke importeres.")

# --- Sektion: Swarm Fleet Monitor ---
elif menu == "🤖 Swarm Fleet Monitor":
    if render_swarm_monitor is not None:
        render_swarm_monitor()
    else:
        st.error("`dashboard.swarm_monitor` kunne ikke importeres.")

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
            agent_count = pd.read_sql("SELECT COUNT(*) as c FROM agents", conn).iloc[0][
                "c"
            ]
            dept_count = pd.read_sql(
                "SELECT COUNT(*) as c FROM departments", conn
            ).iloc[0]["c"]
            task_count = pd.read_sql("SELECT COUNT(*) as c FROM tasks", conn).iloc[0][
                "c"
            ]
            event_count = pd.read_sql("SELECT COUNT(*) as c FROM event_log", conn).iloc[
                0
            ]["c"]

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
            name = st.text_input(
                "Agent Navn / Alias", placeholder="f.eks. CodeReviewer-Alpha"
            )
            role_options = list(STANDARD_ROLES.keys())
            selected_role = st.selectbox("Vælg Rolle (Skabelon)", role_options)

        with col2:
            model_name = st.selectbox(
                "Underliggende AI Model",
                [
                    "claude-3-7-sonnet",
                    "claude-3-5-sonnet",
                    "gpt-4o",
                    "mistral-large",
                    "custom",
                ],
            )
            status = st.selectbox("Initial Status", ["active", "idle", "disabled"])

        st.markdown("### Standard Rettigheder & Evner")
        role_template = STANDARD_ROLES.get(selected_role)
        default_caps = list(role_template.capabilities) if role_template else []
        selected_caps = st.multiselect(
            "Tilknyttede Capabilities", list(STANDARD_CAPABILITIES.keys()), default=default_caps
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

# --- Sektion: Indstillinger & Integrationer ---
elif menu == "⚙️ Indstillinger & Integrationer":
    st.subheader("⚙️ Systemindstillinger & Eksterne Integrationer")
    st.caption(
        "Konfigurer forbindelser til eksterne issue trackers, metrics og runtime-miljø."
    )

    tab_redmine, tab_general = st.tabs(["🐞 Redmine Issue Tracker", "🌐 Generelt"])

    with tab_redmine:
        st.markdown("### Redmine Error Ticketing Konfiguration")
        st.info(
            "Når Redmine er konfigureret, vil uafklarede fejl i self-healing loops "
            "og syntesefejl automatisk oprette strukturerede fejlrapporter i Redmine."
        )

        curr_url = os.getenv("REDMINE_URL", "")
        curr_api_key = os.getenv("REDMINE_API_KEY", "")
        curr_project = os.getenv("REDMINE_PROJECT_ID", "dor")
        curr_tracker = os.getenv(
            "REDMINE_TRACKER_ID", os.getenv("REDMINE_ISSUE_TRACKER_ID", "1")
        )
        curr_severity = os.getenv("REDMINE_SEVERITY", "ERROR")

        with st.form("redmine_config_form"):
            col1, col2 = st.columns(2)
            with col1:
                redmine_url = st.text_input(
                    "Redmine URL",
                    value=curr_url,
                    placeholder="https://redmine.example.com",
                    help="Grund-URL for dit Redmine-system (f.eks. https://redmine.example.com)",
                )
                project_id = st.text_input(
                    "Projekt ID / Identifier",
                    value=curr_project,
                    placeholder="f.eks. dor eller 1",
                    help="Redmine projekt-identifier eller numerisk ID.",
                )
                tracker_id = st.text_input(
                    "Tracker ID",
                    value=curr_tracker,
                    placeholder="1",
                    help="Tracker ID for fejl/bugs (standard: 1).",
                )

            with col2:
                api_key = st.text_input(
                    "API Key",
                    value=curr_api_key,
                    type="password",
                    placeholder="Indtast Redmine REST API-nøgle",
                    help="Findes i Redmine under Min konto -> API-adgangsnøgle.",
                )
                severity_options = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]
                default_sev_idx = (
                    severity_options.index(curr_severity)
                    if curr_severity in severity_options
                    else 1
                )
                severity = st.selectbox(
                    "Standard Severity",
                    severity_options,
                    index=default_sev_idx,
                    help="Standard alvorsgrad for genererede Redmine-sager.",
                )

            st.markdown("#### Forbindelsestest & Gem")
            col_test, col_save = st.columns([1, 1])
            with col_test:
                test_connection = st.form_submit_button("🔍 Test Forbindelse")
            with col_save:
                save_config = st.form_submit_button("💾 Gem Indstillinger")

            if test_connection:
                if not redmine_url or not api_key:
                    st.warning(
                        "Angiv venligst både Redmine URL og API Key for at teste."
                    )
                else:
                    try:
                        from services.redmine_api import RedmineAPIClient
                        from services.redmine_contracts import RedmineConfig

                        cfg = RedmineConfig(
                            url=redmine_url.strip(),
                            api_key=api_key.strip(),
                            project_id=project_id.strip() or "dor",
                            tracker_id=tracker_id.strip() or "1",
                        )
                        cfg.validate()
                        client = RedmineAPIClient(cfg)
                        with st.spinner("Kontakter Redmine..."):
                            issues = client.list_issues(limit=1)
                        st.success(
                            "✅ Forbindelse til Redmine etableret! "
                            f"(Fundet {len(issues)} issues tilgængelige)"
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"❌ Forbindelsesfejl: {exc}")

            if save_config:
                os.environ["REDMINE_URL"] = redmine_url.strip()
                os.environ["REDMINE_API_KEY"] = api_key.strip()
                os.environ["REDMINE_PROJECT_ID"] = project_id.strip() or "dor"
                os.environ["REDMINE_TRACKER_ID"] = tracker_id.strip() or "1"
                os.environ["REDMINE_SEVERITY"] = severity
                st.success(
                    "✅ Redmine-indstillinger opdateret i aktiv runtime-session!"
                )

    with tab_general:
        st.markdown("### Generelle Systemparametre")
        st.text_input("DOR Database Sti", value=DB_PATH, disabled=True)
        st.text_input(
            "API URL",
            value=os.getenv("DOR_API_URL", "http://localhost:8000"),
            disabled=True,
        )
