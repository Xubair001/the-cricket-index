import type {
  ApiGender,
  BattingRankingRow,
  BowlingRankingRow,
  DashboardStats,
  ExplorerKind,
  ExplorerPage,
  FormLeaderboard,
  FormVerdict,
  HeadToHead,
  IccRankingTable,
  IccTeamRankingTable,
  MatchDetail,
  MatchSummary,
  Paginated,
  PeriodPaginated,
  PaginatedFixtures,
  ParFigures,
  PerformanceIndexPage,
  PeriodOption,
  PlayerComparison,
  PlayerDetail,
  PlayerDirectory,
  PlayerSummary,
  SquadAnalysis,
  TeamDetail,
  TeamStrengthTable,
  CompetitionInfo,
  TeamWeakness,
  UnderratedTable,
  TournamentDetail,
  TournamentSummary,
  MatchIntelligence,
  NewsArticleDetail,
  NewsHealth,
  NewsSourceInfo,
  PaginatedNews,
  SelectedSide,
  AvailabilityWindow,
  ScoutResult,
  TeamSummary,
  TeamType,
  VenueOption,
  VenueProfile,
  TournamentEditionDetail,
  PlayerSplits,
  TeamStrengthProfile,
  IccMovementReport,
  GroundCharacter,
} from './types'

