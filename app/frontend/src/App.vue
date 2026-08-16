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
   更透明玻璃 —— 背景透明度低至 rgba(255,255,255,0.20)，边框更亮
   rgba(255,255,255,0.65)，backdrop-filter blur 10px + saturate 170%，
   让背景彩色光晕透出来。启用 @ybouane/liquidglass 的真实 WebGL 液态玻璃后，
   此处作为不支持 WebGL 时的 CSS 降级兜底。 */
.liquid-glass {
  background: rgba(255,255,255,0.20);
  border: 1px solid rgba(255,255,255,0.65);
  border-radius: 20px;
  box-shadow:
    0 8px 32px rgba(0,0,0,0.06),
    inset 0 1px 0 rgba(255,255,255,0.85),
    inset 0 -1px 0 rgba(255,255,255,0.2);
  backdrop-filter: saturate(170%) blur(10px);
  -webkit-backdrop-filter: saturate(170%) blur(10px);
  /* 玻璃高光：一条沿顶部的细亮线模拟反射 */
  position: relative;
  transition: backdrop-filter 0.2s ease;
}
.liquid-glass::before {
  content: '';
  position: absolute;
  top: 0;
  left: 5%;
  right: 5%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.95), transparent);
  pointer-events: none;
}

/* ------- 控件玻璃化（按钮 / 输入框 / 下拉 / 文本域） -------
   给主要控件加半透明背景 + 细亮边框 + 轻 backdrop-filter，
   与液态玻璃卡片保持同一质感。文字保持深色高对比以保证可读性。
   选择器尽量通用：玻璃卡内的按钮与字段、各页面的专用控件。 */
.liquid-glass button,
.liquid-glass input,
.liquid-glass select,
.liquid-glass textarea,
.liquid-glass .field-input,
.liquid-glass .upload-zone {
  backdrop-filter: saturate(150%) blur(8px);
  -webkit-backdrop-filter: saturate(150%) blur(8px);
}
.liquid-glass .btn,
.liquid-glass .upload-zone {
  background: rgba(255,255,255,0.28);
  border: 1px solid rgba(255,255,255,0.55);
}
.liquid-glass .field-input {
  background: rgba(255,255,255,0.28);
  border: 1px solid rgba(255,255,255,0.5);
}
/* 首页控制台内专用控件 */
.console-card .btn,
.console-card .btn-primary,
.console-card .mode-tab,
.console-card .media-toggle {
  backdrop-filter: saturate(150%) blur(8px);
  -webkit-backdrop-filter: saturate(150%) blur(8px);
  border: 1px solid rgba(255,255,255,0.6);
}
.console-card .btn {
  background: rgba(255,255,255,0.30);
}
/* 主 CTA 按钮：半透明玻璃但不失柑橘主色认同，文字高对比保证可读 */
.console-card .btn-primary {
  background: rgba(161,197,10,0.72);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.55);
}
.console-card .btn-primary:hover:not(:disabled) {
  background: rgba(143,174,9,0.82);
}
/* 世界设定页 step-card / sim 控件 */
.step-card button,
.step-card input,
.step-card select,
.step-card textarea {
  backdrop-filter: saturate(150%) blur(8px);
  -webkit-backdrop-filter: saturate(150%) blur(8px);
}
.step-card .sim-input,
.step-card .sim-goal-input,
.step-card .world-textarea,
.step-card .search-input,
.step-card .justify-input,
.step-card .assistant-input {
  background: rgba(255,255,255,0.30);
  border: 1px solid rgba(255,255,255,0.5);
}
/* 时间线 tl-btn / 输入条 */
.tl-btn,
.tl-play-btn,
.branch-chip,
.type-chip,
.future-input,
.tl-edit-input {
  backdrop-filter: saturate(150%) blur(8px);
  -webkit-backdrop-filter: saturate(150%) blur(8px);
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

/* ================= 手机端响应式（全局，覆盖所有页面） ================= */
html, body {
  overflow-x: hidden;
}

/* ---- ≤768px（平板竖屏 / 大手机） ---- */
@media (max-width: 768px) {
  /* App 根背景白，防止浏览器橡皮筋露黑边 */
  #app { background-color: #ffffff; }
}

/* ---- ≤480px（手机）：
     通用控件玻璃化的模糊可收窄以省 GPU，避免小屏卡顿 ---- */
@media (max-width: 480px) {
  .liquid-glass,
  .liquid-glass button,
  .liquid-glass input,
  .liquid-glass select,
  .liquid-glass textarea,
  .step-card button,
  .step-card input,
  .step-card select,
  .step-card textarea,
  .tl-btn,
  .tl-play-btn {
    backdrop-filter: saturate(150%) blur(6px);
    -webkit-backdrop-filter: saturate(150%) blur(6px);
  }
  #app { background-color: #ffffff; }
}

</style>
