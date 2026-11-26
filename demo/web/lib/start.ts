// Where the page opens, and in which language. A Comune that puts this page on its site
// gives its place in the environment (FIRMS_UI_*) or in the address of the page
// (?lat=&lon=&place=&zoom=&lang=&embed=1). The address wins, one source at a time, so a
// name never goes with the coordinates of another. The data are always those of the
// area of the API (FIRMS_UI_LAT, FIRMS_UI_LON, FIRMS_UI_RADIUS_KM): a point given in the
// address is where the page asks how far to trust a detection.

export type Lang = "it" | "en";

export type Start = {
  lat: number;
  lon: number;
  zoom: number;
  /** The name to show, such as "Comune di Palermo". */
  place: string | null;
  /** True when the coordinates were given: the page asks how far to trust a detection there. */
  given: boolean;
  lang: Lang;
  /** In an iframe: no header and no footer. */
  embed: boolean;
};

export type Asked = {
  lat?: string;
  lon?: string;
  zoom?: string;
  place?: string;
  lang?: string;
  embed?: string;
};

// Palermo: the fires of July 2023 reached the town.
const DEFAULT = { lat: 38.1157, lon: 13.3615 };
const DEFAULT_ZOOM = 11;
export const MIN_ZOOM = 5;
export const MAX_ZOOM = 16;

const number = (text: string | undefined) => {
  const value = text?.trim() ? Number(text.replace(",", ".")) : NaN;
  return Number.isFinite(value) ? value : null;
};

const valid = (lat: number | null, lon: number | null): lat is number =>
  lat !== null && lon !== null && lat >= -60 && lat <= 80 && lon >= -180 && lon <= 180;

const langOf = (sources: Asked[]): Lang =>
  sources.map((s) => s.lang?.trim().toLowerCase()).find((l) => l === "it" || l === "en") === "en" ? "en" : "it";

/** The start from what was asked: the first source with valid coordinates. */
export function startFrom(...sources: Asked[]): Start {
  const lang = langOf(sources);
  const embed = sources.some((s) => ["1", "true", "yes"].includes(s.embed?.trim().toLowerCase() ?? ""));
  for (const [i, asked] of sources.entries()) {
    const lat = number(asked.lat);
    const lon = number(asked.lon);
    if (!valid(lat, lon)) continue;
    const zoom = number(asked.zoom) ?? DEFAULT_ZOOM;
    return {
      lat,
      lon: lon as number,
      zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)),
      place: asked.place?.trim().slice(0, 80) || null,
      // Only a point in the address is a question; the environment is the Comune itself.
      given: i === 0,
      lang,
      embed,
    };
  }
  const place = sources.map((s) => s.place?.trim()).find((p) => p) ?? null;
  return { ...DEFAULT, zoom: DEFAULT_ZOOM, place: place?.slice(0, 80) ?? null, given: false, lang, embed };
}

export type Tiles = { url: string; attribution: string };

/** The background map: OpenStreetMap, or the tiles of whoever hosts the page. */
export const tilesFrom = (url: string | undefined, attribution: string | undefined): Tiles => ({
  url: url?.trim() || "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution:
    attribution?.trim() ||
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
});
