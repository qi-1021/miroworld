<template>
  <Teleport to="body">
    <Transition name="fade">
      <button
        v-if="open"
        type="button"
        class="drawer-backdrop"
        :aria-label="$t('common.close')"
        @click="$emit('close')"
      ></button>
    </Transition>
    <Transition name="drawer">
      <aside v-if="open" class="model-drawer" role="dialog" aria-modal="true" :aria-label="$t('modelSettings.title')">
        <header class="drawer-header">
          <div>
            <span>MODEL CONTROL</span>
            <h2>{{ $t('modelSettings.title') }}</h2>
            <small>{{ contextLabel }}</small>
          </div>
          <button type="button" class="close-button" :title="$t('common.close')" @click="$emit('close')">
            <X :size="20" />
          </button>
        </header>

        <div v-if="loading && !registry" class="drawer-loading">
          <LoaderCircle class="spin" :size="26" />
          <span>{{ $t('common.loading') }}</span>
        </div>

        <template v-else>
          <div class="snapshot-summary">
            <div>
              <span>{{ $t('modelSettings.currentConfiguration') }}</span>
              <strong>{{ summary }}</strong>
            </div>
            <span class="revision">v{{ registry?.revision ?? 0 }}</span>
          </div>

          <nav class="drawer-tabs" :aria-label="$t('modelSettings.tabsLabel')">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              type="button"
              :class="{ active: activeTab === tab.id }"
              @click="activeTab = tab.id"
            >
              <component :is="tab.icon" :size="15" />
              {{ $t(tab.label) }}
            </button>
          </nav>

          <main class="drawer-content">
            <RoleBindingsEditor
              v-if="activeTab === 'roles'"
              :project-id="projectId"
              :revision="registry.revision"
              :connections="registry.connections"
              :models="registry.models"
              :bindings="bindings"
              @saved="handleBindingsSaved"
            />
            <SmartConnectionForm
              v-else-if="activeTab === 'connect'"
              :revision="registry.revision"
              @saved="handleConnectionSaved"
            />
            <ConnectionManager
              v-else
              :connections="registry.connections"
              :models="registry.models"
              @refresh="loadRegistry"
              @delete-connection="handleDeleteConnection"
              @delete-model="handleDeleteModel"
            />
            <LocalEmbeddingPanel
              v-if="activeTab === 'library'"
              :revision="registry.revision"
              @registered="loadRegistry"
            />
          </main>
        </template>

        <footer class="drawer-footer">
          <span v-if="error" class="footer-error">{{ error }}</span>
          <span v-else-if="success" class="footer-success">{{ success }}</span>
          <span v-else>{{ $t('modelSettings.secretFooter') }}</span>
          <button type="button" @click="loadRegistry">
            <RefreshCw :size="14" />
            {{ $t('modelSettings.refresh') }}
          </button>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Boxes, Cable, LoaderCircle, RefreshCw, SlidersHorizontal, X } from '@lucide/vue'
import { getModelRegistry, getProjectModelBindings, deleteModelConnection, deleteModelEntry } from '../../api/models'
import ConnectionManager from './ConnectionManager.vue'
import LocalEmbeddingPanel from './LocalEmbeddingPanel.vue'
import RoleBindingsEditor from './RoleBindingsEditor.vue'
import SmartConnectionForm from './SmartConnectionForm.vue'

const props = defineProps({
  open: Boolean,
  projectId: { type: String, default: '' },
  contextType: { type: String, default: 'global' },
  contextId: { type: String, default: '' }
})
const emit = defineEmits(['close', 'updated'])
const { t } = useI18n()

const registry = ref(null)
const bindings = ref({})
const loading = ref(false)
const error = ref('')
const success = ref('')
const activeTab = ref('roles')
const tabs = [
  { id: 'roles', label: 'modelSettings.tabRoles', icon: markRaw(SlidersHorizontal) },
  { id: 'connect', label: 'modelSettings.tabConnect', icon: markRaw(Cable) },
  { id: 'library', label: 'modelSettings.tabLibrary', icon: markRaw(Boxes) }
]

const contextLabel = computed(() => {
  if (props.projectId) return `${t('modelSettings.projectContext')} · ${props.projectId}`
  if (props.contextId) return `${props.contextType} · ${props.contextId}`
  return t('modelSettings.globalContext')
})

const summary = computed(() => {
  if (!registry.value) return t('modelSettings.notConfigured')
  const primaryId = bindings.value.primary
  const primary = registry.value.models.find(item => item.id === primaryId)
  return primary ? primary.model_id : t('modelSettings.notConfigured')
})

const loadRegistry = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await getModelRegistry()
    registry.value = response.data
    if (props.projectId) {
      const bindingResponse = await getProjectModelBindings(props.projectId)
      bindings.value = bindingResponse.data.roles || {}
    } else {
      bindings.value = {}
    }
    emit('updated', { summary: summary.value, registry: registry.value })
  } catch (err) {
    error.value = err.message || t('modelSettings.loadFailed')
  } finally {
    loading.value = false
  }
}

