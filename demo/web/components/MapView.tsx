"use client";

import L from "leaflet";
import { useEffect, useRef } from "react";
import { COLOURS } from "@/lib/colours";
import { MAX_ZOOM, MIN_ZOOM, type Start, type Tiles } from "@/lib/start";
import type { Area, Point } from "@/lib/types";

type Props = {
  start: Start;
  tiles: Tiles;
  area: Area | null;
  season: Point[];
  recent: Point[];
  /** The point asked about, with its marker. */
  asked: { lat: number; lon: number } | null;
  onPoint: (lat: number, lon: number) => void;
};


const style = (p: Point, recent: boolean): L.CircleMarkerOptions => ({
  radius: recent ? 6 : 4,
  color: "#fff",
  weight: 1,
  fillColor: p.fire ? (recent ? COLOURS.recent : COLOURS.season) : COLOURS.other,
  fillOpacity: 0.9,
});

export default function MapView(props: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const frame = useRef<L.LayerGroup | null>(null);
  const dots = useRef<L.LayerGroup | null>(null);
  const marker = useRef<L.CircleMarker | null>(null);
  const handlers = useRef(props);
  useEffect(() => {
    handlers.current = props;
  });

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = L.map(box.current, { minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM, zoomControl: true }).setView(
      [props.start.lat, props.start.lon],
      props.start.zoom,
    );
    L.tileLayer(props.tiles.url, { attribution: props.tiles.attribution, maxZoom: MAX_ZOOM }).addTo(m);
    m.attributionControl.setPrefix(false);
    frame.current = L.layerGroup().addTo(m);
    dots.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => handlers.current.onPoint(e.latlng.lat, e.latlng.lng));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // The map is made once; what changes is drawn by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const m = map.current;
    const a = props.area;
    if (!m || !a || !frame.current) return;
    frame.current.clearLayers();
    const bounds = L.latLngBounds([a.south, a.west], [a.north, a.east]);
    L.rectangle(bounds, { color: "#0066cc", weight: 2, fill: false, dashArray: "6 4" }).addTo(frame.current);
    if (!props.start.given) m.fitBounds(bounds, { padding: [16, 16] });
  }, [props.area, props.start.given]);

  useEffect(() => {
    if (!dots.current) return;
    dots.current.clearLayers();
    for (const p of props.season) L.circleMarker([p.lat, p.lon], style(p, false)).addTo(dots.current);
    for (const p of props.recent) L.circleMarker([p.lat, p.lon], style(p, true)).addTo(dots.current);
  }, [props.season, props.recent]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    marker.current?.remove();
    marker.current = null;
    if (props.asked) {
      marker.current = L.circleMarker([props.asked.lat, props.asked.lon], {
        radius: 9,
        color: "#0066cc",
        weight: 3,
        fill: false,
      }).addTo(m);
    }
  }, [props.asked]);

  return <div ref={box} className="firms-map" />;
}
