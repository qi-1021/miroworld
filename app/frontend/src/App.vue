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
  <!--
    MiroFish 液态玻璃 SVG 滤镜定义（隐藏，供 CSS 通过 url(#...) 引用）。
    以 GitHub nikdelvin/liquid-glass（纯 CSS+SVG 复刻 Apple iOS 26 Liquid Glass）为蓝本：
      - #lg-morph  ：feTurbulence 位移扰动，还原玻璃表面的"液态折射"边缘。
      - #lg-gloss  ：feSpecularLighting 镜面高光，还原玻璃光泽。
    纯 CSS + 内联 SVG，无 npm 依赖、无 WebGL。
  -->
  <svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
    <defs>
      <filter id="lg-morph" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.012 0.018" numOctaves="2" seed="7" result="noise"/>
        <feDisplacementMap in="SourceGraphic" in2="noise" scale="14" xChannelSelector="R" yChannelSelector="G"/>
      </filter>
      <filter id="lg-gloss" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
        <feGaussianBlur stdDeviation="2.2" result="blur"/>
        <feSpecularLighting in="blur" specularConstant="0.75" specularExponent="24" surfaceScale="3" lighting-color="#ffffff" result="spec">
          <fePointLight x="30%" y="-20%" z="220"/>
        </feSpecularLighting>
        <feComposite in="spec" in2="SourceAlpha" operator="in"/>
      </filter>
    </defs>
  </svg>
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
   MiroFish 全站视觉（frontend-dev）
   设计语言：LGGC 液态玻璃升级版（蓝本 nikdelvin/liquid-glass 纯 CSS+SVG）
   - 保持 #f5f5f7 浅画布 + 柑橘强调色 #a1c50a
   - glass 纯 CSS + 内联 SVG 滤镜（#lg-morph 位移扰动 / #lg-gloss 镜面高光）
   - 无 npm 依赖、无 WebGL、无彩色光晕
   ============================================================ */

/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  overflow-x: clip;
  /* 用 clip 而非 hidden：clip 不创建横向滚动容器，装饰性光晕
     不会撑大 body.scrollWidth，也就不会让滚动到底部时布局/卡片错位。 */
}

:root {
  /* ---- 设计 tokens ---- */
  --mf-canvas: #f5f7fb;            /* 页面基底（带蓝调的浅色） */
  --mf-ink: #10203a;               /* 主文字（深海军蓝，与 LGGC 一致） */
  --mf-ink-muted: #536078;
  --mf-ink-subtle: #7b879e;
  --mf-accent: #a1c50a;            /* 柑橘色 */
  --mf-accent-hover: #8fae09;
  --mf-accent-soft: #f3f7e6;
  --mf-hairline: rgba(16, 32, 58, 0.12);
  --mf-radius: 8px;
  --mf-card-shadow: 0 10px 30px rgba(16, 32, 58, 0.08);
}

