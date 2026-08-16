<template>
  <section class="bindings-editor">
    <div class="section-heading">
      <div>
        <span class="eyebrow">ROLE BINDINGS</span>
        <h3>{{ $t('modelSettings.roleBindings') }}</h3>
      </div>
      <span v-if="projectId" class="context-chip">{{ projectId }}</span>
    </div>

    <p v-if="!projectId" class="empty-note">
      <Info :size="16" />
      {{ $t('modelSettings.noProjectContext') }}
    </p>

    <div v-else class="roles">
      <label v-for="role in roleDefinitions" :key="role.id" class="role-row">
        <span class="role-copy">
          <strong>{{ $t(role.label) }}</strong>
          <small>{{ $t(role.description) }}</small>
        </span>
        <select v-model="localBindings[role.id]">
          <option value="">{{ role.inherit ? $t('modelSettings.inheritPrimary') : $t('modelSettings.notConfigured') }}</option>
          <option v-for="model in modelsFor(role.capability)" :key="model.id" :value="model.id">
            {{ connectionName(model.connection_id) }} / {{ model.model_id }}
          </option>
        </select>
        <span class="role-status" :class="localBindings[role.id] ? 'ready' : 'empty'">
          {{ localBindings[role.id] ? $t('modelSettings.bound') : $t('modelSettings.unbound') }}
        </span>
      </label>
    </div>

    <div v-if="embeddingChanged" class="embedding-warning">
      <TriangleAlert :size="17" />
      <span>{{ $t('modelSettings.embeddingRebuildWarning') }}</span>
    </div>

    <div v-if="error" class="message error">{{ error }}</div>
    <div v-if="saved" class="message success">{{ $t('modelSettings.bindingsSaved') }}</div>

    <div v-if="projectId" class="actions">
      <button type="button" class="secondary-button" :disabled="saving" @click="resetBindings">
        <RotateCcw :size="15" />
        {{ $t('modelSettings.reset') }}
      </button>
      <button type="button" class="primary-button" :disabled="saving || !hasPrimary" @click="save">
        <LoaderCircle v-if="saving" class="spin" :size="15" />
        <Save v-else :size="15" />
        {{ saving ? $t('modelSettings.saving') : $t('modelSettings.saveBindings') }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Info, LoaderCircle, RotateCcw, Save, TriangleAlert } from '@lucide/vue'
import { updateProjectModelBindings } from '../../api/models'

const props = defineProps({
  projectId: { type: String, default: '' },
  revision: { type: Number, required: true },
  connections: { type: Array, default: () => [] },
  models: { type: Array, default: () => [] },
  bindings: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['saved'])

const roleDefinitions = [
  { id: 'primary', label: 'modelSettings.rolePrimary', description: 'modelSettings.rolePrimaryDesc', capability: 'chat' },
  { id: 'simulation', label: 'modelSettings.roleSimulation', description: 'modelSettings.roleSimulationDesc', capability: 'chat', inherit: true },
  { id: 'simulation_boost', label: 'modelSettings.roleBoost', description: 'modelSettings.roleBoostDesc', capability: 'chat', inherit: true },
  { id: 'graphiti_llm', label: 'modelSettings.roleGraphiti', description: 'modelSettings.roleGraphitiDesc', capability: 'chat', inherit: true },
  { id: 'graphiti_embedding', label: 'modelSettings.roleEmbedding', description: 'modelSettings.roleEmbeddingDesc', capability: 'embedding' }
]

const localBindings = reactive({})
const saving = ref(false)
const error = ref('')
const saved = ref(false)

const resetBindings = () => {
  for (const role of roleDefinitions) localBindings[role.id] = props.bindings[role.id] || ''
  saved.value = false
}

watch(() => props.bindings, resetBindings, { immediate: true, deep: true })
watch(() => props.projectId, resetBindings)

const modelsFor = (capability) => props.models.filter(model => (
  model.verified && model.capabilities?.includes(capability)
))

const connectionName = (connectionId) => (
  props.connections.find(item => item.id === connectionId)?.name || 'Local'
)

const hasPrimary = computed(() => Boolean(localBindings.primary))
const embeddingChanged = computed(() => (
  Boolean(props.bindings.graphiti_embedding) &&
  localBindings.graphiti_embedding !== props.bindings.graphiti_embedding
))

const save = async () => {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const roles = Object.fromEntries(
      Object.entries(localBindings).filter(([, value]) => Boolean(value))
    )
    const response = await updateProjectModelBindings(props.projectId, {
      revision: props.revision,
      roles
    })
    saved.value = true
    emit('saved', response.data)
  } catch (err) {
    error.value = err.message || 'Failed to save bindings'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.bindings-editor { padding: 18px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.eyebrow { color: #a1c50a; font-size: 9px; font-weight: 800; }
h3 { margin-top: 4px; font-size: 17px; }
.context-chip { max-width: 170px; overflow: hidden; padding: 5px 7px; background: #eee; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.empty-note { display: flex; gap: 8px; margin-top: 15px; padding: 12px; border-left: 3px solid #d69a00; background: #fff7d9; font-size: 11px; line-height: 1.45; }
.roles { margin-top: 15px; border-top: 1px solid #ddd; }
.role-row { display: grid; grid-template-columns: 145px minmax(0, 1fr) 58px; gap: 9px; align-items: center; padding: 12px 0; border-bottom: 1px solid #e7e7e3; }
.role-copy strong, .role-copy small { display: block; }
.role-copy strong { font-size: 11px; }
.role-copy small { margin-top: 3px; color: #777; font-size: 9px; line-height: 1.35; }
select { min-width: 0; min-height: 37px; border: 1px solid #aaa; border-radius: 0; background: #fff; padding: 7px 9px; font: inherit; font-size: 10px; }
.role-status { font-size: 9px; font-weight: 800; text-align: right; }
.role-status.ready { color: #17804c; }
.role-status.empty { color: #888; }
.embedding-warning { display: flex; gap: 8px; margin-top: 12px; padding: 10px; border-left: 3px solid #d69a00; background: #fff7d9; color: #725600; font-size: 10px; line-height: 1.45; }
.message { margin-top: 10px; padding: 9px; font-size: 10px; }
.message.error { background: #fff0ef; color: #8c211c; }
.message.success { background: #e8f7ed; color: #126d3e; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.primary-button, .secondary-button { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 8px 12px; font-weight: 800; cursor: pointer; }
.primary-button { border: 1px solid #a1c50a; background: #a1c50a; color: white; }
.secondary-button { border: 1px solid #222; background: white; color: #222; }
button:disabled { opacity: .45; cursor: not-allowed; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) { .role-row { grid-template-columns: 1fr; } .role-status { text-align: left; } }
</style>
