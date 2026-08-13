import { useMemo } from 'react'
import { useTheme } from './useTheme'

/**
 * Chart colours, read out of the stylesheet.
 *
 * Recharts takes literal colour strings, not classes, so a chart cannot
 * inherit the palette the way the rest of the product does. The previous
 * approach was to copy the hex values into the chart file by hand, which was
 * correct exactly once: the moment a second theme existed, every chart was
 * pinned to the dark palette and rendered dark-on-white.
 *
 * Reading the computed custom properties keeps one source of truth in
 * `index.css`. The read is keyed on the resolved theme, so it happens on mount
 * and on every swap, not on every render.
 */
export interface ChartTheme {
  /** Categorical identity, in fixed order. Never cycled — see index.css. */
  series: [string, string, string, string]
  grid: string
  axis: string
  surface: string
  ink: string
  border: string
  positive: string
  negative: string
}

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  return styles.getPropertyValue(name).trim() || fallback
}

export function useChartTheme(): ChartTheme {
  const { resolved } = useTheme()

  return useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    const dark = resolved === 'dark'
    return {
      series: [
        readVar(styles, '--color-series-1', dark ? '#3987e5' : '#1f5fc4'),
        readVar(styles, '--color-series-2', dark ? '#d95926' : '#e0662b'),
        readVar(styles, '--color-series-3', dark ? '#199e70' : '#16a578'),
        readVar(styles, '--color-series-4', dark ? '#c98500' : '#b07300'),
      ],
      grid: readVar(styles, '--color-border-subtle', dark ? '#1b2530' : '#e4e9ee'),
      axis: readVar(styles, '--color-muted', dark ? '#9aa7b4' : '#55636f'),
      surface: readVar(styles, '--color-surface', dark ? '#111922' : '#ffffff'),
      ink: readVar(styles, '--color-ink', dark ? '#f4f7fa' : '#0f1a24'),
      border: readVar(styles, '--color-border-default', dark ? '#25313c' : '#cfd8e0'),
      positive: readVar(styles, '--color-positive', dark ? '#199e70' : '#0f7a56'),
      negative: readVar(styles, '--color-negative', dark ? '#e06a60' : '#ce3a2e'),
    }
  }, [resolved])
}

/**
 * Legend label renderer.
 *
 * Recharts paints legend text in the series colour by default. Text wears text
 * tokens: the swatch beside the label already carries identity, and a coloured
 * label is a second, weaker copy of that signal which also drags the label
 * below the contrast the ink tokens guarantee.
 */
export function legendLabel(theme: ChartTheme) {
  return (value: string) => <span style={{ color: theme.ink }}>{value}</span>
}

/** Tooltip chrome, matched to the card treatment the rest of the product uses. */
export function tooltipStyle(theme: ChartTheme) {
  return {
    borderRadius: 10,
    fontSize: 12,
    padding: '8px 10px',
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    color: theme.ink,
    boxShadow: '0 4px 8px rgb(0 0 0 / 0.06), 0 12px 32px rgb(0 0 0 / 0.12)',
  }
}
