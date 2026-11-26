"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { COLOURS } from "@/lib/colours";
import { count, TEXT, type Text } from "@/lib/i18n";
import type { Start, Tiles } from "@/lib/start";
import { ask, failed, type AreaFacts, type Fires as FireAnswer, type Health, type History, type Trust } from "@/lib/types";

// Leaflet needs the window: the map is drawn in the browser only.
const MapView = dynamic(() => import("./MapView"), { ssr: false });

const POLL_MS = 2000;
const DAYS = 7;

function Counts({ t, facts }: { t: Text; facts: AreaFacts }) {
  if (!facts.measured) {
    return (
      <p className="firms-muted">
        {facts.not_measured_because === "no_map_key"
          ? t.noKey
          : facts.not_measured_because === "archive_missing"
            ? t.archiveMissing
            : t.notMeasured}
      </p>
    );
  }
  return (
    <>
      <dl className="firms-counts">
        <div>
          <dt>{count(t, facts.fire_days)}</dt>
          <dd>{t.fireDays}</dd>
        </div>
        <div>
          <dt>{count(t, facts.events)}</dt>
          <dd>{t.events}</dd>
        </div>
        <div>
          <dt>{count(t, facts.detections)}</dt>
          <dd>
            {t.detections}, {count(t, facts.fires)} {t.fires}
          </dd>
        </div>
      </dl>
      {facts.by_type && Object.values(facts.by_type).some((n) => n > 0) && (
        <p className="firms-small">
          {t.byType}:{" "}
          {Object.entries(facts.by_type)
            .filter(([, n]) => n > 0)
            .map(([k, n]) => `${t.types[k] ?? k} ${n.toLocaleString(t.locale)}`)
            .join(" · ")}
        </p>
      )}
      {facts.largest_events.length > 0 && (
        <>
          <h3 className="firms-h3">{t.largest}</h3>
          <ul className="firms-events">
            {facts.largest_events.map((e) => (
              <li key={`${e.start}-${e.latitude}-${e.longitude}`}>
                {e.start === e.end ? e.start : `${e.start} → ${e.end}`}: {t.hotspots(e.hotspots)}
                {e.land && <> · {t.land[e.land.kind] ?? e.land.kind}</>}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function Years({ t, history, year, onYear }: { t: Text; history: History; year: number | null; onYear: (y: number) => void }) {
  const top = Math.max(1, ...history.years.map((y) => y.fire_days));
  return (
    <>
      <ul className="firms-years" aria-label={t.historyTitle}>
        {history.years.map((y) => (
          <li key={y.year}>
            <button
              type="button"
              className={y.year === year ? "active" : ""}
              onClick={() => onYear(y.year)}
              title={`${y.year}: ${y.fire_days} ${t.fireDays}`}
            >
              <span className="bar" style={{ height: `${(100 * y.fire_days) / top}%` }} />
              <span className="label">{String(y.year).slice(2)}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="firms-small firms-muted">{t.historyNote}</p>
    </>
  );
}

function TrustCard({ t, trust }: { t: Text; trust: Trust | string | null }) {
  if (trust === null) return <p className="firms-small">{t.trustHint}</p>;
  if (typeof trust === "string") return <p className="firms-small">{trust}</p>;
  const r = trust.reliability;
  return (
    <>
      <p>
        <strong>{r.score === null ? t.notMeasured : t.trustScore(r.score.toLocaleString(t.locale))}</strong>
        {r.score !== null && <> · {r.reliable ? t.reliable : t.unreliable}</>}
      </p>
      {r.reasons.length > 0 && (
        <ul className="firms-small">
          {r.reasons.map((why) => (
            <li key={why}>{why}</li>
          ))}
        </ul>
      )}
      {trust.land_cover && (
        <p className="firms-small">
          {t.landCover}:{" "}
          {Object.entries(trust.land_cover)
            .map(([k, v]) => `${k} ${Math.round(100 * v)}%`)
            .join(" · ")}
        </p>
      )}
    </>
  );
}

export default function Fires({ start, tiles }: { start: Start; tiles: Tiles }) {
  const [lang, setLang] = useState(start.lang);
  const t = TEXT[lang];
  const [health, setHealth] = useState<Health | null>(null);
  const [silent, setSilent] = useState(false);
  const [recent, setRecent] = useState<FireAnswer | null>(null);
  const [season, setSeason] = useState<FireAnswer | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [asked, setAsked] = useState<{ lat: number; lon: number } | null>(start.given ? { lat: start.lat, lon: start.lon } : null);
  const [trust, setTrust] = useState<Trust | string | null>(null);
  const ready = health?.data.state === "ready";

  // Until the archives are on the server, ask how far it is.
  useEffect(() => {
    if (ready) return;
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      const h = await ask<Health>("health", {});
      if (!live) return;
      setSilent(failed(h));
      if (!failed(h)) {
        setHealth(h);
        if (h.data.state === "ready" || h.data.state === "failed") return;
      }
      timer = window.setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [ready]);

  const up = health !== null;
  useEffect(() => {
    if (!up) return;
    ask<FireAnswer>("recent", { days: DAYS }).then((a) => setRecent(failed(a) ? null : a));
  }, [up]);

  useEffect(() => {
    if (!ready) return;
    ask<History>("history", {}).then((h) => {
      if (failed(h)) return;
      setHistory(h);
      const last = h.years.at(-1)?.year;
      if (last !== undefined) setYear((y) => y ?? last);
    });
  }, [ready]);

  useEffect(() => {
    if (!ready || year === null) return;
    ask<FireAnswer>("season", { year }).then((a) => setSeason(failed(a) ? null : a));
  }, [ready, year]);

  const askTrust = useCallback(
    async (lat: number, lon: number) => {
      setAsked({ lat, lon });
      const a = await ask<Trust>("trust", { lat: lat.toFixed(5), lon: lon.toFixed(5) });
      setTrust(failed(a) ? (a.status === 404 ? t.outside : a.error) : a);
    },
    [t.outside],
  );

  useEffect(() => {
    if (ready && start.given) askTrust(start.lat, start.lon);
  }, [ready, start, askTrust]);

  const place = start.place || health?.place || "";
  const landUsed = [recent, season].some((a) => a?.facts.licence.length === 2);

  return (
    <div className={`firms ${start.embed ? "embed" : ""}`}>
      {!start.embed && (
        <header className="firms-header">
          <div>
            <div className="firms-title">{place ? `${place} · ${t.title}` : t.title}</div>
            <div className="firms-tagline">{t.tagline}</div>
          </div>
          <button type="button" className="firms-lang" onClick={() => setLang(t.langCode)} lang={t.langCode}>
            {t.lang}
          </button>
        </header>
      )}
      <div role="alert" className="firms-not-alert">
        {t.notAlert}
      </div>
      <main className="firms-main">
        <div className="firms-map-wrap">
          <MapView
            start={start}
            tiles={tiles}
            area={health?.area ?? null}
            season={season?.points ?? []}
            recent={recent?.points ?? []}
            asked={asked}
            onPoint={askTrust}
          />
          <div className="firms-legend firms-small">
            <span style={{ background: COLOURS.recent }} /> {t.legendRecent}
            <span style={{ background: COLOURS.season }} /> {t.legendSeason}
            <span style={{ background: COLOURS.other }} /> {t.legendStatic}
          </div>
        </div>
        <aside className="firms-panel">
          {silent && <p className="firms-warning">{t.noApi}</p>}
          {health && <p className="firms-place">{t.area(health.area.radius_km)}</p>}
          {health?.data.state === "failed" && <p className="firms-warning">{t.failedData(health.data.error ?? "")}</p>}
          {health && !ready && health.data.state !== "failed" && <p className="firms-warning">{t.preparing}</p>}

          <section>
            <h2 className="firms-h2">{t.recentTitle(DAYS)}</h2>
            {recent ? <Counts t={t} facts={recent.facts} /> : health && !health.map_key && <p>{t.noKey}</p>}
          </section>

          {ready && year !== null && (
            <section>
              <h2 className="firms-h2">{t.seasonTitle(year)}</h2>
              {season && <Counts t={t} facts={season.facts} />}
              {history && history.years.length > 1 && (
                <>
                  <h3 className="firms-h3">{t.historyTitle}</h3>
                  <Years t={t} history={history} year={year} onYear={setYear} />
                </>
              )}
            </section>
          )}

          <section>
            <h2 className="firms-h2">{t.trustTitle}</h2>
            <TrustCard t={t} trust={trust} />
          </section>

          <p className="firms-small firms-muted">{t.presence}</p>
          <details className="firms-small">
            <summary>{t.sources}</summary>
            <p>{health?.attribution}</p>
            {(landUsed || (trust !== null && typeof trust !== "string" && trust.licence.length === 2)) && (
              <p>{health?.licence_land_cover}</p>
            )}
            <p>
              <a href="https://firms.modaps.eosdis.nasa.gov/">NASA FIRMS</a> ·{" "}
              <a href="https://github.com/agent-engineering-studio/firms-client">firms-client</a>
            </p>
          </details>
        </aside>
      </main>
    </div>
  );
}