const handleConnectionSaved = async () => {
  await loadRegistry()
  activeTab.value = 'library'
}

const handleDeleteConnection = async (connectionId) => {
  const connection = registry.value.connections.find(item => item.id === connectionId)
  const name = connection ? connection.name : connectionId
  if (!window.confirm(t('modelSettings.confirmDeleteConnection', { name }))) return
  error.value = ''
  success.value = ''
  try {
    // 操作前取最新 revision，避免配置版本过期导致 409
    const latest = await getModelRegistry()
    const response = await deleteModelConnection(connectionId, latest.data.revision)
    const cleaned = response.data.cleaned_bindings + response.data.cleaned_presets
    await loadRegistry()
    if (cleaned > 0) {
      success.value = t('modelSettings.deletedWithCleanup', { name, count: cleaned })
    }
  } catch (err) {
    error.value = err.message || t('modelSettings.deleteFailed')
  }
}

const handleDeleteModel = async (modelId) => {
  const model = registry.value.models.find(item => item.id === modelId)
  const name = model ? model.model_id : modelId
  if (!window.confirm(t('modelSettings.confirmDeleteModel', { name }))) return
  error.value = ''
  success.value = ''
  try {
    const latest = await getModelRegistry()
    const response = await deleteModelEntry(modelId, latest.data.revision)
    const cleaned = response.data.cleaned_bindings + response.data.cleaned_presets
    await loadRegistry()
    if (cleaned > 0) {
      success.value = t('modelSettings.deletedWithCleanup', { name, count: cleaned })
    }
  } catch (err) {
    error.value = err.message || t('modelSettings.deleteFailed')
  }
}

const handleBindingsSaved = async () => {
  await loadRegistry()
}

watch(() => props.open, value => {
  if (value) loadRegistry()
})
watch(() => props.projectId, () => {
  if (props.open) loadRegistry()
})
</script>

<style scoped>
.drawer-backdrop { position: fixed; inset: 0; z-index: 900; border: 0; background: rgba(0, 0, 0, .32); }
.model-drawer { position: fixed; top: 0; right: 0; bottom: 0; z-index: 910; display: flex; flex-direction: column; width: min(580px, 100vw); background: #fff; box-shadow: -12px 0 35px rgba(0, 0, 0, .2); }
.drawer-header { display: flex; align-items: flex-start; justify-content: space-between; min-height: 94px; padding: 18px; background: #171717; color: #fff; }
.drawer-header span { color: #ff6a2b; font-size: 9px; font-weight: 800; }
.drawer-header h2 { margin-top: 5px; font-size: 20px; }
.drawer-header small { display: block; max-width: 440px; margin-top: 5px; overflow: hidden; color: #aaa; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.close-button { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid #555; background: transparent; color: #fff; cursor: pointer; }
.snapshot-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 18px; border-bottom: 1px solid #ddd; background: #fff4ee; }
.snapshot-summary span, .snapshot-summary strong { display: block; }
.snapshot-summary span { color: #777; font-size: 9px; }
.snapshot-summary strong { margin-top: 3px; font-size: 12px; }
.snapshot-summary .revision { padding: 5px 7px; background: #171717; color: white; font-weight: 800; }
.drawer-tabs { display: grid; grid-template-columns: repeat(3, 1fr); border-bottom: 1px solid #ccc; }
.drawer-tabs button { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 42px; border: 0; border-right: 1px solid #ddd; border-bottom: 3px solid transparent; background: #f7f7f5; cursor: pointer; font-size: 10px; }
.drawer-tabs button:last-child { border-right: 0; }
.drawer-tabs button.active { border-bottom-color: #f25c21; background: #fff; font-weight: 800; }
.drawer-content { flex: 1; overflow: auto; }
.drawer-loading { display: flex; flex: 1; align-items: center; justify-content: center; gap: 10px; color: #666; }
.drawer-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 48px; padding: 9px 14px; border-top: 1px solid #ddd; background: #fafaf8; color: #666; font-size: 9px; }
.drawer-footer span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drawer-footer .footer-error { color: #d9534f; font-weight: 800; }
.drawer-footer .footer-success { color: #147342; font-weight: 800; }
.drawer-footer button { display: inline-flex; align-items: center; gap: 5px; border: 0; background: transparent; cursor: pointer; font-weight: 800; }
.drawer-enter-active, .drawer-leave-active, .fade-enter-active, .fade-leave-active { transition: .2s ease; }
.drawer-enter-from, .drawer-leave-to { transform: translateX(100%); }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 600px) { .model-drawer { width: 100vw; } .drawer-header { min-height: 84px; } }
</style>
