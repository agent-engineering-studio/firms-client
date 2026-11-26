// The answers of demo/api.py. The numbers are firms_client.facts answers: null is
// "not measured", never 0.

export type Area = {
  lat: number;
  lon: number;
  radius_km: number;
  west: number;
  south: number;
  east: number;
  north: number;
};

export type Health = {
  ok: boolean;
  place: string;
  country: string;
  area: Area;
  map_key: boolean;
  nrt_source: string;
  product: string;
  data: {
    state: "waiting" | "downloading" | "ready" | "failed";
    error: string | null;
    years: number[];
    static_mask: boolean;
    land_cover: "off" | "downloading" | "ready" | "failed" | "unavailable";
  };
  attribution: string;
  licence_land_cover: string;
  not_an_alert: string;
};

export type LandVerdict = { kind: string; reason: string };

export type FireEvent = {
  start: string;
  end: string;
  hotspots: number;
  latitude: number;
  longitude: number;
  land?: LandVerdict;
};

export type AreaFacts = {
  answer: "fires_in_area";
  window: { start: string; end: string };
  product: string;
  sources: string[];
  measured: boolean;
  detections: number | null;
  fires: number | null;
  fire_days: number | null;
  events: number | null;
  by_type: Record<string, number> | null;
  largest_events: FireEvent[];
  licence: string[];
  notes: string[];
  not_measured_because?: "no_map_key" | "archive_missing";
};

export type Point = {
  lat: number;
  lon: number;
  date: string;
  frp_mw: number | null;
  type: number | null;
  fire: boolean;
};

export type Fires = { facts: AreaFacts; points: Point[] };

export type Year = { year: number; detections: number; fires: number; fire_days: number };

export type History = { years: Year[] };

export type Trust = {
  answer: "trust_at";
  latitude: number;
  longitude: number;
  measured: boolean;
  reliability: {
    score: number | null;
    reliable: boolean;
    reliable_from: number;
    reasons: string[];
  };
  land_cover: Record<string, number> | null;
  licence: string[];
};

export type Failed = { error: string; status: number };

export const failed = (x: unknown): x is Failed =>
  typeof x === "object" && x !== null && "error" in x && "status" in x;

/** One question to the API, through the page's own address. */
export async function ask<T>(path: string, params: Record<string, string | number>): Promise<T | Failed> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  try {
    const answer = await fetch(`/api/${path}?${query}`, { cache: "no-store" });
    const body = await answer.json();
    return answer.ok ? (body as T) : { error: String(body.error ?? answer.statusText), status: answer.status };
  } catch {
    return { error: "network", status: 0 };
  }
}
