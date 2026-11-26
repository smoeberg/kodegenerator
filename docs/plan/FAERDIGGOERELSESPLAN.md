# DOR – plan for færdiggørelse

Version 9 · 26. november 2026 · Whiteboard: https://claude.ai/artifact/5ZMM2dgqXTTGB1TSzeAcNg

Nyt i version 9: første gennemløb af hele kæden efter trin 8 (beslutning 33, afsnittet "Første gennemløb" og trin 8a). Testisolationen er løst (#292).

## Mål

Et udviklingsværktøj, hvor flere AI-agenter i en stram organisation med roller og kontroller udvikler software ud fra en kravspec (opdraget):

kravspec → arkitektur → kontrakter → opgaver → kodning → kontrol → samlet system → opdragskontrol → tilbage til kravspec

Forløbet er en lukket sløjfe, ikke en linje. DOR er styringslaget: det styrer og kontrollerer, mens færdige kodeagenter udfører. Den menneskelige kontrol er den overordnede: systemet anbefaler, mennesket beslutter. Systemet lærer af sine egne job: hvilke agenter og prompts der klarer hvilke opgaver bedst. På sigt udvikler DOR sig selv. Den eksisterende dokumentation i repoet er retningslinje, ikke bindende.

## Udgangspunkt

Analysen er lavet mod `smoeberg/kodegenerator`, branch `main`, commit `98449e2`, Alembic-head `036_runtime_settings`. Lokalt bestod 2.425 tests og 3 fejlede. De tre ligger i `test_swarm_operations_api.py` og består, når filen køres alene; de fejler kun sammen med de øvrige API-tests, fordi login med standard-administratoren afvises. Det peger på, at testene deler tilstand, og ikke på en fejl i produktet. E2E-, phase6- og acceptance-suiterne er ikke kørt.

Status 26. november 2026: #292 er flettet (main `bb22186`). Standard-administratoren sættes nu op i en fælles `tests/conftest.py`, og hele suiten består lokalt med 2.473 beståede og 15 oversprungne. #293 (OpenTelemetry-sårbarhed) og #294 (CI-artefakter og CodeQL) venter på fletning. Selve koden er ellers uændret siden analysen.

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
6. Kode samles i milestone-branches, ikke i én branch pr. leverance mod main.
7. Fejler niveau 2, går koden tilbage til koderen højst to gange og derefter til mennesket.
8. Hver milestone godkendes af et menneske, før den går til main.
9. Udviklingsreglerne skal defineres (se `docs/plan/HUSREGLER_V1_UDKAST.md`).
10. Husreglerne er dynamiske: et versioneret regelsæt, der udvikles ud fra egen empiri og ekstern best practice.
11. Styringen følger PRINCE2 Agile: PRINCE2 for retning og beslutninger, sprints for leverancen.
12. Sprint er et selvstændigt niveau under milestone. En milestone kan have flere sprints.
13. Omfangsændringer besluttes af den menneskelige projektleder på baggrund af en anbefaling fra systemet. Systemet udskyder aldrig selv krav.
14. En agent er projektassistent. Den anbefaler; projektlederen beslutter.
15. GUI'en er en central del af produktet: den viser projektet og er stedet, hvor hele systemet og de enkelte projekter konfigureres. Den bygges løbende, ikke til sidst.
16. Koden kontrolleres mod opdraget (kravspec'en). Kontrollen kan give anledning til ændringer i opdraget.
17. Når opdraget ændres, skal alle led opdatere deres opgaver. Intet led må arbejde videre på en forældet version.
18. Sprints er korte, som udgangspunkt én dag. Der kan rettes til hver dag, og en dags arbejde kan kasseres.
19. AI-agenter er ikke en knap ressource. Tiden holdes ved at dele en milestone i flere dele og sætte flere agenter på. Tid og omfang ligger fast; forbruget giver sig.
20. En plan for skaleringen skal godkendes af projektlederen.
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
| Opgavesynteser, scheduler, worktree-styring | Behold |
| Integrationscontroller | Tilpas til milestone-branches |
| Rådet og bot-konfiguration | Tilpas til færdige kodeagenter |
| Lint/test/build-adaptere, arkitekturregel-evaluatorer | Behold |
| Evalueringskoordinator og evalueringsposter | Tilpas til jobposter og statistik |
| Egen patch-agent (`phase4/implementation_agent`) | Kassér |
| Skabelon-arkitektur (`generation/scaffold_engine`) | Kassér |
| Regex-kontrakter (`generation/contract_generator`) | Kassér |
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
| Kendt facit | Designet er fastlagt i `docs/plan/HUSREGLER_V1_UDKAST.md` |

Registeret bygges som selvstændig komponent. Projektlederen fletter det selv ind i DOR.

### Tre trin til selvudvikling

1. **Milepæl 1:** Fabrikken bygger husregel-registeret som ny komponent.
2. **Milepæl 2:** DOR tilsluttes som det første eksisterende repo. Repo-analysen danner et kravspec-udkast, som holdes op mod denne plan.
3. **Derefter:** DOR udvikler sig selv.

### Regler for selvudvikling

- En stabil, frigivet version af fabrikken bygger den næste. Den kørende fabrik ændrer aldrig sig selv.
- Kontrollaget er en beskyttet kerne: faktakontrol, niveau 1 og 2, opdragskontrol, godkendelser, regelmotoren og agentudvælgelsen. Ændringer dér kræver projektlederens godkendelse hver gang, også når projektet kører på "kun undtagelser".

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

Prompts følger samme livscyklus som husreglerne: foreslået, på prøve, aktiv, udfaset. Statistikken viser, om en ny promptversion giver færre misforståelser, målt på antagelser, faktakontrol-fejl og rework. Agenter foreslår promptændringer; projektlederen godkender.

### Kappestrid som forsøg

Fordi agenter ikke er en knap ressource, kan samme arbejdspakke gives til flere agenter samtidig. Kontrollerne udpeger højst én vinder, og alle forsøg giver målinger. Det er den hurtigste vej til sammenlignelige tal, fordi opgaven er den samme.

### Valg af agent

1. Projektlederen godkender, hvilke agenter der må bruges i hver rolle (puljen).
2. Systemet vælger inden for puljen ud fra statistikken for opgavetypen.
3. Valget og dets begrundelse gemmes.
4. Systemet kan anbefale ændringer af puljen, men ændrer den ikke selv.

### Forbehold

- **Mængde:** Få job pr. agent og opgavetype giver støj. Statistikken påvirker først valget efter et mindste antal job.
- **Sammenlign ens med ens:** Samme opgavetype, promptversion og sværhedsgrad. Udbydere opdaterer modeller uden varsel, så modelversionen skal med.
- **Uafhængig dommer:** Niveau 2 må ikke bedømmes af samme modelfamilie som koderen, ellers bliver tallene skæve.
- **Opgavetyper skal defineres:** De fastlægges i opgavekompileren og er selv versionerede.

## Rytme: dagssprints

| Tidspunkt | Hvad sker der |
|---|---|
| Sprintstart | Godkendte ændringer af opdraget træder i kraft; alle led kvitterer; dagens arbejdspakker frigives efter skaleringsplanen |
| I løbet af sprinten | Agenter leverer arbejdspakker; faktakontrol, niveau 1 og niveau 2 pr. pakke; fletning til milestone-branchen |
| Sprintslut | Opdragskontrol på milestone-branchen; projektassistentens dagsrapport med afvigelser og indstillinger |
| Eftersyn | Projektlederen godkender, retter eller kasserer; retrospektiv giver eventuelle regelforslag |

En dagssprint ender i én af tre tilstande:

| Udfald | Følge |
|---|---|
| Godkendt | Arbejdet står; næste sprint bygger videre |
| Rettet | Afvigelser bliver rework-pakker eller ændringsforslag i næste sprint |
| Kasseret | Milestone-branchen sættes tilbage til sprintens startpunkt; pakkerne planlægges om |

Hver sprint får et startmærke på milestone-branchen, så kassering er en enkel og sikker handling. En kasseret dag er billig, så længe intet andet bygger på den; dagssprints begrænser netop det til højst én dag.

### To måder at føre eftersyn

- **Godkend hver dag:** Næste sprint starter først, når den forrige er godkendt, rettet eller kasseret.
- **Kun undtagelser:** Sprints fortsætter uden godkendelse, så længe kontrollerne er bestået. Projektlederen ser dagsrapporten og får kun undtagelser til beslutning. Godkendelsen sker ved milestonen.

Måden vælges pr. projekt og kan skiftes ved en sprintgrænse.

## Skalering

Tiden holdes ved at skalere ud, ikke ved at skære i omfanget.

### Skaleringsplan

Projektassistenten udarbejder en skaleringsplan for hver milestone, og projektlederen godkender den, før arbejdet starter:

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

Projektassistenten indstiller for hver afvigelse. Projektlederen beslutter.

For et eksisterende repo uden kravspec er det samme kontrol: alt i koden mangler et krav, og resultatet er et kravspec-udkast (trin 2).

### Ændringsløb

En godkendt ændring giver en ny, uforanderlig kravspec-version. Den gamle markeres som erstattet. Ændringen træder i kraft ved næste sprintstart.

1. **Forskel:** Hvilke krav-id'er er tilføjet, ændret eller fjernet.
2. **Konsekvensanalyse:** Gennem sporbarhedskæden krav → arkitekturbeslutning → kontrakt → arbejdspakke → kode → test → kontrolpost findes alt, der er berørt.
3. **Konsekvensrapport:** Projektassistenten beskriver omfang, forbrug og påvirkning af skaleringsplanen, med en anbefaling.
4. **Beslutning:** Projektlederen godkender ændringen og afgør, om berørt arbejde fra den igangværende sprint rettes eller kasseres.
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
- **Indbakken først:** Projektlederen er flaskehalsen, så alt, der venter på en beslutning, samles ét sted.

### Rækkefølge

Hvert trin i planen leverer sit eget skærmbillede. Et GUI-skelet med projektoverblik, godkendelsesindbakke og projektkonfiguration bygges tidligt, fordi gates og godkendelser kræver det.

## Styring: PRINCE2 Agile

### Niveauer

projekt → fase (milestone) → sprint → arbejdspakke

| Niveau | Afsluttes med | Branch |
|---|---|---|
| Projekt | Opdragskontrol viser kravspec opfyldt; business case genbekræftet | main |
| Fase (milestone) | Fuld test, niveau 2 på helheden, projektlederens godkendelse, fletning til main, opdragskontrol | Milestone-branch |
| Sprint (én dag) | Opdragskontrol, dagsrapport, eftersyn: godkendt, rettet eller kasseret; retrospektiv | Ingen egen; startmærke på milestone-branchen |
| Arbejdspakke | Faktakontrol, niveau 1 og niveau 2 bestået; flettet til milestone-branchen | Kort opgave-branch |

Regelsæt og prompts er frosne inden for en sprint.

### Roller

| Rolle | Hvem | Ansvar |
|---|---|---|
| Projektleder | Menneske | Godkender kravspec og dens ændringer, arkitektur, kontrakter, skaleringsplaner, agentpuljer og hver milestone; beslutter undtagelser og omfang; godkender ændringer af regler og prompts |
| Projektassistent | Agent | Foreslår sprintplan, skaleringsplan og prioritering; skriver dagsrapporter, undtagelsesrapporter og konsekvensrapporter med muligheder og anbefaling |
| Orkestrator | System (DOR) | Fordeler arbejdspakker efter den godkendte skaleringsplan; vælger agent inden for puljen; håndhæver tolerancer, rækkefølge og kvittering for ny kravspec-version |
| Koder | Færdig kodeagent via arbejder-adapter | Leverer én arbejdspakke ad gangen |
| Kontrollant | Færdig kodeagent, en anden end koderen | Niveau 1, niveau 2 og opdragskontrol |

Projektassistenten kan ikke godkende, ændre omfang, ændre opdraget, ændre skaleringen, ændre puljer eller ændre regler.

### Tolerancer og undtagelser

Tid og omfang ligger fast. Tolerancer sættes for antal rework-runder (højst to), for afvigelse fra skaleringsplanen og for tid på den kritiske vej. Forbrug registreres, men har intet loft i v1.

Ved overskridelse stopper arbejdet på det berørte niveau, og projektassistenten skriver en undtagelsesrapport: hvad der skete, mulighederne, konsekvensen for hver og en anbefaling. Første mulighed er at skalere ud med en revideret skaleringsplan. Ændring af omfang er kun en mulighed, når den kritiske vej gør fristen umulig. Projektlederen beslutter.

### PRINCE2-begreber i fabrikken

| PRINCE2 / agil | I fabrikken |
|---|---|
| Business case | Formålet i kravspec'en, genbekræftes ved hver fasegrænse |
| Faseplan | Skaleringsplanen for en milestone |
| Produktbaseret planlægning | Arkitektur → kontrakter → opgaver |
| Produktbeskrivelse med kvalitetskriterier | Kontrakt med acceptkriterier |
| Arbejdspakke | Opgaven (work package) |
| Kvalitetsregister | Kontrolposter fra faktakontrol, niveau 1, niveau 2 og opdragskontrol |
| Statusrapport | Projektassistentens dagsrapport |
| Undtagelsesrapport | Projektassistentens rapport med anbefaling |
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

Faktakontrollen bygger ikke selv på en sprogmodel. Den gælder også projektassistentens anbefalinger og rapporter. Den fanger ikke en plausibel, men forkert fortolkning af et krav; den fanges af niveau 2, opdragskontrollen og den menneskelige godkendelse.

### Niveau 1 – teknisk

Koden holdes op mod udviklingsreglerne. Maskinelle checks først; resten vurderes af en review-bot.

### Niveau 2 – krav og arkitektur

En anden bot end koderen, og fra en anden modelfamilie, vurderer koden mod kravspec, arkitekturkontrakt og modulkontrakt. Niveau 2 kører kun efter bestået niveau 1 og kan ikke omgøre en teknisk fejl. Det kører pr. opgave før fletning og igen på hele milestonen før main.

## Milestone-branches

Problemet med forældede branches følger af, at hver opgave bindes til én præcis base-commit, og at en ændret base ugyldiggør opgavens beviser.

1. Opgavekompileren grupperer opgaver i milestones og dagssprints, så hver milestone er et kørbart delsystem.
2. Hver milestone får én branch. Opgave-branches udgår fra dens top og lever højst én sprint.
3. Parallelle opgaver får adskilte filer; overlappende opgaver køres efter hinanden.
4. Flytter milestone-toppen sig, genbaseres og genkontrolleres en ventende opgave i stedet for at blive kasseret. Det ændrer den nuværende regel.
5. Hver sprint får et startmærke, så en kasseret sprint kan rulles tilbage.
6. Kontrakter er frosne inden for en sprint. En ændring af opdraget træder i kraft ved næste sprintstart.
7. Kun milestone-branchen går til main, efter fuld test, niveau 2 på helheden og projektlederens godkendelse.

## Plan

| # | Trin | Indhold | Skærmbillede |
|---|---|---|---|
| 1 | Rygrad, reference, regler | Pipelinen som eneste spor; gennemgående sporbarhed med krav-id og kravspec-version på hvert artefakt; jobpost for hvert agentjob; kravspec for husregel-registeret; husregler v1; `AGENTS.md` og dokumentationen rettes til denne plan | GUI-skelet: projektoverblik, indbakke, projektkonfiguration |
| 2 | Repo-analyse til kravspec | Project Audit danner et kravspec-udkast, som projektlederen godkender; DOR er første repo | Repo-tilknytning og kravspec-udkast |
| 3 | Arkitektur via rådet | Proposer, reviewere og verifier er færdige kodeagenter med Spec Kits plan-prompts; stak vælges ud fra kravspec; moduler skal kunne bygges uafhængigt; gate | Arkitekturforslag, uenigheder, godkendelse |
| 4 | Kontrakter pr. modul | Skemavaliderede, sporbare til krav-id'er; gate | Kontrakter og sporbarhed til krav |
| 5 | Opgavekompiler | Kontrakter til arbejdspakker pr. milestone og dagssprint med adskilte filer, afhængigheder og opgavetype; kritisk vej; skaleringsplan til godkendelse | Opgavegraf, sprintplan og skaleringsplan |
| 6 | Arbejder-adapter | Claude Code og Codex uden skærm i afskærmet worktree; kort branch fra milestone-toppen; omsætning af arbejdspakke til Spec Kit-format; jobpost med forbrug | Arbejdspakkers status og forbrug |
| 7 | Kontrol | Faktakontrol, niveau 1, niveau 2; rework-sløjfe; målinger skrives på jobposten | Kontrolresultater pr. arbejdspakke |
| 8 | Milestone-branch | Samling, sprintmærker og kassering, fuld test, projektlederens godkendelse, én PR til main | Dagseftersyn og milestone-godkendelse |
| 8a | Første gennemløb | Hele kæden på husregel-registeret med Claude Code og Codex parallelt på samme kontrakter; manuelle trin registreres; målinger af integrationsfejl, kontraktbrud og indgreb (se "Første gennemløb") | Dokumenteret kørsel med målinger |
| 9 | Opdragskontrol og ændringsløb | Kode mod kravspec begge veje, dagligt og ved main; rework eller ændringsforslag; ny kravspec-version rulles ned gennem alle led med kvittering | Opfyldelse krav for krav; ændringsforslag og konsekvensrapport |
| 10 | Styring og erfaring | Projektassistent, dagsrapport, tolerancer og undtagelsesrapporter, retrospektiv, regelsløjfe | Dagsrapport, undtagelsesrapporter, husregler og tolerancer |
| 11 | Agentstatistik og agentvalg | Statistik pr. agent, opgavetype og promptversion; versionerede prompts; kappestrid som forsøg; valg af agent inden for godkendte puljer | Statistik pr. agent og opgavetype; puljer og prompts |
| 12 | GUI samlet | Systemkonfiguration færdiggøres | Hele forløbet |
| 13 | Samlet test | Hele systemet testes samlet på husregel-registeret: mindst én ændring af opdraget, én kasseret sprint, to agenter parallelt i samme rolle og begge arbejdere; derefter DOR som eksisterende repo | Dokumenteret kørsel gennem GUI'en |

Milepæl 1: trin 1, 3–8, 8a (første gennemløb) og 9, inklusive GUI-skelet. Dagssprints og skaleringsplan er med fra start; planen udarbejdes manuelt, indtil projektassistenten er bygget. Jobposter og målinger indsamles fra første kørsel.

Milepæl 2: trin 2, 10, 11 og 12.

Milepæl 3: trin 13, samlet test. Derefter første kundeopgave, og DOR udvikler sig selv under reglerne for selvudvikling.

V2: økonomilag. Venter til senere: autonominiveauer, Redmine, deploy.

## Åbne punkter

- Husregler v1 skal rettes til og godkendes.
- Kravspec for husregel-registeret skal skrives og godkendes.
- Hvem der kan bedømme kode og arkitektur fagligt, når kontrollerne er uenige.
- Om DeepSeek og Rool kan køre som kodeagenter gennem et åbent værktøj.
- Om GUI'en skal blive i Streamlit.
