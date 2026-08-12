import { useParams } from 'react-router-dom'

export type GenderSlug = 'men' | 'women'
export type ApiGender = 'male' | 'female'

const SLUG_TO_API: Record<GenderSlug, ApiGender> = { men: 'male', women: 'female' }
const API_TO_SLUG: Record<ApiGender, GenderSlug> = { male: 'men', female: 'women' }

export function apiGenderFromSlug(slug: string): ApiGender {
  return SLUG_TO_API[slug as GenderSlug] ?? 'male'
}

export function slugFromApiGender(gender: ApiGender): GenderSlug {
  return API_TO_SLUG[gender]
}

/** Reads the :gender path segment ('men' | 'women') present on every route. */
export function useGender(): { slug: GenderSlug; apiGender: ApiGender } {
  const { gender } = useParams<{ gender: string }>()
  const slug: GenderSlug = gender === 'women' ? 'women' : 'men'
  return { slug, apiGender: apiGenderFromSlug(slug) }
}
