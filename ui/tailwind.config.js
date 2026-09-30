/** Tokens map straight to the CSS custom properties in index.css, so the layer
 *  semantics live in exactly one place and never get re-hardcoded in a component. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: 'var(--paper)', surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)', 'surface-3': 'var(--surface-3)',
        ink: 'var(--ink)', 'ink-soft': 'var(--ink-soft)', 'ink-dim': 'var(--ink-dim)',
        rule: 'var(--rule)', 'rule-soft': 'var(--rule-soft)',
        chain: 'var(--chain)', network: 'var(--network)', fusion: 'var(--fusion)',
        confirm: 'var(--confirm)', data: 'var(--data)', danger: 'var(--danger)',
        'chain-wash': 'var(--chain-wash)', 'network-wash': 'var(--network-wash)',
        'fusion-wash': 'var(--fusion-wash)', 'confirm-wash': 'var(--confirm-wash)',
        'danger-wash': 'var(--danger-wash)',
        chrome: 'var(--chrome)',
        active: 'var(--active)', 'active-wash': 'var(--active-wash)',
      },
      fontFamily: {
        sans: ['Public Sans', 'system-ui', 'sans-serif'],
        cond: ['Archivo', 'system-ui', 'sans-serif'],
        mono: ['Spline Sans Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      /* SIX SIZES, WITH REAL STEPS BETWEEN THEM.
         Ten were declared and 78% of every use landed on the two smallest, so
         hierarchy was carried almost entirely by weight and colour - the mirror
         image of the mono monoculture this interface already fixed once. `xs`
         (11.5) sat inside 2px of both its neighbours; `xl` had two uses and
         `4xl` had one. Gone. `md` and `lg` were widened so prose and
         sub-headings are separated by something a reader can actually see. */
      fontSize: {
        '2xs': ['11px', '15px'],     // metadata: colheads, tags, receipts
        sm:    ['12px', '17px'],     // dense values and control labels
        base:  ['13px', '19px'],     // the body default
        md:    ['16px', '23px'],     // prose meant to be read
        lg:    ['18px', '25px'],     // sub-headings
        '2xl': ['24px', '28px'],
        '3xl': ['34px', '36px'],
      },
      borderRadius: { DEFAULT: '2px', none: '0', sm: '1px', md: '2px' },
      spacing: { '0.5': '2px', '1.5': '6px', '2.5': '10px', '3.5': '14px', '4.5': '18px' },
    },
  },
  plugins: [],
}
