<template>
  <section class="settings-section">
    <div class="section-heading">
      <div>
        <span class="eyebrow">QUICK CONNECT</span>
        <h3>{{ $t('modelSettings.addConnection') }}</h3>
      </div>
      <button type="button" class="icon-button" :title="$t('modelSettings.reset')" @click="reset">
        <RotateCcw :size="16" />
      </button>
    </div>

    <p class="section-desc">{{ $t('modelSettings.simpleConnectDesc') }}</p>

    <label class="field">
      <span>{{ $t('modelSettings.endpoint') }}</span>
      <input
        v-model.trim="form.endpoint"
        type="text"
        autocomplete="url"
        :placeholder="$t('modelSettings.endpointPlaceholder')"
      />
    </label>

    <label class="field">
      <span>
        {{ $t('modelSettings.apiKey') }}
        <small>{{ $t('modelSettings.localOptional') }}</small>
      </span>
      <div class="secret-input">
        <input
          v-model="form.api_key"
          :type="showSecret ? 'text' : 'password'"
          autocomplete="new-password"
          :placeholder="$t('modelSettings.apiKeyPlaceholder')"
        />
        <button type="button" :title="showSecret ? $t('modelSettings.hideKey') : $t('modelSettings.showKey')" @click="showSecret = !showSecret">
          <EyeOff v-if="showSecret" :size="16" />
          <Eye v-else :size="16" />
        </button>
      </div>
    </label>

    <label class="field">
      <span>
        {{ $t('modelSettings.connectionName') }}
        <small>{{ $t('modelSettings.optional') }}</small>
      </span>
      <input v-model.trim="form.name" type="text" :placeholder="$t('modelSettings.namePlaceholder')" />
    </label>

    <button type="button" class="expert-toggle" @click="expertOpen = !expertOpen">
      <SlidersHorizontal :size="15" />
      <span>{{ $t('modelSettings.expertSettings') }}</span>
      <ChevronDown :size="15" :class="{ rotated: expertOpen }" />
    </button>

    <div v-if="expertOpen" class="expert-panel">
      <label class="check-row">
        <input v-model="form.options.allow_private_network" type="checkbox" />
        <span>
          <strong>{{ $t('modelSettings.allowPrivateNetwork') }}</strong>
          <small>{{ $t('modelSettings.allowPrivateNetworkDesc') }}</small>
        </span>
      </label>
      <label class="field">
        <span>{{ $t('modelSettings.providerTemplate') }}</span>
        <select v-model="form.provider_id">
          <option value="custom">{{ $t('modelSettings.autoDetect') }}</option>
          <option value="openai">OpenAI</option>
          <option value="dashscope">DashScope</option>
          <option value="deepseek">DeepSeek</option>
          <option value="openrouter">OpenRouter</option>
          <option value="ollama">Ollama</option>
          <option value="lm-studio">LM Studio</option>
          <option value="vllm">vLLM</option>
        </select>
      </label>
    </div>

    <div v-if="error" class="message error-message">
      <CircleAlert :size="16" />
      <span>{{ error }}</span>
    </div>

    <div class="actions">
      <button type="button" class="primary-button" :disabled="detecting || !form.endpoint" @click="detect">
        <LoaderCircle v-if="detecting" class="spin" :size="16" />
        <ScanSearch v-else :size="16" />
        {{ detecting ? $t('modelSettings.detecting') : $t('modelSettings.detectAndConnect') }}
      </button>
    </div>

    <div v-if="result" class="detection-result">
      <div class="result-heading">
        <div>
          <span class="result-state" :class="result.usable ? 'usable' : 'partial'">
            {{ result.usable ? $t('modelSettings.usable') : $t('modelSettings.partial') }}
          </span>
          <h4>{{ result.provider_name }}</h4>
          <code>{{ result.normalized_endpoint }}</code>
        </div>
        <CircleCheckBig v-if="result.usable" :size="24" />
        <CircleAlert v-else :size="24" />
      </div>

      <div class="capability-list">
        <div v-for="(capability, name) in result.capabilities" :key="name" class="capability-row">
          <span>{{ capabilityLabel(name) }}</span>
          <small>{{ capability.url }}</small>
          <strong :class="capability.status">{{ statusLabel(capability.status) }}</strong>
        </div>
      </div>

      <div v-if="result.models.length" class="models-found">
        <div class="model-list-head">
          <strong>{{ $t('modelSettings.modelsFound', { count: result.models.length }) }}</strong>
          <button type="button" @click="toggleAllModels">{{ allSelected ? $t('modelSettings.clearSelection') : $t('modelSettings.selectAll') }}</button>
        </div>
        <label v-for="model in result.models" :key="model" class="model-option">
          <input v-model="selectedModels" type="checkbox" :value="model" />
          <code>{{ model }}</code>
        </label>
      </div>

      <div v-if="result.manual_model_required" class="manual-model">
        <label class="field">
          <span>{{ $t('modelSettings.manualModelId') }}</span>
          <input v-model.trim="manualModelId" type="text" :placeholder="$t('modelSettings.manualModelPlaceholder')" />
        </label>
      </div>

      <ul v-if="result.errors.length" class="detection-errors">
        <li v-for="item in result.errors" :key="item">{{ item }}</li>
      </ul>

      <button
        type="button"
        class="primary-button confirm-button"
        :disabled="saving || (!selectedModels.length && !manualModelId)"
        @click="confirm"
      >
        <LoaderCircle v-if="saving" class="spin" :size="16" />
        <Save v-else :size="16" />
        {{ saving ? $t('modelSettings.saving') : $t('modelSettings.confirmAndAdd') }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChevronDown, CircleAlert, CircleCheckBig, Eye, EyeOff, LoaderCircle,
  RotateCcw, Save, ScanSearch, SlidersHorizontal
} from '@lucide/vue'
import { createModelConnection, createModelEntry, detectModelConnection } from '../../api/models'