#app {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'PingFang SC',
    'Noto Sans SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--mf-ink);
  /* 苹果风：干净浅灰画布，不做花哨渐变。液态玻璃靠卡片自身的 LGGC 效果呈现。 */
  background-color: #f5f5f7;
  background-image: none;
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
   LGGC 液态玻璃通用卡片（终极升级版）
   蓝本：GitHub nikdelvin/liquid-glass（纯 CSS+SVG 复刻 Apple iOS 26 Liquid Glass）
   三层液态结构：
     layer 1 ::before —— 顶部液态折光带（filter:url(#lg-morph) 位移扰动，边缘像水波）
     layer 2 ::after  —— 镜面高光（filter:url(#lg-gloss) 模拟玻璃光泽的反光）
     backdrop-filter —— 磨砂透模糊 + 提亮 + 增饱和，透出 #f5f5f7 画布
   保持 .liquid-glass / 手机端降级接口不变，自动覆盖全站卡片。
   ============================================================ */
.liquid-glass {
  --lggc-radius: 8px;
  --lggc-padding: 1.5rem 1.75rem;
  --lggc-bg: rgba(255, 255, 255, 0.42);
  --lggc-border: rgba(255, 255, 255, 0.92);
  --lggc-blur: 16px;
  --lggc-highlight: rgba(255, 255, 255, 1);
  position: relative;
  isolation: isolate;
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: var(--lggc-radius);
  background:
    radial-gradient(120% 140% at 18% -12%, rgba(255, 255, 255, 0.62), transparent 46%),
    var(--lggc-bg);
  color: var(--mf-ink);
  backdrop-filter: blur(var(--lggc-blur)) saturate(185%) brightness(1.08);
  -webkit-backdrop-filter: blur(var(--lggc-blur)) saturate(185%) brightness(1.08);
  box-shadow:
    /* 玻璃投影：轻微冷灰、柔和 */
    0 0 0 1px rgba(16, 32, 58, 0.07),
    0 24px 48px rgba(16, 32, 58, 0.14),
    0 8px 18px rgba(16, 32, 58, 0.08),
    /* 液态内缘：上下亮沿 + 侧向暗沿，模拟玻璃厚度与折射 */
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 -1px 0 rgba(255, 255, 255, 0.55),
    inset 1px 0 0 rgba(255, 255, 255, 0.45),
    inset -1px 0 0 rgba(255, 255, 255, 0.45);
  transition: box-shadow 0.25s ease, transform 0.25s ease, background 0.25s ease;
}
/* 顶部液态折光带：位移扰动让玻璃上沿像水波一样折射 */
.liquid-glass::before {
  content: '';
  position: absolute;
  top: -1px; left: 6%; right: 6%;
  height: 3px;
  border-radius: var(--lggc-radius);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.98) 18%, rgba(255, 255, 255, 0.75) 50%, rgba(255, 255, 255, 0.98) 82%, transparent);
  filter: url(#lg-morph);
  -webkit-filter: url(#lg-morph);
  opacity: 0.9;
  pointer-events: none;
  z-index: 1;
}
/* 镜面高光：左上部一片柔和反光，还原玻璃光泽 */
.liquid-glass::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background:
    linear-gradient(148deg, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0) 34%),
    radial-gradient(90% 70% at 30% 0%, rgba(255, 255, 255, 0.28), transparent 62%);
  filter: url(#lg-gloss);
  -webkit-filter: url(#lg-gloss);
  mix-blend-mode: screen;
  pointer-events: none;
  z-index: 1;
}
.liquid-glass:hover {
  background:
    radial-gradient(120% 140% at 18% -12%, rgba(255, 255, 255, 0.68), transparent 46%),
    rgba(255, 255, 255, 0.55);
  box-shadow:
    0 0 0 1px rgba(16, 32, 58, 0.08),
    0 32px 60px rgba(16, 32, 58, 0.18),
    0 12px 24px rgba(16, 32, 58, 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 0.98),
    inset 0 -1px 0 rgba(255, 255, 255, 0.6);
  transform: translateY(-2px);
}

/* ============================================================
   通用控件玻璃化（按钮 / 输入框 / 下拉 / 文本域）：
   与 LGGC 液态玻璃卡片保持同一通透质感，文字高对比保证可读。
   ============================================================ */
.btn, button.btn, .field-input, textarea, input[type="text"],
input[type="email"], input[type="search"] {
  font-family: inherit;
}


/* ------- 控件玻璃化（按钮 / 输入框 / 下拉 / 文本域） -------
   与升级后的液态玻璃卡片同一通透质感：磨砂模糊 + 提亮 + 液态内缘高光。
   文字保持深色高对比以保证可读。 */
.liquid-glass button,
.liquid-glass input,
.liquid-glass select,
.liquid-glass textarea,
.liquid-glass .field-input,
.liquid-glass .upload-zone,
.liquid-glass .mode-tab,
.liquid-glass .media-toggle {
  backdrop-filter: blur(10px) saturate(170%) brightness(1.05);
  -webkit-backdrop-filter: blur(10px) saturate(170%) brightness(1.05);
  border: 1px solid rgba(255, 255, 255, 0.65);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    inset 0 -1px 0 rgba(255, 255, 255, 0.35);
}
.liquid-glass .btn,
.liquid-glass .upload-zone,
.liquid-glass .field-input,
.liquid-glass input[type="text"],
.liquid-glass textarea {
  background: rgba(255, 255, 255, 0.30);
  border: 1px solid rgba(255, 255, 255, 0.65);
}
.liquid-glass .btn-primary {
  background: rgba(161, 197, 10, 0.86);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.65);
  box-shadow:
    0 6px 16px rgba(161, 197, 10, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
}
.liquid-glass .btn-primary:hover:not(:disabled) {
  background: rgba(143, 174, 9, 0.94);
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
  backdrop-filter: blur(9px) saturate(165%) brightness(1.05);
  -webkit-backdrop-filter: blur(9px) saturate(165%) brightness(1.05);
}
.step-card .sim-input,
.step-card .sim-goal-input,
.step-card .world-textarea,
.step-card .search-input,
.step-card .justify-input,
.step-card .assistant-input {
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

/* ================= 手机端响应式（全局，覆盖所有页面） ================= */

/* ---- ≤768px（平板竖屏 / 大手机）：窄屏收紧内边距，避免拥挤 ---- */
@media (max-width: 768px) {
  #app { background-attachment: scroll; }
  .liquid-glass {
    --lggc-radius: 8px;
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
  #app {
    background-color: #f5f5f7;
    background-image: none;
    background-attachment: scroll;
  }
}


</style>
