/**
 * =============================================================================
 * FILE: main.ts
 * LOCATION: /docextract/frontend/src/main.ts
 * =============================================================================
 *
 * PURPOSE:
 *   Vue application entry point. Creates the app instance, registers
 *   plugins (router), and mounts to the DOM.
 *
 * =============================================================================
 */

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)

app.use(router)

app.mount('#app')