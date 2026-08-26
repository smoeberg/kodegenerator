"""System Generator & Workflow Cockpit — end-to-end wizard for Controllers.

Guides a human Controller from vision/requirements through AI council,
architecture HITL decisions, WBS task graph, and code/verification evidence.

Uses session state for wizard progress. Mock data enables offline demos;
live Control Plane hooks are stubs that degrade gracefully.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Wizard state keys
# ---------------------------------------------------------------------------

_WIZ = "workflow_wizard"
_STEPS = [
    "1 · Krav & Vision",
    "2 · AI-Rådslagning",
    "3 · Arkitektur & Beslutninger",
    "4 · Opgavenedbrydning (WBS)",
    "5 · Kode & Verifikation",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _init_wizard() -> None:
    if _WIZ not in st.session_state:
        st.session_state[_WIZ] = {
            "step": 0,
            "vision": {
                "system_name": "",
                "goal": "",
                "features": "",
                "tech_wishes": "",
                "constraints": "",
                "priority": "medium",
                "submitted": False,
                "submitted_at": None,
            },
            "council_seen": False,
            "architecture": {
                "style": "hexagonal",
                "data_store": "postgresql",
                "auth": "oauth2_pkce",
                "notes": "",
                "approved": False,
                "approved_at": None,
                "controller_choice": None,
            },
            "wbs_acknowledged": False,
            "verification": {
                "patches_reviewed": False,
                "tests_reviewed": False,
            },
        }


def _wiz() -> dict[str, Any]:
    _init_wizard()
    return st.session_state[_WIZ]


def _set_step(n: int) -> None:
    w = _wiz()
    w["step"] = max(0, min(n, len(_STEPS) - 1))


def _can_advance(step: int) -> bool:
    w = _wiz()
    if step == 0:
        return bool(w["vision"].get("submitted"))
    if step == 1:
        return bool(w.get("council_seen"))
    if step == 2:
        return bool(w["architecture"].get("approved"))
    if step == 3:
        return bool(w.get("wbs_acknowledged"))
    return True


def _mock_council(vision: dict[str, Any]) -> list[dict[str, str]]:
    name = vision.get("system_name") or "Systemet"
    return [
        {
            "agent": "Architect",
            "icon": "🏗️",
            "text": (
                f"For **{name}** anbefaler jeg hexagonal arkitektur med klare "
                "ports/adapters. Domain forbliver framework-uafhængigt; "
                "FastAPI kun i interface-laget."
            ),
        },
        {
            "agent": "Security",
            "icon": "🛡️",
            "text": (
                "Auth skal være OAuth2 Authorization Code + PKCE. Secrets via "
                "referencer, aldrig i klartekst i artefakter. PCI/PII-scope "
                "skal afgrænses tidligt hvis betalingsdata indgår."
            ),
        },
        {
            "agent": "PM",
            "icon": "📋",
            "text": (
                "Scope ser realistisk ud til ét governed single-run. "
                "Jeg foreslår MVP med kerneflows først, og udskyder "
                "nice-to-have integrationer til fase 2."
            ),
        },
        {
            "agent": "Impl Agent",
            "icon": "⚙️",
            "text": (
                "Allowlisted adapters dækker Postgres, Redis og test-runners. "
                "Patches holdes inden for godkendt context packet — ingen "
                "fri shell."
            ),
        },
        {
            "agent": "Architect",
            "icon": "🏗️",
            "text": (
                "Enighed om hexagonal + OAuth2/PKCE. Rejser HITL-beslutning "
                "på data-store (Postgres vs. hybrid) til Controller."
            ),
        },
    ]


def _mock_wbs(vision: dict[str, Any]) -> list[dict[str, str]]:
    name = vision.get("system_name") or "Target system"
    return [
        {"id": "T-01", "name": "Requirements contract", "role": "PM Agent", "status": "DONE", "deps": "—"},
        {"id": "T-02", "name": f"Architecture ADR for {name}", "role": "Architect", "status": "DONE", "deps": "T-01"},
        {"id": "T-03", "name": "Domain model & ports", "role": "Impl Agent", "status": "IN_PROGRESS", "deps": "T-02"},
        {"id": "T-04", "name": "API adapters (FastAPI)", "role": "Impl Agent", "status": "PENDING", "deps": "T-03"},
        {"id": "T-05", "name": "Auth (OAuth2/PKCE)", "role": "Impl Agent", "status": "PENDING", "deps": "T-02"},
        {"id": "T-06", "name": "Security review gate", "role": "Security", "status": "PENDING", "deps": "T-04, T-05"},
        {"id": "T-07", "name": "Integration & contract tests", "role": "Test Agent", "status": "PENDING", "deps": "T-04, T-05"},
        {"id": "T-08", "name": "P3-20 verification gate", "role": "Verifier", "status": "PENDING", "deps": "T-06, T-07"},
    ]


def _mock_patches() -> list[dict[str, Any]]:
    return [
        {"id": "patch-001", "path": "domain/order.py", "summary": "Order aggregate + invariants", "lines": "+86 / -0", "ast_ok": True, "fingerprint": "a3f1c8…e2b0"},
        {"id": "patch-002", "path": "api/endpoints/orders.py", "summary": "Create/list order endpoints", "lines": "+112 / -4", "ast_ok": True, "fingerprint": "b7d902…91aa"},
        {"id": "patch-003", "path": "tests/test_order_domain.py", "summary": "Domain unit tests", "lines": "+64 / -0", "ast_ok": True, "fingerprint": "c0e441…77f3"},
    ]


def _mock_test_results() -> list[dict[str, str]]:
    return [
        {"suite": "domain/order", "passed": "12", "failed": "0", "status": "PASS"},
        {"suite": "api/orders", "passed": "8", "failed": "0", "status": "PASS"},
        {"suite": "architecture AST constraints", "passed": "5", "failed": "0", "status": "PASS"},
        {"suite": "security static checks", "passed": "3", "failed": "0", "status": "PASS"},
    ]


def _step_vision() -> None:
    st.subheader("Trin 1 · Krav & Vision")
    st.markdown(
        "Beskriv systemet, du vil have DOR til at generere under governance. "
        "Felterne bliver input til AI-råd, arkitektur og WBS."
    )
    w = _wiz()
    v = w["vision"]

    c1, c2 = st.columns(2)
    with c1:
        v["system_name"] = st.text_input("Systemnavn", value=v.get("system_name") or "", placeholder="fx Order Service")
        v["priority"] = st.selectbox(
            "Prioritet",
            ["low", "medium", "high", "critical"],
            index=["low", "medium", "high", "critical"].index(v.get("priority") or "medium"),
        )
    with c2:
        v["goal"] = st.text_input("Overordnet mål", value=v.get("goal") or "", placeholder="fx Accepter og fuldfør ordrer med audit-spor")

    v["features"] = st.text_area("Funktioner / capabilities", value=v.get("features") or "", height=100, placeholder="Én pr. linje eller komma-separeret…")
    v["tech_wishes"] = st.text_area("Tekniske ønsker", value=v.get("tech_wishes") or "", height=80, placeholder="fx Python, FastAPI, Postgres, hexagonal…")
    v["constraints"] = st.text_area("Constraints / non-funktionelle krav", value=v.get("constraints") or "", height=80, placeholder="fx GDPR, max latency, ingen vendor lock-in…")

    if v.get("submitted"):
        st.success(f"Vision indsendt {_fmt(v.get('submitted_at'))}. Du kan opdatere felterne og indsende igen.")

    if st.button("💾 Gem & fortsæt til AI-rådslagning", type="primary"):
        if not (v.get("system_name") or "").strip() or not (v.get("goal") or "").strip():
            st.error("Systemnavn og overordnet mål er påkrævet.")
        else:
            v["submitted"] = True
            v["submitted_at"] = _now()
            _set_step(1)
            st.rerun()


def _step_council() -> None:
    st.subheader("Trin 2 · AI-Rådslagning (Live)")
    st.markdown("Specialist-bots diskuterer løsningsmodeller ud fra din vision. I production abonnerer feedet på Control Plane events.")
    w = _wiz()
    vision = w["vision"]
    if not vision.get("submitted"):
        st.warning("Indsend vision i trin 1 først.")
        return
    st.info(f"**{vision.get('system_name')}** — {vision.get('goal')} (prioritet: `{vision.get('priority')}`)")
    for msg in _mock_council(vision):
        st.markdown(
            f"<div class='council-msg'><strong>{msg['icon']} {msg['agent']}</strong><br/>{msg['text']}</div>",
            unsafe_allow_html=True,
        )
    w["council_seen"] = True
    if st.button("➡️ Videre til arkitektur & beslutninger", type="primary"):
        _set_step(2)
        st.rerun()


def _step_architecture() -> None:
    st.subheader("Trin 3 · Arkitektur & Beslutninger (HITL)")
    st.markdown("Godkend eller tilpas arkitekturvalg. Kun Controller kan lukke dette trin — AI kan anbefale, ikke selv godkende.")
    w = _wiz()
    arch = w["architecture"]
    c1, c2, c3 = st.columns(3)
    with c1:
        arch["style"] = st.selectbox(
            "Arkitekturstil",
            ["hexagonal", "layered", "modular_monolith", "event_driven"],
            index=["hexagonal", "layered", "modular_monolith", "event_driven"].index(arch.get("style") or "hexagonal"),
        )
    with c2:
        arch["data_store"] = st.selectbox(
            "Primær data store",
            ["postgresql", "postgresql+redis", "sqlite_dev_only"],
            index=["postgresql", "postgresql+redis", "sqlite_dev_only"].index(arch.get("data_store") or "postgresql"),
        )
    with c3:
        arch["auth"] = st.selectbox(
            "Auth-model",
            ["oauth2_pkce", "session_cookie", "mtls_service"],
            index=["oauth2_pkce", "session_cookie", "mtls_service"].index(arch.get("auth") or "oauth2_pkce"),
        )
    arch["notes"] = st.text_area("Controller-noter / ADR-kommentar", value=arch.get("notes") or "", height=80)
    st.markdown("#### AI-rådets anbefaling")
    st.write("- **Stil:** hexagonal (domain uafhængig af framework)\n- **Store:** postgresql (+ Redis kun hvis session/cache kræves)\n- **Auth:** oauth2_pkce")
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("✅ Godkend anbefaling", type="primary", use_container_width=True):
            arch["approved"] = True
            arch["approved_at"] = _now()
            arch["controller_choice"] = "APPROVE_RECOMMENDATION"
            st.success("Arkitektur godkendt.")
            st.rerun()
    with b2:
        if st.button("✏️ Godkend mine valg", use_container_width=True):
            arch["approved"] = True
            arch["approved_at"] = _now()
            arch["controller_choice"] = "CUSTOM_ARCHITECTURE"
            st.success("Dine arkitekturvalg er registreret.")
            st.rerun()
    with b3:
        if st.button("🔎 Kræv mere analyse", use_container_width=True):
            arch["approved"] = False
            arch["controller_choice"] = "REQUEST_MORE_ANALYSIS"
            st.warning("Mere analyse krævet — bliv på dette trin.")
    if arch.get("approved"):
        st.success(
            f"Godkendt {_fmt(arch.get('approved_at'))} ({arch.get('controller_choice')}): "
            f"`{arch['style']}` / `{arch['data_store']}` / `{arch['auth']}`"
        )
        if st.button("➡️ Videre til WBS", type="primary"):
            _set_step(3)
            st.rerun()


def _step_wbs() -> None:
    st.subheader("Trin 4 · Opgavenedbrydning (WBS)")
    st.markdown("Inspicér den genererede task-graf og tildelte roller. Identiteter er stabile; PM Agent må ikke selv eksekvere eller verificere.")
    w = _wiz()
    rows = _mock_wbs(w["vision"])
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    done = sum(1 for r in rows if r["status"] == "DONE")
    st.caption(f"{done}/{len(rows)} tasks markeret DONE i demo-grafen.")
    w["wbs_acknowledged"] = st.checkbox(
        "Jeg har inspiceret WBS og accepterer opgavenedbrydningen",
        value=bool(w.get("wbs_acknowledged")),
    )
    if w["wbs_acknowledged"]:
        if st.button("➡️ Videre til kode & verifikation", type="primary"):
            _set_step(4)
            st.rerun()


def _step_code_verify() -> None:
    st.subheader("Trin 5 · Kode & Verifikation")
    st.markdown("Genererede patches, AST-validering og test-resultater. Endelig PASS/FAIL ligger hos P3-20 — ikke hos Impl eller Test Agent.")
    w = _wiz()
    st.markdown("#### Patches")
    for p in _mock_patches():
        icon = "✅" if p["ast_ok"] else "❌"
        with st.expander(f"{icon} `{p['path']}` · {p['id']}"):
            st.write(p["summary"])
            st.caption(f"Diff: {p['lines']} · AST: {'OK' if p['ast_ok'] else 'FAIL'} · Fingerprint: `{p['fingerprint']}`")
    st.markdown("#### Test & architecture checks")
    st.dataframe(pd.DataFrame(_mock_test_results()), use_container_width=True, hide_index=True)
    ver = w["verification"]
    ver["patches_reviewed"] = st.checkbox("Patches gennemgået", value=bool(ver.get("patches_reviewed")))
    ver["tests_reviewed"] = st.checkbox("Test- og AST-resultater gennemgået", value=bool(ver.get("tests_reviewed")))
    if ver["patches_reviewed"] and ver["tests_reviewed"]:
        st.success("Controller har gennemgået evidence. I production sendes næste command via Control Plane under authority grant.")
        st.balloons()
        if st.button("🏁 Afslut wizard / start forfra"):
            del st.session_state[_WIZ]
            st.rerun()
    else:
        st.info("Markér begge gennemgange for at lukke pipeline-demoen.")


def _fmt(ts: str | None) -> str:
    return ts or "—"


def render_workflow_cockpit() -> None:
    """Render the System Generator wizard (call from app.py page branch)."""
    _init_wizard()
    w = _wiz()
    st.header("🚀 System Generator & Workflow")
    st.caption(
        "End-to-end pipeline: vision → AI-råd → HITL-arkitektur → WBS → kode/verifikation. "
        "Demo anvender mock evidence; live hooks falder tilbage gracefully."
    )
    step = w["step"]
    cols = st.columns(len(_STEPS))
    for i, label in enumerate(_STEPS):
        with cols[i]:
            if i == step:
                st.markdown(f"**▶ {label}**")
            elif i < step:
                st.markdown(f"~~{label}~~ ✓")
            else:
                st.markdown(f"{label}")
    st.progress((step + 1) / len(_STEPS))
    st.divider()
    nav_l, nav_c, nav_r = st.columns([1, 2, 1])
    with nav_l:
        if step > 0 and st.button("← Forrige"):
            _set_step(step - 1)
            st.rerun()
    with nav_r:
        if step < len(_STEPS) - 1:
            disabled = not _can_advance(step)
            if st.button("Næste →", disabled=disabled):
                if _can_advance(step):
                    _set_step(step + 1)
                    st.rerun()
            if disabled:
                st.caption("Fuldfør trinnet for at gå videre.")
    if step == 0:
        _step_vision()
    elif step == 1:
        _step_council()
    elif step == 2:
        _step_architecture()
    elif step == 3:
        _step_wbs()
    else:
        _step_code_verify()
