# DOR – plan for færdiggørelse

Version 14 · 27. november 2026 · Whiteboard: https://claude.ai/artifact/5ZMM2dgqXTTGB1TSzeAcNg

Nyt i version 14: styringslaget (beslutning 40–43). Styregruppen er mennesket og den eneste, der beslutter; produktejer, systemarkitekt, projektleder, kvalitetsansvarlig og release-ansvarlig er agentroller, der ejer et artefakt og indstiller. Nye roller: opgaveproducent, testdesigner, promptproducent, promptreviewer, sikkerhedsansvarlig og rapport og statistik. Rollekataloget er version 2 (`config/role_process/catalog.v2.yaml`).

Nyt i version 13: grundprincippet om rolle-proces-logik (beslutning 39), rollekataloget som versioneret data i `config/role_process/catalog.v1.yaml` og håndhævelsen i pipelinen.

Nyt i version 12: kontrol er rolleadskillelse mellem koder, kodeauditør og kontekstkontrollant, og de to kontrolroller kommer fra en anden producent end koderen (beslutning 36); tilbagerulning frem for fejlretning (beslutning 35); agentlog for hvert job (beslutning 37); backup i fire lag (beslutning 38).

Nyt i version 11: husregler v1 og kravspec'en for husregel-registeret er godkendt (`docs/plan/HUSREGLER_V1.md`, `docs/plan/kravspec/husregel-register.yaml`). #297, #298 og #299 er flettet; repoet er offentligt.

Nyt i version 10: milestone-branchen er kortlivet og genbaseres på den nyeste `main` ved hver sprintstart, og hver arbejdspakke bindes til commit, kravspec-revision og kontraktversion (beslutning 34 og afsnittet "Milestone-branches").

