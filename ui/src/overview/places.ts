/** Where to draw a jurisdiction: its ISO 3166-1 numeric code (the id of its outline in the bundled
 *  borders) and one point inside it. Only geography: which exchange belongs to which jurisdiction
 *  comes from the cited directory, never from here. A jurisdiction missing from this table is still
 *  listed under the map; it is just not drawn. */
export const PLACES: Record<string, { iso: string; lon: number; lat: number }> = {
  India: { iso: '356', lon: 78.96, lat: 22.59 },
  Singapore: { iso: '702', lon: 103.82, lat: 1.35 },
  'Hong Kong': { iso: '344', lon: 114.17, lat: 22.32 },
  Seychelles: { iso: '690', lon: 55.45, lat: -4.68 },
  'British Virgin Islands': { iso: '092', lon: -64.62, lat: 18.42 },
  'Cayman Islands': { iso: '136', lon: -81.25, lat: 19.31 },
  Panama: { iso: '591', lon: -80.1, lat: 8.54 },
}
