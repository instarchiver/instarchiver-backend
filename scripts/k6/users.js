/**
 * k6 Load Test — Users Endpoints
 *
 * Endpoints covered:
 *   GET /instagram/users/                         list (cursor pagination)
 *   GET /instagram/users/?search=<q>&ordering=<f> search + ordering
 *   GET /instagram/users/<uuid>/                  detail
 *   GET /instagram/users/<uuid>/history/          change history (cursor pagination)
 *   cursor pagination follow-through
 *
 * Run:
 *   k6 run scripts/k6/users.js
 *   BASE_URL=http://localhost:8000 JWT_TOKEN=<token> k6 run scripts/k6/users.js
 *   k6 run --vus 20 --duration 60s scripts/k6/users.js
 */

import { check, sleep } from 'k6'
import http from 'k6/http'
import {
  BASE_URL,
  getHeaders,
  checkPaginationResponse,
  followCursorPages,
  thresholds,
} from './config.js'

export const options = {
  scenarios: {
    // Scenario 1: List users baseline
    list: {
      executor: 'constant-vus',
      vus: 10,
      duration: '30s',
      exec: 'listUsers',
      tags: { scenario: 'list' },
    },
    // Scenario 2: Search with ordering
    list_search: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'listUsersSearch',
      startTime: '5s',
      tags: { scenario: 'list_search' },
    },
    // Scenario 3: Cursor pagination
    pagination: {
      executor: 'constant-vus',
      vus: 5,
      duration: '60s',
      exec: 'paginateUsers',
      startTime: '5s',
      tags: { scenario: 'pagination' },
    },
    // Scenario 4: Detail endpoint
    detail: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'userDetail',
      startTime: '5s',
      tags: { scenario: 'detail' },
    },
    // Scenario 5: History endpoint with pagination
    history: {
      executor: 'constant-vus',
      vus: 3,
      duration: '30s',
      exec: 'userHistory',
      startTime: '10s',
      tags: { scenario: 'history' },
    },
  },
  thresholds: {
    ...thresholds,
    'http_req_duration{scenario:list}': ['p(95)<500'],
    'http_req_duration{scenario:list_search}': ['p(95)<600'],
    'http_req_duration{scenario:pagination}': ['p(95)<600'],
    'http_req_duration{scenario:detail}': ['p(95)<400'],
    'http_req_duration{scenario:history}': ['p(95)<500'],
  },
}

export function setup() {
  const headers = getHeaders()
  const res = http.get(`${BASE_URL}/instagram/users/?page_size=20`, { headers })

  const data = { userUuids: [] }

  if (res.status !== 200) {
    console.warn(`setup: users list returned ${res.status}`)
    return data
  }

  try {
    const body = JSON.parse(res.body)
    for (const user of body.results || []) {
      if (user.uuid) data.userUuids.push(user.uuid)
    }
  } catch (e) {
    console.warn('setup: failed to parse users response', e)
  }

  console.log(`setup: collected ${data.userUuids.length} user UUIDs`)
  return data
}

export function listUsers() {
  const res = http.get(`${BASE_URL}/instagram/users/?page_size=20`, {
    headers: getHeaders(),
    tags: { name: 'users_list' },
  })
  checkPaginationResponse(res, 'users_list')
  sleep(1)
}

export function listUsersSearch() {
  const headers = getHeaders()

  const searchTerms = ['photo', 'official', 'studio', 'travel', 'art']
  const term = searchTerms[Math.floor(Math.random() * searchTerms.length)]
  const orderOptions = ['-created_at', 'created_at', '-updated_at', 'username', 'full_name']
  const ordering = orderOptions[Math.floor(Math.random() * orderOptions.length)]

  const res = http.get(
    `${BASE_URL}/instagram/users/?search=${encodeURIComponent(term)}&ordering=${ordering}&page_size=20`,
    { headers, tags: { name: 'users_list_search' } }
  )
  checkPaginationResponse(res, 'users_list_search')

  sleep(1)
}

export function paginateUsers() {
  const total = followCursorPages(
    `${BASE_URL}/instagram/users/?page_size=20`,
    5,
    'users_pagination'
  )
  console.log(`Paginated users: collected ${total} items across up to 5 pages`)
  sleep(2)
}

export function userDetail(data) {
  if (!data.userUuids || data.userUuids.length === 0) {
    console.warn('userDetail: no user UUIDs available from setup, skipping')
    sleep(1)
    return
  }

  const uuid = data.userUuids[Math.floor(Math.random() * data.userUuids.length)]
  const res = http.get(`${BASE_URL}/instagram/users/${uuid}/`, {
    headers: getHeaders(),
    tags: { name: 'user_detail' },
  })

  check(res, {
    'user_detail: status 200': (r) => r.status === 200,
    'user_detail: has uuid': (r) => {
      try {
        return !!JSON.parse(r.body).uuid
      } catch (_) {
        return false
      }
    },
    'user_detail: has username': (r) => {
      try {
        return !!JSON.parse(r.body).username
      } catch (_) {
        return false
      }
    },
    'user_detail: has follower_count': (r) => {
      try {
        const body = JSON.parse(r.body)
        return Object.prototype.hasOwnProperty.call(body, 'follower_count')
      } catch (_) {
        return false
      }
    },
  })

  sleep(1)
}

export function userHistory(data) {
  if (!data.userUuids || data.userUuids.length === 0) {
    console.warn('userHistory: no user UUIDs available from setup, skipping')
    sleep(1)
    return
  }

  const uuid = data.userUuids[Math.floor(Math.random() * data.userUuids.length)]
  const headers = getHeaders()

  // First page of history
  const res = http.get(`${BASE_URL}/instagram/users/${uuid}/history/?page_size=20`, {
    headers,
    tags: { name: 'user_history' },
  })
  checkPaginationResponse(res, 'user_history')

  // Check history-specific fields
  check(res, {
    'user_history: entries have history_date': (r) => {
      try {
        const body = JSON.parse(r.body)
        return (
          body.results.length === 0 ||
          Object.prototype.hasOwnProperty.call(body.results[0], 'history_date')
        )
      } catch (_) {
        return false
      }
    },
    'user_history: entries have history_type': (r) => {
      try {
        const body = JSON.parse(r.body)
        return (
          body.results.length === 0 ||
          Object.prototype.hasOwnProperty.call(body.results[0], 'history_type')
        )
      } catch (_) {
        return false
      }
    },
  })

  // Follow to next history page if available
  try {
    const body = JSON.parse(res.body)
    if (body.next) {
      const nextRes = http.get(body.next, {
        headers,
        tags: { name: 'user_history_page2' },
      })
      checkPaginationResponse(nextRes, 'user_history_page2')
    }
  } catch (_) {}

  sleep(2)
}
