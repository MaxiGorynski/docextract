<!--
==============================================================================
FILE: PromptEditorPage.vue
LOCATION: /docextract/frontend/src/pages/PromptEditorPage.vue
==============================================================================

PURPOSE:
  Simplified configuration editor. Users edit "Extraction Instructions"
  and optionally add notes - no technical prompt template knowledge required.

==============================================================================
-->

<template>
  <div class="p-6">
    <!-- Back Link -->
    <router-link to="/prompts" class="text-primary-600 hover:text-primary-800 mb-4 inline-block">
      ← Back to Settings
    </router-link>

    <!-- Loading -->
    <div v-if="loading" class="text-center py-12">
      <p class="text-gray-500">Loading configuration...</p>
    </div>

    <!-- Error -->
    <div v-else-if="loadError" class="card p-4 bg-red-50 border-red-200">
      <p class="text-red-700">{{ loadError }}</p>
    </div>

    <!-- Editor -->
    <div v-else-if="template">
      <!-- Header -->
      <div class="flex justify-between items-start mb-6">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">Edit Configuration</h1>
          <p class="text-gray-600">Customise how the AI extracts information</p>
        </div>

        <div class="flex gap-2">
          <button
            v-if="!template.is_active"
            @click="activateTemplate"
            class="btn-secondary"
          >
            Activate
          </button>
          <button
            @click="saveTemplate"
            :disabled="saving"
            class="btn-primary"
          >
            {{ saving ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="error" class="card p-4 mb-6 bg-red-50 border-red-200">
        <p class="text-red-700">{{ error }}</p>
        <button @click="error = null" class="btn-secondary btn-sm mt-2">Dismiss</button>
      </div>

      <!-- Success Message -->
      <div v-if="saved" class="card p-4 mb-6 bg-green-50 border-green-200">
        <p class="text-green-700">Configuration saved successfully!</p>
      </div>

      <!-- Form -->
      <div class="space-y-6">
        <!-- Basic Info -->
        <div class="card p-6">
          <h2 class="text-lg font-semibold text-gray-900 mb-4">Configuration Details</h2>

          <div>
            <label class="label">Name</label>
            <input
              v-model="template.name"
              type="text"
              class="input max-w-md"
              placeholder="My Custom Configuration"
            />
          </div>

          <div class="mt-4">
            <label class="label">Description (optional)</label>
            <input
              v-model="template.description"
              type="text"
              class="input"
              placeholder="E.g., Optimised for UK CVs with detailed work history"
            />
          </div>

          <div class="mt-4 flex items-center gap-2">
            <span :class="template.is_active ? 'badge-green' : 'badge-gray'">
              {{ template.is_active ? 'Active' : 'Inactive' }}
            </span>
          </div>
        </div>

        <!-- Extraction Instructions -->
        <div class="card p-6">
          <h2 class="text-lg font-semibold text-gray-900 mb-2">Extraction Instructions</h2>
          <p class="text-sm text-gray-500 mb-4">
            Tell the AI how to behave when extracting information. Be specific about what matters most to you.
          </p>

          <textarea
            v-model="template.system_prompt"
            rows="14"
            class="input font-mono text-sm"
            placeholder="You are a precise document parser. Extract structured information with high accuracy..."
          ></textarea>

          <div class="mt-3 text-sm text-gray-500">
            <strong>Tips:</strong> Mention what types of documents you're processing, what fields are most important,
            and any specific formatting preferences (e.g., date formats, UK vs US spelling).
          </div>
        </div>

        <!-- Additional Notes -->
        <div class="card p-6">
          <h2 class="text-lg font-semibold text-gray-900 mb-2">Additional Notes (optional)</h2>
          <p class="text-sm text-gray-500 mb-4">
            Quick notes to guide the AI. These are appended to the instructions above.
          </p>

          <textarea
            v-model="additionalNotes"
            rows="4"
            class="input"
            placeholder="E.g., Focus on work experience dates, ignore personal interests section"
          ></textarea>
        </div>

        <!-- Actions -->
        <div class="flex justify-between">
          <button
            @click="deleteTemplate"
            :disabled="deleting"
            class="btn-danger"
          >
            {{ deleting ? 'Deleting...' : 'Delete Configuration' }}
          </button>

          <div class="flex gap-2">
            <router-link to="/prompts" class="btn-secondary">
              Cancel
            </router-link>
            <button
              @click="saveTemplate"
              :disabled="saving"
              class="btn-primary"
            >
              {{ saving ? 'Saving...' : 'Save Changes' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { promptsApi } from '@/api/client'

interface Template {
  id: string
  name: string
  description: string
  document_type: string | null
  system_prompt: string
  user_prompt_template: string
  is_active: boolean
}

const route = useRoute()
const router = useRouter()

const template = ref<Template | null>(null)
const additionalNotes = ref('')
const loading = ref(true)
const loadError = ref<string | null>(null)
const error = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const deleting = ref(false)

onMounted(() => {
  fetchTemplate()
})

async function fetchTemplate() {
  loading.value = true
  loadError.value = null

  const templateId = route.params.id as string

  try {
    const response = await promptsApi.get(templateId)
    template.value = response.data
  } catch (e: any) {
    loadError.value = e.response?.data?.detail || 'Failed to load configuration'
  } finally {
    loading.value = false
  }
}

async function saveTemplate() {
  if (!template.value) return

  saving.value = true
  saved.value = false
  error.value = null

  // Combine system prompt with additional notes if provided
  let finalSystemPrompt = template.value.system_prompt
  if (additionalNotes.value.trim()) {
    finalSystemPrompt = `${template.value.system_prompt}\n\nAdditional guidance:\n${additionalNotes.value.trim()}`
  }

  try {
    await promptsApi.update(template.value.id, {
      name: template.value.name,
      description: template.value.description,
      document_type: template.value.document_type,
      system_prompt: finalSystemPrompt,
      user_prompt_template: template.value.user_prompt_template,
    })

    // Update local state with combined prompt
    template.value.system_prompt = finalSystemPrompt
    additionalNotes.value = ''

    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to save configuration'
  } finally {
    saving.value = false
  }
}

async function activateTemplate() {
  if (!template.value) return

  error.value = null

  try {
    await promptsApi.activate(template.value.id)
    template.value.is_active = true
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to activate configuration'
  }
}

async function deleteTemplate() {
  if (!template.value) return

  if (!confirm('Are you sure you want to delete this configuration?')) return

  deleting.value = true
  error.value = null

  try {
    await promptsApi.delete(template.value.id)
    router.push('/prompts')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to delete configuration'
    deleting.value = false
  }
}
</script>