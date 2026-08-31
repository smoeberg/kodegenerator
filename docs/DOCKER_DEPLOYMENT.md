# Docker Deployment & Auto-Update Guide

Systemet understøtter komplet containeriseret drift via Docker & Docker Compose med automatisk opdatering, når `main` grenen opdateres på GitHub.

---

## 🏗️ Arkitektur i Docker

Docker Compose orkestrerer 4 sammenhængende services:

| Service | Port | Beskrivelse |
|---|---|---|
| **`api`** | `8000` | FastAPI REST API backend & core engine |
| **`dashboard`** | `8501` | Streamlit Visual Management & Controller GUI |
| **`worker`** | - | Baggrunds-agent worker & swarm orchestrator |
| **`watchtower`** | - | **Auto-updater:** Poller GHCR hvert 60. sekund og opdaterer kørende containere uden nedetid |

---

## 🚀 Hurtig Start (Lokal eller Server)

### 1. Klon eller hent `docker-compose.yml`
```bash
git clone https://github.com/smoeberg/kodegenerator.git
cd kodegenerator
```

### 2. Konfigurer miljøvariable (`.env`)
```bash
cp .env.example .env
# Rediger .env med dine nøgler (f.eks. REDMINE_URL, REDMINE_API_KEY, DOR_ADMIN_PASSWORD)
```

### 3. Start hele systemet
```bash
docker compose up -d
```

- **Dashboard / GUI:** [http://localhost:8501](http://localhost:8501)
- **API & Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🔄 Automatisk Opdatering ved Push til `main`

Når du merger eller pusher kode til `main`:

1. **GitHub Actions (`docker-publish.yml`)** bygger automatisk et nyt Docker image og pusher til GitHub Container Registry (`ghcr.io/smoeberg/kodegenerator:latest`).
2. **Watchtower** (kørende på din server) opdager det nye image inden for 60 sekunder.
3. Watchtower downloader det nye image og genstarter `api`, `dashboard` og `worker` med bevaret data (`dor-data` volume).

### Manuel opdatering (hvis Watchtower ikke anvendes):
```bash
docker compose pull
docker compose up -d
```
