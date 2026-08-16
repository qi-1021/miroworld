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
/* ============================================================
   MiroFish 全站视觉重做（frontend-dev）
   设计语言：LGGC 纯 CSS 液态玻璃 + 柔和渐变光底 + 柑橘强调色
   - glass 由 LGGC（.lggc / 其 CSS 变量）驱动，纯 CSS，无 WebGL
   - 强调色保留柑橘色 #a1c50a（用户指定）
   ============================================================ */

/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  overflow-x: hidden;
}

:root {
  /* ---- 设计 tokens ---- */
  --mf-canvas: #f5f7fb;            /* 页面基底（带蓝调的浅色） */
  --mf-ink: #10203a;               /* 主文字（深海军蓝，与 LGGC 一致） */
  --mf-ink-muted: #536078;
  --mf-ink-subtle: #7b879e;
  --mf-accent: #a1c50a;            /* 柑橘色（用户指定，保留） */
  --mf-accent-hover: #8fae09;
  --mf-accent-soft: #f3f7e6;
  --mf-hairline: rgba(16, 32, 58, 0.12);
  --mf-radius: 18px;
  --mf-card-shadow: 0 10px 30px rgba(16, 32, 58, 0.08);
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'PingFang SC',
    'Noto Sans SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--mf-ink);
  /* 柔和渐变光底：为液态玻璃的 backdrop-filter 提供可模糊的彩色内容 */
  background:
    radial-gradient(120% 90% at 0% 0%, rgba(165, 200, 246, 0.55), transparent 55%),
    radial-gradient(130% 100% at 100% 0%, rgba(242, 246, 226, 0.7), transparent 55%),
    radial-gradient(140% 120% at 50% 100%, rgba(253, 206, 206, 0.55), transparent 60%),
    linear-gradient(135deg, #eef4fb 0%, #f6f8ec 48%, #fff1ee 100%);
  background-attachment: fixed;
  min-height: 100vh;
}

/* 滚动条样式 */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(16, 32, 58, 0.25); border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: rgba(16, 32, 58, 0.4); }

/* 全局按钮样式 */
button { font-family: inherit; }

/* ============================================================
   LGGC 液态玻璃通用卡片：
   全站 .liquid-glass 卡片改用 LGGC（纯 CSS）效果。
   通过 LGGC 变量微调圆角/底色/模糊，让既有 class 自动升级为液态玻璃。
   ============================================================ */
.liquid-glass {
  --lggc-radius: 22px;
  --lggc-padding: 1.5rem 1.75rem;
  --lggc-bg: rgba(255, 255, 255, 0.35);
  --lggc-border: rgba(255, 255, 255, 0.5);
  --lggc-blur: 10px;
  --lggc-highlight: rgba(255, 255, 255, 0.9);
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: var(--lggc-radius);
  background: var(--lggc-bg);
  color: var(--mf-ink);
  backdrop-filter: blur(calc(var(--lggc-blur) * 0.35)) saturate(170%);
  -webkit-backdrop-filter: blur(calc(var(--lggc-blur) * 0.35)) saturate(170%);
  box-shadow:
    inset 1.5px -1.5px 1px -1px rgba(255, 255, 255, 0.8),
    inset -1.5px 1.5px 1px -1px rgba(255, 255, 255, 0.8),
    0 16px 36px rgba(16, 32, 58, 0.10);
  transition: box-shadow 0.2s ease, transform 0.2s ease, background 0.2s ease;
}
.liquid-glass::before {
  content: '';
  position: absolute;
  top: 0; left: 8%; right: 8%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.95), transparent);
  pointer-events: none;
  border-radius: inherit;
  z-index: 1;
}
.liquid-glass:hover {
  box-shadow:
    inset 1.5px -1.5px 1px -1px rgba(255, 255, 255, 0.9),
    inset -1.5px 1.5px 1px -1px rgba(255, 255, 255, 0.9),
    0 22px 44px rgba(16, 32, 58, 0.14);
  transform: translateY(-2px);
}

