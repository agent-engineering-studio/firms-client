# Riuso nella Pubblica Amministrazione

firms-client legge i dati aperti di FIRMS, il servizio della NASA che pubblica
i fuochi attivi visti dai satelliti, e li rende usabili da chiunque. Questa
pagina è per un ente che vuole usarlo: che cosa trova pronto, che cosa resta a
lui, e come il progetto entra nel Catalogo del software di Developers Italia.

> **Prima versione.** Oggi firms-client è una libreria Python con riga di
> comando e un server MCP. La pagina per il sito del Comune, da installare con
> Docker, è in lavorazione
> ([roadmap, fase 6](https://github.com/agent-engineering-studio/firms-client/issues/26)):
> questa pagina crescerà con lei.

## Che cosa trova pronto

- Gli **archivi annuali per paese**: MODIS dal 2000 e VIIRS dal 2012, aperti,
  senza chiave e senza registrazione.
- Gli **ultimi giorni** su un'area qualsiasi, con una chiave gratuita della
  NASA (il MAP_KEY).
- Il **tipo** di ogni rilevazione: incendio di vegetazione, vulcano, industria,
  piattaforma in mare. Sull'Italia del 2025 circa un quarto delle rilevazioni
  VIIRS non sono incendi di vegetazione.
- Una **maschera delle fonti fisse** (acciaierie, torce) per i dati degli
  ultimi giorni, che il tipo non lo portano. Sull'Italia del 2025 prende il
  99,3 % delle rilevazioni statiche e scarta per errore il 3,0 % degli incendi.
- **Eventi**, riassunti, l'**anomalia della stagione** rispetto agli anni
  passati, e se a bruciare sono **campi o bosco**.
- Un **server MCP** perché un assistente AI risponda con i numeri dei dati,
  citando la fonte.

## Che cosa resta all'ente

Il progetto dà il software. Queste cose sono di chi lo usa.

- **Non è un'allerta.** Un fuoco visto dal satellite è una misura, non un
  giudizio sul pericolo. Per il pericolo valgono le comunicazioni ufficiali
  della Protezione Civile e dei Vigili del Fuoco.
- **Che cosa i dati non vedono.** FIRMS dice dove ha visto calore, non dove
  non c'è fuoco: sotto le nuvole o il fumo denso, tra un passaggio e l'altro
  del satellite, o per un fuoco più piccolo del pixel (375 m per VIIRS, 1 km
  per MODIS), la risposta è «non misurato», non zero. FIRMS non dà l'area
  bruciata. Una rilevazione con confidenza alta può essere un'acciaieria.
  L'anno in corso non è negli archivi: arriva solo dagli ultimi giorni.
- **Attribuzione dei dati.** I dati FIRMS sono della NASA e liberi da usare.
  Chi pubblica qualcosa ricavato da questi dati deve citarne la fonte, per
  esempio: «We acknowledge the use of data and imagery from LANCE FIRMS
  operated by NASA's Earth Science Data and Information System (ESDIS) with
  funding provided by NASA Headquarters.» Il testo è nella costante
  `ATTRIBUTION`.
- **Il MAP_KEY.** È personale e gratuito, e ha un limite di transazioni ogni
  dieci minuti. Va tenuto come una password, fuori dal codice e dai
  repository, in una variabile d'ambiente (`FIRMS_MAP_KEY`) o in un segreto di
  Docker. Gli archivi annuali non lo richiedono.
- **Dati personali.** Il software non ne raccoglie: niente account, niente
  cookie. Su disco restano solo gli archivi scaricati e la maschera calcolata.

## Intelligenza artificiale

I numeri della libreria sono calcolati dai dati con codice aperto e
verificato. Il server MCP dà a un assistente AI riassunti, non righe grezze, e
le bozze di bollettino passano un controllo: ogni numero e ogni luogo devono
venire dai fatti, altrimenti la bozza viene respinta. Un bollettino resta
sempre una bozza per una persona. La classe di rischio, la valutazione
d'impatto e l'informativa agli utenti riguardano l'uso che l'ente ne fa, e
sono sue.

## Il Catalogo di Developers Italia

**Oggi: software open source di terze parti.** Il codice non è di una PA.
Entra nel Catalogo con il file [`publiccode.yml`](https://github.com/agent-engineering-studio/firms-client/blob/main/publiccode.yml)
nel repository, con `codiceIPA` vuoto, e una segnalazione sul repository
[`italia/catalogo-software`](https://github.com/italia/catalogo-software).

**Domani: software a riuso.** Se un ente lo adotta e ne diventa titolare (art.
69 del CAD), lo dichiara con l'[onboarding](https://onboarding.developers.italia.it/)
di Developers Italia, e `codiceIPA` prende il codice dell'ente.

- [x] Repository pubblico, licenza Apache-2.0
- [x] README, documentazione, `CONTRIBUTING.md`, `CHANGELOG.md`
- [x] `publiccode.yml` valido per il validatore ufficiale, controllato a ogni modifica dalla CI
- [ ] Installazione con Docker e pagina per il Comune con Bootstrap Italia
- [ ] Segnalazione su `italia/catalogo-software`

## Fonti

- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), e la sua
  [pagina su Earthdata](https://www.earthdata.nasa.gov/data/tools/firms)
- [Linee guida su acquisizione e riuso di software per le PA](https://docs.italia.it/italia/developers-italia/lg-acquisizione-e-riuso-software-per-pa-docs/)
- [Standard publiccode.yml](https://yml.publiccode.tools/)
