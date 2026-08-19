import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { CompetitionInfo } from '../api/types'
import {
  COMPETITION_TYPE_FAMILY,
  FAMILY_COMPETITION_TYPE,
  ScopeContext,
  forGender,
  persistFamily,
  storedFamily,
  type ScopeFamily,
  type ScopeValue,
} from './scope'

/** Holds the international/league selection. See scope.ts for why it exists. */
export function ScopeProvider({ children }: { children: ReactNode }) {
  const [family, setFamilyState] = useState<ScopeFamily>(storedFamily)
  // The provider wraps the router's <Routes>, so the :gender param is not
  // available here - but the location is, and gender is always the first
  // segment. Read from there rather than moving the provider inside the
  // gender route, which would remount it (and refetch) on every switch.
  const { pathname } = useLocation()
  const apiGender = pathname.startsWith('/women') ? 'female' : 'male'
  const [allCompetitions, setAll] = useState<CompetitionInfo[]>([])
  const [loading, setLoading] = useState(true)

  // Fetched once for the whole app rather than per page. The list is four rows
  // today, and the point of reading it from the API at all is that ingesting a
  // new league should not need a frontend change - which is exactly the
  // coupling the five hardcoded copies reintroduced.
  useEffect(() => {
    let cancelled = false
    api
      .competitions()
      .then((c) => {
        if (!cancelled) setAll(c)
      })
      .catch(() => {
        if (!cancelled) setAll([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const setFamily = useCallback((next: ScopeFamily) => {
    setFamilyState(next)
    persistFamily(next)
  }, [])

  const value = useMemo<ScopeValue>(() => {
    // Everything below is scoped to the CURRENT GENDER first. Without this the
    // switch offered "Leagues" to a women's scope on the strength of the PSL,
    // which is men-only, and every board behind it returned nothing.
    const mine = forGender(allCompetitions, apiGender)
    const available = Array.from(
      new Set(mine.map((c) => COMPETITION_TYPE_FAMILY[c.type]).filter(Boolean))
    ) as ScopeFamily[]
    // Fall back rather than leave the app in a family this gender cannot fill.
    const effective =
      available.length === 0 || available.includes(family) ? family : available[0]
    const wanted = FAMILY_COMPETITION_TYPE[effective]
    return {
      family: effective,
      setFamily,
      competitionType: wanted,
      competitions: mine.filter((c) => c.type === wanted),
      availableFamilies: available,
      allCompetitions,
      familyOf: (key: string) => {
        const found = allCompetitions.find((c) => c.key === key)
        return found ? (COMPETITION_TYPE_FAMILY[found.type] ?? null) : null
      },
      loading,
    }
  }, [family, setFamily, allCompetitions, loading, apiGender])

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
}
