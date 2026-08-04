# 🖥️ DOR Web Dashboard

Visual Governance and Runtime Monitoring Interface for **Digital Organization Runtime (DOR)** built with Streamlit.

## 🚀 Features
- **Organization Overview:** Real-time metrics on Organizations, Digital/Human Actors, Workflows, and Artifacts.
- **Active Workflows:** Monitor state transitions (`NEW` → `IMPLEMENTATION` → `REVIEW` → `APPROVED`).
- **Governance Gates Action Center:** Human-in-the-loop review interface for signing artifacts and evaluating gates.
- **Digital Actors Registry:** Overview of active AI employees, human supervisors, and service bots.
- **Artifacts Registry:** Cryptographic SHA-256 audit trail for all software and decision artifacts.

## 🏃 Quickstart

1. Install dependencies:
   ```bash
   pip install streamlit pandas
   ```

2. Initialize demo data (optional):
   ```bash
   python3 seed_data.py
   ```

3. Launch Dashboard:
   ```bash
   streamlit run dashboard/app.py
   ```