Nyt i version 9: første gennemløb af hele kæden efter trin 8 (beslutning 33, afsnittet "Første gennemløb" og trin 8a). Testisolationen er løst (#292).

## Mål

Et udviklingsværktøj, hvor flere AI-agenter i en stram organisation med roller og kontroller udvikler software ud fra en kravspec (opdraget):

kravspec → arkitektur → kontrakter → opgaver → kodning → kontrol → samlet system → opdragskontrol → tilbage til kravspec

Forløbet er en lukket sløjfe, ikke en linje. DOR er styringslaget: det styrer og kontrollerer, mens færdige kodeagenter udfører. Den menneskelige kontrol er den overordnede: systemet anbefaler, mennesket beslutter. Systemet lærer af sine egne job: hvilke agenter og prompts der klarer hvilke opgaver bedst. På sigt udvikler DOR sig selv. Den eksisterende dokumentation i repoet er retningslinje, ikke bindende.

## Grundprincip: rolle-proces-logik

DOR er rolle-proces-logik. Processen er en fast kæde af roller; agenterne er udskiftelige og tildeles roller pr. job.

Formålet er at skabe intelligens gennem dialog mellem flere AI-modeller: én rolle foreslår, en anden fra en anden producent udfordrer, og forslaget revideres. Modeller fra forskellige producenter har forskellige styrker og blinde vinkler, og det er i mødet mellem dem, at fejl og bedre løsninger findes. Dialogen er struktureret af rollerne, så den har et formål, et begrænset antal runder og en afslutning.

- **Uenighed er et signal.** Den registreres og ender som rework, et ændringsforslag eller en beslutning hos styregruppen; den glattes aldrig ud.
- **Enighed er ikke bevis.** Modeller kan blive enige om noget forkert. Kun det efterprøvede tæller: tests, systemet selv har kørt, og faktakontrollen.

- **En rolle er en prompt plus en kontekstpakke i et frisk job.** Enhver agent kan have enhver rolle; den samme model kan være koder i ét job og kodeauditør i det næste.
- **Intet output går videre ukontrolleret.** Hver agentrolles output kontrolleres af en anden rolle, og faktakontrollen kører på alle.
- **Uafhængighed hvor det betyder noget.** På samme arbejdspakke kommer en kontrolrolle fra en anden producent (brand: anthropic, openai, mistral …) end den rolle, den kontrollerer, og den kører i en ny session uden dennes kontekst. Kan uafhængigheden ikke efterprøves, afvises tildelingen.
- **Rollerne er data, ikke kode.** Rollekataloget er versioneret konfiguration (`config/role_process/catalog.v2.yaml`), godkendt af styregruppen. `domain/role_process.py` validerer det og afviser et inkonsistent katalog; pipelinen tager hvert jobs rolle fra kataloget og håndhæver reglen, når en agent bindes til et job.

Alle andre beslutninger bygger på dette princip.

## Udgangspunkt

Analysen er lavet mod `smoeberg/kodegenerator`, branch `main`, commit `98449e2`, Alembic-head `036_runtime_settings`. Lokalt bestod 2.425 tests og 3 fejlede. De tre ligger i `test_swarm_operations_api.py` og består, når filen køres alene; de fejler kun sammen med de øvrige API-tests, fordi login med standard-administratoren afvises. Det peger på, at testene deler tilstand, og ikke på en fejl i produktet. E2E-, phase6- og acceptance-suiterne er ikke kørt.

Status 26. november 2026: #292 (testisolation), #293 (OpenTelemetry-sårbarhed) og #294 (CI-artefakter og CodeQL) er flettet, og CI er grøn. Standard-administratoren sættes nu op i en fælles `tests/conftest.py`. Første del af trin 1, kravspec-revision og jobposter, ligger i #296.

Status 27. november 2026, trin 1: kravspec-revision og jobposter (#296), Swarm-sporet udfaset (#301), grundprincippet om rolle-proces-logik med rollekatalog og håndhævelse (#304), husregler v1 og kravspec'en for husregel-registeret godkendt (#300), og GUI-skelettet som fabrikskonsol med projektoverblik, godkendelsesindbakke og projektkonfiguration. Rollekataloget vises i GUI'en med systemkonfigurationen i trin 12.

Byggeklodserne findes og er testet hver for sig. Sammenkoblingen til ét forløb fra kravspec til færdigt system er ikke påbegyndt.

| Trin | I dag | Mangler |
|---|---|---|
| Kravspec | Datamodel, skema, validator og godkendelsesgate findes | Agent til kravafklaring; kravspec ud fra repo-analyse |
| Arkitektur | Fast hexagonal skabelon og regelbaseret syntese uden AI | Rådet (proposer, reviewer, verifier) er kun koblet i tests |
| Kontrakter | Regex over acceptkriterier giver OpenAPI | Modul-, data- og interfacekontrakter |
| Opgaver | Opgavesynteser laver afhængighedsgraf ud fra færdige specifikationer | Intet omsætter kontrakter til opgaver |
| Kodning | Egen patch-agent: én afgrænset patch pr. kørsel | Arbejder-adapter til færdige kodeagenter; egen patch-agent udgår |
| Kontrol | Lint/test/build-adaptere, arkitekturregel-evaluatorer, evalueringskoordinator | Ikke koblet på en kodningsløkke |
| Samling | Integrationscontroller er skrevet og testet | Kaldes ikke fra nogen kørende sti |
| Opdragskontrol | Sporbarhed krav → artefakt findes, men kun strukturelt; kravspec er versioneret | Kontrol mod kravspec; ændringsløb ned gennem alle led |
| Agentstatistik | Modeladaptere til flere udbydere; bot-profiler, tildelingspuljer, udvælgelse og evalueringsposter er modelleret | Ingen kørende løkke, der leverer målinger |
| GUI | Streamlit-app med sagsforløb, administration og bot-styring | Projektoverblik, godkendelsesindbakke, projektkonfiguration, regler og tolerancer |

Der er fire parallelle spor: pipelinen (`/pipeline/start`), GUI-kæden (9 sider, én patch på et eksisterende repo), Swarm og multi-bot-fabrikken.

## Beslutninger

1. Pipelinen er rygrad og eneste spor. Den fyldes med fabrikkens byggeklodser. Swarm-sporet udfases; GUI-kæden beholdes til vedligehold.
2. Værktøjet skal både bygge ny software og kunne forbinde til et eksisterende repo, analysere koden og danne en kravspec, der kan udvikles videre.
3. Målstakken styres af kravspec'en.
4. Governance v0 lempes for trin 2–9. Tenant-isolation og authority-grænser står urørt.
5. Efter kodning kommer kontrol i to niveauer, med faktakontrol forud.
6. Kode samles i kortlivede milestone-branches, ikke i én branch pr. leverance mod main (se beslutning 34).
7. Fejler niveau 2, går koden tilbage til koderen højst to gange. Derefter bygges pakken ny af en frisk agent (beslutning 35), og først hvis det også fejler, går den til mennesket.
8. Hver milestone godkendes af et menneske, før den går til main.
9. Udviklingsreglerne er defineret og godkendt som husregler v1 (`docs/plan/HUSREGLER_V1.md`).
10. Husreglerne er dynamiske: et versioneret regelsæt, der udvikles ud fra egen empiri og ekstern best practice.
11. Styringen følger PRINCE2 Agile: PRINCE2 for retning og beslutninger, sprints for leverancen.
12. Sprint er et selvstændigt niveau under milestone. En milestone kan have flere sprints.
13. Omfangsændringer besluttes af styregruppen på baggrund af en anbefaling fra systemet. Systemet udskyder aldrig selv krav.
14. En agent er projektleder. Den anbefaler; styregruppen beslutter.
15. GUI'en er en central del af produktet: den viser projektet og er stedet, hvor hele systemet og de enkelte projekter konfigureres. Den bygges løbende, ikke til sidst.
16. Koden kontrolleres mod opdraget (kravspec'en). Kontrollen kan give anledning til ændringer i opdraget.
17. Når opdraget ændres, skal alle led opdatere deres opgaver. Intet led må arbejde videre på en forældet version.
18. Sprints er korte, som udgangspunkt én dag. Der kan rettes til hver dag, og en dags arbejde kan kasseres.
19. AI-agenter er ikke en knap ressource. Tiden holdes ved at dele en milestone i flere dele og sætte flere agenter på. Tid og omfang ligger fast; forbruget giver sig.
20. En plan for skaleringen skal godkendes af styregruppen.
21. Det daglige eftersyn kan køre på to måder, valgt pr. projekt: godkendelse af hver dagssprint, eller daglige undtagelser med godkendelse ved milestonen.
22. Den menneskelige integration er den overordnede kontrol i hele forløbet.
23. Et økonomilag venter til v2. I v1 er der intet forbrugsloft.
24. Referenceprojektet er husregel-registeret, bygget af fabrikken som en ny, selvstændig del af DOR.
25. DOR skal på sigt udvikle sig selv, i tre trin og med en beskyttet kerne.
26. Alle agentjob får tilknyttet statistik, så systemet kan lære af prompt-definitioner og af agenternes forståelse af dem og vælge den rette agent til hver opgavetype.
27. DOR bygger ikke sin egen kodeagent. Færdige kodeagenter kører som arbejdere under DOR's styring.
28. De to første arbejdere er Claude Code og Codex.
29. Spec Kit bruges som format og promptsæt for arbejderne. DOR's pipeline er rygraden.
30. Hele planen er opdraget. Der er ingen stopregel og intet mellemprodukt; opgaven er at få det hele udviklet.
31. Streg i sandet: hvordan repoet er blevet til, bruges der ikke tid på. Det, der ligger der, bedømmes kun på, om det fungerer sammen med resten.
32. Under sammenbygningen skal vi være skarpe på, hvad der fungerer sammen, og hurtigt kassere og skrive nyt, når det er bedst.
33. Hele kæden køres igennem første gang, så snart trin 3–8 er koblet sammen: husregel-registeret med to arbejdere parallelt på samme fundament. Kørslen er en måling af, om agenternes kode passer sammen, ikke en leverance og ikke en stopregel.
34. `main` er det fælles fundament. Milestone-branchen lever kun, mens milestonen kører, og genbaseres på den nyeste `main` ved hver sprintstart, så den højst er én dag bagud. Hver arbejdspakke bindes til en commit, en kravspec-revision og en kontraktversion; bliver én af dem forældet, genbaseres og genkontrolleres pakken i stedet for at arbejde videre. Godkendelsen før `main` (beslutning 8) og kassering af en dagssprint (beslutning 18) bevares.

35. Tilbagerulning frem for fejlretning. Når genereret kode fejler, er udgangspunktet at kassere og bygge på ny med en frisk agent, ikke at fejlrette. Det forudsætter, at årsagen findes i inputtet (kravspec, kontrakt, prompt) og rettes først. Valget følger en fast sortering (afsnittet "Tilbagerulning frem for fejlretning"). Den beskyttede kerne fejlrettes under styregruppens godkendelse.
36. Kontrol er rolleadskillelse. Hver arbejdspakke har tre roller: koder, kodeauditør og kontekstkontrollant. Kodeauditøren og kontekstkontrollanten kommer altid fra en anden producent end koderen. De arbejder ud fra en fast kontekstpakke og ser aldrig koderens samtale eller forklaring. Er der ingen anden producent til rådighed, venter kontrollen; den falder aldrig tilbage til koderens producent.
37. Hvert agentjob gemmer en agentlog: prompt, kontekstpakke, hele agentens forløb med værktøjskald, diff og testoutput. Loggen er uforanderlig, har et fingeraftryk og knyttes til jobposten. DOR's egen log er sandheden, uanset hvad udbyderne gemmer.
38. Backup i fire lag: kendte gode punkter som tags på `main`, beskyttelse af `main` og tags, en kopi uden for GitHub og backup af DOR's database taget sammen med hvert kendt godt punkt.

39. Grundprincip: DOR er rolle-proces-logik (afsnittet "Grundprincip"). En rolle er en prompt plus en kontekstpakke i et frisk job; enhver agent kan have enhver rolle. På samme arbejdspakke kommer en kontrolrolle fra en anden producent og kører i en ny session. Rollekataloget er versioneret data, og reglen håndhæves i koden; den står ikke kun i dokumentationen.
40. Styringslaget følger PRINCE2 Agile. Mennesket er styregruppen (projektejer) og den eneste rolle, der beslutter og godkender. Produktejer, systemarkitekt, projektleder, kvalitetsansvarlig og release-ansvarlig er agentroller i styringslaget: hver ejer et artefakt, styrer og indstiller, men godkender aldrig. Produktejeren ejer kravspec'en og står for opdragskontrollen af helheden; systemarkitekten ejer arkitekturen gennem hele forløbet. Kataloget håndhæver det: kun et menneske kan have myndigheden "beslutter", og hver styringsrolle kontrolleres af styregruppen. Hvor planen tidligere sagde "projektlederen" om den, der godkender, er det nu styregruppen; den tidligere projektassistent er projektleder-agenten.
41. Opgaveproducenten er en agent, der foreslår opdelingen af kontrakterne i arbejdspakker med beskrivelse, vægt og rækkefølge. Opgavekompileren bliver dens faktakontrol (adskilte skrive-områder, dækning af kriterier, ingen cykler), og systemarkitekten og projektlederen kontrollerer den.
42. Prompts er versionerede data, ikke kode. Hver agentrolle får sin prompt fra en versioneret fil, som promptproducenten skriver, en promptreviewer fra en anden producent kontrollerer, og styregruppen godkender. Promptversionen står på hver jobpost. Det sker før første gennemløb, så målingerne fra første kørsel hører til en kendt promptversion.
43. Flere produktions- og kontrolroller: testdesigneren skriver accepttests ud fra kriterierne før kodningen og fra en anden producent end koderen; sikkerhedsansvarlig kontrollerer pakker og milestones; rapport og statistik er en systemrolle, der regner tallene uden sprogmodel, så projektlederens rapporter bygger på efterprøvede tal.

## Arkitektur: styringslag over færdige agenter

### Fordeling

| DOR beholder | Færdige kodeagenter leverer |
|---|---|
| Kravspec med faste krav-id'er og versioner | Udkast til arkitektur og kontrakter (via rådet) |
| Gates og menneskelig godkendelse | Kode og tests pr. arbejdspakke |
| Opgavegraf, skaleringsplan og fordeling | Reviews i niveau 1 og niveau 2 |
| Worktrees, opgave-branches og milestone-branches | |
| Faktakontrol, niveau 1, niveau 2 og opdragskontrol | |
| Ændringsløb, statistik og GUI | |

### Arbejder-adapter

Én lille adapter pr. kodeagent. Den får et worktree, en arbejdspakke, kontrakten, reglerne og en promptversion. Den starter agenten uden skærm (Claude Code med `claude -p`, Codex med `codex exec`), og samler ændringer, log, varighed og forbrug op på jobposten.

- Agenten kører afskærmet, uden hemmeligheder og uden ret til at skubbe kode. DOR fletter og skubber.
- DOR stoler ikke på agentens rapport. Kontrollerne ser på det, der faktisk ligger i worktree'et.
- Alle agenter får samme opgaveformat, så målingerne kan sammenlignes.

### Spec Kit

Spec Kit er en MIT-licenseret pakke med skabeloner, tjeklister, prompts og scripts, som køres inde i en kodeagent. Det er ikke et system, der selv kører noget.

| Spec Kit | I DOR |
|---|---|
| Constitution | Husregler og projektregler |
| Specify og clarify | Kravspec og kravafklaring |
| Plan | Arkitektur og kontrakter |
| Tasks | Arbejdspakker |
| Analyze | En del af faktakontrollen |
| Implement | Kodeagentens arbejde |

DOR's strukturerede kravspec er sandheden. Den omsættes til Spec Kits Markdown-filer, når en agent skal arbejde. Spec Kit kan ikke bære rollen som rygrad, fordi det mangler vedvarende tilstand, håndhævede gates, uafhængig kontrol, parallelle agenter, branches og ændringsløb. Vurderingen bygger på dokumentationen; Spec Kit er ikke afprøvet her.

### Forbehold

- **Ikke alle udbydere har en kodeagent.** DeepSeek og Rool leverer modeller og skal køre gennem et åbent værktøj som opencode. Det er ikke undersøgt.
- **Udbydernes forbrugsgrænser** sætter et loft for, hvor meget der kan køre døgnet rundt. Flere udbydere hæver loftet.
- **Sandkassen** i repoet (`phase6`) er ikke afprøvet.

## Sammenbygning

Opgaven er at koble det, der findes, sammen til ét forløb og bygge det, der mangler. Der leveres intet undervejs. Kæden køres første gang igennem efter trin 8 (se "Første gennemløb"); den samlede test af hele systemet ligger til sidst.

### Behold, tilpas eller kassér

Hver eksisterende del afprøves i kæden sammen med det, der allerede er koblet. Der er tre udfald:

| Udfald | Når |
|---|---|
| Behold | Delen virker sammen med resten, som den er |
| Tilpas | Delen virker efter en afgrænset ændring |
| Kassér og skriv nyt | Tilpasning er dyrere eller mere usikker end at skrive nyt |

Beslutningen træffes hurtigt og på, hvad der virker sammen. Arbejde, der allerede er lagt i en del, tæller ikke.

### Forventet udfald for de kendte dele

| Del | Forventning |
|---|---|
| Kravspec-model, validator, godkendelsesgate | Behold |
| Pipelinens tilstandsmaskine med gates og rework | Behold, tilpas til milestones og sprints |
| Opgavesynteser, scheduler, worktree-styring | Behold. Udfald i trin 5: opgavekompileren (`execution/task_compiler.py`) laver kontrakterne om til en fundamentpakke (interfaces, typer og kontrakttests under `contracts/`) og én pakke pr. modul, der bygger mod kontrakterne parallelt; `FactoryTaskSynthesizer` validerer pakkerne og serialiserer overlappende skrive-områder. Dagssprints, kritisk vej og skaleringsplan afledes deterministisk og godkendes sammen med kontrakterne ved kontrakt-gaten |
| Integrationscontroller | Udfald i trin 8: milestone-branchen styres af `execution/milestone.py` og ikke af den eksisterende integrationscontroller, som binder til én kandidat pr. leverance. Ved sprintstart genbaseres branchen på den nyeste `main` i et smidbart worktree, og hele suiten køres; konflikt eller rød suite er en undtagelse, og branchen flyttes ikke. Kontrakttests for moduler, der ikke er flettet endnu, holdes uden for suiten, fordi de fejler med vilje; fundamentet lægger derfor hvert moduls kontrakttests i sin egen fil. Startmærket er et tag, og en kasseret sprint sættes tilbage til det. Hver pakke bindes til start-commit, kravspec-version og kontraktversion; en ændring af inputtet registreres og træder i kraft ved næste sprintstart, og pakker bundet til den gamle version listes til ændringsløbet. Pakkerne i en sprint kører parallelt gennem pakkelinjen fra trin 7; fletningen sker én ad gangen med compare-and-swap på branchen. Er toppen flyttet, genbaseres pakken og kontrolleres igen; passer den ikke eller fejler kontrollen, bygges den én gang ny fra den nye top. Ved milestonens afslutning: genbasering, fuld suite og niveau 2 på helheden fra en kontekstkontrollant, der er uafhængig af alle kodere; derefter styregruppens godkendelse. Efter fletningen til `main` sættes `known-good/<milestone>`, der tages en verificeret `git bundle` og en kopi af milestone-tilstanden med release-bevis, og branchen slettes. Tilbagerulning er en ny `rollback/`-branch fra tagget. Ikke med endnu: DOR skubber ikke selv og åbner ikke PR'en, backup af DOR's database er en krog uden implementering, og pipelinen (`/pipeline`) kalder ikke milestonen; det kobles på ved første gennemløb (trin 8a) |
| Rådet og bot-konfiguration | Udfald i trin 3: rådet i `phase4/council` vurderer, om en handling er klar, og producerer ikke et arkitekturdokument, så det bruges ikke til arkitekturen. Arkitekturen kører som en smal dialog mellem arkitekt og arkitekturreviewer (`execution/architecture_council.py`) på `GovernedLLMRuntime`, modeladapterne og bot-kataloget, som beholdes. Skabelon-arkitekturen kører ved siden af, indtil trin 4 kasserer den |
| Lint/test/build-adaptere, arkitekturregel-evaluatorer | Behold |
| Evalueringskoordinator og evalueringsposter | Tilpas til jobposter og statistik |
| Opgaveproducenten (trin 8b) | Udfald: opgaveproducenten (`execution/task_council.py`) foreslår opdelingen af modulerne i arbejdspakker med id, beskrivelse, vægt, skrive-område, kriterier og afhængigheder; et modul deles kun, når det er for stort til én kørsel. Opgavekompileren er dens faktakontrol (`check_split`): hvert modul dækket, hvert af modulets kriterier i præcis én af dets pakker, skrive-områder inden for modulets egne stier og uden for `contracts/`, kendte afhængigheder uden cykler, vægt 1–100. Kontraktfundamentet er altid pakke 0 og kan ikke deles væk. Systemarkitekten fra en anden producent udfordrer opdelingen mod arkitekturen. Kun en enig opdeling bliver til en arbejdsplan ved kontrakt-gaten; uden enighed er der ingen plan, og styregruppen ser uenigheden. Profiler: `DOR_TASK_PRODUCER_BOT_PROFILE` og `DOR_SYSTEM_ARCHITECT_BOT_PROFILE`; uden dem bruger kompileren sin standardopdeling (ét modul, én pakke), og planen siger hvilken (`task_split`) |
| Testdesigner og sikkerhed (trin 8b) | Udfald (beslutning 43): kontraktfundamentet bygges nu af testdesigneren og ikke af koderen; prompten `coder/build_contract_foundation` er udfaset, og `test_designer/build_contract_foundation` skriver grænseflader, typer og accepttests ud fra kriterier og kontrakter alene. En modulpakke består kun faktakontrollen, hvis hvert af dens kriterier har en accepttest fra fundamentet under `contracts/`; koderens egne tests er ikke nok. Koderen må ikke komme fra testdesignerens producent: det tjekkes, før der skrives kode, og igen i kontrollen; milestonen husker, hvem der byggede fundamentet. Sikkerhedskontrollen er et trin mellem niveau 1 og niveau 2: faktakontrollen kører en maskinel hemmelighedsscanning (private nøgler, AWS-, GitHub- og API-nøgler, tildelte hemmeligheder) og noterer ændrede afhængighedsfiler; en hemmelighed stopper leverancen, før nogen model ser den. Derefter vurderer sikkerhedsansvarlig fra en anden producent diff, afhængigheder og scanning. Kontrollen kræver nu tre profiler (`DOR_CODE_AUDITOR_BOT_PROFILE`, `DOR_SECURITY_REVIEWER_BOT_PROFILE`, `DOR_CONTEXT_CONTROLLER_BOT_PROFILE`); uden sikkerhedsansvarlig består intet. Kataloget lader nu også kodeauditør og sikkerhedsansvarlig kontrollere testdesigneren, og opgavetypen `build_contract_foundation` hører til testdesigneren |
| Egen patch-agent (`phase4/implementation_agent`) | Kassér. Udfald i trin 6: arbejder-adapteren (`execution/worker_adapter.py`) kører Claude Code (`claude -p --output-format stream-json`) og Codex (`codex exec --json`) uden skærm i et worktree fra pakkens base-commit. Miljøet har kun agentens egen nøgle, et tomt `HOME` og git-opsætning, der omskriver alle push-adresser til en ubrugelig adresse. DOR committer, attesterer skrive-området og skriver en uforanderlig, indholdsadresseret agentlog (`services/agent_log_store.py`); jobposten bærer rolle, session, forbrug og logreference. Et fejlet forsøg rulles tilbage (branchen slettes, diffen ligger i loggen), og et nyt forsøg får sit eget nummer. Opgaveformatet er DOR's eget (`dor-task-v1`: prompt plus kontekstpakke med kontrakter, krav, acceptkriterier og aktive husregler) i stedet for Spec Kits Markdown-filer, fordi Spec Kit ikke er afprøvet; formatet er versioneret, så Spec Kit kan prøves som næste version i sammenligningen. Den egne patch-agent fjernes sammen med regex- og skabelonvejen, når rådene gøres obligatoriske |
| Kontrollen af arbejdspakker | Udfald i trin 7 (`execution/package_control.py`): faktakontrollen er maskinel. Den slår krav-id'er op (opdigtede referencer afvises), kræver en test, der nævner hvert acceptkriterium (at nævne det i koden tæller ikke), tjekker skrive-området igen og kører selv testene i et rent worktree uden nøgler; fundamentpakkens kontrakttests skal kun kunne samles op, fordi de fejler, til modulerne findes. Niveau 1 (kodeauditør) ser diff, husregler og testresultater; niveau 2 (kontekstkontrollant) ser diff, krav, acceptkriterier og modulkontrakt og kører kun efter bestået niveau 1. Ingen af dem ser koderens samtale. Fund skal pege på en ændret fil og en eksisterende linje eller på pakkens krav og kriterier, ellers afvises de; en "revise" uden et efterprøvet fund registreres, men følges ikke. Er der ingen producent, der er uafhængig af koderen, venter kontrollen, og branchen bevares. Sorteringen: lokal fejl giver rework på den leverede kode, højst to runder; derefter kasseres pakken og bygges ny af en frisk agent uden de gamle fund; fejler den også, går pakken til mennesket. Et niveau 2-fund med årsag i inputtet stopper pakken til ændringsløbet. Et nedbrud eller brud på skrive-området hos arbejderen behandles som ikke forstået og går direkte til ny bygning. Målingerne fra "Hvad der måles" skrives på resultatet. Begrænsninger: testkørslen findes kun til Python indtil videre, og den kører leveret kode uden sandkasse, så den skal køre på arbejder-maskinen. Lint/test-adapterne og evalueringskoordinatoren er ikke koblet på endnu |
| Prompts (trin 8b, første del) | Udfald: prompts ligger som versionerede filer i `config/prompts/<rolle>/<formål>.v<N>.md` med status foreslået, på prøve, aktiv eller udfaset. `domain/prompt_registry.py` afviser registeret, hvis rollen ikke er en agentrolle i kataloget, hvis en aktiv eller prøveversion mangler styregruppens godkendelse, eller hvis der ikke er præcis én aktiv version pr. rolle og formål. Styregruppen godkender ved at flette ændringen, der gør en version aktiv. Arkitekturrådet, kontraktrådet og pakkekontrollen henter deres prompts derfra, og jobposten bærer `rolle/formål@vN+fingeraftryk`. Promptproducent og promptreviewer (`execution/prompt_council.py`) skriver nye versioner som foreslåede; faktakontrollen afviser en prompt, der ikke nævner sin rolle, ikke siger, at projektdata er upålidelige, lader rollen godkende, springe en kontrol over eller stole på en anden agents rapport, eller som taber en sikkerhedsregel fra den aktive version. Faktakontrollen fandt straks, at niveau 1- og niveau 2-prompterne manglede sætningen om upålidelige data; den er tilføjet. Koderens prompts (modul, kontraktfundament og rework-runde) og prompten til niveau 2 på hele milestonen ligger også i registeret; koderens jobpost bærer de promptversioner, opgaven blev bygget af, og faktakontrollen sikrer, at pladsholdere som `{allowed_paths}` bevares. Tilbage i koden er kun den gamle rådgivende modelvej i skabelonsporet (`_pipeline_llm_proposal`), der fjernes sammen med skabelonsporet, og den ubrugte `execution/ai_task_executor.py`. Den eksisterende `services/adaptive_prompt_optimizer.py` aktiverer og ruller prompts tilbage af sig selv og strider mod beslutning 42; den bruges ikke, og dens A/B-evaluering vurderes i trin 11 |
| Skabelon-arkitektur (`generation/scaffold_engine`) | Kassér fra pipelinen; modulet beholdes, fordi onboarding-sporet (GUI-kæden) bruger det |
| Regex-kontrakter (`generation/contract_generator`) | Kassér. Udfald i trin 4: modulkontrakter laves af kontraktforfatter og kontekstkontrollant i dialog (`execution/contract_council.py`); OpenAPI og sporbarhed afledes af kontrakterne. Regex-vejen kører kun, når rådene ikke er konfigureret, og fjernes, når de gøres obligatoriske |
| Swarm-sporet | Kassér |
| GUI-kæden med ni sider | Behold til vedligehold; nyt projektoverblik skrives |

Forventningerne er sat ud fra en gennemlæsning af koden. Det endelige udfald afgøres, når delen har kørt i kæden.

### Målinger undervejs

- **Referenceprojektet:** Husregel-registeret er den faste opgave, som kæden køres på, efterhånden som den bliver længere.
- **Første gennemløb:** Efter trin 8 køres hele kæden med to arbejdere parallelt. Det viser tidligt, om koden fra flere agenter passer sammen.
- **Sammenligning:** Samme opgave løses med Spec Kit og en kodeagent direkte. Det er en måling af, hvad DOR's styring er værd, ikke en stopregel.
- **Samlet test:** Hele systemet testes samlet, når alle trin er bygget. Derefter kommer første kundeopgave.

## Første gennemløb

Formålet er at måle så tidligt som muligt det, hele planen hviler på: at flere agenter, der arbejder ud fra samme fundament, leverer kode, som passer sammen. Kørslen leverer ikke noget til en kunde og er ikke et mellemprodukt.

### Hvornår og hvordan

- **Tidspunkt:** Så snart trin 3–8 kan køres i sammenhæng, før trin 9.
- **Opgave:** Husregel-registeret ud fra dets godkendte kravspec, som én milestone.
- **Arbejdere:** Claude Code og Codex arbejder parallelt på arbejdspakker, der bygger på de samme kontrakter.
- **Manuelle trin** er tilladt, hvor et led endnu ikke er automatiseret. Hvert manuelt indgreb registreres med årsag.

### Hvad kørslen skal vise

1. Kravspec, arkitektur og kontrakter er godkendt, og kontrakterne ligger på milestone-branchen, før kodningen starter.
2. Opgavekompileren har delt arbejdet i pakker med adskilte filer.
3. De to arbejdere leverer parallelt, og hver pakke passerer faktakontrol, niveau 1 og niveau 2.
4. Pakkerne flettes til milestone-branchen uden konflikter.
5. Hele testsuiten består på den samlede revision og ikke kun pr. pakke.
6. Sporbarheden går fra krav-id til test.

### Hvad der måles

| Måling | Hvorfor |
|---|---|
| Fejl, der først viser sig efter fletning | Viser, om modulerne passer sammen |
| Kontraktbrud fundet i kontrollen | Viser, om fundamentet blev fulgt |
| Ændringsforslag til kontrakterne fra arbejderne | Viser, om fundamentet var godt nok |
| Rework-runder pr. pakke | Viser kontrollernes og promptenes kvalitet |
| Manuelle indgreb | Viser, hvad der mangler i kæden |
| Jobposter | Første data til agentstatistikken |

### Udfald

Holder fundamentet, fortsætter arbejdet med trin 9. Holder det ikke, peger målingerne på, hvilket trin der skal rettes, og det rettes før videre arbejde. Ifølge beslutning 30 er det en rettelse og ikke et stop. Gennemløbet gentages, når kæden bliver længere.

## Referenceprojekt og selvudvikling

### Referenceprojekt: husregel-registeret

Referenceprojektet er den faste prøveopgave, som fabrikken bygger fra kravspec til færdigt system.

| Krav til en prøveopgave | Husregel-registeret |
|---|---|
| Flere moduler | Regellager med versioner, livscyklus, måling pr. regel, API, skærmbillede |
| Parallelt arbejde | Måling og skærmbillede kan bygges uafhængigt, når lageret har en kontrakt |
| Lille nok | Få dagssprints |
| Kendt facit | Designet er fastlagt i `docs/plan/HUSREGLER_V1.md`; kravspec i `docs/plan/kravspec/husregel-register.yaml` |

Registeret bygges som selvstændig komponent. Styregruppen fletter det selv ind i DOR.

### Tre trin til selvudvikling

1. **Milepæl 1:** Fabrikken bygger husregel-registeret som ny komponent.
2. **Milepæl 2:** DOR tilsluttes som det første eksisterende repo. Repo-analysen danner et kravspec-udkast, som holdes op mod denne plan.
3. **Derefter:** DOR udvikler sig selv.

### Regler for selvudvikling

- En stabil, frigivet version af fabrikken bygger den næste. Den kørende fabrik ændrer aldrig sig selv.
- Kontrollaget er en beskyttet kerne: faktakontrol, niveau 1 og 2, opdragskontrol, godkendelser, regelmotoren og agentudvælgelsen. Ændringer dér kræver styregruppens godkendelse hver gang, også når projektet kører på "kun undtagelser".

## Agentstatistik og valg af agent

### Hvad der måles

Hvert agentjob får en jobpost. Kontrollerne leverer målingerne, så statistikken kræver ingen ekstra vurdering:

| Måling | Kilde |
|---|---|
| Opdigtede referencer og uefterprøvede påstande | Faktakontrol |
| Ændringer uden for opgaven | Faktakontrol |
| Bestået teknisk kontrol i første forsøg | Niveau 1 |
| Bestået mod krav og arkitektur i første forsøg | Niveau 2 |
| Antal rework-runder | Rework-sløjfen |
| Afvigelser fundet senere og sporet tilbage | Opdragskontrol |
| Arbejde, der blev kasseret | Dagseftersyn |
| Antal mærkede antagelser | Leverancen |
| Varighed og forbrug | Jobposten |

### Hvad der registreres pr. job

Agent (værktøj og bot-profil), udbyder, model og modelversion, rolle, opgavetype, stak, promptversion, kravspec-version og regelversion. Uden dem kan to målinger ikke sammenlignes.

### Prompts som versionerede artefakter

Prompts følger samme livscyklus som husreglerne: foreslået, på prøve, aktiv, udfaset. Statistikken viser, om en ny promptversion giver færre misforståelser, målt på antagelser, faktakontrol-fejl og rework. Agenter foreslår promptændringer; styregruppen godkender.

### Kappestrid som forsøg

Fordi agenter ikke er en knap ressource, kan samme arbejdspakke gives til flere agenter samtidig. Kontrollerne udpeger højst én vinder, og alle forsøg giver målinger. Det er den hurtigste vej til sammenlignelige tal, fordi opgaven er den samme.

### Valg af agent

1. Styregruppen godkender, hvilke agenter der må bruges i hver rolle (puljen).
2. Systemet vælger inden for puljen ud fra statistikken for opgavetypen.
3. Valget og dets begrundelse gemmes.
4. Systemet kan anbefale ændringer af puljen, men ændrer den ikke selv.

### Forbehold

- **Mængde:** Få job pr. agent og opgavetype giver støj. Statistikken påvirker først valget efter et mindste antal job.
- **Sammenlign ens med ens:** Samme opgavetype, promptversion og sværhedsgrad. Udbydere opdaterer modeller uden varsel, så modelversionen skal med.
- **Uafhængig dommer:** Kodeauditøren og kontekstkontrollanten kommer fra en anden producent end koderen (beslutning 36), ellers bliver tallene skæve.
- **Opgavetyper skal defineres:** De fastlægges i opgavekompileren og er selv versionerede.

## Rytme: dagssprints

| Tidspunkt | Hvad sker der |
|---|---|
| Sprintstart | Milestone-branchen genbaseres på den nyeste `main`, og hele suiten køres; godkendte ændringer af opdraget træder i kraft; alle led kvitterer; dagens arbejdspakker frigives efter skaleringsplanen |
| I løbet af sprinten | Agenter leverer arbejdspakker; faktakontrol, niveau 1 og niveau 2 pr. pakke; fletning til milestone-branchen |
| Sprintslut | Opdragskontrol på milestone-branchen; projektlederens dagsrapport med afvigelser og indstillinger |
| Eftersyn | Styregruppen godkender, retter eller kasserer; retrospektiv giver eventuelle regelforslag |

En dagssprint ender i én af tre tilstande:

| Udfald | Følge |
|---|---|
| Godkendt | Arbejdet står; næste sprint bygger videre |
| Rettet | Afvigelser bliver rework-pakker eller ændringsforslag i næste sprint |
| Kasseret | Milestone-branchen sættes tilbage til sprintens startpunkt; pakkerne planlægges om |

Hver sprint får et startmærke på milestone-branchen, så kassering er en enkel og sikker handling. En kasseret dag er billig, så længe intet andet bygger på den; dagssprints begrænser netop det til højst én dag.

### To måder at føre eftersyn

- **Godkend hver dag:** Næste sprint starter først, når den forrige er godkendt, rettet eller kasseret.
- **Kun undtagelser:** Sprints fortsætter uden godkendelse, så længe kontrollerne er bestået. Styregruppen ser dagsrapporten og får kun undtagelser til beslutning. Godkendelsen sker ved milestonen.

Måden vælges pr. projekt og kan skiftes ved en sprintgrænse.

## Skalering

Tiden holdes ved at skalere ud, ikke ved at skære i omfanget.

### Skaleringsplan

Projektlederen udarbejder en skaleringsplan for hver milestone, og styregruppen godkender den, før arbejdet starter:

- hvordan milestonen er delt i arbejdspakker og dagssprints;
- hvor mange agenter der arbejder parallelt i hver rolle;
- den kritiske vej: den længste kæde af pakker, der skal ske efter hinanden;
- forventet varighed og forventet forbrug (til orientering i v1).

En ændring af skaleringsplanen undervejs, for eksempel flere agenter for at holde tiden, er en ny version, som også skal godkendes.

### Grænser

- **Afhængigheder:** Arbejde kan kun deles, hvis delene er uafhængige. Den kritiske vej sætter en nedre grænse for tiden uanset antal agenter. Kan en frist ikke holdes selv med ubegrænsede agenter, meldes det som undtagelse ved planlægningen.
- **Menneskelig tid:** Flere parallelle dele giver mere at tage stilling til. Eftersynet styres derfor efter undtagelser.
- **Forbrugsgrænser:** Udbydernes grænser sætter et loft for parallelt arbejde pr. udbyder.

Hvor meget der kan køre parallelt, afgøres af kontrakterne. Arkitekturtrinnet får derfor som kvalitetskrav, at modulerne kan bygges uafhængigt af hinanden.

### Økonomi

V1 har intet forbrugsloft og ingen økonomistyring. Forbruget registreres pr. job, arbejdspakke, sprint og milestone, så et økonomilag i v2 har tal at bygge på.

## Opdragskontrol og ændringsløb

### Opdragskontrol

Kontrollen kører ved hver sprintslut på milestone-branchen, efter hver fletning af en milestone til main, ved projektets afslutning og på anmodning. Den går begge veje:

- **Fra krav til kode:** Hvert krav og acceptkriterium får en status: opfyldt, delvist, ikke opfyldt eller ikke efterprøvet. Status bygger på tests, som systemet selv har kørt, og på sporbarheden.
- **Fra kode til krav:** Funktionalitet uden et krav bag findes og markeres.
- **Fund om selve opdraget:** Krav, der viste sig tvetydige, modstridende, uprøvelige eller manglende.

En afvigelse siger ikke, hvilken side der er forkert. Hver afvigelse ender derfor ét af to steder:

| Udfald | Betydning | Følge |
|---|---|---|
| Rework | Koden er forkert, opdraget står ved magt | Ny arbejdspakke i næste sprint |
| Ændringsforslag | Opdraget er forkert, ufuldstændigt eller overhalet | Forslag til ny kravspec-version |

Projektlederen indstiller for hver afvigelse. Styregruppen beslutter.

For et eksisterende repo uden kravspec er det samme kontrol: alt i koden mangler et krav, og resultatet er et kravspec-udkast (trin 2).

### Ændringsløb

En godkendt ændring giver en ny, uforanderlig kravspec-version. Den gamle markeres som erstattet. Ændringen træder i kraft ved næste sprintstart.

1. **Forskel:** Hvilke krav-id'er er tilføjet, ændret eller fjernet.
2. **Konsekvensanalyse:** Gennem sporbarhedskæden krav → arkitekturbeslutning → kontrakt → arbejdspakke → kode → test → kontrolpost findes alt, der er berørt.
3. **Konsekvensrapport:** Projektlederen beskriver omfang, forbrug og påvirkning af skaleringsplanen, med en anbefaling.
4. **Beslutning:** Styregruppen godkender ændringen og afgør, om berørt arbejde fra den igangværende sprint rettes eller kasseres.
5. **Udrulning led for led:**

| Led | Opdatering |
|---|---|
| Arkitektur | Rådet vurderer de berørte beslutninger; resultatet er en ny version eller en begrundet "ingen ændring" |
| Kontrakter | Berørte kontrakter får ny version |
| Opgaver | Nye arbejdspakker oprettes, berørte ændres, overflødige annulleres; skaleringsplanen opdateres |
| Kodning | Åbne arbejdspakker på gammel version stoppes; leveret kode, der er berørt, mærkes til genkontrol |
| Test og kontrol | Berørte tests og kontrolposter mærkes forældede og køres igen |
| Husregler og projektregler | Projektregler vurderes, hvis stak eller arkitektur er berørt |

6. **Kvittering:** Hvert led kvitterer for den nye version. Først når alle har kvitteret, starter næste sprint på de berørte dele.

Hvert artefakt bærer den kravspec-version, det er lavet ud fra. I dag stopper pipelinen, hvis kravene ændres efter arkitekturen; det skal blive et styret ændringsløb.

### Forudsætning

Sporbarheden skal være gennemgående fra trin 1: samme krav-id'er i alle led, og kravspec-version på hvert artefakt. Den nuværende sporbarhed er strukturel og viser ikke, om et krav er opfyldt.

## GUI

### Hvad der findes

En Streamlit-app på cirka 14.600 linjer, som er en tynd klient over API'et:

- **Sagsforløb** bygget om kæden med én patch på et eksisterende repo (9 sider).
- **Administration:** organisationer, brugere, projekter (kun læsning), Redmine, Implementation AI, systemstatus.
- **Bot-styring:** forbindelser, modeller, bot-profiler, roller, skabeloner og tildeling.

Roadmappen i repoet siger "GUI not started"; det er forældet.

### Tre områder

| Område | Indhold | Status |
|---|---|---|
| Projektoverblik | Hierarkiet projekt → milestone → sprint → arbejdspakke; status pr. trin i forløbet; kontrolresultater; opfyldelse af opdraget krav for krav; branch-tilstand; forbrug; dagsrapport; godkendelsesindbakke med gates, skaleringsplaner, undtagelsesrapporter og ændringsforslag | Mangler |
| Systemkonfiguration | Kodeagenter, udbydere, modeller og bot-profiler; roller og rådsskabeloner; husregler, prompts og deres versioner; agentstatistik pr. opgavetype; standardtolerancer; brugere og organisationer; integrationer | Delvist: bots, roller, brugere og integrationer findes; regler, prompts, statistik og tolerancer mangler |
| Projektkonfiguration | Repo-tilknytning; kravspec og dens versioner; stak og projektregler; agentpuljer pr. rolle; tolerancer; sprintlængde og eftersynsmåde; milestone-, sprint- og skaleringsplan | Mangler; projekter kan i dag kun læses |

### Principper

- **Arv:** Systemkonfigurationen er standard. Et projekt arver den og kan tilsidesætte udvalgte dele.
- **Versioneret:** En konfigurationsændring giver en ny version. En kørende sprint fortsætter på den version, den startede med.
- **GUI'en beslutter ikke:** Den viser tilstand og sender kommandoer. Regler, godkendelser og kontrol ligger i backenden.
- **Indbakken først:** Styregruppen er flaskehalsen, så alt, der venter på en beslutning, samles ét sted.

### Rækkefølge

Hvert trin i planen leverer sit eget skærmbillede. Et GUI-skelet med projektoverblik, godkendelsesindbakke og projektkonfiguration bygges tidligt, fordi gates og godkendelser kræver det.

## Styring: PRINCE2 Agile

### Niveauer

projekt → fase (milestone) → sprint → arbejdspakke

| Niveau | Afsluttes med | Branch |
|---|---|---|
| Projekt | Opdragskontrol viser kravspec opfyldt; business case genbekræftet | main |
| Fase (milestone) | Fuld test, niveau 2 på helheden, styregruppens godkendelse, fletning til main, opdragskontrol | Milestone-branch |
| Sprint (én dag) | Opdragskontrol, dagsrapport, eftersyn: godkendt, rettet eller kasseret; retrospektiv | Ingen egen; startmærke på milestone-branchen |
| Arbejdspakke | Faktakontrol, niveau 1 og niveau 2 bestået; flettet til milestone-branchen | Kort opgave-branch |

Regelsæt og prompts er frosne inden for en sprint.

### Roller

| Rolle | Hvem | Ansvar |
|---|---|---|
| Styregruppe / projektejer | Menneske | Godkender kravspec og dens ændringer, arkitektur, kontrakter, skaleringsplaner, agentpuljer, prompts, regler, rollekataloget og hver milestone; beslutter undtagelser og omfang |
| Produktejer | Agent | Ejer kravspec og opdrag; opdragskontrol af helheden begge veje; vurderer ændringsforslag og indstiller |
| Systemarkitekt | Agent | Ejer arkitekturen gennem hele forløbet; kontrollerer kontrakter, opgaveopdeling og milestones mod den; fører beslutningsloggen |
| Projektleder | Agent | Sprintplan, skaleringsplan og prioritering; frigiver pakker; dagsrapporter, undtagelsesrapporter og konsekvensrapporter med muligheder og anbefaling |
| Kvalitetsansvarlig | Agent | Ejer husreglerne og kvalitetsregisteret; foreslår regelændringer ud fra kontrolresultater og statistik |
| Release-ansvarlig | Agent | Release-tjekliste, release-noter og release-bevis for en milestone |
| Orkestrator | System (DOR) | Fordeler arbejdspakker efter den godkendte skaleringsplan; vælger agent inden for puljen; håndhæver tolerancer, rækkefølge og kvittering for ny kravspec-version; udfører git-operationerne |
| Koder | Færdig kodeagent via arbejder-adapter | Leverer én arbejdspakke ad gangen |
| Kodeauditør, sikkerhedsansvarlig, kontekstkontrollant | Agenter fra en anden producent end koderen | Niveau 1 (husregler og projektregler), sikkerhed, niveau 2 (kravspec, arkitektur og kontrakt) |

Hele rollekataloget står i afsnittet "Roller og kontekst".

Ingen styringsagent kan godkende, ændre omfang, ændre opdraget, ændre skaleringen, ændre puljer eller ændre regler.

### Tolerancer og undtagelser

Tid og omfang ligger fast. Tolerancer sættes for antal rework-runder (højst to), for afvigelse fra skaleringsplanen og for tid på den kritiske vej. Forbrug registreres, men har intet loft i v1.

Ved overskridelse stopper arbejdet på det berørte niveau, og projektlederen skriver en undtagelsesrapport: hvad der skete, mulighederne, konsekvensen for hver og en anbefaling. Første mulighed er at skalere ud med en revideret skaleringsplan. Ændring af omfang er kun en mulighed, når den kritiske vej gør fristen umulig. Styregruppen beslutter.

### PRINCE2-begreber i fabrikken

| PRINCE2 / agil | I fabrikken |
|---|---|
| Business case | Formålet i kravspec'en, genbekræftes ved hver fasegrænse |
| Faseplan | Skaleringsplanen for en milestone |
| Produktbaseret planlægning | Arkitektur → kontrakter → opgaver |
| Produktbeskrivelse med kvalitetskriterier | Kontrakt med acceptkriterier |
| Arbejdspakke | Opgaven (work package) |
| Kvalitetsregister | Kontrolposter fra faktakontrol, niveau 1, niveau 2 og opdragskontrol |
| Statusrapport | Projektlederens dagsrapport |
| Undtagelsesrapport | Projektlederens rapport med anbefaling |
| Ændringsanmodning med konsekvensanalyse | Ændringsforslag og konsekvensrapport i ændringsløbet |
| Erfaringslog | Kilden til nye husregler og promptversioner |
| Sprint-backlog og MoSCoW | Opgaver valgt efter kravenes prioritet |
| Retrospektiv | Forslag til næste version af husregler og prompts |

## Kontrol af AI-leverancer

### Faktakontrol (alle leverancer, maskinel)

Grundregel: en agents egen rapport er aldrig bevis.

1. Referencer skal findes. Krav-id, kontrakt-id, filnavn, funktion og bibliotek slås op.
2. Påstande efterprøves. Tests tæller kun, når systemet selv har kørt dem.
3. Antagelser mærkes og holdes adskilt fra det, kravspec'en siger.
4. Kun det bestilte. Ændringer uden for opgavens filer afvises; funktionalitet uden krav markeres.
5. Reviewere kontrolleres også. Fund skal pege på fil og linje, som slås op.

Faktakontrollen bygger ikke selv på en sprogmodel. Den gælder også projektlederens anbefalinger og rapporter. Den fanger ikke en plausibel, men forkert fortolkning af et krav; den fanges af niveau 2, opdragskontrollen og den menneskelige godkendelse.

### Niveau 1 – teknisk

Kodeauditøren holder koden op mod husreglerne og projektreglerne. Maskinelle checks kører først; vurderingsreglerne bedømmes af kodeauditøren.

### Niveau 2 – krav og arkitektur

Kontekstkontrollanten vurderer koden mod kravspec, arkitekturkontrakt og modulkontrakt. Niveau 2 kører kun efter bestået niveau 1 og kan ikke omgøre en teknisk fejl. Det kører pr. opgave før fletning og igen på hele milestonen før main.

### Roller og kontekst

Rollekataloget (`config/role_process/catalog.v2.yaml`, version 2) er den gældende kilde. Uddrag:

| Rolle | Lag | Ejer af | Input | Output | Kontrolleres af | Art |
|---|---|---|---|---|---|---|
| Styregruppe / projektejer | Styring | Business case, omfang og alle godkendelser | Indstillinger, undtagelsesrapporter, ændringsforslag | Beslutninger og godkendelser (kravspec, arkitektur, kontrakter, skaleringsplan, milestones, omfang, regler, prompts, rollekatalog) | – | Menneske |
| Produktejer | Styring | Kravspec og opdraget | Opdrag, kravspec, ændringsforslag, opdragskontrol-resultater, milestone-diff | Prioriteret kravspec, vurdering af ændringsforslag, opdragskontrol af helheden mod kravspec begge veje | Faktakontrol og testkørsel, Systemarkitekt, Styregruppe / projektejer | Agent |
| Systemarkitekt | Styring | Arkitekturen gennem hele forløbet | Godkendt kravspec og arkitektur, kontrakter, opgaveopdeling, milestone-diff | Arkitekturbeslutningslog, indstilling om kontrakter og opgaveopdeling, arkitekturkontrol af milestones | Faktakontrol og testkørsel, Arkitekturreviewer, Styregruppe / projektejer | Agent |
| Projektleder | Styring | Planen, rytmen og tolerancerne | Godkendte planer, jobposter, kontrolresultater, statistik, tolerancer | Sprintplan, skaleringsplan, frigivelse af pakker, undtagelsesrapporter, dagsrapport | Faktakontrol og testkørsel, Styregruppe / projektejer | Agent |
| Kvalitetsansvarlig | Styring | Husreglerne og kvalitetsregisteret | Husregler, kontrolresultater, statistik, retrospektiv | Regelforslag (foreslået, på prøve, aktiv, udfaset) og kvalitetsregister | Faktakontrol og testkørsel, Styregruppe / projektejer | Agent |
| Release-ansvarlig | Styring | Releasen af en milestone | Milestone-branch, kontrolresultater, fuld test, styregruppens godkendelse | Release-tjekliste, release-noter og release-bevis til PR, known-good-tag og backup | Faktakontrol og testkørsel, Produktejer, Styregruppe / projektejer | Agent |
| Kravafklarer | Produktion | – | Opdrag eller repo-analyse | Kravspec-udkast | Faktakontrol og testkørsel, Produktejer, Styregruppe / projektejer | Agent |
| Arkitekt | Produktion | – | Godkendt kravspec | Arkitekturforslag | Faktakontrol og testkørsel, Arkitekturreviewer, Systemarkitekt, Styregruppe / projektejer | Agent |
| Kontraktforfatter | Produktion | – | Godkendt arkitektur | Modulkontrakter | Faktakontrol og testkørsel, Kontekstkontrollant, Systemarkitekt, Styregruppe / projektejer | Agent |
| Opgaveproducent | Produktion | – | Godkendte kontrakter og arkitektur | Arbejdspakker med beskrivelse, vægt og rækkefølge (opgavekompileren er faktakontrollen) | Faktakontrol og testkørsel, Systemarkitekt, Projektleder, Styregruppe / projektejer | Agent |
| Testdesigner | Produktion | – | Acceptkriterier og kontrakter | Accepttests skrevet før kodningen, uafhængigt af koderen | Faktakontrol og testkørsel, Kontekstkontrollant, Systemarkitekt | Agent |
| Promptproducent | Produktion | – | Rollekatalog, husregler, statistik pr. promptversion | Versionerede prompts pr. agentrolle | Faktakontrol og testkørsel, Promptreviewer, Styregruppe / projektejer | Agent |
| Koder | Produktion | – | Arbejdspakke og kontekstpakke | Kode og tests | Faktakontrol og testkørsel, Testdesigner, Kodeauditør, Sikkerhedsansvarlig, Kontekstkontrollant | Agent |
| Arkitekturreviewer | Kontrol | – | Kravspec og arkitekturforslag | Fund og uenigheder | Faktakontrol og testkørsel | Agent |
| Promptreviewer | Kontrol | – | Prompt, rollens beskrivelse i kataloget, husregler | Fund og uenigheder | Faktakontrol og testkørsel | Agent |
| Kodeauditør | Kontrol | – | Diff, husregler og projektregler, testresultater | Niveau 1-fund | Faktakontrol og testkørsel | Agent |
| Sikkerhedsansvarlig | Kontrol | – | Diff, afhængigheder, hemmelighedsscanning, sikkerhedsregler | Sikkerhedsfund pr. pakke og pr. milestone | Faktakontrol og testkørsel | Agent |
| Kontekstkontrollant | Kontrol | – | Diff, kravspec, arkitektur, kontrakt, testresultater | Niveau 2-fund | Faktakontrol og testkørsel | Agent |
| Faktakontrol og testkørsel | System | – | Leverance og systemets egne testkørsler (for opgaver opgavekompilerens validering) | Verificerede referencer, påstande og testresultater | – | System |
| Rapport og statistik | System | – | Jobposter, kontrolposter og målinger | Statistik pr. agent, opgavetype og promptversion; tal til dagsrapport og undtagelsesrapporter | – | System |
| Orkestrator | System | – | Godkendte planer og gates | Fordeling, kvitteringer, frigivelse, git-operationer på milestone-branchen | – | System |

Faktakontrollen, statistikken og orkestratoren er systemroller uden sprogmodel. Kun styregruppen beslutter; styringsrollerne ejer hver et artefakt, styrer og indstiller (beslutning 40).

Kontrolrollerne får en fast kontekstpakke: kravspec-revisionen, kontrakten, de gældende regler, diffen og de testresultater, systemet selv har kørt. De får ikke koderens samtale, ræsonnement eller rapport, så de efterprøver koden i stedet for koderens fortolkning af den.

Med to producenter kontrollerer den ene den andens kode. Med flere producenter kan kodeauditør og kontekstkontrollant komme fra hver sin. Modeller fra forskellige producenter kan stadig tage fejl på samme måde; de maskinelle kontroller kommer derfor først, og styregruppens godkendelse ved milestonen er sidste værn.

### Tilbagerulning frem for fejlretning

At generere kode er billigt; at forstå og rette fremmed kode er dyrt, og en agent, der retter sin egen kode, bygger ofte videre på sin forkerte antagelse. Udgangspunktet er derfor at kassere og bygge på ny (beslutning 35). Men en ny agent laver samme fejl, hvis årsagen ligger i inputtet. Årsagen findes derfor i agentloggen og rettes i inputtet først: fejlretning flytter fra koden til kravspec, kontrakt og prompt.

| Situation | Handling |
|---|---|
| Lokal fejl i pakken, og årsagen er forstået | Rework, højst to runder (beslutning 7) |
| Ikke forstået, eller to runders rework hjalp ikke | Kassér pakken; byg den ny med en frisk agent |
| Fejlen ligger i en antagelse, kontrakt eller kravspec | Ret inputtet gennem ændringsløbet; byg de berørte pakker ny |
| Projektet er kørt af sporet: flere pakker eller opdragskontrollen røde | Rul tilbage til seneste kendte gode punkt; find årsagen i agentloggen; ret inputtet; byg ny |
| Den beskyttede kerne | Fejlret, med styregruppens godkendelse |

Hver kassering og tilbagerulning registrerer årsagen på jobposten, så agentstatistikken, husreglerne og promptversionerne lærer af den. Tilbagerulning er billig, så længe fejlen findes tidligt; derfor hænger princippet sammen med dagssprints og den daglige opdragskontrol.

### Agentlog og backup

**Agentlog (beslutning 37).** Arbejder-adapteren gemmer for hvert job prompt, kontekstpakke, hele agentens forløb som maskinlæsbar strøm (Claude Code `--output-format stream-json`, Codex `exec --json`), diff og testoutput. Udbydernes egne logs kan ikke bruges som revisionsspor: Claude API'et gemmer ingen samtaler, og OpenAI gemmer svar i en begrænset periode.

**Backup i fire lag (beslutning 38):**

| Lag | Hvad | Beskytter mod |
|---|---|---|
| Kendte gode punkter | Hver godkendt milestone får et tag `known-good/<milestone>` på `main` med release-bevis. Tilbagerulning er en ny branch fra tagget, aldrig omskrivning af historikken. | Et projekt, der er kørt af sporet |
| Beskyttelse | Branch protection på `main` og beskyttelse af tags: ingen force-push, ingen sletning, krævede checks | At en agent eller et uheld omskriver historikken |
| Kopi uden for GitHub | Natlig `git bundle` af hele repoet | Tab af repo eller konto |
| Tilstand | Backup af DOR's database (kravspec-versioner, godkendelser, jobposter, agentlogs), taget sammen med hvert tag | At kode og beslutninger ikke passer sammen efter en tilbagerulning |

## Milestone-branches

Problemet med forældede branches følger af, at hver opgave bindes til én præcis base-commit, og at en ændret base ugyldiggør opgavens beviser. Det forværres, hvis en milestone-branch lever længe, mens `main` flytter sig, fordi branchen så bliver et historisk øjebliksbillede. Det sker, når mennesker eller andre milestones også skriver til `main`, som når DOR udvikler sig selv eller arbejder i en kundes repo.

`main` er derfor det fælles fundament, og en milestone-branch er kun et kortlivet arbejdsområde oven på det.

1. Opgavekompileren grupperer opgaver i milestones og dagssprints, så hver milestone er et kørbart delsystem.
2. Hver milestone får én branch, der kun lever, mens milestonen kører. Opgave-branches udgår fra dens top og lever højst én sprint.
3. **Ved hver sprintstart genbaseres milestone-branchen på den nyeste `main`**, og hele suiten køres, før dagens pakker frigives. Branchen er dermed højst én dag bagud. Giver genbaseringen konflikter eller fejl, bliver det en undtagelse til styregruppen, før sprinten starter.
4. **Hver arbejdspakke bindes til tre versioner:** den commit, den starter fra, kravspec-revisionen og kontraktversionen. DOR registrerer alle tre på pakken og jobposten.
5. Bliver en af de tre versioner forældet, mens pakken er i gang, markeres pakken forældet. Den genbaseres og genkontrolleres i stedet for at blive kasseret eller arbejde videre i stilhed. Det ændrer den nuværende regel.
6. Parallelle opgaver får adskilte filer; overlappende opgaver køres efter hinanden. Når én pakke er flettet, kontrolleres den næste mod den nye milestone-top og antages ikke at passe.
7. Hver sprint får et startmærke efter genbaseringen, så en kasseret sprint kan rulles tilbage.
8. Kontrakter er frosne inden for en sprint. En ændring af opdraget træder i kraft ved næste sprintstart.
9. Kun milestone-branchen går til `main`, efter fuld test på en revision, der er genbaseret på den nyeste `main`, niveau 2 på helheden og styregruppens godkendelse. Derefter slettes branchen, og milestonen markeres med et tag på `main`.

En ren trunk-model, hvor hver pakke flettes direkte til `main`, er fravalgt, fordi den fjerner godkendelsen før `main` og gør kassering af en dagssprint til revert-commits på `main`. Den kan genovervejes, når kontrollerne har vist, at de kan bære det alene.

## Plan

| # | Trin | Indhold | Skærmbillede |
|---|---|---|---|
| 1 | Rygrad, reference, regler | Rollekatalog og håndhævelse af grundprincippet; pipelinen som eneste spor; gennemgående sporbarhed med krav-id og kravspec-version på hvert artefakt; jobpost for hvert agentjob; kravspec for husregel-registeret; husregler v1; `AGENTS.md` og dokumentationen rettes til denne plan | GUI-skelet: projektoverblik, indbakke, projektkonfiguration |
| 2 | Repo-analyse til kravspec | Project Audit danner et kravspec-udkast, som styregruppen godkender; DOR er første repo | Repo-tilknytning og kravspec-udkast |
| 3 | Arkitektur via rådet | Proposer, reviewere og verifier er færdige kodeagenter med Spec Kits plan-prompts; stak vælges ud fra kravspec; moduler skal kunne bygges uafhængigt; gate | Arkitekturforslag, uenigheder, godkendelse |
| 4 | Kontrakter pr. modul | Skemavaliderede, sporbare til krav-id'er; gate | Kontrakter og sporbarhed til krav |
| 5 | Opgavekompiler | Kontrakter til arbejdspakker pr. milestone og dagssprint med adskilte filer, afhængigheder og opgavetype; kritisk vej; skaleringsplan til godkendelse | Opgavegraf, sprintplan og skaleringsplan |
| 6 | Arbejder-adapter | Claude Code og Codex uden skærm i afskærmet worktree; kort branch fra milestone-toppen; omsætning af arbejdspakke til Spec Kit-format; jobpost med forbrug; agentlog for hvert job | Arbejdspakkers status og forbrug |
| 7 | Kontrol | Faktakontrol; kodeauditør (niveau 1) og kontekstkontrollant (niveau 2) fra en anden producent end koderen med fast kontekstpakke; rework-sløjfe og sortering mellem rework, ny udvikling og ændring af input; målinger og årsager skrives på jobposten | Kontrolresultater pr. arbejdspakke |
| 8 | Milestone-branch | Kortlivet branch genbaseret på `main` ved sprintstart; binding af pakker til commit, kravspec-revision og kontraktversion med genbasering ved forældelse; samling, sprintmærker og kassering, fuld test, styregruppens godkendelse, én PR til main og tag `known-good/<milestone>`; backup af database og kopi uden for GitHub ved hvert tag; tilbagerulning til kendt godt punkt | Dagseftersyn, milestone-godkendelse og tilbagerulning |
| 8b | Styringslag og prompts (før 8a) | Rollekatalog v2 med styregruppe og styringsroller (beslutning 40); prompts som versionerede data med promptproducent og promptreviewer, promptversion på hver jobpost (beslutning 42); opgaveproducent med kompileren som faktakontrol (beslutning 41); testdesigner før kodningen og sikkerhedsansvarlig i kontrollen (beslutning 43); produktejeren og systemarkitekten kontrollerer milestonen før styregruppens godkendelse; release-ansvarlig og rapport og statistik på milestonen | Roller, prompts med versioner og fund fra styringsrollerne |
| 8a | Første gennemløb | Hele kæden på husregel-registeret med Claude Code og Codex parallelt på samme kontrakter; manuelle trin registreres; målinger af integrationsfejl, kontraktbrud og indgreb (se "Første gennemløb") | Dokumenteret kørsel med målinger |
| 9 | Opdragskontrol og ændringsløb | Kode mod kravspec begge veje, dagligt og ved main; rework eller ændringsforslag; ny kravspec-version rulles ned gennem alle led med kvittering | Opfyldelse krav for krav; ændringsforslag og konsekvensrapport |
| 10 | Styring og erfaring | Projektleder-agenten, kvalitetsansvarlig, dagsrapport, tolerancer og undtagelsesrapporter, retrospektiv, regelsløjfe | Dagsrapport, undtagelsesrapporter, husregler og tolerancer |
| 11 | Agentstatistik og agentvalg | Statistik pr. agent, opgavetype og promptversion; versionerede prompts; kappestrid som forsøg; valg af agent inden for godkendte puljer | Statistik pr. agent og opgavetype; puljer og prompts |
| 12 | GUI samlet | Systemkonfiguration færdiggøres | Hele forløbet |
| 13 | Samlet test | Hele systemet testes samlet på husregel-registeret: mindst én ændring af opdraget, én kasseret sprint, to agenter parallelt i samme rolle og begge arbejdere; derefter DOR som eksisterende repo | Dokumenteret kørsel gennem GUI'en |

Milepæl 1: trin 1, 3–8, 8b (styringslag og prompts), 8a (første gennemløb) og 9, inklusive GUI-skelet. Dagssprints og skaleringsplan er med fra start; planen udarbejdes manuelt, indtil projektlederen er bygget. Jobposter og målinger indsamles fra første kørsel.

Milepæl 2: trin 2, 10, 11 og 12.

Milepæl 3: trin 13, samlet test. Derefter første kundeopgave, og DOR udvikler sig selv under reglerne for selvudvikling.

V2: økonomilag. Venter til senere: autonominiveauer, Redmine, deploy.

## Åbne punkter

- Hvem der kan bedømme kode og arkitektur fagligt, når kontrollerne er uenige.
- Om DeepSeek og Rool kan køre som kodeagenter gennem et åbent værktøj.
- Om GUI'en skal blive i Streamlit.
- Hvor kopien uden for GitHub skal ligge (UpCloud er foreslået).
