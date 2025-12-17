/**
 * =============================================================================
 * FILE: router/index.js
 * LOCATION: /docextract/frontend/src/router/index.js
 * =============================================================================
 *
 * PURPOSE:
 *   Vue Router configuration. Defines routes for the application.
 *
 * ROUTES:
 *   /                    - Documents list and upload
 *   /documents/:id       - Document detail with extractions
 *   /prompts             - Prompt template list
 *   /prompts/:id         - Prompt editor
 *
 * =============================================================================
 */

import { createRouter, createWebHistory } from 'vue-router'

// Lazy-load page components
const DocumentsPage = () => import('@/pages/DocumentsPage.vue')
const DocumentDetailPage = () => import('@/pages/DocumentDetailPage.vue')
const PromptsPage = () => import('@/pages/PromptsPage.vue')
const PromptEditorPage = () => import('@/pages/PromptEditorPage.vue')

const routes = [
  {
    path: '/',
    name: 'documents',
    component: DocumentsPage,
    meta: { title: 'Documents' }
  },
  {
    path: '/documents/:id',
    name: 'document-detail',
    component: DocumentDetailPage,
    meta: { title: 'Document Detail' }
  },
  {
    path: '/prompts',
    name: 'prompts',
    component: PromptsPage,
    meta: { title: 'Prompt Templates' }
  },
  {
    path: '/prompts/:id',
    name: 'prompt-editor',
    component: PromptEditorPage,
    meta: { title: 'Edit Prompt' }
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Update page title on navigation
router.beforeEach((to, from, next) => {
  document.title = to.meta.title
    ? `${to.meta.title} | DocExtract`
    : 'DocExtract'
  next()
})

export default router