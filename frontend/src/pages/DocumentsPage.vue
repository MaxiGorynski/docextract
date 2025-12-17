<!--
==============================================================================
FILE: DocumentsPage.vue
LOCATION: /docextract/frontend/src/pages/DocumentsPage.vue
==============================================================================

PURPOSE:
  Main documents page showing list of uploaded documents with status,
  upload functionality, and links to trigger extraction.

FEATURES:
  - Document list with status badges
  - File upload via hidden input
  - Trigger extraction with progress tracking
  - Polling for extraction completion
  - "Hit Refresh!" prompt when extraction completes

==============================================================================
-->

<template>
  <div class="p-6">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-900">Documents</h1>
        <p class="text-gray-600">Upload and manage documents for extraction</p>
      </div>

      <label class="btn-primary cursor-pointer">
        <input
          type="file"
          class="hidden"
          accept=".pdf,.docx"
          @change="handleFileUpload"
        />
        Upload Document
      </label>
    </div>

    <!-- Upload Progress -->
    <div v-if="uploading" class="card p-4 mb-6 bg-blue-50 border-blue-200">
      <p class="text-blue-700">Uploading {{ uploadingFileName }}...</p>
    </div>

    <!-- Error State -->
    <div v-if="error" class="card p-4 mb-6 bg-red-50 border-red-200">
      <p class="text-red-700">{{ error }}</p>
      <button @click="error = null" class="btn-secondary btn-sm mt-2">
        Dismiss
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="text-center py-12">
      <p class="text-gray-500">Loading documents...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="documents.length === 0" class="card p-12 text-center">
      <p class="text-gray-500 mb-4">No documents uploaded yet</p>
      <label class="btn-primary cursor-pointer">
        <input
          type="file"
          class="hidden"
          accept=".pdf,.docx"
          @change="handleFileUpload"
        />
        Upload Your First Document
      </label>
    </div>

    <!-- Documents Table -->
    <div v-else class="card overflow-hidden">
      <table class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Document
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Status
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Uploaded
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Progress
            </th>
            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody class="bg-white divide-y divide-gray-200">
          <tr v-for="doc in documents" :key="doc.id" class="hover:bg-gray-50">
            <td class="px-6 py-4">
              <router-link
                :to="`/documents/${doc.id}`"
                class="text-primary-600 hover:text-primary-800 font-medium"
              >
                {{ doc.original_filename }}
              </router-link>
              <p class="text-sm text-gray-500">{{ formatFileSize(doc.file_size) }}</p>
            </td>
            <td class="px-6 py-4">
              <span :class="statusBadgeClass(doc.status)">
                {{ doc.status }}
              </span>
            </td>
            <td class="px-6 py-4 text-sm text-gray-500">
              {{ formatDate(doc.created_at) }}
            </td>
            <td class="px-6 py-4">
              <!-- Processing: Show progress bar -->
              <div v-if="isProcessing(doc.id)" class="flex items-center space-x-2">
                <div class="flex-1 max-w-[120px]">
                  <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div class="h-full bg-blue-500 rounded-full animate-progress"></div>
                  </div>
                </div>
                <span class="text-xs text-blue-600 whitespace-nowrap">Processing...</span>
              </div>

              <!-- Just completed: Show refresh prompt -->
              <div v-else-if="justCompleted(doc.id)" class="flex items-center space-x-2">
                <button
                  @click="handleRefresh"
                  class="text-sm text-green-600 hover:text-green-800 font-medium flex items-center space-x-1"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  <span>Hit Refresh!</span>
                </button>
              </div>

              <!-- Idle: Show dash or nothing -->
              <div v-else class="text-gray-400 text-sm">
                —
              </div>
            </td>
            <td class="px-6 py-4 text-right space-x-2">
              <button
                v-if="doc.status === 'pending' || doc.status === 'failed'"
                @click="triggerExtraction(doc.id)"
                :disabled="isProcessing(doc.id)"
                class="btn-secondary btn-sm"
              >
                {{ isProcessing(doc.id) ? 'Extracting...' : 'Extract' }}
              </button>
              <router-link
                :to="`/documents/${doc.id}`"
                class="btn-secondary btn-sm"
              >
                View
              </router-link>
              <button
                @click="deleteDocument(doc.id, doc.original_filename)"
                :disabled="deleting === doc.id"
                class="btn-danger btn-sm"
              >
                {{ deleting === doc.id ? '...' : 'Delete' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { documentsApi } from '@/api/client'

interface Document {
  id: string
  original_filename: string
  file_size: number
  status: string
  created_at: string
}

const documents = ref<Document[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const uploading = ref(false)
const uploadingFileName = ref('')
const deleting = ref<string | null>(null)

// Track processing documents
const processingDocs = ref<Set<string>>(new Set())
const completedDocs = ref<Set<string>>(new Set())

// Polling interval
let pollInterval: ReturnType<typeof setInterval> | null = null
const POLL_INTERVAL_MS = 3000

onMounted(() => {
  fetchDocuments()
})

onUnmounted(() => {
  stopPolling()
})

function startPolling() {
  if (pollInterval) return // Already polling

  pollInterval = setInterval(async () => {
    if (processingDocs.value.size === 0) {
      stopPolling()
      return
    }

    await checkProcessingStatus()
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

async function checkProcessingStatus() {
  try {
    const response = await documentsApi.list()
    const latestDocs = response.data.results || response.data

    // Check each processing doc
    for (const docId of processingDocs.value) {
      const latestDoc = latestDocs.find((d: Document) => d.id === docId)

      if (latestDoc && latestDoc.status !== 'processing' && latestDoc.status !== 'pending') {
        // Document finished processing
        processingDocs.value.delete(docId)
        completedDocs.value.add(docId)

        // Auto-clear the "Hit Refresh!" after 30 seconds
        setTimeout(() => {
          completedDocs.value.delete(docId)
        }, 30000)
      }
    }

    // Update documents list silently (to reflect status changes)
    documents.value = latestDocs

  } catch (e) {
    console.error('Polling error:', e)
  }
}

function isProcessing(docId: string): boolean {
  return processingDocs.value.has(docId)
}

function justCompleted(docId: string): boolean {
  return completedDocs.value.has(docId)
}

function handleRefresh() {
  // Clear all completed flags and refresh
  completedDocs.value.clear()
  fetchDocuments()
}

async function fetchDocuments() {
  loading.value = true
  error.value = null

  try {
    const response = await documentsApi.list()
    documents.value = response.data.results || response.data

    // Check if any docs are in 'processing' status and track them
    for (const doc of documents.value) {
      if (doc.status === 'processing') {
        processingDocs.value.add(doc.id)
      }
    }

    // Start polling if we have processing docs
    if (processingDocs.value.size > 0) {
      startPolling()
    }

  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to load documents'
  } finally {
    loading.value = false
  }
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]

  if (!file) return

  uploading.value = true
  uploadingFileName.value = file.name
  error.value = null

  try {
    const formData = new FormData()
    formData.append('file', file)

    await documentsApi.upload(formData)
    await fetchDocuments()
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to upload document'
  } finally {
    uploading.value = false
    uploadingFileName.value = ''
    target.value = ''
  }
}

async function triggerExtraction(docId: string) {
  error.value = null

  // Mark as processing immediately
  processingDocs.value.add(docId)

  // Start polling
  startPolling()

  try {
    await documentsApi.triggerExtraction(docId)
    // Don't refresh immediately - let polling handle it
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to trigger extraction'
    processingDocs.value.delete(docId)
  }
}

async function deleteDocument(docId: string, filename: string) {
  if (!confirm(`Are you sure you want to delete "${filename}"?`)) return

  deleting.value = docId
  error.value = null

  try {
    await documentsApi.delete(docId)
    // Clean up tracking
    processingDocs.value.delete(docId)
    completedDocs.value.delete(docId)
    await fetchDocuments()
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to delete document'
  } finally {
    deleting.value = null
  }
}

function formatFileSize(bytes: number): string {
  if (!bytes || isNaN(bytes)) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function statusBadgeClass(status: string): string {
  const classes: Record<string, string> = {
    pending: 'badge-yellow',
    processing: 'badge-blue',
    extracted: 'badge-green',
    committed: 'badge-green',
    failed: 'badge-red',
  }
  return classes[status] || 'badge-gray'
}
</script>

<style scoped>
/* Animated progress bar */
@keyframes progress {
  0% {
    width: 5%;
  }
  50% {
    width: 80%;
  }
  100% {
    width: 95%;
  }
}

.animate-progress {
  animation: progress 2s ease-in-out infinite;
}
</style>