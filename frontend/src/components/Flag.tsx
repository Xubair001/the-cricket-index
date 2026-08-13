/**
 * A side's flag.
 *
 * Drawn from Unicode regional-indicator pairs rather than image assets: 111
 * international sides appear in this dataset, and 111 SVGs is a maintenance
 * surface and a payload for something the text renderer already knows how to
 * draw. It also scales with the type around it, which image sprites do not.
 *
 * England, Scotland and Wales are not ISO countries but are cricketing nations,
 * so they use Unicode subdivision tag sequences instead of the letter pair.
 *
 * A side with no code — every franchise, the invitational XIs, and the West
 * Indies — renders a neutral mark rather than nothing, so a row's leading
 * column stays aligned and the absence reads as deliberate. See
 * `backend/app/flags.py` for why those cases carry no country.
 *
 * Known limitation: Windows renders no emoji flags at all, showing the letter
 * pair instead. That is legible rather than broken, and the alternative costs
 * an asset pipeline for every side in the dataset.
 */

const SUBDIVISION_TAGS: Record<string, string> = {
  // Black flag + tag characters spelling the subdivision + cancel tag.
  'gb-eng': '\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}',
  'gb-sct': '\u{1F3F4}\u{E0067}\u{E0062}\u{E0073}\u{E0063}\u{E0074}\u{E007F}',
  'gb-wls': '\u{1F3F4}\u{E0067}\u{E0062}\u{E0077}\u{E006C}\u{E0073}\u{E007F}',
}

const REGIONAL_INDICATOR_A = 0x1f1e6
const ASCII_A = 65

function toEmoji(code: string): string | null {
  const key = code.toLowerCase()
  if (SUBDIVISION_TAGS[key]) return SUBDIVISION_TAGS[key]
  if (!/^[A-Za-z]{2}$/.test(code)) return null
  return [...code.toUpperCase()]
    .map((c) => String.fromCodePoint(c.charCodeAt(0) - ASCII_A + REGIONAL_INDICATOR_A))
    .join('')
}

export function Flag({
  code,
  name,
  className = '',
}: {
  code: string | null | undefined
  name?: string
  className?: string
}) {
  const emoji = code ? toEmoji(code) : null

  if (!emoji) {
    return (
      <span
        aria-hidden
        title={name ? `${name} represents no single nation` : undefined}
        className={`inline-block w-[1.25em] shrink-0 text-center text-dim ${className}`}
      >
        ·
      </span>
    )
  }

  return (
    <span
      // The flag repeats information the adjacent name already carries, so it
      // is decorative to a screen reader rather than a second announcement.
      aria-hidden
      title={name}
      className={`inline-block w-[1.25em] shrink-0 text-center leading-none ${className}`}
    >
      {emoji}
    </span>
  )
}
