import { useMemo, useState, useCallback, type SyntheticEvent } from 'react';
import { ComposableMap, Geographies, Geography, Marker, type RsmGeography } from 'react-simple-maps';
import { geoCentroid } from 'd3-geo';

const GEO_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';

/** Normalize for matching GeoIP strings to Natural Earth / world-atlas names. */
function norm(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Map: normalized world-atlas geography name → normalized keys that may appear in usage_logs.country.
 */
const GEO_TO_USAGE_KEYS: Record<string, string[]> = {
  'united states of america': ['united states', 'usa', 'us'],
  'united kingdom': ['uk', 'great britain', 'britain', 'england', 'scotland', 'wales', 'northern ireland'],
  russia: ['russian federation'],
  'russian federation': ['russia'],
  'south korea': ['korea republic of', 'republic of korea', 'korea south', 'south korea'],
  'north korea': ['korea democratic peoples republic of', 'north korea', 'korea north'],
  vietnam: ['viet nam'],
  czechia: ['czech republic'],
  'czech republic': ['czechia'],
  'democratic republic of the congo': [
    'congo the democratic republic of the',
    'kinshasa',
    'dr congo',
    'drc',
    'democratic republic of congo',
  ],
  'republic of the congo': ['congo', 'congo brazzaville', 'republic of congo'],
  "cote d ivoire": ['ivory coast', "cote d'ivoire"],
  myanmar: ['burma'],
  'bolivia plurinational state of': ['bolivia'],
  'venezuela bolivarian republic of': ['venezuela'],
  'tanzania united republic of': ['tanzania'],
  'moldova republic of': ['moldova'],
  'north macedonia': ['macedonia'],
  'iran islamic republic of': ['iran'],
  'lao people s democratic republic': ['laos'],
  'syrian arab republic': ['syria'],
  'brunei darussalam': ['brunei'],
  'palestine state of': ['palestine', 'gaza strip', 'west bank'],
  'taiwan province of china': ['taiwan'],
  'hong kong sar': ['hong kong'],
  'macao sar': ['macau', 'macao'],
  eswatini: ['swaziland'],
  'swaziland': ['eswatini'],
  'cabo verde': ['cape verde'],
  'timor leste': ['east timor'],
  'micronesia federated states of': ['micronesia'],
  'sao tome and principe': ['sao tome principe'],
  'saint kitts and nevis': ['st kitts and nevis'],
  'saint lucia': ['st lucia'],
  'saint vincent and the grenadines': ['st vincent and the grenadines'],
  'trinidad and tobago': ['trinidad tobago'],
  'bosnia and herzegovina': ['bosnia herzegovina'],
  'sri lanka': ['sri lanka'],
  'papua new guinea': ['papua new guinea'],
  'solomon islands': ['solomon islands'],
  'equatorial guinea': ['equatorial guinea'],
  'guinea bissau': ['guinea bissau'],
  'burkina faso': ['burkina faso'],
  'central african republic': ['central african republic'],
  'dominican republic': ['dominican republic'],
  'costa rica': ['costa rica'],
  'el salvador': ['el salvador'],
  'new zealand': ['new zealand'],
  'south africa': ['south africa'],
  'south sudan': ['south sudan'],
  'western sahara': ['western sahara'],
  'french guiana': ['french guiana'],
  'french polynesia': ['french polynesia'],
  'new caledonia': ['new caledonia'],
  'puerto rico': ['puerto rico'],
};

function geoDisplayName(geo: RsmGeography): string {
  const p = geo.properties;
  const raw =
    (typeof p.name === 'string' && p.name) ||
    (typeof p.NAME === 'string' && p.NAME) ||
    (typeof p.ADMIN === 'string' && p.ADMIN) ||
    'Unknown';
  return raw;
}

function buildUsageCountMap(rows: { country: string; count: number }[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const r of rows) {
    const k = norm(r.country || 'unknown');
    m.set(k, (m.get(k) ?? 0) + r.count);
  }
  return m;
}

function countForGeography(geo: RsmGeography, usage: Map<string, number>): number {
  const display = geoDisplayName(geo);
  const gn = norm(display);
  const tryKeys = [gn, ...(GEO_TO_USAGE_KEYS[gn] ?? [])];
  for (const k of tryKeys) {
    const c = usage.get(k);
    if (c != null && c > 0) return c;
  }
  return 0;
}

function fillForCount(count: number, max: number): string {
  if (count <= 0 || max <= 0) return 'rgba(39, 39, 42, 0.92)';
  const t = Math.min(1, count / max);
  const alpha = 0.22 + t * 0.78;
  return `rgba(234, 88, 12, ${alpha})`;
}

export interface UsageWorldMapProps {
  byCountry: { country: string; count: number }[];
  totalRequests: number;
}

export default function UsageWorldMap({ byCountry, totalRequests }: UsageWorldMapProps) {
  const [hover, setHover] = useState<{ name: string; count: number; x: number; y: number } | null>(null);

  const usageMap = useMemo(() => buildUsageCountMap(byCountry), [byCountry]);
  const maxCount = useMemo(() => Math.max(...byCountry.map((r) => r.count), 1), [byCountry]);

  const sortedList = useMemo(
    () => [...byCountry].sort((a, b) => b.count - a.count),
    [byCountry],
  );

  const onMove = useCallback((e: SyntheticEvent, name: string, count: number) => {
    const ne = e.nativeEvent as MouseEvent;
    setHover({ name, count, x: ne.clientX, y: ne.clientY });
  }, []);

  if (!byCountry.length) return null;

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
      <div className="relative min-h-[280px] min-w-0 flex-1 overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-[#0c0c0e]">
        <ComposableMap
          projection="geoMercator"
          projectionConfig={{
            scale: 140,
            center: [0, 24],
          }}
          className="h-full w-full max-h-[min(420px,60vh)] [&_.rsm-svg]:h-full [&_.rsm-svg]:w-full"
        >
          <Geographies geography={GEO_URL}>
            {({ geographies }) => {
              const markers: {
                key: string;
                coords: [number, number];
                count: number;
                name: string;
              }[] = [];

              const geos = geographies.filter((g) => {
                const n = norm(geoDisplayName(g));
                return n !== 'antarctica';
              });

              for (const geo of geos) {
                const c = countForGeography(geo, usageMap);
                if (c <= 0) continue;
                try {
                  const ctd = geoCentroid(geo as Parameters<typeof geoCentroid>[0]);
                  if (Array.isArray(ctd) && ctd.length === 2) {
                    markers.push({
                      key: String(geo.rsmKey),
                      coords: [ctd[0], ctd[1]],
                      count: c,
                      name: geoDisplayName(geo),
                    });
                  }
                } catch {
                  /* skip tiny / invalid geometries */
                }
              }

              return (
                <>
                  {geos.map((geo) => {
                    const name = geoDisplayName(geo);
                    const count = countForGeography(geo, usageMap);
                    const fill = fillForCount(count, maxCount);
                    return (
                      <Geography
                        key={geo.rsmKey}
                        geography={geo}
                        tabIndex={-1}
                        className="outline-none"
                        style={{
                          default: {
                            fill,
                            stroke: 'rgba(255,255,255,0.12)',
                            strokeWidth: 0.35,
                            outline: 'none',
                          },
                          hover: {
                            fill: count > 0 ? 'rgba(251, 146, 60, 0.92)' : 'rgba(63, 63, 70, 0.95)',
                            stroke: 'rgba(255,255,255,0.35)',
                            strokeWidth: 0.5,
                            outline: 'none',
                            cursor: count > 0 ? 'pointer' : 'default',
                          },
                          pressed: { outline: 'none' },
                        }}
                        onMouseEnter={(e: SyntheticEvent) => onMove(e, name, count)}
                        onMouseMove={(e: SyntheticEvent) => onMove(e, name, count)}
                        onMouseLeave={() => setHover(null)}
                      />
                    );
                  })}
                  {markers.map((m) => (
                    <Marker key={m.key} coordinates={m.coords}>
                      <circle
                        r={Math.min(10, 4 + (m.count / maxCount) * 6)}
                        fill="rgba(251, 191, 36, 0.95)"
                        stroke="rgba(0,0,0,0.45)"
                        strokeWidth={0.75}
                        className="pointer-events-none"
                      />
                    </Marker>
                  ))}
                </>
              );
            }}
          </Geographies>
        </ComposableMap>

        {hover && hover.count > 0 && (
          <div
            className="pointer-events-none fixed z-[200] max-w-xs rounded-lg border border-gray-200 dark:border-white/15 bg-white/95 dark:bg-zinc-950/95 px-3 py-2 text-xs shadow-xl ring-1 ring-black/10 dark:ring-black/40"
            style={{ left: hover.x + 12, top: hover.y + 12 }}
          >
            <p className="font-semibold text-gray-900 dark:text-white">{hover.name}</p>
            <p className="mt-0.5 tabular-nums text-orange-700 dark:text-orange-200">
              {hover.count.toLocaleString()} requests
              {totalRequests > 0 && (
                <span className="text-zinc-500">
                  {' '}
                  · {Math.round((hover.count / totalRequests) * 1000) / 10}% of total
                </span>
              )}
            </p>
          </div>
        )}

        <div className="pointer-events-none absolute bottom-3 left-3 flex max-w-[min(100%,280px)] flex-col gap-1 rounded-lg border border-gray-200 dark:border-white/[0.08] bg-white/80 dark:bg-black/50 px-3 py-2 text-[10px] text-gray-600 dark:text-zinc-400 backdrop-blur-sm">
          <span className="font-semibold uppercase tracking-wide text-zinc-500">Intensity</span>
          <div className="h-2 w-full rounded-full bg-gradient-to-r from-zinc-800 via-orange-900/80 to-orange-500" />
          <div className="flex justify-between tabular-nums">
            <span>None</span>
            <span>Peak · {maxCount.toLocaleString()}</span>
          </div>
        </div>
      </div>

      <div className="flex w-full shrink-0 flex-col rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-black/25 p-4 lg:w-56 xl:w-64">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">By country</p>
        <p className="mt-1 text-[11px] leading-snug text-zinc-600">
          Matches IP-derived country names to the map. Hover regions for detail.
        </p>
        <ul className="mt-3 max-h-[min(360px,50vh)] space-y-2 overflow-y-auto pr-1">
          {sortedList.map((row, idx) => {
            const pct =
              totalRequests > 0 ? Math.round((row.count / totalRequests) * 1000) / 10 : 0;
            return (
              <li
                key={`${idx}-${norm(row.country)}`}
                className="flex items-baseline justify-between gap-2 border-b border-gray-200 dark:border-white/[0.04] pb-2 text-xs last:border-0"
              >
                <span className="min-w-0 truncate text-zinc-300" title={row.country}>
                  {row.country || 'Unknown'}
                </span>
                <span className="shrink-0 tabular-nums text-zinc-500">
                  {row.count.toLocaleString()}
                  <span className="text-zinc-600"> ({pct}%)</span>
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