const props = defineProps({
  revision: { type: Number, required: true }
})
const emit = defineEmits(['saved'])
const { t } = useI18n()

const defaultForm = () => ({
  endpoint: '',
  api_key: '',
  name: '',
  provider_id: 'custom',
  options: { allow_private_network: false }
})

const form = reactive(defaultForm())
const expertOpen = ref(false)
const showSecret = ref(false)
const detecting = ref(false)
const saving = ref(false)
const error = ref('')
const result = ref(null)
const selectedModels = ref([])
const manualModelId = ref('')
const allSelected = computed(() => result.value?.models?.length && selectedModels.value.length === result.value.models.length)

const apiErrorText = (err) => {
  const fallback = err.message || t('modelSettings.detectFailed')
  if (err?.response?.data?.error?.message) {
    return err.response.data.error.message
  }
  if (err?.response?.status === 422) {
    const code = err.response.data?.error?.code
    if (code === 'PRIVATE_NETWORK_REQUIRED') {
      return t('modelSettings.privateNetworkRequired')
    }
  }
  if (err?.response) {
    return err.response.data?.error?.message || `${t('modelSettings.requestFailed')} (${err.response.status})`
  }
  return fallback
}

const isPrivateNetworkError = (err) => (
  err?.response?.status === 422 && err.response.data?.error?.code === 'PRIVATE_NETWORK_REQUIRED'
)

const reset = () => {
  Object.assign(form, defaultForm())
  result.value = null
  selectedModels.value = []
  manualModelId.value = ''
  error.value = ''
}

const detect = async () => {
  detecting.value = true
  error.value = ''
  result.value = null
  try {
    const response = await detectModelConnection({ ...form, options: { ...form.options } })
    result.value = response.data
    selectedModels.value = response.data.models.slice(0, 1)
  } catch (err) {
    error.value = apiErrorText(err)
    if (isPrivateNetworkError(err)) expertOpen.value = true
  } finally {
    detecting.value = false
  }
}

const confirm = async () => {
  saving.value = true
  error.value = ''
  try {
    const connectionResponse = await createModelConnection({
      ...form,
      name: form.name || result.value.provider_name,
      endpoint: result.value.normalized_endpoint,
      provider_id: result.value.provider_id,
      capabilities: result.value.capabilities,
      revision: props.revision
    })
    let revision = connectionResponse.data.revision
    const connection = connectionResponse.data.connection
    const models = [...selectedModels.value]
    if (manualModelId.value) models.push(manualModelId.value)
    const created = []
    for (const modelId of [...new Set(models)]) {
      const entry = await createModelEntry({
        revision,
        name: modelId,
        connection_id: connection.id,
        model_id: modelId,
        capabilities: ['chat'],
        verified: result.value.usable
      })
      revision = entry.data.revision
      created.push(entry.data.model)
    }
    emit('saved', { revision, connection, models: created })
    reset()
  } catch (err) {
    error.value = apiErrorText(err)
  } finally {
    saving.value = false
  }
}

const toggleAllModels = () => {
  selectedModels.value = allSelected.value ? [] : [...result.value.models]
}

