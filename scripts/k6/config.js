import { check } from 'k6'
import http from 'k6/http'

export const BASE_URL = __ENV.BASE_URL || 'https://api.instarchiver.net'

export function getHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  if (__ENV.JWT_TOKEN) {
    headers['Authorization'] = `Bearer ${__ENV.JWT_TOKEN}`
  }
  return headers
}

// Extract cursor value from DRF next URL
// e.g. "http://localhost:8000/instagram/stories/?cursor=cD0y..."  →  "cD0y..."
export function extractCursor(nextUrl) {
  if (!nextUrl) return null
  try {
    const url = new URL(nextUrl)
    return url.searchParams.get('cursor')
  } catch (_) {
    return null
  }
}

// Assert standard DRF cursor pagination response shape
export function checkPaginationResponse(res, label) {
  check(res, {
    [`${label}: status 200`]: (r) => r.status === 200,
    [`${label}: has results array`]: (r) => {
      try {
        const body = JSON.parse(r.body)
        return Array.isArray(body.results)
      } catch (_) {
        return false
      }
    },
    [`${label}: has next field`]: (r) => {
      try {
        const body = JSON.parse(r.body)
        return Object.prototype.hasOwnProperty.call(body, 'next')
      } catch (_) {
        return false
      }
    },
    [`${label}: has previous field`]: (r) => {
      try {
        const body = JSON.parse(r.body)
        return Object.prototype.hasOwnProperty.call(body, 'previous')
      } catch (_) {
        return false
      }
    },
  })
}

// Follow cursor pagination up to maxPages, returns all collected items
export function followCursorPages(initialUrl, maxPages, label) {
  const headers = getHeaders()
  let url = initialUrl
  let page = 0
  let totalItems = 0

  while (url && page < maxPages) {
    const res = http.get(url, { headers, tags: { name: label } })
    checkPaginationResponse(res, `${label} page ${page + 1}`)

    let body
    try {
      body = JSON.parse(res.body)
    } catch (_) {
      break
    }

    totalItems += (body.results || []).length
    page++

    const cursor = extractCursor(body.next)
    if (!cursor) break

    // Rebuild URL using current base to avoid following absolute URLs to wrong host
    const baseEndpoint = initialUrl.split('?')[0]
    url = `${baseEndpoint}?cursor=${cursor}&page_size=20`
  }

  return totalItems
}

export const thresholds = {
  http_req_duration: ['p(95)<500', 'p(99)<1000'],
  http_req_failed: ['rate<0.01'],
  checks: ['rate>0.99'],
}
