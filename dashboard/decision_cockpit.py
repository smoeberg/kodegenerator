"""Decision Cockpit & Specialist Council View for DOR Controller Dashboard."""
from __future__ import annotations

import os
from typing import Any
import requests
import streamlit as st

API_URL = os.getenv("DOR_API_URL", "http://localhost:8000")


def render_decision_cockpit() -> None:
    """Render the Human Controller Decision Cockpit."""
    st.subheader("🎛️ Human Controller Decision Cockpit")
    st.caption("Gennemse, afvej og godkend AI-rådets strategiske og tekniske beslutninger.")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search = st.text_input("Søg beslutninger", placeholder="f.eks. Database, Arkitektur, Release...")
    with col2:
        status_filter = st.selectbox("Status", ["Alle", "HUMAN_REQUIRED", "PROPOSED", "APPROVED", "REJECTED"])
    with col3:
        risk_filter = st.selectbox("Risikoniveau", ["Alle", "CRITICAL", "HIGH", "MEDIUM", "LOW"])

    # Sample / live state retrieval
    st.markdown("---")
    st.markdown("### 📋 Aktive Beslutninger der kræver stillingtagen")

    demo_decisions = [
        {
            "id": "dec-arch-001",
            "title": "Arkitektur: Database persistens-strategi",
            "category": "ARCHITECTURE",
            "risk": "HIGH",
            "status": "HUMAN_REQUIRED",
            "question": "Hvilken primær lagringsmodel skal anvendes til audit-state og AST-kompilering?",
            "votes": [
                {"role": "Architect-Bot", "choice": "PostgreSQL JSONB", "confidence": "95%", "rationale": "Sikrer ACID og skalerbar AST-struktur."},
                {"role": "Security-Bot", "choice": "PostgreSQL JSONB", "confidence": "90%", "rationale": "Valideret adgangskontrol og encryption at rest."},
                {"role": "PM-Bot", "choice": "PostgreSQL JSONB", "confidence": "85%", "rationale": "Overholder SLA og driftsbudget."},
                {"role": "QA-Bot", "choice": "SQLite + JSON", "confidence": "60%", "rationale": "Hurtigere lokal test-cyklus, men mangler concurency."},
            ],
            "alternatives": [
                {
                    "key": "POSTGRESQL",
                    "title": "PostgreSQL med native JSONB",
                    "pros": ["ACID-compliance", "Skalerbar AST", "Maksimal dataintegritet"],
                    "cons": ["Kræver ekstern database-instans i drift"],
                    "risk": "LOW"
                },
                {
                    "key": "SQLITE",
                    "title": "Indlejret SQLite",
                    "pros": ["Nul ekstern infrastruktur", "Hurtig lokal eksekvering"],
                    "cons": ["Begrænset samtidig skriveadgang"],
                    "risk": "MEDIUM"
                }
            ]
        }
    ]

    for dec in demo_decisions:
        with st.expander(f"⚠️ **[{dec['risk']}]** {dec['title']} ({dec['status']})", expanded=True):
            st.write(f"**Spørgsmål:** {dec['question']}")
            st.write(f"**Kategori:** `{dec['category']}` | **Risiko:** `{dec['risk']}`")

            st.markdown("#### 🤖 Agent Council Rådslagnings-panel")
            cols = st.columns(len(dec["votes"]))
            for idx, vote in enumerate(dec["votes"]):
                with cols[idx]:
                    st.info(f"**{vote['role']}**\n\n**Valg:** {vote['choice']}\n\n**Sikkerhed:** {vote['confidence']}\n\n_{vote['rationale']}_")

            st.markdown("#### ⚖️ Valgmuligheder & Konsekvensanalyse")
            for alt in dec["alternatives"]:
                st.markdown(f"**Valg {alt['key']}: {alt['title']}** (Risiko: `{alt['risk']}`)")
                p_col, c_col = st.columns(2)
                with p_col:
                    st.write("✅ **Fordele:**")
                    for p in alt["pros"]:
                        st.write(f"- {p}")
                with c_col:
                    st.write("⚠️ **Ulemper / Risici:**")
                    for c in alt["cons"]:
                        st.write(f"- {c}")

            st.markdown("#### ✍️ Controller Afgørelse")
            choice = st.radio(
                "Vælg godkendt alternativ:",
                [alt["key"] for alt in dec["alternatives"]],
                key=f"radio_{dec['id']}"
            )
            rationale = st.text_area("Begrundelse for valg:", key=f"txt_{dec['id']}", placeholder="Angiv controller-begrundelse her...")

            b_col1, b_col2, _ = st.columns([1, 1, 3])
            with b_col1:
                if st.button("✅ Godkend Valg", key=f"btn_app_{dec['id']}"):
                    st.success(f"Beslutning '{dec['id']}' godkendt med valg: {choice}!")
            with b_col2:
                if st.button("❌ Afvis Alle / Kræv Ny Rådslagning", key=f"btn_rej_{dec['id']}"):
                    st.warning(f"Beslutning '{dec['id']}' afvist.")
