import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { DashboardStats } from '../api/types'
import { StatCard } from '../components/StatCard'
import { LoadingSpinner, ErrorMessage } from '../components/LoadingSpinner'
import { useTheme } from '../theme/ThemeContext'
import { useGender } from '../gender/useGender'

const COMPETITION_COLORS: Record<string, string> = {
  tests: '#d97706',
  odis: '#0284c7',
  t20is: '#c026d3',
  psl: '#059669',
}

const COMPETITION_LABELS: Record<string, string> = {
  tests: 'Tests',
  odis: 'ODIs',
  t20is: 'T20Is',
  psl: 'PSL',
}

function parseSeasonYear(season: string): number {
  const match = season.match(/\d{4}/)
  return match ? parseInt(match[0], 10) : 0
}

export function Dashboard() {
  const { theme } = useTheme()
  const { slug, apiGender } = useGender()
  const gridStroke = theme === 'dark' ? '#334155' : '#e2e8f0'
  const axisTickColor = theme === 'dark' ? '#94a3b8' : '#64748b'
  const tooltipStyle = {
    borderRadius: 8,
    fontSize: 13,
    background: theme === 'dark' ? '#1e293b' : '#ffffff',
    border: `1px solid ${theme === 'dark' ? '#334155' : '#e2e8f0'}`,
    color: theme === 'dark' ? '#f1f5f9' : '#0f172a',
  }
  const [data, setData] = useState<DashboardStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    api
      .dashboard(apiGender)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((e) => {
        if (!cancelled) setError(String(e))
      })
    return () => {
      cancelled = true
    }
  }, [apiGender])

  if (error) return <ErrorMessage message={error} />
  if (!data) return <LoadingSpinner />

  const seasonChartData = [...data.matches_by_season]
    .sort((a, b) => parseSeasonYear(a.season) - parseSeasonYear(b.season))
    .map((s) => ({ season: s.season, matches: s.count }))

  const competitionChartData = data.by_competition.map((c) => ({
    name: COMPETITION_LABELS[c.competition_key] ?? c.display_name,
    matches: c.count,
    fill: COMPETITION_COLORS[c.competition_key] ?? '#64748b',
  }))

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Overview</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          International cricket, 2001&ndash;present, sourced from Cricsheet
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Total Matches" value={data.total_matches.toLocaleString()} accent="emerald" />
        <StatCard label="Players" value={data.total_players.toLocaleString()} accent="sky" />
        <StatCard label="Teams" value={data.total_teams.toLocaleString()} accent="amber" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">Matches by Format</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={competitionChartData} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={gridStroke} />
              <XAxis type="number" tick={{ fontSize: 12, fill: axisTickColor }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 13, fill: axisTickColor }} width={60} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => [Number(value).toLocaleString(), 'Matches']}
              />
              <Bar dataKey="matches" radius={[0, 6, 6, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">Matches per Season</h2>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={seasonChartData} margin={{ left: -20, right: 24 }}>
              <defs>
                <linearGradient id="seasonFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={gridStroke} />
              <XAxis
                dataKey="season"
                tick={{ fontSize: 10, fill: axisTickColor }}
                interval={Math.max(0, Math.floor(seasonChartData.length / 8))}
              />
              <YAxis tick={{ fontSize: 12, fill: axisTickColor }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Area type="monotone" dataKey="matches" stroke="#10b981" fill="url(#seasonFill)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
            <h2 className="font-semibold text-slate-800 dark:text-slate-100">Top Run Scorers</h2>
            <Link to={`/${slug}/rankings`} className="text-sm text-emerald-600 hover:underline dark:text-emerald-400">
              View all &rarr;
            </Link>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {data.top_run_scorers.map((p, i) => (
                <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
                  <td className="w-8 py-2.5 pl-5 text-slate-400">{i + 1}</td>
                  <td className="py-2.5">
                    <Link
                      to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {p.player_name}
                    </Link>
                  </td>
                  <td className="py-2.5 pr-5 text-right font-semibold text-slate-700 dark:text-slate-200">
                    {p.runs.toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-5 text-right text-slate-400">avg {p.average ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
            <h2 className="font-semibold text-slate-800 dark:text-slate-100">Top Wicket Takers</h2>
            <Link to={`/${slug}/rankings`} className="text-sm text-emerald-600 hover:underline dark:text-emerald-400">
              View all &rarr;
            </Link>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {data.top_wicket_takers.map((p, i) => (
                <tr key={p.player_identifier ?? p.player_name} className="border-b border-slate-100 last:border-0 dark:border-slate-800/50">
                  <td className="w-8 py-2.5 pl-5 text-slate-400">{i + 1}</td>
                  <td className="py-2.5">
                    <Link
                      to={p.player_identifier ? `/${slug}/players/${p.player_identifier}` : '#'}
                      className="font-medium text-slate-800 hover:text-emerald-600 dark:text-slate-100 dark:hover:text-emerald-400"
                    >
                      {p.player_name}
                    </Link>
                  </td>
                  <td className="py-2.5 pr-5 text-right font-semibold text-slate-700 dark:text-slate-200">
                    {p.wickets.toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-5 text-right text-slate-400">avg {p.average ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
