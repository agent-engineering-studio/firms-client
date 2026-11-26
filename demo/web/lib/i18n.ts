// The words of the page, in Italian and in English. The numbers come from the API
// (firms_client.facts); here are only the words around them.

import type { Lang } from "./start";

const it = {
  locale: "it-IT",
  title: "Fuochi visti dal satellite",
  tagline: "Che cosa hanno visto i satelliti della NASA, quanto fidarsi, e dove non guardano",
  notAlert:
    "Non è un'allerta. Un punto sulla mappa è un pixel caldo visto dallo spazio, non un incendio confermato. Per il pericolo valgono la Protezione Civile e i Vigili del Fuoco.",
  presence:
    "FIRMS dice dove ha visto calore, non dove non c'è fuoco: nuvole, fumo e l'ora del passaggio nascondono gli incendi. Nessun punto non vuol dire nessun incendio.",
  preparing: "Preparo i dati: scarico gli archivi FIRMS del paese (circa 2 MB l'anno, una volta sola).",
  failedData: (error: string) => `Gli archivi non sono stati letti: ${error}`,
  noApi: "Il server dei dati non risponde ancora: riprovo.",
  area: (km: number) => `Area: ${km} km intorno al Comune`,
  recentTitle: (days: number) => `Ultimi ${days} giorni`,
  noKey:
    "Senza una chiave MAP_KEY della NASA la pagina mostra solo gli archivi annuali: gli ultimi giorni non sono misurati.",
  seasonTitle: (year: number) => `Stagione ${year}`,
  historyTitle: "Anno per anno",
  historyNote: "Giorni con almeno un incendio nell'area, archivio VIIRS S-NPP.",
  detections: "rilevazioni",
  fires: "di incendi di vegetazione",
  fireDays: "giorni con incendi",
  events: "incendi distinti (eventi)",
  notMeasured: "non misurato",
  archiveMissing: "L'archivio di quell'anno non è ancora pubblicato: non misurato.",
  byType: "Che cosa era caldo",
  types: {
    vegetation_fire: "vegetazione",
    active_volcano: "vulcano",
    static_land_source: "fonte fissa (industria)",
    offshore: "in mare",
    unknown: "senza tipo",
  } as Record<string, string>,
  largest: "Gli incendi più grandi",
  hotspots: (n: number) => (n === 1 ? "1 rilevazione" : `${n} rilevazioni`),
  land: {
    wildfire: "bosco o macchia",
    crop_burning: "campi (bruciatura agricola)",
    cropland_fire: "incendio su campi",
    mixed: "campi e vegetazione naturale",
    other: "altro",
    unknown: "non si sa",
  } as Record<string, string>,
  trustTitle: "Quanto fidarsi qui",
  trustHint: "Clicca un punto dell'area: la pagina dice quanto una rilevazione lì è un incendio di vegetazione.",
  trustScore: (s: string) => `Affidabilità ${s}`,
  reliable: "una rilevazione qui è probabilmente un incendio di vegetazione",
  unreliable: "una rilevazione qui va letta con cautela",
  landCover: "Copertura del suolo intorno",
  outside: "Fuori dall'area della pagina: qui non si legge niente.",
  year: "Anno",
  legendRecent: "ultimi giorni",
  legendSeason: "stagione",
  legendStatic: "non incendio",
  sources: "Fonti e licenze",
  lang: "English",
  langCode: "en" as Lang,
};

type Text = typeof it;

const en: Text = {
  locale: "en-GB",
  title: "Fires seen from space",
  tagline: "What NASA's satellites saw, how far to trust it, and where they do not look",
  notAlert:
    "Not an alert. A point on the map is a hot pixel seen from space, not a confirmed fire. For danger, follow Civil Protection and the fire brigade.",
  presence:
    "FIRMS says where it saw heat, not where there is no fire: clouds, smoke and the time of the overpass hide fires. No point does not mean no fire.",
  preparing: "Preparing the data: downloading the FIRMS archives of the country (about 2 MB a year, once).",
  failedData: (error: string) => `The archives could not be read: ${error}`,
  noApi: "The data server does not answer yet: trying again.",
  area: (km: number) => `Area: ${km} km around the Comune`,
  recentTitle: (days: number) => `Last ${days} days`,
  noKey: "Without a NASA MAP_KEY the page shows the yearly archives only: the last days are not measured.",
  seasonTitle: (year: number) => `Season ${year}`,
  historyTitle: "Year by year",
  historyNote: "Days with at least one fire in the area, VIIRS S-NPP archive.",
  detections: "detections",
  fires: "of vegetation fires",
  fireDays: "days with fires",
  events: "separate fires (events)",
  notMeasured: "not measured",
  archiveMissing: "The archive of that year is not published yet: not measured.",
  byType: "What was hot",
  types: {
    vegetation_fire: "vegetation",
    active_volcano: "volcano",
    static_land_source: "static source (industry)",
    offshore: "offshore",
    unknown: "no type",
  },
  largest: "The largest fires",
  hotspots: (n: number) => (n === 1 ? "1 detection" : `${n} detections`),
  land: {
    wildfire: "forest or scrub",
    crop_burning: "fields (crop burning)",
    cropland_fire: "fire on fields",
    mixed: "fields and natural vegetation",
    other: "other",
    unknown: "unknown",
  },
  trustTitle: "How far to trust it here",
  trustHint: "Click a point of the area: the page says how far a detection there is a vegetation fire.",
  trustScore: (s: string) => `Reliability ${s}`,
  reliable: "a detection here is probably a vegetation fire",
  unreliable: "read a detection here with care",
  landCover: "Land cover around",
  outside: "Outside the area of the page: nothing is read here.",
  year: "Year",
  legendRecent: "last days",
  legendSeason: "season",
  legendStatic: "not a fire",
  sources: "Sources and licences",
  lang: "Italiano",
  langCode: "it",
};

export type { Text };
export const TEXT: Record<Lang, Text> = { it, en };

/** A count, or "not measured": null is never written as 0. */
export const count = (t: Text, n: number | null | undefined) =>
  n === null || n === undefined ? t.notMeasured : n.toLocaleString(t.locale);
