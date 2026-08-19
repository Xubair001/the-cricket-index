import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { CompetitionInfo } from '../api/types'
import {
  COMPETITION_TYPE_FAMILY,
  FAMILY_COMPETITION_TYPE,
  ScopeContext,
  persistFamily,
  storedFamily,
  type ScopeFamily,
  type ScopeValue,
} from './scope'

/** Holds the international/league selection. See scope.ts for why it exists. */
export function ScopeProvider({ children }: { children: ReactNode }) {
  const [family, setFamilyState] = useState<ScopeFamily>(storedFamily)
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
    const wanted = FAMILY_COMPETITION_TYPE[family]
    return {
      family,
      setFamily,
      competitionType: wanted,
      competitions: allCompetitions.filter((c) => c.type === wanted),
      allCompetitions,
      familyOf: (key: string) => {
        const found = allCompetitions.find((c) => c.key === key)
        return found ? (COMPETITION_TYPE_FAMILY[found.type] ?? null) : null
      },
      loading,
    }
  }, [family, setFamily, allCompetitions, loading])

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
}
