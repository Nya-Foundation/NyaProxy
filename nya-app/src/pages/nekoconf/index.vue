<script setup lang="ts">
import { computed, ref } from 'vue';

// Page loading state
const iframeLoading = ref(true);
const iframeError = ref<string | null>(null);

// Build config page URL dynamically based on current location
const configUrl = computed(() => {
  // In production, use the same origin as the current page
  if (import.meta.env.PROD) {
    return `${window.location.origin}/config/`;
  }
  // In development
  return 'http://localhost:8080/config';
});

// Handle iframe load events
const handleIframeLoad = () => {
  iframeLoading.value = false;
  iframeError.value = null;
};

const handleIframeError = () => {
  iframeLoading.value = false;
  iframeError.value = 'Configuration panel failed to load';
};
</script>

<template>
  <div class="config-page">
    <div class="iframe-container">
      <!-- Iframe loading indicator -->
      <div v-if="iframeLoading" class="iframe-loading">
        <div class="loading-spinner"></div>
        <p>Loading configuration panel...</p>
      </div>

      <!-- Iframe error message -->
      <div v-if="iframeError" class="iframe-error">
        <h3>{{ iframeError }}</h3>
        <p>Please check if the server is running properly</p>
      </div>

      <!-- Config iframe - nested browsing context -->
      <iframe
        :src="configUrl"
        class="config-iframe"
        allowfullscreen
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
        loading="lazy"
        referrerpolicy="strict-origin-when-cross-origin"
        @load="handleIframeLoad"
        @error="handleIframeError"
        title="Configuration Panel - Nested Browsing Context"
        name="config-frame"
      ></iframe>
    </div>
  </div>
</template>

<style scoped>
.config-page {
  @apply w-full h-full relative;
}

.loading-container,
.error-container {
  @apply flex flex-col items-center justify-center h-full;
}

.loading-spinner {
  @apply w-8 h-8 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-4;
}

.error-container .error-message {
  @apply text-center p-6 bg-red-50 border border-red-200 rounded-lg;
}

.error-message h3 {
  @apply text-lg font-semibold text-red-700 mb-2;
}

.error-message p {
  @apply text-red-600 mb-4;
}

.retry-button {
  @apply px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 transition-colors;
}

.iframe-container {
  @apply w-full h-full relative;
}

.iframe-loading,
.iframe-error {
  @apply absolute inset-0 flex items-center justify-center bg-white z-10;
}

.iframe-error {
  @apply text-center text-red-600;
}

.iframe-error h3 {
  @apply text-lg font-semibold mb-2;
}

.config-iframe {
  @apply w-full h-full border-0;
  min-height: calc(100vh - 120px);
}

/* Dark mode support */
@media (prefers-color-scheme: dark) {
  .error-container .error-message {
    @apply bg-red-900/20 border-red-800;
  }

  .error-message h3 {
    @apply text-red-300;
  }

  .error-message p {
    @apply text-red-400;
  }

  .iframe-loading,
  .iframe-error {
    @apply bg-gray-900;
  }

  .iframe-error {
    @apply text-red-400;
  }

  .iframe-error h3 {
    @apply text-red-300;
  }
}
</style>
