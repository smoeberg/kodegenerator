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

3. Configure the required dashboard secrets:
   ```bash
   export DOR_ADMIN_PASSWORD='replace-with-a-strong-password'
   export DOR_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
   ```

4. Launch Dashboard:
   ```bash
   streamlit run dashboard/app.py
   ```
