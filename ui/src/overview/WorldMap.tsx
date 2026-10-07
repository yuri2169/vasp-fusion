import { geoNaturalEarth1, geoPath } from 'd3-geo'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import world from 'world-atlas/countries-110m.json'
import { PLACES } from './places'

const W = 960
const H = 480

export type MapPlace = { name: string; share: number; label: string }

const topology = world as unknown as Topology<{ countries: GeometryCollection }>
const countries = (feature(topology, topology.objects.countries) as FeatureCollection<Geometry>).features
const projection = geoNaturalEarth1().fitExtent(
  [
    [8, 8],
    [W - 8, H - 8],
  ],
  { type: 'Sphere' },
)
const path = geoPath(projection)
const OUTLINES = countries.map((f: Feature<Geometry>) => ({ id: String(f.id), d: path(f) ?? '' }))
const SPHERE = path({ type: 'Sphere' }) ?? ''

/** The world, with a labelled dot on every jurisdiction that has money. A country large enough to
 *  see is also shaded; the dot is what makes Singapore or the Seychelles findable at this scale.
 *  Borders are bundled (Natural Earth, 1:110m): nothing is fetched. */
export default function WorldMap({ places, selected, onSelect }: { places: MapPlace[]; selected: string | null; onSelect: (name: string | null) => void }) {
  const drawn = places.flatMap((p) => {
    const at = PLACES[p.name]
    const xy = at ? projection([at.lon, at.lat]) : null
    return at && xy ? [{ ...p, iso: at.iso, x: xy[0], y: xy[1], left: xy[0] > W * 0.82 }] : []
  })
  const shade = new Map(drawn.map((p) => [p.iso, p]))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label="World map of the jurisdictions the traced money reached" className="block h-auto w-full">
      <path d={SPHERE} fill="var(--surface-2)" stroke="var(--rule-soft)" />
      <g aria-hidden="true">
        {OUTLINES.map((c) => {
          const hit = shade.get(c.id)
          return (
            <path
              key={c.id}
              d={c.d}
              fill={hit ? 'var(--fusion)' : 'var(--surface)'}
              fillOpacity={hit ? 0.25 + 0.55 * hit.share : 1}
              stroke="var(--rule)"
              strokeWidth={0.5}
            />
          )
        })}
      </g>
      {drawn.map((p) => {
        const on = selected === p.name
        return (
          <g
            key={p.name}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            aria-label={p.label}
            className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-[3]"
            onClick={() => onSelect(on ? null : p.name)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect(on ? null : p.name)
              }
            }}
          >
            <title>{p.label}</title>
            <circle cx={p.x} cy={p.y} r={5 + 9 * Math.sqrt(p.share)} fill="var(--fusion)" fillOpacity={on ? 0.95 : 0.7} stroke="var(--ink)" strokeWidth={on ? 2.5 : 1} />
            <text
              x={p.x + (p.left ? -1 : 1) * (9 + 9 * Math.sqrt(p.share))}
              y={p.y + 5}
              textAnchor={p.left ? 'end' : 'start'}
              fontSize={15}
              fontWeight={on ? 700 : 600}
              fill="var(--ink)"
              stroke="var(--surface)"
              strokeWidth={4}
              paintOrder="stroke"
            >
              {p.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
