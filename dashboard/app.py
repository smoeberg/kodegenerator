"""DOR Web Dashboard - Visual Governance & Admin Management Interface."""

import os
import json
import sqlite3
import pandas as pd
import streamlit as st
from domain.predefined_roles import STANDARD_ROLES, STANDARD_CAPABILITIES

st.set_page_config(
    page_title="DOR - Admin & Digital Employee Management",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚡ Digital Organization Runtime (DOR) Dashboard")

DB_PATH = os.getenv("DOR_DB_PATH", "dor_runtime.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS digital_employees (
            id TEXT PRIMARY KEY,
            identity TEXT NOT NULL,
            role TEXT,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            system_prompt TEXT,
            capabilities TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn

conn = get_db_connection()

# Sidebar Navigation
st.sidebar.title("🏢 Navigation & Admin")
page = st.sidebar.radio(
    "Vælg visning",
    [
        "Overview", 
        "➕ Admin: Opret AI-Medarbejder", 
        "🤖 AI-Medarbejdere Oversight", 
        "📜 Roller & Capabilities Specifikation",
        "Active Workflows", 
        "Governance Gates", 
        "Artifacts Registry"
    ]
)

if page == "Overview":
    st.header("📊 Organization Metrics Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    try:
        ai_count = pd.read_sql_query("SELECT COUNT(*) as count FROM digital_employees", conn)['count'][0]
    except Exception:
        ai_count = 0

    col1.metric("Organizations", "1")
    col2.metric("Oprettede AI-Medarbejdere", ai_count)
    col3.metric("Definerede Roller", len(STANDARD_ROLES))
    col4.metric("Capabilities Registry", len(STANDARD_CAPABILITIES))

    st.subheader("🏛️ Digital Organization Architecture")
    st.info("DOR lader dig tilføje specifikke AI-medarbejdere med deres egne dedikerede API-nøgler, veldefinerede roller og autoriteter.")

elif page == "➕ Admin: Opret AI-Medarbejder":
    st.header("⚙️ Admin: Opret Ny AI-Medarbejder (Digital Employee)")
    st.markdown("Opret en ny fuldautonom AI-medarbejder med sin egen API-nøgle, veldefinerede rolle og kompetencer.")

    role_options = {role.name: role for role in STANDARD_ROLES.values()}
    
    with st.form("create_ai_employee_form"):
        col_left, col_right = st.columns(2)

        with col_left:
            identity = st.text_input("AI-Medarbejder Navn / Identitet", "EIRA Senior AI Developer")
            selected_role_name = st.selectbox("Tildelt Veldefineret Rolle", list(role_options.keys()))
            selected_role = role_options[selected_role_name]
            
            provider = st.selectbox("AI Model Provider", ["OpenAI", "Anthropic", "DeepSeek", "Mistral", "Google Gemini"])

        with col_right:
            model_name = st.selectbox("Model Navn", [
                "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307",
                "deepseek-coder", "mistral-large-latest", "gemini-1.5-pro"
            ])
            api_key = st.text_input("API Nøgle for denne AI-Medarbejder", type="password", help="Indtast AI-medarbejderens private API nøgle")
            
            # Vis automatiske capabilities baseret på den valgte rolle
            st.info(f"💡 **Rollebeskrivelse:** {selected_role.description}")
            st.markdown(f"**Ansvar:** {', '.join(selected_role.responsibilities)}")

        system_prompt = st.text_area(
            "System Prompt / Adfærdskodeks", 
            f"Du er ansat som {selected_role.name} i DOR.\n"
            f"Dine primære ansvarsområder er:\n- " + "\n- ".join(selected_role.responsibilities)
        )

        submit_btn = st.form_submit_button("🚀 Opret og Aktiver AI-Medarbejder")

        if submit_btn:
            if not api_key:
                st.error("⚠️ Du skal indtaste en API-nøgle for at oprette AI-medarbejderen.")
            else:
                import uuid
                emp_id = f"ai-emp-{str(uuid.uuid4())[:8]}"
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO digital_employees (id, identity, role, provider, model_name, api_key, system_prompt, capabilities)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (emp_id, identity, selected_role.name, provider, model_name, api_key, system_prompt, json.dumps(selected_role.capabilities)))
                conn.commit()
                st.success(f"✅ AI-Medarbejder **{identity}** oprettet som **{selected_role.name}**! [ID: {emp_id}]")

elif page == "📜 Roller & Capabilities Specifikation":
    st.header("📜 Veldefinerede Roller & Capabilities i DOR")
    st.markdown("Oversigt over hvordan Roller, Autoriteter og Capabilities er defineret og håndhæves i systemet.")

    st.subheader("1. Systemets Roller & Autoriteter")
    for r_id, role in STANDARD_ROLES.items():
        with st.expander(f"🎭 {role.name} (`{r_id}`)"):
            st.write(f"**Beskrivelse:** {role.description}")
            st.write(f"**Tilknyttede Capabilities:** {', '.join(role.capabilities)}")
            st.write("**Autoriteter (Rights & Permissions):**")
            st.json(role.authority)
            st.write("**Ansvar:**")
            for resp in role.responsibilities:
                st.write(f"- {resp}")

    st.subheader("2. Registrerede Capabilities")
    for c_id, cap in STANDARD_CAPABILITIES.items():
        st.write(f"- **{cap.name}** (`{cap.id}`): {cap.description} *(Niveau: {cap.level.name})*")

elif page == "🤖 AI-Medarbejdere Oversight":
    st.header("🤖 Register over Aktive AI-Medarbejdere")
    df_ai = pd.read_sql_query("SELECT id, identity, role, provider, model_name, capabilities, created_at FROM digital_employees", conn)
    if not df_ai.empty:
        st.dataframe(df_ai, use_container_width=True)
    else:
        st.info("Ingen AI-medarbejdere oprettet endnu. Gå til **➕ Admin: Opret AI-Medarbejder** for at tilføje den første!")

elif page == "Active Workflows":
    st.header("🔄 Active Workflows & State Transitions")
    workflows_data = [
        {"ID": "wf-101", "Name": "Feature Development: OAuth2 Auth", "State": "REVIEW", "Gate Pending": "Security Review", "Actor": "EIRA AI Developer"},
    ]
    st.dataframe(pd.DataFrame(workflows_data), use_container_width=True)

elif page == "Governance Gates":
    st.header("🛡️ Governance Gates & Approvals")
    with st.form("gate_approval_form"):
        st.write("### Review Gate: Security Audit")
        status_choice = st.selectbox("Decision", ["APPROVED", "REJECTED", "NEEDS_CHANGES"])
        comments = st.text_area("Audit Comments", "Clean implementation.")
        if st.form_submit_button("Submit Decision"):
            st.success(f"Decision '{status_choice}' recorded!")

elif page == "Artifacts Registry":
    st.header("📦 Artifacts Registry")
    artifacts_data = [
        {"ID": "art-001", "Name": "auth_service.py", "Type": "IMPLEMENTATION", "Hash (SHA-256)": "a7c82...99f1", "State": "APPROVED"},
    ]
    st.dataframe(pd.DataFrame(artifacts_data), use_container_width=True)
