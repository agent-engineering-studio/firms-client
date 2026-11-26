# Riuso nella Pubblica Amministrazione

firms-client legge i dati aperti di FIRMS, il servizio della NASA che pubblica
i fuochi attivi visti dai satelliti, e li rende usabili da chiunque. Questa
pagina è per un ente che vuole usarlo: che cosa trova pronto, che cosa resta a
lui, e come il progetto entra nel Catalogo del software di Developers Italia.

firms-client è una libreria Python con riga di comando e un server MCP, e
una **pagina per il sito del Comune** che si installa con Docker.

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
- Una **pagina per il sito del Comune**, con Bootstrap Italia, in italiano e
  in inglese: i fuochi visti negli ultimi giorni e in ogni anno d'archivio
  nell'area del Comune, quanto fidarsi di una rilevazione in un punto, e
  «Non è un'allerta» sempre in vista.
- Quattro **notebook**: la storia nazionale degli incendi, una stagione
  contro le altre, quanto fidarsi, i dati per cella per un modello.

## Installare la pagina per un Comune

Serve una macchina con Docker (Linux, 2 GB di RAM, qualche GB di disco) e il
repository:

```bash
git clone https://github.com/agent-engineering-studio/firms-client.git
cd firms-client
cp .env.example .env
```

Nel file `.env` l'ente scrive:

- **il Comune**: `FIRMS_UI_LAT` e `FIRMS_UI_LON` (gradi decimali, il centro
  del territorio), `FIRMS_UI_PLACE` (il nome nell'intestazione),
  `FIRMS_UI_RADIUS_KM` (il raggio dell'area, da 1 a 30 km, 10 se vuoto);
- **la lingua**: `FIRMS_UI_LANG=it` o `en` (chi visita può cambiarla);
- **il MAP_KEY**, se vuole gli ultimi giorni: `FIRMS_MAP_KEY`, oppure un file
  di una riga in `./secrets/map_key`, montato in sola lettura. Senza chiave
  la pagina mostra solo gli archivi annuali e lo dice: gli ultimi giorni sono
  «non misurati», non zero;
- **chi può incorporarla**: `FIRMS_UI_FRAME_ANCESTORS`, per esempio
  `"https://www.comune.esempio.it"`.

Poi:

```bash
docker compose up -d        # la pagina su http://127.0.0.1:3005
docker compose logs -f api  # il primo avvio scarica gli archivi e la copertura del suolo
```

Al primo avvio l'API scarica gli archivi del paese (per l'Italia circa 2 MB
l'anno) e le tessere ESA WorldCover dell'area (circa 60 MB l'una), una volta
sola, nel volume `firms-data`. Agli avvii successivi la pagina risponde
subito.

**Pubblicarla.** Le porte ascoltano solo su 127.0.0.1: davanti serve un proxy
con HTTPS (nginx, Caddy, Traefik) che inoltri a `127.0.0.1:3005`. La pagina
non ha account, né cookie, né moduli: è di sola lettura.

**Incorporarla nel sito del Comune** con un iframe; `embed=1` toglie
l'intestazione, `lat` e `lon` aprono la pagina su un punto e dicono quanto
fidarsi di una rilevazione lì:

```html
<iframe src="https://fuochi.comune.esempio.it/?embed=1&lang=it"
        title="Fuochi visti dal satellite" width="100%" height="640"></iframe>
```

**La mappa di sfondo** è OpenStreetMap, che vede l'indirizzo di chi visita.
Un ente che ha le sue tessere le indica con `FIRMS_UI_TILES` e
`FIRMS_UI_TILES_CREDIT`.

**Aggiornarla**: `git pull && docker compose up -d --build`. I dati restano
nel volume.

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
  cookie. Su disco restano solo gli archivi scaricati, la maschera calcolata e
  le tessere della copertura del suolo. Il proxy davanti alla pagina scrive i
  suoi log di accesso: la loro conservazione è dell'ente.
- **Copertura del suolo.** Dove la pagina dice che cosa è bruciato (campi o
  bosco) usa ESA WorldCover, licenza CC BY 4.0: la pagina ne riporta il
  credito, e lo deve riportare chi ripubblica quei risultati. È una stima dal
  suolo, non la causa dell'incendio.

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
- [x] Installazione con Docker e pagina per il Comune con Bootstrap Italia
- [ ] Segnalazione su `italia/catalogo-software`

## Fonti

- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/), e la sua
  [pagina su Earthdata](https://www.earthdata.nasa.gov/data/tools/firms)
- [Linee guida su acquisizione e riuso di software per le PA](https://docs.italia.it/italia/developers-italia/lg-acquisizione-e-riuso-software-per-pa-docs/)
- [Standard publiccode.yml](https://yml.publiccode.tools/)
