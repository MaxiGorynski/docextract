/**
 * =============================================================================
 * FILE: api/client.js
 * LOCATION: /docextract/frontend/src/api/client.js
 * =============================================================================
 *
 * PURPOSE:
 *   Axios HTTP client configured for Django backend communication.
 *   Handles CSRF tokens for session-based authentication.
 *
 * USAGE:
 *   import api from '@/api/client'
 *
 *   // GET request
 *   const response = await api.get('/api/v1/documents/')
 *
 *   // POST request
 *   const response = await api.post('/api/v1/documents/', formData)
 *
 * CSRF HANDLING:
 *   Django requires CSRF token for non-GET requests. This client:
 *   1. Reads the csrftoken cookie
 *   2. Includes it in X-CSRFToken header for POST/PUT/DELETE
 *
 * =============================================================================
 */

import axios from 'axios'

/**
 * Get CSRF token from cookie.
 * Django sets this as 'csrftoken' by default.
 */
function getCsrfToken() {
  const name = 'csrftoken'
  const cookies = document.cookie.split(';')

  for (let cookie of cookies) {
    cookie = cookie.trim()
    if (cookie.startsWith(name + '=')) {
      return decodeURIComponent(cookie.substring(name.length + 1))
    }
  }
  return null
}

/**
 * Configured Axios instance for API requests.
 */
const api = axios.create({
  // Base URL is relative - Vite proxy handles /api/*
  baseURL: '',

  // Include cookies (session auth)
  withCredentials: true,

  // Default headers
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * Request interceptor to add CSRF token.
 */
api.interceptors.request.use(
  (config) => {
    // Add CSRF token for mutating requests
    if (['post', 'put', 'patch', 'delete'].includes(config.method)) {
      const csrfToken = getCsrfToken()
      if (csrfToken) {
        config.headers['X-CSRFToken'] = csrfToken
      }
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

/**
 * Response interceptor for error handling.
 */
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Handle common errors
    if (error.response) {
      const { status } = error.response

      if (status === 401) {
        // Unauthorized - redirect to login
        console.warn('Unauthorized - session may have expired')
        // Could redirect to Django admin login:
        // window.location.href = '/admin/login/?next=/'
      }

      if (status === 403) {
        console.warn('Forbidden - CSRF token may be missing')
      }
    }

    return Promise.reject(error)
  }
)

export default api

/**
 * API helper functions for common endpoints.
 */
export const documentsApi = {
  list: (params = {}) => api.get('/api/v1/documents/', { params }),
  get: (id) => api.get(`/api/v1/documents/${id}/`),
  upload: (formData) => api.post('/api/v1/documents/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
  triggerExtraction: (id, options = {}) =>
    api.post(`/api/v1/documents/${id}/extract/`, options),
  getExtractions: (id) => api.get(`/api/v1/documents/${id}/extractions/`),
  delete: (id) => api.delete(`/api/v1/documents/${id}/`),
}

export const extractionsApi = {
  get: (id) => api.get(`/api/v1/extractions/${id}/`),
  commit: (id, data = {}) => api.post(`/api/v1/extractions/${id}/commit/`, data),
  reject: (id, data = {}) => api.post(`/api/v1/extractions/${id}/reject/`, data),
}

export const promptsApi = {
  list: () => api.get('/api/v1/prompts/'),
  get: (id) => api.get(`/api/v1/prompts/${id}/`),
  create: (data) => api.post('/api/v1/prompts/', data),
  update: (id, data) => api.put(`/api/v1/prompts/${id}/`, data),
  delete: (id) => api.delete(`/api/v1/prompts/${id}/`),
  getActive: (docType = null) => {
    const url = docType
      ? `/api/v1/prompts/active/${docType}/`
      : '/api/v1/prompts/active/'
    return api.get(url)
  },
  activate: (id) => api.post(`/api/v1/prompts/${id}/activate/`),
  duplicate: (id) => api.post(`/api/v1/prompts/${id}/duplicate/`),
  createFromDefault: (data = {}) => api.post('/api/v1/prompts/create-default/', data),
  getPlaceholders: () => api.get('/api/v1/prompts/placeholders/'),
}