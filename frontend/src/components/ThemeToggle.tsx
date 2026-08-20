import type { ReactNode } from 'react'
import { useTheme, type ThemePreference } from '../theme/useTheme'

/**
 * Theme control - a three-way segmented control, not a switch.
 *
 * A two-state switch cannot express "follow my machine", so the moment anyone
 * touches it they are opted out of their OS setting permanently. The third
 * option is the default and is labelled with what it currently resolves to,
 * so "System" is never an unknown.
 */

const OPTIONS: { value: ThemePreference; label: string; icon: ReactNode }[] = [
  {
    value: 'system',
    label: 'System',
    icon: (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden className="h-3.5 w-3.5">
        <rect
          x="1.75"
          y="2.75"
          width="12.5"
          height="8.5"
          rx="1.25"
          stroke="currentColor"
          strokeWidth="1.3"
        />
        <path d="M5.5 13.75h5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    value: 'light',
    label: 'Light',
    icon: (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden className="h-3.5 w-3.5">
        <circle cx="8" cy="8" r="3.1" stroke="currentColor" strokeWidth="1.3" />
        <path
          d="M8 1.4v1.6M8 13v1.6M14.6 8H13M3 8H1.4M12.66 3.34l-1.13 1.13M4.47 11.53l-1.13 1.13M12.66 12.66l-1.13-1.13M4.47 4.47L3.34 3.34"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    value: 'dark',
    label: 'Dark',
    icon: (
      <svg viewBox="0 0 16 16" fill="none" aria-hidden className="h-3.5 w-3.5">
        <path
          d="M13.4 9.6A5.8 5.8 0 0 1 6.4 2.6a5.8 5.8 0 1 0 7 7Z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
]

export function ThemeToggle() {
  const { preference, setPreference, systemIsDark } = useTheme()

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-lg border border-border-default bg-surface p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = preference === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setPreference(option.value)}
            title={
              option.value === 'system'
                ? `Follow the system setting (currently ${systemIsDark ? 'dark' : 'light'})`
                : `Always ${option.label.toLowerCase()}`
            }
            className={`flex h-6 w-7 items-center justify-center rounded-md transition-colors ${
              active
                ? 'bg-elevated text-ink shadow-card ring-1 ring-border-default'
                : 'text-dim hover:text-ink'
            }`}
          >
            {option.icon}
            <span className="sr-only">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
