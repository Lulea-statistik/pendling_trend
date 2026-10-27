# Pendling trend – kommun- och FA-regiongränser

Analys av **sysselsatta 15–74 år efter bostadskommun och arbetsställekommun**, SCB ArRegPend2 (2020–2024).

## Syfte
Visa hur många och hur stor andel av de boende sysselsatta som har ett arbetsställe:
1. i en annan kommun,
2. i en annan funktionell analysregion (FA25).

Fasta klassifikationer för att inte skapa konstgjorda tidsbrott:
- **SKR kommungruppsindelning 2023**, nio grupper.
- **Tillväxtverkets FA-regionindelning FA25 (2025–2035)**.

## Källor
- SCB tabell: https://www.statistikdatabasen.scb.se/pxweb/sv/ssd/START__AM__AM0210__AM0210F/ArRegPend2/
- SCB bulk CSV: https://www.statistikdatabasen.scb.se/Resources/PX/bulk/ssd/sv/TAB1830_sv.zip
- SCB officiella kodtabeller: https://www.scb.se/hitta-statistik/regional-statistik-och-kartor/regionala-indelningar/funktionella-regioner-och-kommungrupper/
- FA25: https://tillvaxtverket.se/tillvaxtverket/publikationer/publikationer2025/funktionellaanalysregioner2025.9233.html

## Tekniskt
Kör **Build commuting trend data** under Actions. Det hämtar SCB och referenslistorna, kontrollerar struktur, dubbelräkning och fullständiga kommunnycklar och skriver först därefter `docs/data/summary.json`. GitHub Pages: välj **Deploy from a branch**, gren `main`, katalog `/docs`.

**Status:** Första implementationsversion. API-/bulkdatahämtningen och automatiska identifieringen av kolumner i Excel-filerna är ännu inte verifierade med en lyckad körning. En misslyckad körning publicerar inte ersättningsstatistik.

## Metodgränser
Måttet avser inte resor eller faktiska pendlingsdagar. Arbetsställeplacering skiljer sig från var arbetet faktiskt utförs vid distansarbete. SCB:s sekretessmetod kan orsaka avvikelser mellan totalsummor och delsummor. Från 2024 har SCB justerat klassificeringen av företagare, varför tidsserien bör tolkas försiktigt.
\n## Historiska tabeller (separata RAMS-serier)\n- TAB333: kommunpar, 2004–2018.\n- TAB5850: kommunpar, 2019–2021.\n- TAB3266: kommunvis in-/utpendling samt bor och arbetar, 2004–2018. Läggs inte ovanpå kommunpar, för att undvika dubbelräkning.\n\nMetodbrott 2011 (åldersklassning), 2019 (AGI i stället för kontrolluppgifter) och 2020 vid övergång till BAS bör markeras. Historiska RAMS-antal omfattar endast pendling över kommungräns och kan inte användas för att beräkna andel av alla förvärvsarbetande utan en kontrollerad totalpopulation.\n