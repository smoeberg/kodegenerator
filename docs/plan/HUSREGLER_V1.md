# DOR – husregler v1

Status: **godkendt** · version 1 · godkendt af projektlederen 27. november 2026

Husreglerne gælder al kode, som fabrikken leverer, uanset stak. Projektregler for den valgte stak afledes i arkitekturtrinnet og godkendes sammen med arkitekturen.

Hver regel er mærket med en type:

- **M** = maskinelt kontrollerbar. Brud er et hårdt stop i niveau 1, når reglen er aktiv.
- **V** = vurderingssag. Bedømmes af review-botten i niveau 1 og kan sende koden til rework, når reglen er aktiv.

Kolonnen "Grundlag" viser, om reglen bygger på noget, repoet allerede håndhævede på sig selv (commit `98449e2`), eller var et nyt forslag. Kolonnen "Tilstand" er reglens tilstand i version 1.

## Sådan udvikler reglerne sig

Husreglerne er et versioneret regelsæt. En version ændres aldrig; en ændring giver en ny version.

### Livscyklus

| Tilstand | Betydning |
|---|---|
| Foreslået | Beskrevet og begrundet, endnu ikke i brug |
| På prøve | Måles på hver leverance, men stopper ingen |
| Aktiv | Håndhæves i niveau 1 |
| Udfaset | Ikke længere i brug; bevares i historikken |

### Kilder til ændringer

- **Egen empiri:** fund fra niveau 1 og 2, rework-runder, fejl fundet ved milestone-kontrollen eller efter fletning, og sprintens retrospektiv (erfaringsloggen).
- **Ekstern best practice:** gennemgås med faste mellemrum.

### Måling pr. regel

- hvor ofte reglen udløses;
- hvor ofte et menneske eller niveau 2 underkender den;
- om den hænger sammen med færre fejl senere.

En regel på prøve bliver aktiv, når målingen viser, at den fanger reelle fejl uden mange falske fund. En aktiv regel, der sjældent udløses eller ofte underkendes, foreslås udfaset.

### Hvem må hvad

- Agenter og projektassistenten må foreslå regler og ændringer.
- Projektlederen godkender hver ny version.
- En agent må aldrig selv ændre de regler, den bliver målt på.
- Regelsættet er frosset inden for en sprint. En ny version gælder fra næste sprint.

## 1. Omfang og sporbarhed

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 1.1 | En leverance ændrer kun filer inden for opgavens skriveområde | M | Repo: patch-scope i implementeringsagenten | Aktiv |
| 1.2 | Hver opgave henviser til mindst ét krav-id og én kontrakt | M | Repo: sporbarhedsmodel | Aktiv |
| 1.3 | Funktionalitet uden et krav bag er ikke tilladt | V | Forslag | På prøve |
| 1.4 | Antagelser skrives eksplicit i leverancen og ikke i koden som fakta | V | Repo: kravspec-modellens antagelsesfelt | Aktiv |

## 2. Kodekvalitet

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 2.1 | Hele leverancen består stakkens linter uden fejl | M | Repo: Ruff, men kun på `ci/` og én testfil | Aktiv |
| 2.2 | Hele leverancen følger stakkens formateringsværktøj | M | Repo: `ruff format --check`, samme begrænsede omfang | Aktiv |
| 2.3 | Koden bygger og kan importeres uden fejl | M | Repo: build-adapter | Aktiv |
| 2.4 | Ingen død kode, udkommenteret kode eller TODO uden opgave-id | V | Forslag | På prøve |
| 2.5 | Navngivning følger stakkens konvention og kontraktens begreber | V | Forslag | På prøve |
| 2.6 | Én funktion har ét ansvar; dublering af eksisterende komponenter er ikke tilladt | V | Repo: `AGENTS.md` (søg efter eksisterende komponent først) | Aktiv |

## 3. Test

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 3.1 | Hver leverance har kørbare tests | M | Repo: `AGENTS.md` | Aktiv |
| 3.2 | Hele testsuiten består, kørt af systemet selv | M | Repo: CI | Aktiv |
| 3.3 | Dækningen af den genererede kode er mindst 70 % | M | Repo: `--cov-fail-under=70` i `phase7.yml` | Aktiv |
| 3.4 | Hvert acceptkriterium har mindst én test, der henviser til det | M | Repo: kontrakttest-generator | Aktiv |
| 3.5 | Tests afprøver adfærd og ikke kun, at koden kan kaldes | V | Forslag | På prøve |

## 4. Arkitektur

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 4.1 | Afhængigheder følger arkitekturkontraktens lag- og afhængighedsregler | M | Repo: afhængigheds- og AST-evaluatorer | Aktiv |
| 4.2 | Moduler taler kun sammen gennem deres kontrakter | M | Forslag (kræver modulkontrakter, trin 4) | Aktiv |
| 4.3 | Offentlige interfaces ændres ikke uden kontraktændring | M | Forslag | Aktiv |

## 5. Sikkerhed og afhængigheder

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 5.1 | Ingen hemmeligheder i kode, logs, prompts eller tests | M | Repo: secret-boundary-dokumentation; scanner skal vælges | Aktiv |
| 5.2 | Statisk sikkerhedsscanning uden fund med alvorlighed medium eller højere (Bandit eller stakkens tilsvarende) | M | Repo: Bandit og CodeQL | Aktiv |
| 5.3 | Nye biblioteker skal findes i det officielle register og være uden kendte sårbarheder; enhver kendt sårbarhed stopper leverancen | M | Repo: pip-audit; register-opslag er nyt | Aktiv |
| 5.4 | Nye biblioteker begrundes i leverancen | V | Forslag | På prøve |
| 5.5 | Ekstern input valideres ved systemgrænsen | V | Forslag | På prøve |

## 6. Data og fejl

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 6.1 | Databaseændringer sker kun gennem migrationer med én entydig head | M | Repo: Alembic-check i CI | Aktiv |
| 6.2 | Migrationer kan køres på en tom database | M | Repo: CI | Aktiv |
| 6.3 | Fejl håndteres eksplicit; ingen tavse `except` eller tilsvarende | V | Forslag | På prøve |
| 6.4 | Ved manglende eller usikre data fejler koden lukket | V | Repo: fail-closed-princippet | Aktiv |

## 7. Dokumentation

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 7.1 | Offentlige funktioner og moduler har en kort beskrivelse | V | Forslag | På prøve |
| 7.2 | Ændret adfærd afspejles i modulets dokumentation i samme leverance | V | Forslag | På prøve |

## 8. Praksis

| # | Regel | Type | Grundlag | Tilstand |
|---|---|---|---|---|
| 8.1 | Kode, navne og kommentarer skrives på engelsk | V | Projektlederens praksis | På prøve |
| 8.2 | Hver commit-besked indeholder opgavens id | M | Projektlederens praksis | Aktiv |

## Beslutninger ved godkendelsen

Projektlederen godkendte version 1 den 27. november 2026 med disse afklaringer:

1. Dækningsgrænsen på 70 % gælder for den genererede kode (regel 3.3).
2. Lint og formatering gælder hele leverancen og ikke kun en del af den (regel 2.1 og 2.2).
3. En leverance stoppes af sikkerhedsfund med alvorlighed medium eller højere og af enhver kendt sårbarhed i afhængigheder (regel 5.2 og 5.3).
4. To regler fra projektlederens praksis er tilføjet: engelsk i kode og kommentarer (8.1) og opgave-id i commit-beskeder (8.2).
5. V-regler, der var nye forslag, starter på prøve. Alle M-regler og V-regler med grundlag i repoet starter aktive.