const capabilityLabel = (name) => ({
  models: t('modelSettings.capabilityModels'),
  chat: t('modelSettings.capabilityChat'),
  embedding: t('modelSettings.capabilityEmbedding')
}[name] || name)

const statusLabel = (status) => ({
  available: t('modelSettings.available'),
  unavailable: t('modelSettings.unavailable'),
  not_tested: t('modelSettings.notTested')
}[status] || status)
</script>

<style scoped>
.settings-section { padding: 18px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.eyebrow { color: #f25c21; font-size: 9px; font-weight: 800; }
h3 { margin-top: 4px; font-size: 17px; }
.section-desc { margin: 10px 0 16px; color: #626262; font-size: 12px; line-height: 1.55; }
.field { display: block; margin-bottom: 13px; }
.field > span { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 11px; font-weight: 700; }
.field small { color: #777; font-weight: 400; }
input, select { width: 100%; min-height: 38px; border: 1px solid #a8a8a8; border-radius: 0; background: #fff; padding: 8px 10px; color: #111; font: inherit; font-size: 12px; }
input:focus, select:focus { outline: 2px solid rgba(242, 92, 33, 0.22); border-color: #f25c21; }
.secret-input { display: grid; grid-template-columns: 1fr 38px; }
.secret-input input { border-right: 0; }
.secret-input button, .icon-button { display: grid; place-items: center; border: 1px solid #a8a8a8; background: #f7f7f5; cursor: pointer; }
.expert-toggle { display: grid; grid-template-columns: 20px 1fr 18px; align-items: center; width: 100%; margin: 4px 0 13px; border: 1px dashed #aaa; background: #f8f8f6; padding: 9px; text-align: left; cursor: pointer; }
.expert-toggle .rotated { transform: rotate(180deg); }
.expert-panel { margin-bottom: 13px; padding: 12px; border-left: 3px solid #f25c21; background: #fff4ee; }
.check-row { display: grid; grid-template-columns: 18px 1fr; gap: 7px; align-items: start; margin-bottom: 12px; }
.check-row input { min-height: 16px; height: 16px; padding: 0; }
.check-row strong, .check-row small { display: block; font-size: 10px; }
.check-row small { margin-top: 3px; color: #666; line-height: 1.4; }
.actions { display: flex; justify-content: flex-end; }
.primary-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 39px; border: 1px solid #f25c21; background: #f25c21; color: #fff; padding: 9px 13px; font-weight: 800; cursor: pointer; }
.primary-button:disabled { opacity: 0.45; cursor: not-allowed; }
.message { display: flex; gap: 7px; margin: 10px 0; padding: 9px; font-size: 11px; line-height: 1.4; }
.error-message { border-left: 3px solid #c9352d; background: #fff0ef; color: #8c211c; }
.detection-result { margin-top: 16px; border: 1px solid #bbb; background: #fff; }
.result-heading { display: flex; justify-content: space-between; gap: 10px; padding: 13px; border-bottom: 1px solid #ddd; }
.result-heading h4 { margin: 5px 0; font-size: 14px; }
.result-heading code { display: block; overflow-wrap: anywhere; color: #555; font-size: 10px; }
.result-state { padding: 3px 5px; font-size: 9px; font-weight: 800; }
.result-state.usable { background: #dff4e7; color: #167342; }
.result-state.partial { background: #fff0c5; color: #7a5b00; }
.capability-list { padding: 0 12px; }
.capability-row { display: grid; grid-template-columns: 75px minmax(0, 1fr) 68px; gap: 7px; align-items: center; padding: 9px 0; border-bottom: 1px solid #eee; font-size: 10px; }
.capability-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #777; }
.capability-row strong { text-align: right; }
.capability-row .available { color: #167342; }
.capability-row .unavailable { color: #a42b23; }
.capability-row .not_tested { color: #866500; }
.models-found, .manual-model { margin: 12px; padding: 10px; background: #f7f7f5; }
.model-list-head { display: flex; justify-content: space-between; margin-bottom: 7px; font-size: 10px; }
.model-list-head button { border: 0; background: transparent; color: #f25c21; cursor: pointer; }
.model-option { display: grid; grid-template-columns: 18px 1fr; align-items: center; gap: 7px; padding: 7px 0; border-top: 1px solid #e1e1dd; }
.model-option input { width: 15px; min-height: 15px; height: 15px; padding: 0; }
.model-option code { overflow-wrap: anywhere; font-size: 10px; }
.detection-errors { margin: 12px 24px; color: #8c211c; font-size: 10px; }
.confirm-button { width: calc(100% - 24px); margin: 0 12px 12px; }
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
