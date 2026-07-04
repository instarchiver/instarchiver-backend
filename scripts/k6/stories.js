/**
 * k6 Load Test — Stories Endpoints
 *
 * Endpoints covered:
 *   GET /instagram/stories/                   list (cursor pagination)
 *   GET /instagram/stories/?user=<id>         filtered by user
 *   GET /instagram/stories/?search=<q>        full-text search
 *   GET /instagram/stories/<story_id>/        detail
 *   cursor pagination follow-through
 *
 * Run:
 *   k6 run scripts/k6/stories.js
 *   BASE_URL=http://localhost:8000 JWT_TOKEN=<token> k6 run scripts/k6/stories.js
 *   k6 run --vus 20 --duration 60s scripts/k6/stories.js
 */

import { check, sleep } from 'k6'
import http from 'k6/http'
import { SharedArray } from 'k6/data'
import {
  BASE_URL,
  getHeaders,
  checkPaginationResponse,
  followCursorPages,
  thresholds,
} from './config.js'

export const options = {
  scenarios: {
    // Scenario 1: List stories baseline
    list: {
      executor: 'constant-vus',
      vus: 10,
      duration: '30s',
      exec: 'listStories',
      tags: { scenario: 'list' },
    },
    // Scenario 2: List with user filter
    list_filtered: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'listStoriesFiltered',
      startTime: '5s',
      tags: { scenario: 'list_filtered' },
    },
    // Scenario 3: Cursor pagination — follow through multiple pages
    pagination: {
      executor: 'constant-vus',
      vus: 5,
      duration: '60s',
      exec: 'paginateStories',
      startTime: '5s',
      tags: { scenario: 'pagination' },
    },
    // Scenario 4: Detail endpoint
    detail: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'storyDetail',
      startTime: '5s',
      tags: { scenario: 'detail' },
    },
  },
  thresholds: {
    ...thresholds,
    'http_req_duration{scenario:list}': ['p(95)<500'],
    'http_req_duration{scenario:pagination}': ['p(95)<600'],
    'http_req_duration{scenario:detail}': ['p(95)<300'],
  },
}

// setup() runs once before VUs start; collect real IDs from the first page
export function setup() {
  const headers = getHeaders()
  const res = http.get(`${BASE_URL}/instagram/stories/?page_size=20`, { headers })

  const data = { storyIds: [], userIds: [] }

  if (res.status !== 200) {
    console.warn(`setup: stories list returned ${res.status}`)
    return data
  }

  try {
    const body = JSON.parse(res.body)
    for (const story of body.results || []) {
      if (story.story_id) data.storyIds.push(story.story_id)
      if (story.user && story.user.uuid) {
        if (!data.userIds.includes(story.user.uuid)) {
          data.userIds.push(story.user.uuid)
        }
      }
    }
  } catch (e) {
    console.warn('setup: failed to parse stories response', e)
  }

  console.log(
    `setup: collected ${data.storyIds.length} story IDs, ${data.userIds.length} user IDs`
  )
  return data
}

export function listStories() {
  const res = http.get(`${BASE_URL}/instagram/stories/?page_size=20`, {
    headers: getHeaders(),
    tags: { name: 'stories_list' },
  })
  checkPaginationResponse(res, 'stories_list')
  sleep(1)
}

export function listStoriesFiltered(data) {
  const headers = getHeaders()

  // Filter by user if we collected user IDs in setup
  if (data.userIds && data.userIds.length > 0) {
    const userId = data.userIds[Math.floor(Math.random() * data.userIds.length)]
    const res = http.get(
      `${BASE_URL}/instagram/stories/?user=${userId}&page_size=20`,
      { headers, tags: { name: 'stories_list_user_filter' } }
    )
    checkPaginationResponse(res, 'stories_list_user_filter')
  }

  // Search
  const searchTerms = ['photo', 'morning', 'happy', 'travel']
  const term = searchTerms[Math.floor(Math.random() * searchTerms.length)]
  const searchRes = http.get(
    `${BASE_URL}/instagram/stories/?search=${encodeURIComponent(term)}&page_size=20`,
    { headers, tags: { name: 'stories_list_search' } }
  )
  checkPaginationResponse(searchRes, 'stories_list_search')

  sleep(1)
}

export function paginateStories() {
  const total = followCursorPages(
    `${BASE_URL}/instagram/stories/?page_size=20`,
    5,
    'stories_pagination'
  )
  console.log(`Paginated stories: collected ${total} items across up to 5 pages`)
  sleep(2)
}

export function storyDetail(data) {
  if (!data.storyIds || data.storyIds.length === 0) {
    console.warn('storyDetail: no story IDs available from setup, skipping')
    sleep(1)
    return
  }

  const storyId = data.storyIds[Math.floor(Math.random() * data.storyIds.length)]
  const res = http.get(`${BASE_URL}/instagram/stories/${storyId}/`, {
    headers: getHeaders(),
    tags: { name: 'story_detail' },
  })

  check(res, {
    'story_detail: status 200': (r) => r.status === 200,
    'story_detail: has story_id': (r) => {
      try {
        return !!JSON.parse(r.body).story_id
      } catch (_) {
        return false
      }
    },
    'story_detail: has user object': (r) => {
      try {
        return !!JSON.parse(r.body).user
      } catch (_) {
        return false
      }
    },
  })

  sleep(1)
}
