import { useState } from 'react'

/**
 * Player photo from Wikimedia Commons.
 *
 * Renders nothing at all when there's no image, and removes itself if the
 * fetch fails (Commons rate-limits bursts with 429). A missing photo is a
 * missing photo - no silhouette placeholder, for the same reason the bio
 * fields say "Not available" rather than inventing a value.
 */
export function PlayerAvatar({
  src,
  alt,
  className = 'h-20 w-20',
}: {
  src: string | null
  alt: string
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) return null
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      referrerPolicy="no-referrer"
      className={`${className} shrink-0 rounded-full object-cover ring-1 ring-border-default`}
    />
  )
}
