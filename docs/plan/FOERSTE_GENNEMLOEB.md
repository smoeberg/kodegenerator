# Første gennemløb (trin 8a) — drejebog

Besluttet af styregruppen 27. november 2026: arbejderne kører på en ny UpCloud-maskine, Mistral er tredje producent, og backuppen ligger i UpCloud Object Storage. Rollefordelingen står i `config/first_run/factory.yaml`.

| Producent | Roller |
|---|---|
| Anthropic | Testdesigner (Claude Code), arkitekt, kontraktforfatter, opgaveproducent |
| OpenAI | Kodere (Codex) |
| Mistral | Arkitekturreviewer, kontekstkontrollant, systemarkitekt, kodeauditør, sikkerhedsansvarlig, produktejer, release-ansvarlig |

`python -m execution.first_run check` kontrollerer fordelingen mod rollekataloget. Den giver tre advarsler: systemarkitekt, produktejer og release-ansvarlig er alle Mistral, selv om kataloget lader dem kontrollere hinanden. De kontroller køres ikke i første gennemløb; i milestonen kører de efter hinanden og ser hinandens resultater, men ingen af dem kontrollerer en andens output. Kræver det at blive ægte, skal der en fjerde producent til.

## 1. Maskinen (styregruppen)

1. Opret en UpCloud-server med Ubuntu 24.04 LTS (2 CPU, 4 GB RAM er nok til første gennemløb) og indsæt `deploy/worker/cloud-init.yaml` som user data; skift SSH-nøglen ud med din egen først.
2. Opret en bucket i UpCloud Object Storage og et adgangsnøglepar, der kun må skrive til den bucket.
3. Log ind som `dor`, kopiér `/etc/dor/worker.env.example` til `/etc/dor/worker.env`, `chmod 600`, og udfyld nøglerne. Ingen nøgler i repoet, i chat eller i logs.

## 2. DOR og Bot Catalog

```bash
set -a; . /etc/dor/worker.env; set +a
cd /srv/dor/kodegenerator && . /srv/dor/venv/bin/activate
python -m execution.first_run check
python -m execution.first_run setup --api http://localhost:8000 --organization <org>
eval "$(python -m execution.first_run env)"
```

`setup` opretter forbindelser, udrulninger og profiler gennem DOR's API og gemmer nøglerne krypteret; den viser dem aldrig.

## 3. Kravspec til kontrakter (pipelinen)

Start pipelinen på husregel-registeret (`docs/plan/kravspec/husregel-register.yaml`). Arkitekturrådet, kontraktrådet og opgaveproducenten kører med profilerne; styregruppen godkender ved arkitektur-gaten og kontrakt-gaten (med arbejdsplan og skaleringsplan). Gem pipeline-status som JSON, når kontrakt-gaten er godkendt.

## 4. Milestonen

Målprojektet er sit eget git-repo med en `main`-branch, fx `/srv/dor/projects/husregel-register`.

```bash
R=/srv/dor/projects/husregel-register; S=status.json; O=<org>
python -m execution.first_run start  --repo $R --organization $O --status $S --actor <dig>
python -m execution.first_run sprint --repo $R --organization $O --status $S --actor <dig> --number 1
python -m execution.milestone --repo $R --milestone M1 review-sprint --sprint 1 --decision approved --reviewer <dig>
python -m execution.first_run sprint --repo $R --organization $O --status $S --actor <dig> --number 2
python -m execution.milestone --repo $R --milestone M1 review-sprint --sprint 2 --decision approved --reviewer <dig>
python -m execution.first_run finish --repo $R --organization $O --status $S --actor <dig>
python -m execution.milestone --repo $R --milestone M1 approve --approver <dig>
```

Efter godkendelsen skubber du `milestone/M1` og fletter den ene PR til `main` i målprojektet. Derefter:

```bash
python -m execution.milestone --repo $R --milestone M1 mark-merged --main-sha <sha> --actor <dig>
```

Det sætter `known-good/M1`, tager en verificeret `git bundle`, kopierer milestone-tilstand og release-bevis og lægger dem i Object Storage med kontrolsum.

## 5. Hvad der måles

Statistikken står i milestonens tilstand og i release-beviset: pr. rolle og producent, pr. promptversion og pr. koder og opgavetype. Den er grundlaget for at afgøre, om rådene gøres obligatoriske og skabelonsporet fjernes.
