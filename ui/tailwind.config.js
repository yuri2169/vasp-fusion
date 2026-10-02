/** Every colour maps to a role token in src/styles/tokens.css, so the theme lives in
 *  one place and no component hard-codes a hex. See ui/DESIGN.md. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      // surfaces
      page: 'var(--bg)',
      surface: 'var(--surface)',
      sunk: 'var(--surface-sunk)',
      rule: 'var(--rule)',
      'rule-strong': 'var(--rule-strong)',
      // text
      fg: 'var(--fg)',
      muted: 'var(--fg-muted)',
      focus: 'var(--focus)',
      // nav rail (ink in both themes)
      rail: {
        DEFAULT: 'var(--rail-bg)',
        fg: 'var(--rail-fg)',
        muted: 'var(--rail-fg-muted)',
        rule: 'var(--rail-rule)',
        active: 'var(--rail-active)',
        focus: 'var(--rail-focus)',
      },
      // accents: DEFAULT is the brand fill, `on` the text on that fill,
      // `text` the accent as text on a surface, `wash` its tinted background
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
      ink: 'var(--ink)',
      paper: 'var(--paper)',
    },
    fontFamily: {
      display: ['"Bricolage Grotesque Variable"', '"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
      mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
    },
    // The brief's scale: 12 / 14 / 16 / 20 / 28 / 40. Nothing in between.
    fontSize: {
      xs: ['12px', '16px'],
      sm: ['14px', '20px'],
      base: ['16px', '24px'],
      lg: ['20px', '26px'],
      xl: ['28px', '32px'],
      '2xl': ['40px', '42px'],
    },
    borderRadius: { none: '0', sm: '2px', DEFAULT: '4px', md: '6px', full: '9999px' },
    extend: {
      spacing: { 4.5: '18px', 13: '52px', 15: '60px', rail: '224px' },
      maxWidth: { content: '1240px' },
      screens: { wide: '1440px' },
    },
  },
  plugins: [],
}