/* LGGC 彩色光晕（放在玻璃卡父容器，为 backdrop-filter 提供可模糊内容） */
.lg-bg { position: relative; overflow: hidden; }
.lg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.5;
  pointer-events: none;
  z-index: 0;
}
.lg-glow.g1 { background: radial-gradient(circle, #ffb76b, rgba(255,183,107,0)); }
.lg-glow.g2 { background: radial-gradient(circle, #9ea7ff, rgba(158,167,255,0)); }
.lg-glow.g3 { background: radial-gradient(circle, #6bf0c6, rgba(107,240,198,0)); }
.lg-glow.g4 { background: radial-gradient(circle, #ff8fd0, rgba(208,143,255,0)); }

/* ============================================================
   通用控件玻璃化（按钮 / 输入框 / 下拉 / 文本域）：
   与 LGGC 液态玻璃卡片保持同一通透质感，文字高对比保证可读。
   ============================================================ */
.btn, button.btn, .field-input, textarea, input[type="text"],
input[type="email"], input[type="search"] {
  font-family: inherit;
}


/* ------- 控件玻璃化（按钮 / 输入框 / 下拉 / 文本域） -------
   给主要控件加半透明背景 + 细亮边框 + 轻 backdrop-filter，
   与 LGGC 液态玻璃卡片保持同一通透质感。文字保持深色高对比以保证可读。 */
.liquid-glass button,
.liquid-glass input,
.liquid-glass select,
.liquid-glass textarea,
.liquid-glass .field-input,
.liquid-glass .upload-zone,
.liquid-glass .mode-tab,
.liquid-glass .media-toggle {
  backdrop-filter: saturate(160%) blur(8px);
  -webkit-backdrop-filter: saturate(160%) blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.55);
}
.liquid-glass .btn,
.liquid-glass .upload-zone,
.liquid-glass .field-input,
.liquid-glass input[type="text"],
.liquid-glass textarea {
  background: rgba(255, 255, 255, 0.30);
  border: 1px solid rgba(255, 255, 255, 0.55);
}
.liquid-glass .btn-primary {
  background: rgba(161, 197, 10, 0.78);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.55);
}
.liquid-glass .btn-primary:hover:not(:disabled) {
  background: rgba(143, 174, 9, 0.88);
}

/* 世界设定页 step-card / sim 控件、时间线控件的玻璃降级 */
.step-card button,
.step-card input,
.step-card select,
.step-card textarea,
.tl-btn,
.tl-play-btn,
.branch-chip,
.type-chip,
.future-input,
.tl-edit-input {
  backdrop-filter: saturate(160%) blur(8px);
  -webkit-backdrop-filter: saturate(160%) blur(8px);
}
.step-card .sim-input,
.step-card .sim-goal-input,
.step-card .world-textarea,
.step-card .search-input,
.step-card .justify-input,
.step-card .assistant-input {
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid rgba(255, 255, 255, 0.55);
}

/* ================= 手机端响应式（全局，覆盖所有页面） ================= */

/* ---- ≤768px（平板竖屏 / 大手机）：窄屏收紧内边距，避免拥挤 ---- */
@media (max-width: 768px) {
  #app { background-attachment: scroll; }
  .liquid-glass {
    --lggc-radius: 18px;
    --lggc-padding: 1.25rem 1.25rem;
  }
}

/* ---- ≤480px（手机）：
     通用控件玻璃化的模糊可收窄以省 GPU，避免小屏卡顿。
     光晕/装饰收敛，避免小屏横向滚动。 ---- */
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
    backdrop-filter: saturate(150%) blur(5px);
    -webkit-backdrop-filter: saturate(150%) blur(5px);
  }
  .lg-glow { opacity: 0.35; filter: blur(40px); }
  #app {
    background:
      radial-gradient(150% 70% at 20% 0%, rgba(165, 200, 246, 0.5), transparent 60%),
      linear-gradient(140deg, #eef4fb 0%, #f6f8ec 50%, #fff1ee 100%);
    background-attachment: scroll;
  }
}


</style>
