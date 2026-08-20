/**
 * The small set of directional marks this product needs, as SVG.
 *
 * They replace the text arrows that were scattered through the pages as
 * `&rarr;`, `&larr;` and literal glyphs. Three problems with those:
 *
 * - **They render as whatever the reader's font decides.** A text arrow inherits
 *   the body face, so its weight and baseline never match the label beside it,
 *   and at 11px in a monospace label it sat visibly off-centre.
 * - **They are not consistently available.** JSX resolves named entities through
 *   Babel's table, which carries `&rarr;` but not `&nearr;` - that one rendered
 *   as literal text on the page.
 * - **They read as content to a screen reader.** "Back arrow All players"
 *   announces the glyph. These are `aria-hidden`, because in every use the
 *   adjacent text already says where the link goes.
 *
 * Sized in `em` so a mark scales with whatever text it sits in, and stroked with
 * `currentColor` so it takes the colour of its label without a second rule.
 */

type IconProps = {
  className?: string
  /** Multiplier on the surrounding font size. 1 = cap height. */
  size?: number
}

function Svg({
  children,
  className = '',
  size = 1,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={`${size}em`}
      height={`${size}em`}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`inline-block shrink-0 align-[-0.125em] ${className}`}
    >
      {children}
    </svg>
  )
}

/** Forward: "open this", "see all". */
export function ArrowRight(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 8h9.5" />
      <path d="M9 4.5 12.5 8 9 11.5" />
    </Svg>
  )
}

/** Back: a return link to the list this page came from. */
export function ArrowLeft(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13 8H3.5" />
      <path d="M7 4.5 3.5 8 7 11.5" />
    </Svg>
  )
}

/** Leaves the site. Used on external links, where the destination is not ours. */
export function ArrowExternal(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6.5 3.5H12.5V9.5" />
      <path d="M12.5 3.5 4 12" />
    </Svg>
  )
}
