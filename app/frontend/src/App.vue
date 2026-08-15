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

/* Apple Liquid Glass 通用卡片类：
   增强版 —— 提高透明度的同时保留可读性，配合背景彩色光晕让
   backdrop-filter 的模糊/加饱和效果肉眼可见，呈现真正 Liquid Glass 质感。 */
.liquid-glass {
  background: rgba(255,255,255,0.42);
  border: 1px solid rgba(255,255,255,0.55);
  border-radius: 20px;
  box-shadow:
    0 8px 32px rgba(0,0,0,0.10),
    inset 0 1px 0 rgba(255,255,255,0.75),
    inset 0 -1px 0 rgba(255,255,255,0.20);
  backdrop-filter: saturate(200%) blur(28px);
  -webkit-backdrop-filter: saturate(200%) blur(28px);
  /* 玻璃高光：一条沿顶部的细亮线模拟反射 */
  position: relative;
}
.liquid-glass::before {
  content: '';
  position: absolute;
  top: 0;
  left: 5%;
  right: 5%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.9), transparent);
  pointer-events: none;
}

/* 彩色背景光晕（用在玻璃卡片所在的容器上，为 backdrop-filter 提供可模糊内容）。
   用法：在玻璃卡片的父容器加 class="lg-bg"，内部放若干 .lg-glow 定位光斑。 */
.lg-bg {
  position: relative;
  overflow: hidden;
}
.lg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.55;
  pointer-events: none;
  z-index: 0;
}
.lg-glow.g1 { background: radial-gradient(circle, #ffb76b, rgba(255,183,107,0)); }
.lg-glow.g2 { background: radial-gradient(circle, #9ea7ff, rgba(158,167,255,0)); }
.lg-glow.g3 { background: radial-gradient(circle, #6bf0c6, rgba(107,240,198,0)); }
.lg-glow.g4 { background: radial-gradient(circle, #ff8fd0, rgba(255,143,208,0)); }
</style>
