# DOR – husregler v1 (udkast)

Status: udkast til gennemsyn · 16. november 2026

Husreglerne gælder al kode, som fabrikken leverer, uanset stak. Projektregler for den valgte stak afledes i arkitekturtrinnet og godkendes sammen med arkitekturen.

Hver regel er mærket:

- **M** = maskinelt kontrollerbar. Brud er et hårdt stop i niveau 1.
- **V** = vurderingssag. Bedømmes af review-botten i niveau 1 og kan sende koden til rework.

Kolonnen "Grundlag" viser, om reglen bygger på noget, repoet allerede håndhæver på sig selv (commit `98449e2`), eller er et nyt forslag.

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

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 1.1 | En leverance ændrer kun filer inden for opgavens skriveområde | M | Repo: patch-scope i implementeringsagenten |
| 1.2 | Hver opgave henviser til mindst ét krav-id og én kontrakt | M | Repo: sporbarhedsmodel |
| 1.3 | Funktionalitet uden et krav bag er ikke tilladt | V | Forslag |
| 1.4 | Antagelser skrives eksplicit i leverancen og ikke i koden som fakta | V | Repo: kravspec-modellens antagelsesfelt |

## 2. Kodekvalitet

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 2.1 | Koden består stakkens linter uden fejl | M | Repo: Ruff, men kun på `ci/` og én testfil |
| 2.2 | Koden følger stakkens formateringsværktøj | M | Repo: `ruff format --check`, samme begrænsede omfang |
| 2.3 | Koden bygger og kan importeres uden fejl | M | Repo: build-adapter |
| 2.4 | Ingen død kode, udkommenteret kode eller TODO uden opgave-id | V | Forslag |
| 2.5 | Navngivning følger stakkens konvention og kontraktens begreber | V | Forslag |
| 2.6 | Én funktion har ét ansvar; dublering af eksisterende komponenter er ikke tilladt | V | Repo: `AGENTS.md` (søg efter eksisterende komponent først) |

## 3. Test

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 3.1 | Hver leverance har kørbare tests | M | Repo: `AGENTS.md` |
| 3.2 | Hele testsuiten består, kørt af systemet selv | M | Repo: CI |
| 3.3 | Dækningen falder ikke under 70 % | M | Repo: `--cov-fail-under=70` i `phase7.yml` |
| 3.4 | Hvert acceptkriterium har mindst én test, der henviser til det | M | Repo: kontrakttest-generator |
| 3.5 | Tests afprøver adfærd og ikke kun, at koden kan kaldes | V | Forslag |

## 4. Arkitektur

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 4.1 | Afhængigheder følger arkitekturkontraktens lag- og afhængighedsregler | M | Repo: afhængigheds- og AST-evaluatorer |
| 4.2 | Moduler taler kun sammen gennem deres kontrakter | M | Forslag (kræver modulkontrakter, trin 4) |
| 4.3 | Offentlige interfaces ændres ikke uden kontraktændring | M | Forslag |

## 5. Sikkerhed og afhængigheder

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 5.1 | Ingen hemmeligheder i kode, logs, prompts eller tests | M | Repo: secret-boundary-dokumentation; scanner skal vælges |
| 5.2 | Statisk sikkerhedsscanning uden fund over aftalt niveau | M | Repo: Bandit og CodeQL |
| 5.3 | Nye biblioteker skal findes i det officielle register og være uden kendte sårbarheder | M | Repo: pip-audit; register-opslag er nyt |
| 5.4 | Nye biblioteker begrundes i leverancen | V | Forslag |
| 5.5 | Ekstern input valideres ved systemgrænsen | V | Forslag |

## 6. Data og fejl

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 6.1 | Databaseændringer sker kun gennem migrationer med én entydig head | M | Repo: Alembic-check i CI |
| 6.2 | Migrationer kan køres på en tom database | M | Repo: CI |
| 6.3 | Fejl håndteres eksplicit; ingen tavse `except` eller tilsvarende | V | Forslag |
| 6.4 | Ved manglende eller usikre data fejler koden lukket | V | Repo: fail-closed-princippet |

## 7. Dokumentation

| # | Regel | Type | Grundlag |
|---|---|---|---|
| 7.1 | Offentlige funktioner og moduler har en kort beskrivelse | V | Forslag |
| 7.2 | Ændret adfærd afspejles i modulets dokumentation i samme leverance | V | Forslag |

## Til afklaring

1. Dækningsgrænsen på 70 % er taget fra repoets CI. Skal den gælde for genereret kode?
2. Regel 2.1 og 2.2 håndhæves i dag kun på en lille del af repoet. For genereret kode foreslås hele leverancen.
3. Regel 5.2 kræver et aftalt niveau for, hvilke fund der stopper en leverance.
4. Mangler der regler fra jeres egen praksis, for eksempel om sprog i kode og kommentarer, commit-beskeder eller logning?
5. Hvilke af forslagsreglerne skal starte som "på prøve" i stedet for "aktiv"?
