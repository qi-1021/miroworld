<template>
  <section class="local-embedding-panel">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">LOCAL EMBEDDINGS</span>
        <h3>{{ $t('modelSettings.localEmbeddings') }}</h3>
      </div>
      <button
        type="button"
        class="icon-button"
        :title="$t('modelSettings.refresh')"
        :disabled="scanning"
        @click="load"
      >
        <LoaderCircle v-if="scanning" class="spin" :size="15" />
        <RefreshCw v-else :size="15" />
      </button>
    </div>

    <p class="section-desc">
      {{ $t('modelSettings.localEmbeddingsDesc') }}
      <code class="path-hint">{{ root || 'app/models/embeddings/' }}</code>
    </p>

    <div v-if="error" class="message error-message">
      <CircleAlert :size="15" />
      <span>{{ error }}</span>
    </div>

    <div v-if="!scanning && models.length === 0" class="empty-state">
      <Database :size="20" />
      <span>{{ $t('modelSettings.noLocalModels') }}</span>
    </div>

    <div v-for="model in models" :key="model.name" class="local-model-card">
      <div class="model-main">
        <div class="model-title">
          <strong>{{ model.name }}</strong>
          <span class="badge" :class="model.runtime_available ? 'ok' : 'warn'">
            {{ model.runtime_available ? $t('modelSettings.runtimeReady') : $t('modelSettings.runtimeMissing') }}
          </span>
        </div>
        <div class="model-meta">
          <span v-if="model.dimension">{{ $t('modelSettings.dimension') }}: {{ model.dimension }}d</span>
          <span v-if="model.max_length">{{ $t('modelSettings.maxLength') }}: {{ model.max_length }}</span>
          <span v-if="model.model_type">{{ $t('modelSettings.modelType') }}: {{ model.model_type }}</span>
          <span v-if="model.size_mb">{{ $t('modelSettings.size') }}: {{ model.size_mb }} MB</span>
        </div>
      </div>

      <div class="model-actions">
        <template v-if="model.runtime_available">
          <button type="button" class="secondary-button" :disabled="testing === model.name" @click="test(model)">
            <LoaderCircle v-if="testing === model.name" class="spin" :size="13" />
            <FlaskConical v-else :size="13" />
            {{ $t('modelSettings.testModel') }}
          </button>
          <button
            type="button"
            class="primary-button small"
            :disabled="registering === model.name"
            @click="register(model)"
          >
            <LoaderCircle v-if="registering === model.name" class="spin" :size="13" />
            <Save v-else :size="13" />
            {{ $t('modelSettings.registerModel') }}
          </button>
        </template>
        <span v-else class="runtime-hint">{{ $t('modelSettings.runtimeHint') }}</span>
      </div>

      <div v-if="results[model.name]" class="probe-result">
        <CircleCheckBig :size="14" />
        <span>
          {{ $t('modelSettings.probeOk', {
            dimension: results[model.name].dimension,
            seconds: results[model.name].elapsed_seconds
          }) }}
        </span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CircleAlert, CircleCheckBig, Database, FlaskConical, LoaderCircle, RefreshCw, Save
} from '@lucide/vue'
import { registerLocalModel, scanLocalModels, testLocalModel, getModelRegistry } from '../../api/models'

const props = defineProps({
  revision: { type: Number, required: true }
})
const emit = defineEmits(['registered'])
const { t } = useI18n()

const models = ref([])
const root = ref('')
const scanning = ref(false)
const testing = ref('')
const registering = ref('')
const error = ref('')
const results = ref({})

const load = async () => {
  scanning.value = true
  error.value = ''
  try {
    const response = await scanLocalModels()
    models.value = response.data.models || []
    root.value = response.data.root || ''
  } catch (err) {
    error.value = err.message || t('modelSettings.localScanFailed')
  } finally {
    scanning.value = false
  }
}

const test = async (model) => {
  testing.value = model.name
  error.value = ''
  try {
    const response = await testLocalModel(model.name)
    results.value[model.name] = response.data
  } catch (err) {
    error.value = err.message || t('modelSettings.testFailed')
  } finally {
    testing.value = ''
  }
}

const register = async (model) => {
  registering.value = model.name
  error.value = ''
  try {
    // 注册前取最新 revision，避免配置版本过期导致 409
    const latest = await getModelRegistry()
    await registerLocalModel(model.name, { revision: latest.data.revision })
    emit('registered')
  } catch (err) {
    error.value = err.message || t('modelSettings.registerFailed')
  } finally {
    registering.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.local-embedding-panel { padding: 16px; border-top: 4px solid #171717; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.panel-heading .eyebrow { color: #f25c21; font-size: 9px; font-weight: 800; }
.panel-heading h3 { margin-top: 4px; font-size: 15px; }
.section-desc { margin-top: 6px; color: #666; font-size: 11px; line-height: 1.6; }
.path-hint { display: inline-block; margin-top: 4px; padding: 2px 6px; background: #f2f2f0; font-size: 10px; }
.empty-state { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding: 18px; border: 1px dashed #ccc; color: #888; font-size: 11px; }
.local-model-card { margin-top: 10px; padding: 12px; border: 1px solid #ddd; background: #fafaf8; }
.model-title { display: flex; align-items: center; gap: 8px; }
.model-title strong { font-size: 12px; }
.model-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 6px; color: #777; font-size: 10px; }
.badge { padding: 2px 6px; font-size: 9px; font-weight: 800; }
.badge.ok { background: #e3f3e5; color: #1c7a2e; }
.badge.warn { background: #fff2d9; color: #a05a00; }
.model-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.runtime-hint { color: #a05a00; font-size: 10px; line-height: 1.5; }
.probe-result { display: flex; align-items: center; gap: 6px; margin-top: 8px; color: #1c7a2e; font-size: 10px; }
.secondary-button, .primary-button { display: inline-flex; align-items: center; gap: 5px; padding: 6px 10px; border: 1px solid #bbb; background: #fff; cursor: pointer; font-size: 10px; font-weight: 700; }
.primary-button { border-color: #171717; background: #171717; color: #fff; }
.primary-button.small { padding: 5px 8px; }
.secondary-button:disabled, .primary-button:disabled { opacity: .55; cursor: not-allowed; }
.icon-button { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid #ccc; background: #fff; cursor: pointer; }
.message { display: flex; align-items: flex-start; gap: 7px; margin-top: 10px; padding: 9px 11px; font-size: 11px; line-height: 1.5; }
.error-message { border: 1px solid #e6b4b4; background: #fdf1f1; color: #b3261e; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
