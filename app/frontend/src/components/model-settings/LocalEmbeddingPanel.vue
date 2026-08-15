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

    <!-- 向量模型提供方偏好：云端 / 本地 / 自动 -->
    <div class="pref-block">
      <div class="pref-label">{{ $t('modelSettings.embeddingPreference') }}</div>
      <div class="pref-options">
        <button
          v-for="opt in prefOptions"
          :key="opt.value"
          type="button"
          class="pref-option"
          :class="{ active: preference === opt.value }"
          :disabled="prefSaving"
          @click="setPref(opt.value)"
        >
          <span class="pref-dot" :class="opt.value"></span>
          {{ opt.label }}
        </button>
      </div>
      <p class="pref-hint">{{ prefHint }}</p>
      <p v-if="prefMsg" class="pref-msg" :class="{ error: prefMsgError }">{{ prefMsg }}</p>
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
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CircleAlert, CircleCheckBig, Database, FlaskConical, LoaderCircle, RefreshCw, Save
} from '@lucide/vue'
import { registerLocalModel, scanLocalModels, testLocalModel, getModelRegistry, getEmbeddingPreference, setEmbeddingPreference } from '../../api/models'

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

// ---- 向量模型提供方偏好 ----
const preference = ref('auto')
const prefSaving = ref(false)
const prefMsg = ref('')
const prefMsgError = ref(false)
const prefOptions = [
  { value: 'auto', label: t('modelSettings.prefAuto') },
  { value: 'cloud', label: t('modelSettings.prefCloud') },
  { value: 'local', label: t('modelSettings.prefLocal') }
]
const prefHint = computed(() => ({
  auto: t('modelSettings.prefAutoHint'),
  cloud: t('modelSettings.prefCloudHint'),
  local: t('modelSettings.prefLocalHint')
}[preference.value] || ''))
const loadPreference = async () => {
  try {
    const res = await getEmbeddingPreference()
    preference.value = res.data?.preference || 'auto'
  } catch {
    preference.value = 'auto'
  }
}
const setPref = async (value) => {
  if (prefSaving.value || value === preference.value) return
  prefSaving.value = true
  prefMsg.value = ''
  prefMsgError.value = false
  try {
    const res = await setEmbeddingPreference(value)
    preference.value = res.data?.preference || value
    prefMsg.value = t('modelSettings.prefSaved')
  } catch (err) {
    prefMsg.value = err.message || t('modelSettings.prefSaveFailed')
    prefMsgError.value = true
  } finally {
    prefSaving.value = false
  }
}

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
    // 注册前取最新 revision；若中途 registry 被改动（409），刷新后自动重试一次
    const isRevisionConflict = (err) => (
      err?.response?.status === 409 || /revision|conflict|版本/i.test(err?.message || '')
    )
    for (let attempt = 0; attempt <= 1; attempt++) {
      try {
        const latest = await getModelRegistry()
        await registerLocalModel(model.name, { revision: latest.data.revision })
        break
      } catch (err) {
        if (attempt === 0 && isRevisionConflict(err)) {
          await load()
          continue
        }
        throw err
      }
    }
    emit('registered')
  } catch (err) {
    error.value = err.message || t('modelSettings.registerFailed')
  } finally {
    registering.value = ''
  }
}

onMounted(() => { load(); loadPreference() })
</script>

<style scoped>
.local-embedding-panel { padding: 16px; border-top: 4px solid #171717; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.panel-heading .eyebrow { color: #f25c21; font-size: 9px; font-weight: 800; }
.panel-heading h3 { margin-top: 4px; font-size: 15px; }
.section-desc { margin-top: 6px; color: #666; font-size: 11px; line-height: 1.6; }
.pref-block { margin-top: 14px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; background: #fafaf8; }
.pref-label { font-size: 11px; font-weight: 800; color: #333; }
.pref-options { display: flex; gap: 8px; margin-top: 8px; }
.pref-option { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid #ccc; border-radius: 980px; background: #fff; font-size: 11px; cursor: pointer; }
.pref-option.active { border-color: #a1c50a; color: #5f7008; font-weight: 800; background: #f3f7e6; }
.pref-option:disabled { opacity: 0.5; cursor: not-allowed; }
.pref-dot { width: 8px; height: 8px; border-radius: 50%; background: #bbb; }
.pref-dot.cloud { background: #a1c50a; }
.pref-dot.local { background: #1d1d1f; }
.pref-dot.auto { background: #8e8e93; }
.pref-hint { margin-top: 8px; color: #777; font-size: 10px; line-height: 1.5; }
.pref-msg { margin-top: 6px; color: #1c7a2e; font-size: 10px; }
.pref-msg.error { color: #d9534f; }
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
