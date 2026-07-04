/**
 * k6 Load Test — Posts Endpoints
 *
 * Endpoints covered:
 *   GET /instagram/posts/                         list (cursor pagination)
 *   GET /instagram/posts/?user=<id>              filtered by user
 *   GET /instagram/posts/?search=<q>&ordering=-post_created_at
 *   GET /instagram/posts/<id>/                    detail (30s server-side cache)
 *   GET /instagram/posts/ai-search/?text=<q>      semantic search
 *   cursor pagination follow-through
 *
 * Run:
 *   k6 run scripts/k6/posts.js
 *   BASE_URL=http://localhost:8000 JWT_TOKEN=<token> k6 run scripts/k6/posts.js
 *   k6 run --vus 20 --duration 60s scripts/k6/posts.js
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
    // Scenario 1: List posts baseline
    list: {
      executor: 'constant-vus',
      vus: 10,
      duration: '30s',
      exec: 'listPosts',
      tags: { scenario: 'list' },
    },
    // Scenario 2: List with filters and ordering
    list_filtered: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'listPostsFiltered',
      startTime: '5s',
      tags: { scenario: 'list_filtered' },
    },
    // Scenario 3: Cursor pagination — follow through multiple pages
    pagination: {
      executor: 'constant-vus',
      vus: 5,
      duration: '60s',
      exec: 'paginatePosts',
      startTime: '5s',
      tags: { scenario: 'pagination' },
    },
    // Scenario 4: Detail endpoint (tests 30s cache behaviour)
    detail: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'postDetail',
      startTime: '5s',
      tags: { scenario: 'detail' },
    },
    // Scenario 5: AI semantic search
    ai_search: {
      executor: 'constant-vus',
      vus: 3,
      duration: '30s',
      exec: 'aiSearch',
      startTime: '10s',
      tags: { scenario: 'ai_search' },
    },
  },
  thresholds: {
    ...thresholds,
    'http_req_duration{scenario:list}': ['p(95)<500'],
    'http_req_duration{scenario:pagination}': ['p(95)<600'],
    // Detail has a 30s server-side cache — cached hits should be much faster
    'http_req_duration{scenario:detail}': ['p(95)<300'],
    'http_req_duration{scenario:ai_search}': ['p(95)<2000'],
  },
}

export function setup() {
  const headers = getHeaders()
  const res = http.get(`${BASE_URL}/instagram/posts/?page_size=20`, { headers })

  const data = { postIds: [], userIds: [] }

  if (res.status !== 200) {
    console.warn(`setup: posts list returned ${res.status}`)
    return data
  }

  try {
    const body = JSON.parse(res.body)
    for (const post of body.results || []) {
      if (post.id) data.postIds.push(post.id)
      if (post.user && post.user.uuid) {
        if (!data.userIds.includes(post.user.uuid)) {
          data.userIds.push(post.user.uuid)
        }
      }
    }
  } catch (e) {
    console.warn('setup: failed to parse posts response', e)
  }

  console.log(
    `setup: collected ${data.postIds.length} post IDs, ${data.userIds.length} user IDs`
  )
  return data
}

export function listPosts() {
  const res = http.get(`${BASE_URL}/instagram/posts/?page_size=20`, {
    headers: getHeaders(),
    tags: { name: 'posts_list' },
  })
  checkPaginationResponse(res, 'posts_list')
  sleep(1)
}

export function listPostsFiltered(data) {
  const headers = getHeaders()

  // Filter by user
  if (data.userIds && data.userIds.length > 0) {
    const userId = data.userIds[Math.floor(Math.random() * data.userIds.length)]
    const res = http.get(
      `${BASE_URL}/instagram/posts/?user=${userId}&page_size=20`,
      { headers, tags: { name: 'posts_list_user_filter' } }
    )
    checkPaginationResponse(res, 'posts_list_user_filter')
  }

  // Search with ordering
  const searchTerms = ['beach', 'food', 'sunset', 'city', 'family']
  const term = searchTerms[Math.floor(Math.random() * searchTerms.length)]
  const orderOptions = ['-post_created_at', '-created_at', 'post_created_at']
  const ordering = orderOptions[Math.floor(Math.random() * orderOptions.length)]
  const searchRes = http.get(
    `${BASE_URL}/instagram/posts/?search=${encodeURIComponent(term)}&ordering=${ordering}&page_size=20`,
    { headers, tags: { name: 'posts_list_search' } }
  )
  checkPaginationResponse(searchRes, 'posts_list_search')

  sleep(1)
}

export function paginatePosts() {
  const total = followCursorPages(
    `${BASE_URL}/instagram/posts/?page_size=20`,
    5,
    'posts_pagination'
  )
  console.log(`Paginated posts: collected ${total} items across up to 5 pages`)
  sleep(2)
}

export function postDetail(data) {
  if (!data.postIds || data.postIds.length === 0) {
    console.warn('postDetail: no post IDs available from setup, skipping')
    sleep(1)
    return
  }

  const postId = data.postIds[Math.floor(Math.random() * data.postIds.length)]
  const res = http.get(`${BASE_URL}/instagram/posts/${postId}/`, {
    headers: getHeaders(),
    tags: { name: 'post_detail' },
  })

  check(res, {
    'post_detail: status 200': (r) => r.status === 200,
    'post_detail: has id': (r) => {
      try {
        return !!JSON.parse(r.body).id
      } catch (_) {
        return false
      }
    },
    'post_detail: has user object': (r) => {
      try {
        return !!JSON.parse(r.body).user
      } catch (_) {
        return false
      }
    },
    'post_detail: has media array': (r) => {
      try {
        return Array.isArray(JSON.parse(r.body).media)
      } catch (_) {
        return false
      }
    },
  })

  sleep(1)
}

export function aiSearch() {
  const queries = ['sunset beach photo', 'food photography', 'city night', 'travel adventure']
  const query = queries[Math.floor(Math.random() * queries.length)]

  const res = http.get(
    `${BASE_URL}/instagram/posts/ai-search/?text=${encodeURIComponent(query)}&page_size=10`,
    {
      headers: getHeaders(),
      tags: { name: 'posts_ai_search' },
    }
  )

  check(res, {
    'ai_search: status 200': (r) => r.status === 200,
    'ai_search: has results': (r) => {
      try {
        return Array.isArray(JSON.parse(r.body).results)
      } catch (_) {
        return false
      }
    },
  })

  sleep(3)
}
