<template>
  <section class="connection-manager">
    <div class="section-heading">
      <div>
        <span class="eyebrow">REGISTRY</span>
        <h3>{{ $t('modelSettings.library') }}</h3>
      </div>
      <button type="button" class="icon-button" :title="$t('modelSettings.refresh')" @click="$emit('refresh')">
        <RefreshCw :size="16" />
      </button>
    </div>

    <div class="metrics">
      <div><small>{{ $t('modelSettings.connections') }}</small><strong>{{ connections.length }}</strong></div>
      <div><small>{{ $t('modelSettings.registeredModels') }}</small><strong>{{ models.length }}</strong></div>
      <div><small>{{ $t('modelSettings.verifiedModels') }}</small><strong>{{ verifiedCount }}</strong></div>
    </div>

    <div v-if="!connections.length" class="empty-state">
      <PlugZap :size="24" />
      <strong>{{ $t('modelSettings.noConnections') }}</strong>
      <span>{{ $t('modelSettings.noConnectionsDesc') }}</span>
    </div>

    <article v-for="connection in connections" :key="connection.id" class="connection-card">
      <header>
        <div>
          <strong>{{ connection.name }}</strong>
          <code>{{ connection.endpoint }}</code>
        </div>
        <div class="header-actions">
          <span class="secret-state" :class="connection.has_secret ? 'ready' : 'local'">
            {{ connection.has_secret ? $t('modelSettings.keyConfigured') : $t('modelSettings.noKey') }}
          </span>
          <button
            type="button"
            class="delete-button"
            :title="$t('modelSettings.deleteConnection')"
            @click="$emit('delete-connection', connection.id)"
          >
            <Trash2 :size="13" />
          </button>
        </div>
      </header>
      <div class="connection-meta">
        <span>{{ connection.provider_id }}</span>
        <span>{{ connection.protocol }}</span>
        <span v-if="connection.secret_suffix">•••• {{ connection.secret_suffix }}</span>
      </div>
      <div v-if="notice" class="manager-toast success">{{ notice }}</div>
      <div v-if="noticeError" class="manager-toast error">{{ noticeError }}</div>

      <div class="connection-models">
        <div v-for="model in modelsFor(connection.id)" :key="model.id" class="model-row">
          <Box :size="14" />
          <div class="model-id-col">
            <code>{{ model.model_id }}</code>
            <span v-if="!model.verified" class="unverified-tag">{{ $t('modelSettings.unverified') }}</span>
          </div>
          <span>{{ model.capabilities.join(' · ') }}</span>
          
          <div class="model-actions">
            <button
              v-if="model.capabilities.includes('chat')"
              type="button"
              class="primary-action-btn"
              :class="{ loading: settingPrimary === model.id }"
              :disabled="settingPrimary === model.id || testingModel === model.id"
              :title="$t('modelSettings.setPrimary')"
              @click="handleSetPrimary(model)"
            >
              <LoaderCircle v-if="settingPrimary === model.id" class="spin" :size="12" />
              <Star v-else :size="12" />
              <span>{{ $t('modelSettings.setPrimary') }}</span>
            </button>

            <button
              v-if="model.capabilities.includes('chat')"
              type="button"
              class="test-action-btn"
              :class="{ loading: testingModel === model.id, ok: model.verified }"
              :disabled="testingModel === model.id"
              :title="$t('modelSettings.testModel')"
              @click="handleTestModel(model)"
            >
              <LoaderCircle v-if="testingModel === model.id" class="spin" :size="12" />
              <FlaskConical v-else :size="12" />
              <span>{{ model.verified ? $t('modelSettings.verified') : $t('modelSettings.testModel') }}</span>
            </button>

            <button
              type="button"
              class="model-delete"
              :title="$t('modelSettings.deleteModel')"
              @click="$emit('delete-model', model.id)"
            >
              <X :size="12" />
            </button>
          </div>
        </div>
        <p v-if="!modelsFor(connection.id).length">{{ $t('modelSettings.noRegisteredModels') }}</p>
      </div>
    </article>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Box, FlaskConical, LoaderCircle, PlugZap, RefreshCw, Star, Trash2, X } from '@lucide/vue'
import { testModelEntry, updateProjectModelBindings } from '../../api/models'

const props = defineProps({
  projectId: { type: String, default: '' },
  revision: { type: Number, default: 0 },
  connections: { type: Array, default: () => [] },
  models: { type: Array, default: () => [] }
})
const emit = defineEmits(['refresh', 'delete-connection', 'delete-model'])
const { t } = useI18n()

const settingPrimary = ref('')
const testingModel = ref('')
const notice = ref('')
const noticeError = ref('')

const verifiedCount = computed(() => props.models.filter(item => item.verified).length)
const modelsFor = (connectionId) => props.models.filter(item => item.connection_id === connectionId)

