<!--
==============================================================================
FILE: DocumentDetailPage.vue
LOCATION: /docextract/frontend/src/pages/DocumentDetailPage.vue
==============================================================================
-->

<template>
  <div class="p-6">
    <router-link to="/" class="text-primary-600 hover:text-primary-800 mb-4 inline-block">
      ← Back to Documents
    </router-link>

    <div v-if="loading" class="text-center py-12">
      <p class="text-gray-500">Loading document...</p>
    </div>

    <div v-else-if="error" class="card p-4 bg-red-50 border-red-200">
      <p class="text-red-700">{{ error }}</p>
    </div>

    <div v-else-if="document">
      <div class="card p-6 mb-6">
        <div class="flex justify-between items-start">
          <div>
            <h1 class="text-2xl font-bold text-gray-900">{{ document.original_filename }}</h1>
            <p class="text-gray-600 mt-1">
              {{ formatFileSize(document.file_size) }} •
              Uploaded {{ formatDate(document.created_at) }}
            </p>
          </div>
          <span :class="statusBadgeClass(document.status)">
            {{ document.status }}
          </span>
        </div>

        <div class="mt-4 flex gap-2">
          <button
            v-if="document.status === 'pending' || document.status === 'failed'"
            @click="triggerExtraction"
            :disabled="extracting"
            class="btn-primary"
          >
            {{ extracting ? 'Extracting...' : 'Trigger Extraction' }}
          </button>
          <a
            :href="`/api/v1/documents/${document.id}/download/`"
            class="btn-secondary"
            target="_blank"
          >
            Download Original
          </a>
        </div>
      </div>

      <div class="mb-4">
        <h2 class="text-lg font-semibold text-gray-900">Extractions</h2>
      </div>

      <div v-if="extractions.length === 0" class="card p-6 text-center text-gray-500">
        No extractions yet. Trigger extraction to analyse this document.
      </div>

      <div v-else class="space-y-4">
        <div v-for="extraction in extractions" :key="extraction.id" class="card">
          <div class="p-4 border-b border-gray-200 flex justify-between items-center">
            <div>
              <span :class="statusBadgeClass(extraction.status)" class="mr-2">
                {{ extraction.status }}
              </span>
              <span class="text-sm text-gray-500">
                {{ formatDate(extraction.created_at) }}
              </span>
            </div>
            <div class="text-sm">
              <span class="text-gray-500">Confidence:</span>
              <span class="font-medium ml-1" :class="confidenceColor(extraction.overall_confidence)">
                {{ (extraction.overall_confidence * 100).toFixed(0) }}%
              </span>
            </div>
          </div>

          <div class="p-4">
            <h3 class="text-sm font-medium text-gray-700 mb-3">
              Extracted Fields ({{ extraction.fields?.length || 0 }})
            </h3>

            <div v-if="extraction.fields?.length" class="space-y-2">
              <div
                v-for="field in extraction.fields"
                :key="field.id"
                class="flex items-start gap-4 p-3 bg-gray-50 rounded-lg"
              >
                <div class="flex-1">
                  <p class="text-sm font-medium text-gray-900">{{ field.field_name }}</p>
                  <p class="text-sm text-gray-600">{{ field.value }}</p>
                  <p class="text-xs text-gray-400 mt-1">{{ field.field_type }}</p>
                </div>
                <div class="text-right">
                  <span class="text-sm" :class="confidenceColor(field.confidence)">
                    {{ (field.confidence * 100).toFixed(0) }}%
                  </span>
                </div>
              </div>
            </div>

            <p v-else class="text-sm text-gray-500">No fields extracted</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { documentsApi } from '@/api/client'

interface Field {
  id: string
  field_type: string
  field_name: string
  value: string
  confidence: number
}

interface Extraction {
  id: string
  status: string
  overall_confidence: number
  created_at: string
  fields?: Field[]
}

interface Document {
  id: string
  original_filename: string
  file_size: number
  status: string
  created_at: string
}

const route = useRoute()
const document = ref<Document | null>(null)
const extractions = ref<Extraction[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const extracting = ref(false)

onMounted(() => {
  fetchDocument()
})

async function fetchDocument() {
  loading.value = true
  error.value = null
  const docId = route.params.id as string

  try {
    const [docResponse, extractionsResponse] = await Promise.all([
      documentsApi.get(docId),
      documentsApi.getExtractions(docId)
    ])
    document.value = docResponse.data
    extractions.value = extractionsResponse.data.results || extractionsResponse.data
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to load document'
  } finally {
    loading.value = false
  }
}

async function triggerExtraction() {
  if (!document.value) return
  extracting.value = true
  error.value = null

  try {
    await documentsApi.triggerExtraction(document.value.id)
    setTimeout(fetchDocument, 2000)
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to trigger extraction'
  } finally {
    extracting.value = false
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

function statusBadgeClass(status: string): string {
  const classes: Record<string, string> = {
    pending: 'badge-yellow', processing: 'badge-yellow',
    extracted: 'badge-green', committed: 'badge-green', failed: 'badge-red',
  }
  return classes[status] || 'badge-gray'
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.9) return 'text-green-600'
  if (confidence >= 0.7) return 'text-yellow-600'
  return 'text-red-600'
}
</script>