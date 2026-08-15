<template>
  <router-view />
  <ModelSettingsLauncher
    :open="modelSettingsOpen"
    :summary="modelSummary"
    :status="modelStatus"
    @toggle="modelSettingsOpen = !modelSettingsOpen"
  />
  <ModelSettingsDrawer
    :open="modelSettingsOpen"
    :project-id="modelContext.projectId"
    :context-type="modelContext.type"
    :context-id="modelContext.id"
    @close="modelSettingsOpen = false"
    @updated="handleModelUpdate"
  />
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ModelSettingsDrawer from './components/model-settings/ModelSettingsDrawer.vue'
import ModelSettingsLauncher from './components/model-settings/ModelSettingsLauncher.vue'
import { getModelRegistry, getProjectModelBindings } from './api/models'
import { getReport } from './api/report'
import { getSimulation } from './api/simulation'

const route = useRoute()
const { t } = useI18n()
const modelSettingsOpen = ref(false)
const modelSummary = ref(t('modelSettings.notConfigured'))
const modelStatus = ref('idle')
const resolvedProjectId = ref('')

const modelContext = computed(() => {
  if (route.params.projectId && route.params.projectId !== 'new') {
    return { type: 'project', id: route.params.projectId, projectId: route.params.projectId }
  }
  if (route.params.simulationId) {
    return { type: 'simulation', id: route.params.simulationId, projectId: resolvedProjectId.value }
  }
  if (route.params.reportId) {
    return { type: 'report', id: route.params.reportId, projectId: resolvedProjectId.value }
  }
  return { type: 'global', id: '', projectId: '' }
})

const resolveProjectContext = async () => {
  resolvedProjectId.value = ''
  try {
    if (route.params.simulationId) {
      const response = await getSimulation(route.params.simulationId)
      resolvedProjectId.value = response.data?.project_id || ''
    } else if (route.params.reportId) {
      const report = await getReport(route.params.reportId)
      if (report.data?.simulation_id) {
        const simulation = await getSimulation(report.data.simulation_id)
        resolvedProjectId.value = simulation.data?.project_id || ''
      }
    }
  } catch {
    resolvedProjectId.value = ''
  }
}

const handleModelUpdate = ({ summary, registry }) => {
  modelSummary.value = summary || t('modelSettings.notConfigured')
  const usable = registry?.models?.some(item => item.verified)
  modelStatus.value = usable ? 'ready' : registry?.connections?.length ? 'warning' : 'idle'
}

// 页面加载时主动查询模型配置状态，避免右上角一直显示"尚未配置"
const refreshModelSummary = async () => {
  try {
    const response = await getModelRegistry()
    const registryData = response.data
    let summaryText = t('modelSettings.notConfigured')
    if (modelContext.value.type === 'project' && modelContext.value.id) {
      try {
        const bindingResponse = await getProjectModelBindings(modelContext.value.id)
        const primaryId = bindingResponse.data?.roles?.primary
        const primary = registryData.models.find(item => item.id === primaryId)
        if (primary) summaryText = primary.model_id
      } catch {
        // 项目绑定查询失败则回退到全局判断
      }
    }
    if (summaryText === t('modelSettings.notConfigured')) {
      // 无项目绑定：取第一个已验证模型作为全局状态
      const firstVerified = registryData.models.find(item => item.verified)
      if (firstVerified) summaryText = firstVerified.model_id
    }
    modelSummary.value = summaryText
    const usable = registryData.models?.some(item => item.verified)
    modelStatus.value = usable ? 'ready' : registryData.connections?.length ? 'warning' : 'idle'
  } catch {
    modelSummary.value = t('modelSettings.notConfigured')
    modelStatus.value = 'idle'
  }
}

watch(() => route.fullPath, resolveProjectContext, { immediate: true })
watch(() => route.fullPath, refreshModelSummary, { immediate: true })

function handleOpenModelSettings() {
  modelSettingsOpen.value = true
}

onMounted(() => {
  refreshModelSummary()
  // 供其他页面通过 window 事件一键打开模型设置
  window.addEventListener('open-model-settings', handleOpenModelSettings)
})

onUnmounted(() => {
  window.removeEventListener('open-model-settings', handleOpenModelSettings)
})
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: 'JetBrains Mono', 'Space Grotesk', 'Noto Sans SC', monospace;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #000000;
  background-color: #ffffff;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #f1f1f1;
}

::-webkit-scrollbar-thumb {
  background: #000000;
}

::-webkit-scrollbar-thumb:hover {
  background: #333333;
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}
</style>
