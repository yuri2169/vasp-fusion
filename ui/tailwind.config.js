/** Every colour maps to a token in src/styles/tokens.css, so the layer semantics live in one
 *  place and no component hard-codes a hex. The theme is BTC-FUSION's (its
 *  ui/tailwind.config.js): the same names mean the same thing in both products.
 *  See ui/DESIGN.md. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',

      // --- the BTC-FUSION palette
      paper: 'var(--paper)',
      surface: 'var(--surface)',
      'surface-2': 'var(--surface-2)',
      'surface-3': 'var(--surface-3)',
      ink: 'var(--ink)',
      'ink-soft': 'var(--ink-soft)',
      'ink-dim': 'var(--ink-dim)',
      rule: 'var(--rule)',
      'rule-soft': 'var(--rule-soft)',
      chain: 'var(--chain)',
      network: 'var(--network)',
      fusion: 'var(--fusion)',
      confirm: 'var(--confirm)',
      data: 'var(--data)',
      danger: 'var(--danger)',
      'chain-wash': 'var(--chain-wash)',
      'network-wash': 'var(--network-wash)',
      'fusion-wash': 'var(--fusion-wash)',
      'confirm-wash': 'var(--confirm-wash)',
      'danger-wash': 'var(--danger-wash)',
      chrome: 'var(--chrome)',
      active: 'var(--active)',
      'active-wash': 'var(--active-wash)',

      // --- the role names U1 to U5 components ask for; each is an alias (tokens.css, "aliases")
      page: 'var(--bg)',
      sunk: 'var(--surface-sunk)',
      'rule-strong': 'var(--rule-strong)',
      fg: 'var(--fg)',
      muted: 'var(--fg-muted)',
      focus: 'var(--focus)',
      // DEFAULT is the fill, `on` the text on that fill, `text` the colour as text, `wash` its ground
      saffron: {
        DEFAULT: 'var(--saffron)',
        on: 'var(--on-saffron)',
        text: 'var(--saffron-text)',
        wash: 'var(--saffron-wash)',
      },
      verified: {
        DEFAULT: 'var(--verified)',
        on: 'var(--on-verified)',
        text: 'var(--verified-text)',
        wash: 'var(--verified-wash)',
      },
      seal: {
        DEFAULT: 'var(--seal)',
        on: 'var(--on-seal)',
        text: 'var(--seal-text)',
        wash: 'var(--seal-wash)',
      },
      slate: {
        DEFAULT: 'var(--slate)',
        wash: 'var(--slate-wash)',
      },
    },
    fontFamily: {
      sans: ['"Public Sans"', 'system-ui', 'sans-serif'],
      cond: ['Archivo', 'system-ui', 'sans-serif'],
      display: ['Archivo', 'system-ui', 'sans-serif'],
      mono: ['"Spline Sans Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
    },
    // Seven sizes with real steps between them, as in BTC-FUSION. Nothing in between.
    fontSize: {
      '2xs': ['11px', '15px'], // metadata: colheads, tags, receipts
      sm: ['12px', '17px'], // dense values, hints and control labels
      base: ['13px', '19px'], // the body default
      md: ['16px', '23px'], // prose meant to be read
      lg: ['18px', '25px'], // sub-headings
      '2xl': ['24px', '28px'],
      '3xl': ['34px', '36px'],
    },
    // Radius 0 to 2px. Nothing is a floating rounded card. `full` is for dots only.
    borderRadius: { none: '0', sm: '1px', DEFAULT: '2px', md: '2px', full: '9999px' },
    // Depth comes from hairlines and background steps, never from a shadow.
    boxShadow: { none: 'none' },
    extend: {
      spacing: { 4.5: '18px', 13: '52px', 15: '60px' },
      maxWidth: { content: '1320px' },
      screens: { wide: '1440px' },
    },
  },
  plugins: [],
}