const handleSetPrimary = async (model) => {
  notice.value = ''
  noticeError.value = ''
  settingPrimary.value = model.id
  try {
    if (!model.verified && model.capabilities?.includes('chat')) {
      try {
        await testModelEntry(model.id)
      } catch (_) {}
    }
    await updateProjectModelBindings(props.projectId || '_global', {
      revision: props.revision,
      roles: { primary: model.id }
    })
    notice.value = t('modelSettings.setPrimarySuccess', { name: model.model_id })
    emit('refresh')
  } catch (err) {
    noticeError.value = err.message || t('modelSettings.saveFailed')
  } finally {
    settingPrimary.value = ''
  }
}

const handleTestModel = async (model) => {
  notice.value = ''
  noticeError.value = ''
  testingModel.value = model.id
  try {
    await testModelEntry(model.id)
    notice.value = t('modelSettings.testSuccess')
    emit('refresh')
  } catch (err) {
    noticeError.value = err.message || t('modelSettings.testFailed')
  } finally {
    testingModel.value = ''
  }
}
</script>

<style scoped>
.connection-manager { padding: 18px; }
.section-heading { display: flex; justify-content: space-between; gap: 10px; }
.eyebrow { color: #a1c50a; font-size: 9px; font-weight: 800; }
h3 { margin-top: 4px; font-size: 17px; }
.icon-button { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid #222; background: #fff; cursor: pointer; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 14px; }
.metrics div { min-height: 60px; padding: 9px; border: 1px solid #ccc; background: #f8f8f6; }
.metrics small, .metrics strong { display: block; }
.metrics small { color: #777; font-size: 8px; }
.metrics strong { margin-top: 7px; font-size: 18px; }
.empty-state { display: grid; place-items: center; min-height: 170px; margin-top: 14px; border: 1px dashed #aaa; background: #fafaf8; text-align: center; }
.empty-state strong { margin-top: 8px; font-size: 12px; }
.empty-state span { max-width: 260px; margin-top: 4px; color: #777; font-size: 10px; line-height: 1.4; }
.connection-card { margin-top: 12px; border: 1px solid #bbb; background: #fff; }
.connection-card header { display: flex; justify-content: space-between; gap: 10px; padding: 11px; background: #f5f5f2; }
.connection-card header strong, .connection-card header code { display: block; }
.connection-card header strong { font-size: 12px; }
.connection-card header code { max-width: 310px; margin-top: 4px; overflow: hidden; color: #666; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.secret-state { align-self: start; padding: 4px 6px; font-size: 8px; font-weight: 800; }
.secret-state.ready { background: #dff4e7; color: #147342; }
.secret-state.local { background: #ececec; color: #555; }
.header-actions { display: flex; align-items: center; gap: 6px; }
.delete-button { display: grid; width: 24px; height: 24px; place-items: center; border: 1px solid #d9534f; background: #fff; color: #d9534f; cursor: pointer; }
.delete-button:hover { background: #d9534f; color: #fff; }
.connection-meta { display: flex; flex-wrap: wrap; gap: 5px; padding: 8px 11px; border-top: 1px solid #ddd; border-bottom: 1px solid #ddd; }
.connection-meta span { padding: 3px 5px; background: #eee; font-size: 8px; }
.manager-toast { margin: 8px 0; padding: 7px 10px; font-size: 10px; }
.manager-toast.success { background: #e8f7ed; color: #126d3e; }
.manager-toast.error { background: #fff0ef; color: #8c211c; }
.connection-models { padding: 5px 11px 9px; }
.model-row { display: grid; grid-template-columns: 18px 1fr auto auto; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid #eee; font-size: 10px; }
.model-id-col { display: flex; align-items: center; gap: 6px; overflow: hidden; }
.model-id-col code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unverified-tag { padding: 2px 4px; background: #fff4d9; color: #8a6400; font-size: 8px; font-weight: 700; white-space: nowrap; }
.model-row span { color: #666; font-size: 9px; }
.model-actions { display: flex; align-items: center; gap: 5px; }
.primary-action-btn, .test-action-btn { display: inline-flex; align-items: center; gap: 4px; border: 1px solid #ccc; background: #fafaf8; padding: 3px 6px; font-size: 9px; font-weight: 700; cursor: pointer; border-radius: 2px; }
.primary-action-btn:hover { border-color: #a1c50a; background: #f3f7e6; color: #4e6400; }
.test-action-btn:hover { border-color: #3b82f6; background: #eff6ff; color: #1d4ed8; }
.test-action-btn.ok { border-color: #86efac; color: #15803d; }
.model-delete { display: grid; width: 18px; height: 18px; place-items: center; border: none; background: transparent; color: #b0b0b0; cursor: pointer; }
.model-delete:hover { color: #d9534f; }
.connection-models p { padding: 10px 0 5px; color: #777; font-size: 9px; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
