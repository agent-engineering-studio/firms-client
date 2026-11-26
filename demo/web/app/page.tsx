import Fires from "@/components/Fires";
import { startFrom, tilesFrom } from "@/lib/start";

type Params = Promise<Record<string, string | string[] | undefined>>;

// Read when the page is asked for, not when it is built: one image, any Comune.
export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Params }) {
  const asked = await searchParams;
  const one = (name: string) => {
    const value = asked[name];
    return Array.isArray(value) ? value[0] : value;
  };
  const env = process.env;
  const start = startFrom(
    { lat: one("lat"), lon: one("lon"), zoom: one("zoom"), place: one("place"), lang: one("lang"), embed: one("embed") },
    { lat: env.FIRMS_UI_LAT, lon: env.FIRMS_UI_LON, zoom: env.FIRMS_UI_ZOOM, place: env.FIRMS_UI_PLACE, lang: env.FIRMS_UI_LANG },
  );
  return <Fires start={start} tiles={tilesFrom(env.FIRMS_UI_TILES, env.FIRMS_UI_TILES_CREDIT)} />;
}