// `boolean` is in the value union because FastAPI query flags are real params,
// not just strings. String(false) is "false", which FastAPI parses as False -
// so a flag left off must be `undefined`, never `false`, when the intent is
// "don't send it".
async function getJson<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
    }
  }
  const res = await fetch(url.pathname + '?' + url.searchParams.toString())
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  dashboard: (gender: ApiGender) => getJson<DashboardStats>('/api/dashboard', { gender }),

  battingRankings: (
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      /** A period spec: a preset key, `season:<label>`, or `custom:<from>:<to>`. */
      period?: string
      min_matches?: number
      sort_by?: string
      limit?: number
      offset?: number
    }
  ) => getJson<PeriodPaginated<BattingRankingRow>>('/api/rankings/batting', { gender, ...params }),

  bowlingRankings: (
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      /** A period spec: a preset key, `season:<label>`, or `custom:<from>:<to>`. */
      period?: string
      min_matches?: number
      sort_by?: string
      limit?: number
      offset?: number
    }
  ) => getJson<PeriodPaginated<BowlingRankingRow>>('/api/rankings/bowling', { gender, ...params }),

  // team_type is optional: the Teams page scopes to one kind at a time, but
  // the Matches filter deliberately omits it so you can filter by any side.
  // Paginated server-side. `limit` is explicit at every call site rather than
  // defaulted here, because the two uses want opposite things: a browsing page
  // wants a page, and the Matches team filter wants every side to populate its
  // select.
  teams: (gender: ApiGender, teamType?: TeamType, params: { limit?: number; offset?: number } = {}) =>
    getJson<Paginated<TeamSummary>>('/api/teams', { gender, team_type: teamType, ...params }),

  teamDetail: (teamId: number) => getJson<TeamDetail>(`/api/teams/${teamId}`),

  teamSquad: (teamId: number, params: { window_matches?: number } = {}) =>
    getJson<SquadAnalysis>(`/api/teams/${teamId}/squad`, params),

  headToHead: (teamAId: number, teamBId: number) =>
    getJson<HeadToHead>(`/api/teams/${teamAId}/head-to-head/${teamBId}`),

  players: (gender: ApiGender, params: { search?: string; limit?: number; offset?: number }) =>
    getJson<Paginated<PlayerSummary>>('/api/players', { gender, ...params }),

  playerDetail: (identifier: string, params: { period?: string } = {}) =>
    getJson<PlayerDetail>(`/api/players/${encodeURIComponent(identifier)}`, params),

  // Form is a separate call from the profile on purpose: it is the expensive
  // half, and it answers a different question (Rule 3 -- form is not career).
  /**
   * One split for one player. Split type is a parameter, not a family of
   * endpoints (Section 25).
   *
   * `competition` matters more here than elsewhere: phases are defined per
   * competition and a Test has none, so asking for a phase split without one
   * gets an `applies: false` and a reason rather than a number that looks like
   * the T20 one and means something else.
   */
  playerSplits: (
    identifier: string,
    split: string,
    gender: ApiGender,
    params: { competition?: string } = {},
  ) =>
    getJson<PlayerSplits>(`/api/players/${encodeURIComponent(identifier)}/splits`, {
      split,
      gender,
      ...params,
    }),

  playerForm: (
    identifier: string,
    params: {
      recent?: number
      baseline_days?: number
      competition?: string
      competition_type?: string
    } = {}
  ) => getJson<FormVerdict>(`/api/players/${encodeURIComponent(identifier)}/form`, params),

  // Ranks *change*, not standard -- deliberately beside the batting/bowling
  // rankings rather than replacing them.
  formLeaderboard: (
    gender: ApiGender,
    params: {
      state?: string
      trend?: string
      competition?: string
      competition_type?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<FormLeaderboard>('/api/rankings/form', { gender, ...params }),

  // The discovery surface. Rate sorts apply a default qualification server-side
  // (300 balls bowled / 200 faced) so "best economy" isn't a batter who bowled
  // two balls; pass min_balls_* to raise or explicitly lower it.
  playerDirectory: (
    gender: ApiGender,
    params: {
      search?: string
      competition?: string
      competition_type?: string
      team_id?: number
      min_matches?: number
      min_balls_faced?: number
      min_balls_bowled?: number
      status?: string
      form_state?: string
      /** A period spec. Narrows the aggregate columns, not the form column. */
      period?: string
      sort_by?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<PlayerDirectory>('/api/players/directory', { gender, ...params }),

  periods: () => getJson<PeriodOption[]>('/api/analytics/periods'),

  parFigures: () => getJson<ParFigures[]>('/api/analytics/par'),

  matches: (
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      team_id?: number
      season?: string
      search?: string
      limit?: number
      offset?: number
    }
  ) => getJson<Paginated<MatchSummary>>('/api/matches', { gender, ...params }),

  matchDetail: (matchId: string) => getJson<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}`),

  /**
   * Compare 2 to 5 players (§13). Sent as one comma-separated `players` value,
   * which is the form a shared or hand-written URL takes.
   */
  comparePlayers: (
    identifiers: string[],
    params: { competition?: string; competition_type?: string; period?: string } = {},
  ) =>
    getJson<PlayerComparison>('/api/players/compare', {
      players: identifiers.join(','),
      ...params,
    }),

  // The explorers (§21). Every filter, sort and page is applied server-side -
  // the unfiltered population is ~5,400 players, and sorting a page of them in
  // the browser would give a different answer from the ranking endpoints.
  explorer: (
    explorer: ExplorerKind,
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      team_id?: number
      opposition_team_id?: number
      date_from?: string
      date_to?: string
      /** A period spec. Intersected with any explicit date range above. */
      period?: string
      min_innings?: number
      min_balls?: number
      role?: string
      venue?: string
      sort_by?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<ExplorerPage>(`/api/analytics/${explorer}`, { gender, ...params }),

  // The Performance Index (§14). Always returns its own decomposition - a
  // score without its components is not usable by someone who has to defend
  // the decision it informs (§30).
  performanceIndex: (
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      role?: string
      limit?: number
      offset?: number
    } = {}
  ) => getJson<PerformanceIndexPage>('/api/rankings/performance', { gender, ...params }),

  // Canonical grounds - Cricsheet files one ground under several
  // spellings, so this is the normalised list, not SELECT DISTINCT venue.
  venues: (gender?: ApiGender) =>
    getJson<VenueOption[]>('/api/analytics/venues', { gender }),

  // One ground's character (§20). The name is canonical, and may carry a
  // parenthesised city for the handful that exist in several places.
  /**
   * Every ground in ONE competition on the two axes that describe a pitch.
   * `competition` is required: a ground hosting Tests and T20Is has two
   * characters and one figure describes neither.
   */
  groundCharacter: (
    gender: ApiGender,
    competition: string,
    params: { min_matches?: number } = {},
  ) =>
    getJson<GroundCharacter[]>('/api/analytics/ground-character', {
      gender,
      competition,
      ...params,
    }),

  venueProfile: (venue: string, gender: ApiGender, competition?: string) =>
    getJson<VenueProfile>(`/api/analytics/venues/${encodeURIComponent(venue)}`, {
      gender,
      competition,
    }),

  // Fitted opposition difficulty - the model that scales every adjusted
  // figure elsewhere. Exposed so a reader can check the adjustment (§30).
  teamStrength: (gender: ApiGender, competitionType?: string) =>
    getJson<TeamStrengthTable>('/api/analytics/opposition', {
      gender,
      competition_type: competitionType,
    }),

  // What happened in a match and why it mattered (§22). Partnerships,
  // spells and the over-by-over shape, all off the stored deliveries.
  matchIntelligence: (matchId: string) =>
    getJson<MatchIntelligence>(`/api/matches/${encodeURIComponent(matchId)}/intelligence`),

  // A side picked to a role shape (§18). Works the same for a nation and
  // for a franchise, which is what makes it usable for a league draft.
  bestSide: (
    gender: ApiGender,
    params: {
      competition?: string
      competition_type?: string
      size?: number
      team_id?: number
      /** 'all_time' (default) or 'current'. Two different questions - see the API. */
      pool?: string
      /** One of Section 18's optimisation objectives. Changes the role shape,
       *  the weighting, or both - the response reports which. */
      objective?: string
      /** Canonical ground name. A tilt, not a re-scope: the side is still picked
       *  over the whole scope and a venue record moves a candidate within it. */
      venue?: string
    } = {}
  ) => getJson<SelectedSide>('/api/rankings/best-xi', { gender, ...params }),

  // A scouting brief (§17). Returns candidates with `applied` and `ignored`
  // constraint maps, because a filter that quietly drops half the brief is
  // the failure mode the section warns about.
  scout: (params: {
    gender: ApiGender
    competition?: string
    competition_type?: string
    role?: string
    batting_style?: string
    bowling_family?: string
    max_age?: number
    min_matches?: number
    form_state?: string
    date_from?: string
    date_to?: string
    exclude_committed?: boolean
    limit?: number
  }) => getJson<ScoutResult>('/api/players/scout', params),

  // Who is COMMITTED in a window (§16), from announced squads. Not
  // 'available': absence from a squad is not evidence of freedom.
  availability: (params: {
    date_from: string
    date_to: string
    role?: string
    batting_style?: string
    player?: string
    limit?: number
  }) => getJson<AvailabilityWindow>('/api/players/availability', params),

  /**
   * Where the computed Index and ICC's published position disagree (§15).
   * `rank_type` is an ICC type such as 'test-batting'.
   */
  underrated: (rankType: string, params: { limit?: number } = {}) =>
    getJson<UnderratedTable>('/api/rankings/underrated', { rank_type: rankType, ...params }),

  /**
   * Movement in one ICC ranking since the previous published list.
   * Deliberately not a trend - see the API for why a handful of snapshots
   * cannot be drawn as a history.
   */
  iccMovement: (rankType: string) =>
    getJson<IccMovementReport>(`/api/icc/movement/${encodeURIComponent(rankType)}`),

  iccRankTypes: () => getJson<{ players: string[]; teams: string[] }>('/api/icc/rank-types'),

  iccPlayerRanking: (rankType: string, params: { limit?: number; offset?: number } = {}) =>
    getJson<IccRankingTable>(`/api/icc/players/${encodeURIComponent(rankType)}`, params),

  iccTeamRanking: (rankType: string, params: { limit?: number; offset?: number } = {}) =>
    getJson<IccTeamRankingTable>(`/api/icc/teams/${encodeURIComponent(rankType)}`, params),

  fixtures: (params: {
    gender?: string
    window?: string
    match_type?: string
    limit?: number
    offset?: number
  }) => getJson<PaginatedFixtures>('/api/fixtures', params),

  fixtureMatchTypes: (gender?: string) =>
    getJson<{ match_types: string[] }>('/api/fixtures/match-types', { gender }),

  /**
   * Sports news from four publishers.
   *
   * `gender` is asymmetric and optional: 'female' means the article links to a
   * women's side, 'male' means it links to no women's side. See the backend's
   * list_articles for why the two are not mirror images.
   */
  news: (
    params: {
      gender?: string
      source?: string
      player?: string
      team_id?: number
      tag?: string
      q?: string
      include_syndicated?: boolean
      limit?: number
      offset?: number
    } = {}
  ) => getJson<PaginatedNews>('/api/news', params),

  newsArticle: (articleId: number) => getJson<NewsArticleDetail>(`/api/news/${articleId}`),

  /** Every registered publisher, disabled ones included with the reason. */
  newsSources: () => getJson<NewsSourceInfo[]>('/api/news/sources'),

  newsHealth: () => getJson<NewsHealth>('/api/news/health'),

  /** What has declined for a side against its own recent past (§19). */
  /**
   * A side's depth profile (Section 19). The other half of `teamWeakness`:
   * that one asks what has declined against the side's own past, this asks how
   * their depth compares to the sides that actually contest the competition.
   *
   * NOT `teamStrength` below, which is the opposition model's fitted difficulty
   * rating over every side at once - a different question with a similar name.
   */
  teamStrengthProfile: (
    teamId: number,
    params: { competition?: string; window_matches?: number } = {},
  ) => getJson<TeamStrengthProfile>(`/api/teams/${teamId}/strength`, params),

  teamWeakness: (teamId: number, competition?: string) =>
    getJson<TeamWeakness>(`/api/teams/${teamId}/weakness`, { competition }),

  /** Every competition this dataset holds. Read once by the scope provider. */
  competitions: (gender?: string) =>
    getJson<CompetitionInfo[]>('/api/competitions', { gender }),

  /**
   * Named multi-team events. Bilateral tours are excluded server-side - they
   * are 1,013 of the 1,276 values in `event_name` and would bury the rest.
   */
  tournaments: (gender: ApiGender, params: { competition_type?: string } = {}) =>
    getJson<TournamentSummary[]>('/api/tournaments', { gender, ...params }),

  tournament: (slug: string, gender: ApiGender, params: { competition_type?: string } = {}) =>
    getJson<TournamentDetail>(`/api/tournaments/${encodeURIComponent(slug)}`, {
      gender,
      ...params,
    }),

  /**
   * One edition of one tournament.
   *
   * `season` is NOT encoded, because Cricsheet labels a tournament spanning a
   * new year "2023/24" and the backend takes the season as a path segment for
   * exactly that reason. Encoding the slash gives `2023%2F24`, which the router
   * decodes back to two segments and then fails to match - so encoding it
   * breaks the majority of editions rather than protecting anything.
   */
  tournamentEdition: (
    slug: string,
    season: string,
    gender: ApiGender,
    params: { competition_type?: string } = {},
  ) =>
    getJson<TournamentEditionDetail>(
      `/api/tournaments/${encodeURIComponent(slug)}/editions/${season}`,
      { gender, ...params },
    ),
}
