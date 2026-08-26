"""Swarm Live Monitor & Control Dashboard.

Real-time control panel for Controllers overseeing up to 20+ concurrent
bots working on the same governed project. Uses session-state mock fleet
data so the UI runs offline; live hooks can replace the mock generators.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants / mock fleet
# ---------------------------------------------------------------------------

_STATUSES = ("Idle", "Coding", "Testing", "Merging", "Blocked", "Paused")
_ROLES = (
    "Architect",
    "Impl Agent",
    "Security",
    "Test Agent",
    "PM Agent",
    "Reviewer",
    "Verifier",
)

_STATUS_EMOJI = {
    "Idle": "💤",
    "Coding": "💻",
    "Testing": "🧪",
    "Merging": "🔀",
    "Blocked": "🚫",
    "Paused": "⏸️",
}

_WBS_STATUSES = ("DONE", "IN_PROGRESS", "WAITING_DEP", "BLOCKED", "PENDING")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(seconds_ago: int = 0) -> str:
    return (_now() - timedelta(seconds=seconds_ago)).strftime("%H:%M:%S")


def _init_swarm_state() -> None:
    if "swarm_paused" not in st.session_state:
        st.session_state.swarm_paused = False
    if "swarm_force_review" not in st.session_state:
        st.session_state.swarm_force_review = False
    if "swarm_bots" not in st.session_state:
        st.session_state.swarm_bots = _seed_bots()
    if "swarm_wbs" not in st.session_state:
        st.session_state.swarm_wbs = _seed_wbs()
    if "swarm_log" not in st.session_state:
        st.session_state.swarm_log = _seed_log()
    if "swarm_tick" not in st.session_state:
        st.session_state.swarm_tick = 0


def _seed_bots() -> list[dict[str, Any]]:
    tasks = [
        "T-03 Domain ports",
        "T-04 API adapters",
        "T-05 OAuth2/PKCE",
        "T-06 Security gate",
        "T-07 Contract tests",
        "T-08 P3-20 verify",
        "T-09 Patch apply",
        "T-10 ADR review",
        "—",
    ]
    bots: list[dict[str, Any]] = []
    for i in range(1, 25):
        status = random.choice(_STATUSES[:4])  # bias toward active
        role = _ROLES[(i - 1) % len(_ROLES)]
        task = random.choice(tasks) if status != "Idle" else "—"
        bots.append(
            {
                "bot_id": f"bot-{i:02d}",
                "role": role,
                "task": task,
                "status": status,
                "cpu_pct": random.randint(5, 92) if status not in ("Idle", "Paused") else random.randint(0, 8),
                "last_heartbeat": _ts(random.randint(0, 45)),
            }
        )
    return bots


def _seed_wbs() -> list[dict[str, Any]]:
    return [
        {"id": "T-01", "name": "Requirements contract", "status": "DONE", "deps": "—", "assignee": "PM Agent"},
        {"id": "T-02", "name": "Architecture ADR", "status": "DONE", "deps": "T-01", "assignee": "Architect"},
        {"id": "T-03", "name": "Domain model & ports", "status": "IN_PROGRESS", "deps": "T-02", "assignee": "Impl Agent"},
        {"id": "T-04", "name": "API adapters (FastAPI)", "status": "IN_PROGRESS", "deps": "T-03", "assignee": "Impl Agent"},
        {"id": "T-05", "name": "Auth OAuth2/PKCE", "status": "WAITING_DEP", "deps": "T-02", "assignee": "Impl Agent"},
        {"id": "T-06", "name": "Security review gate", "status": "BLOCKED", "deps": "T-04,T-05", "assignee": "Security"},
        {"id": "T-07", "name": "Integration tests", "status": "PENDING", "deps": "T-04,T-05", "assignee": "Test Agent"},
        {"id": "T-08", "name": "P3-20 verification", "status": "PENDING", "deps": "T-06,T-07", "assignee": "Verifier"},
        {"id": "T-09", "name": "Patch ledger merge", "status": "PENDING", "deps": "T-08", "assignee": "Reviewer"},
        {"id": "T-10", "name": "Release evidence pack", "status": "PENDING", "deps": "T-09", "assignee": "PM Agent"},
    ]


def _seed_log() -> list[dict[str, str]]:
    return [
        {"time": _ts(90), "level": "PASS", "source": "AST", "message": "bot-03 domain/order.py — architecture constraints OK"},
        {"time": _ts(75), "level": "PASS", "source": "TEST", "message": "bot-07 tests/test_order_domain.py — 12 passed"},
        {"time": _ts(60), "level": "MERGE", "source": "Gate", "message": "patch-a7c82 approved under VerifiedAuthorityGrant"},
        {"time": _ts(45), "level": "FAIL", "source": "AST", "message": "bot-12 api/orders.py — forbid_call: subprocess.Popen"},
        {"time": _ts(30), "level": "PASS", "source": "TEST", "message": "bot-05 architecture AST suite — 5 passed"},
        {"time": _ts(18), "level": "INFO", "source": "Swarm", "message": "bot-09 claimed T-04 (lease 5m)"},
        {"time": _ts(8), "level": "PASS", "source": "TEST", "message": "bot-14 security static checks — 3 passed"},
        {"time": _ts(3), "level": "MERGE", "source": "Gate", "message": "patch-b7d902 merged to integration branch"},
    ]


def _simulate_tick() -> None:
    """Lightly mutate mock fleet so refresh feels live."""
    if st.session_state.swarm_paused:
        return
    st.session_state.swarm_tick += 1
    bots = st.session_state.swarm_bots
    for b in random.sample(bots, k=min(4, len(bots))):
        if b["status"] == "Paused":
            continue
        if random.random() < 0.35:
            b["status"] = random.choice(["Coding", "Testing", "Idle", "Merging"])
        b["cpu_pct"] = (
            random.randint(5, 95)
            if b["status"] not in ("Idle", "Paused")
            else random.randint(0, 5)
        )
        b["last_heartbeat"] = _ts(0)
    # Append a log line occasionally
    if random.random() < 0.5:
        levels = ["PASS", "PASS", "INFO", "MERGE", "FAIL"]
        sources = ["AST", "TEST", "Gate", "Swarm"]
        bot = random.choice(bots)["bot_id"]
        st.session_state.swarm_log.insert(
            0,
            {
                "time": _ts(0),
                "level": random.choice(levels),
                "source": random.choice(sources),
                "message": f"{bot} tick-{st.session_state.swarm_tick} activity sample",
            },
        )
        st.session_state.swarm_log = st.session_state.swarm_log[:40]


def _wbs_counts(wbs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {s: 0 for s in _WBS_STATUSES}
    for row in wbs:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def _pause_all() -> None:
    st.session_state.swarm_paused = True
    for b in st.session_state.swarm_bots:
        if b["status"] not in ("Idle", "Blocked"):
            b["status"] = "Paused"
            b["cpu_pct"] = 0
    st.session_state.swarm_log.insert(
        0,
        {
            "time": _ts(0),
            "level": "INFO",
            "source": "Controller",
            "message": "🛑 Swarm PAUSED by Controller",
        },
    )


def _resume_all() -> None:
    st.session_state.swarm_paused = False
    for b in st.session_state.swarm_bots:
        if b["status"] == "Paused":
            b["status"] = "Idle"
    st.session_state.swarm_log.insert(
        0,
        {
            "time": _ts(0),
            "level": "INFO",
            "source": "Controller",
            "message": "▶️ Swarm RESUMED by Controller",
        },
    )


def _restart_task(bot_id: str) -> None:
    for b in st.session_state.swarm_bots:
        if b["bot_id"] == bot_id:
            b["status"] = "Coding"
            b["cpu_pct"] = random.randint(20, 70)
            b["last_heartbeat"] = _ts(0)
            break
    st.session_state.swarm_log.insert(
        0,
        {
            "time": _ts(0),
            "level": "INFO",
            "source": "Controller",
            "message": f"🔄 Task restarted for {bot_id}",
        },
    )


def _force_review() -> None:
    st.session_state.swarm_force_review = True
    _pause_all()
    st.session_state.swarm_log.insert(
        0,
        {
            "time": _ts(0),
            "level": "INFO",
            "source": "Controller",
            "message": "👤 FORCE CONTROLLER REVIEW — all bots paused pending human gate",
        },
    )


# ---------------------------------------------------------------------------
# UI sections
# ---------------------------------------------------------------------------


def _render_overview(bots: list[dict[str, Any]]) -> None:
    st.subheader("🤖 Swarm Overview")
    active = sum(1 for b in bots if b["status"] in ("Coding", "Testing", "Merging"))
    blocked = sum(1 for b in bots if b["status"] == "Blocked")
    paused = sum(1 for b in bots if b["status"] == "Paused")
    idle = sum(1 for b in bots if b["status"] == "Idle")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Bots i alt", len(bots))
    m2.metric("Aktive", active)
    m3.metric("Idle", idle)
    m4.metric("Blocked", blocked)
    m5.metric("Paused", paused)

    if st.session_state.swarm_paused:
        st.warning("🛑 Swarm er **PAUSET**. Genoptag via Nødbremse-panelet.")
    if st.session_state.swarm_force_review:
        st.error("👤 **Controller Review påkrævet** — ingen ny execution før review lukkes.")

    # Filter
    role_filter = st.multiselect(
        "Filtrer på rolle",
        options=sorted({b["role"] for b in bots}),
        default=[],
    )
    status_filter = st.multiselect(
        "Filtrer på status",
        options=list(_STATUSES),
        default=[],
    )
    view = bots
    if role_filter:
        view = [b for b in view if b["role"] in role_filter]
    if status_filter:
        view = [b for b in view if b["status"] in status_filter]

    # Grid as dataframe + card sample
    df = pd.DataFrame(view)
    if not df.empty:
        df["status"] = df["status"].map(lambda s: f"{_STATUS_EMOJI.get(s, '•')} {s}")
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "bot_id": "Bot ID",
                "role": "Rolle",
                "task": "Nuværende opgave",
                "status": "Status",
                "cpu_pct": st.column_config.ProgressColumn("CPU %", min_value=0, max_value=100),
                "last_heartbeat": "Heartbeat",
            },
        )
    else:
        st.info("Ingen bots matcher filteret.")


def _render_wbs(wbs: list[dict[str, Any]]) -> None:
    st.subheader("📊 WBS DAG — fremdrift")
    counts = _wbs_counts(wbs)
    total = max(len(wbs), 1)
    done = counts.get("DONE", 0)
    st.progress(done / total)
    st.caption(f"{done}/{total} tasks fuldført")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("✅ Fuldført", counts.get("DONE", 0))
    c2.metric("🔄 I gang", counts.get("IN_PROGRESS", 0))
    c3.metric("⏳ Venter afhængighed", counts.get("WAITING_DEP", 0))
    c4.metric("🚫 Blokeret", counts.get("BLOCKED", 0))
    c5.metric("⬜ Pending", counts.get("PENDING", 0))

    df = pd.DataFrame(wbs)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_log(log: list[dict[str, str]]) -> None:
    st.subheader("📜 Sandkasse & Gatekeeper Log")
    st.caption("AST-validering · tests · merges · swarm events (seneste først)")

    level_colors = {
        "PASS": "🟢",
        "FAIL": "🔴",
        "MERGE": "🔵",
        "INFO": "⚪",
    }
    for entry in log[:25]:
        icon = level_colors.get(entry["level"], "•")
        st.markdown(
            f"`{entry['time']}` {icon} **{entry['level']}** · "
            f"`{entry['source']}` — {entry['message']}"
        )


def _render_controls(bots: list[dict[str, Any]]) -> None:
    st.subheader("🛑 Nødbremse & Kontrol")
    b1, b2, b3, b4 = st.columns(4)

    with b1:
        if st.session_state.swarm_paused:
            if st.button("▶️ Genoptag Swarm", type="primary", use_container_width=True):
                st.session_state.swarm_force_review = False
                _resume_all()
                st.rerun()
        else:
            if st.button("⏸️ Pause Swarm", type="primary", use_container_width=True):
                _pause_all()
                st.rerun()

    with b2:
        bot_ids = [b["bot_id"] for b in bots]
        chosen = st.selectbox("Bot til genstart", bot_ids, label_visibility="collapsed")
        if st.button("🔄 Genstart Opgave", use_container_width=True):
            _restart_task(chosen)
            st.rerun()

    with b3:
        if st.button("👤 Tving Controller Review", use_container_width=True):
            _force_review()
            st.rerun()

    with b4:
        if st.button("♻️ Simuler tick / refresh", use_container_width=True):
            _simulate_tick()
            st.rerun()

    st.caption(
        "Kontrolhandlinger er session-lokale i demo. Production binder dem til "
        "Control Plane commands under authority + audit (fail-closed)."
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def render_swarm_monitor() -> None:
    """Render the Swarm Fleet Monitor (call from app.py)."""
    _init_swarm_state()

    st.header("🤖 Swarm Fleet Monitor")
    st.caption(
        "Real-tids kontrolpanel for Controllers — op til 20+ bots parallelt. "
        "Mock fleet data; live queue/worker hooks kan erstatte generatorerne."
    )

    auto = st.checkbox("Auto-simuler aktivitet ved load", value=False)
    if auto:
        _simulate_tick()

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "Overview",
            "WBS fremdrift",
            "Sandkasse / Gate log",
            "Nødbremse",
        ]
    )

    bots = st.session_state.swarm_bots
    wbs = st.session_state.swarm_wbs
    log = st.session_state.swarm_log

    with tab1:
        _render_overview(bots)
    with tab2:
        _render_wbs(wbs)
    with tab3:
        _render_log(log)
    with tab4:
        _render_controls(bots)
