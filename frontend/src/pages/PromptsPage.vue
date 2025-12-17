<!--
==============================================================================
FILE: PromptsPage.vue
LOCATION: /docextract/frontend/src/pages/PromptsPage.vue
==============================================================================

PURPOSE:
  Extraction settings page showing current configuration and saved
  custom configurations. Uses friendly terminology for non-technical users.

==============================================================================
-->

<template>
  <div class="p-6">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-900">Extraction Settings</h1>
        <p class="text-gray-600">Customise how the AI extracts information from documents</p>
      </div>

      <button @click="createFromDefault" :disabled="creating" class="btn-primary">
        {{ creating ? 'Creating...' : 'Create Custom Configuration' }}
      </button>
    </div>

    <!-- Error -->
    <div v-if="error" class="card p-4 mb-6 bg-red-50 border-red-200">
      <p class="text-red-700">{{ error }}</p>
      <button @click="error = null" class="btn-secondary btn-sm mt-2">Dismiss</button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="text-center py-12">
      <p class="text-gray-500">Loading settings...</p>
    </div>

    <div v-else>
      <!-- Active Configuration Section -->
      <div class="card mb-6">
        <div class="p-4 border-b border-gray-200">
          <div class="flex justify-between items-start">
            <div>
              <h2 class="text-lg font-semibold text-gray-900">Current Configuration</h2>
              <p class="text-sm text-gray-500">
                This is what the AI uses when extracting from documents
              </p>
            </div>
            <span v-if="activePrompt?.is_default" class="badge-blue">Default</span>
            <span v-else class="badge-green">Custom</span>
          </div>
        </div>

        <div v-if="activePrompt" class="p-4">
          <div v-if="!activePrompt.is_default" class="mb-4">
            <span class="font-medium text-gray-900">{{ activePrompt.name }}</span>
          </div>

          <!-- Extraction Instructions Preview -->
          <div>
            <label class="label">Extraction Instructions</label>
            <div class="bg-gray-50 rounded-lg p-3 max-h-48 overflow-auto">
              <pre class="text-sm text-gray-700 whitespace-pre-wrap">{{ activePrompt.system_prompt }}</pre>
            </div>
          </div>

          <div v-if="!activePrompt.is_default" class="mt-4">
            <router-link
              :to="`/prompts/${activePrompt.id}`"
              class="btn-secondary"
            >
              Edit Configuration
            </router-link>
          </div>
        </div>
      </div>

      <!-- Saved Configurations -->
      <div class="card">
        <div class="p-4 border-b border-gray-200">
          <h2 class="text-lg font-semibold text-gray-900">Saved Configurations</h2>
          <p class="text-sm text-gray-500">
            Custom configurations you've created
          </p>
        </div>

        <div v-if="templates.length === 0" class="p-8 text-center text-gray-500">
          <p>No custom configurations yet.</p>
          <p class="text-sm mt-1">Create one to customise extraction behaviour.</p>
        </div>

        <div v-else class="divide-y divide-gray-200">
          <div
            v-for="template in templates"
            :key="template.id"
            class="p-4 hover:bg-gray-50 flex justify-between items-center"
          >
            <div>
              <div class="flex items-center gap-2">
                <span class="font-medium">{{ template.name }}</span>
                <span v-if="template.is_active" class="badge-green">Active</span>
              </div>
              <p v-if="template.description" class="text-sm text-gray-500 mt-1">
                {{ template.description }}
              </p>
            </div>

            <div class="flex gap-2">
              <button
                v-if="!template.is_active"
                @click="activateTemplate(template.id)"
                class="btn-secondary btn-sm"
              >
                Activate
              </button>
              <router-link
                :to="`/prompts/${template.id}`"
                class="btn-secondary btn-sm"
              >
                Edit
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { promptsApi } from '@/api/client'

interface ActivePrompt {
  id: string | null
  name: string
  system_prompt: string
  is_default: boolean
}

interface Template {
  id: string
  name: string
  description: string | null
  is_active: boolean
}

const router = useRouter()
const activePrompt = ref<ActivePrompt | null>(null)
const templates = ref<Template[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const creating = ref(false)

onMounted(() => {
  fetchData()
})

async function fetchData() {
  loading.value = true
  error.value = null

  try {
    const [activeResponse, listResponse] = await Promise.all([
      promptsApi.getActive(),
      promptsApi.list()
    ])

    activePrompt.value = activeResponse.data
    templates.value = listResponse.data.results || listResponse.data
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to load settings'
  } finally {
    loading.value = false
  }
}

async function createFromDefault() {
  creating.value = true
  error.value = null

  try {
    const response = await promptsApi.createFromDefault({
      name: `Custom Configuration ${new Date().toLocaleDateString('en-GB')}`
    })

    // Navigate to editor
    router.push(`/prompts/${response.data.id}`)
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to create configuration'
    creating.value = false
  }
}

async function activateTemplate(id: string) {
  error.value = null

  try {
    await promptsApi.activate(id)
    await fetchData()
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to activate configuration'
  }
}
</script>