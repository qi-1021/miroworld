<!--
  首页（Apple 极简白 + 柑橘橙主题）
  设计 tokens：背景 #fff/#f5f5f7，文字 #1d1d1f/#6e6e73，强调色柑橘色 #a1c50a（用户指定）
  禁用：蓝紫色系、渐变、玻璃拟态、粗阴影（见 apple-minimal skill 规范）
  品牌名来自 src/config/brand.js（改名只改一处）
-->
<template>
  <div class="home">
    <!-- 单行导航 -->
    <nav class="nav">
      <span class="nav-brand">{{ BRAND.name }}</span>
      <div class="nav-right">
        <LanguageSwitcher />
        <button class="nav-link nav-btn" @click="openWorldLibrary">{{ $t('home.openWorldLibrary') }}</button>
        <a class="nav-link" :href="BRAND.repo" target="_blank" rel="noopener">{{ $t('nav.visitGithub') }}<span class="arrow">↗</span></a>
      </div>
    </nav>

    <!-- Hero -->
    <header class="hero">
      <p class="hero-kicker">{{ $t('home.heroKicker') }}</p>
      <h1 class="hero-title">
        {{ $t('home.heroTitle1') }}<br />
        <span class="accent">{{ $t('home.heroTitle2') }}</span>
      </h1>
      <p class="hero-desc">{{ $t('home.heroDescNew') }}</p>
      <div class="hero-cta">
        <button class="btn btn-primary" @click="scrollToConsole">{{ $t('home.ctaStart') }}</button>
      </div>

      <!-- 产品视觉：纯 CSS 时间线示意图（主线 + 橙色分支） -->
      <div class="hero-visual" aria-hidden="true">
        <div class="tl-demo">
          <div class="tl-main">
            <span class="dot done"></span>
            <span class="dot done"></span>
            <span class="dot done"></span>
            <span class="dot now"></span>
            <span class="dot future"></span>
            <span class="dot future"></span>
          </div>
          <div class="tl-branch">
            <span class="branch-node"></span>
            <span class="branch-line-h"></span>
            <span class="branch-node"></span>
            <span class="branch-line-h"></span>
            <span class="branch-node"></span>
            <span class="branch-label">{{ $t('home.visualBranch') }}</span>
          </div>
          <div class="tl-caption">
            <span class="cap now-label">{{ $t('home.visualNow') }}</span>
            <span class="cap future-label">{{ $t('home.visualFuture') }}</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 特性 -->
    <section class="features">
      <div class="lg-bg features-bg">
        <div class="lg-glow g2 fg-left"></div>
        <div class="lg-glow g1 fg-right"></div>
      </div>
      <div class="features-head">
        <h2 class="section-title">{{ $t('home.featuresTitle') }}</h2>
        <p class="section-desc">{{ $t('home.featuresDesc') }}</p>
      </div>
      <div class="feature-grid">
        <div class="feature-card liquid-glass">
          <div class="f-icon">▤</div>
          <h3 class="f-title">{{ $t('home.f1Title') }}</h3>
          <p class="f-desc">{{ $t('home.f1Desc') }}</p>
        </div>
        <div class="feature-card liquid-glass">
          <div class="f-icon">⑃</div>
          <h3 class="f-title">{{ $t('home.f2Title') }}</h3>
          <p class="f-desc">{{ $t('home.f2Desc') }}</p>
        </div>
        <div class="feature-card liquid-glass">
          <div class="f-icon">◉</div>
          <h3 class="f-title">{{ $t('home.f3Title') }}</h3>
          <p class="f-desc">{{ $t('home.f3Desc') }}</p>
        </div>
        <div class="feature-card liquid-glass">
          <div class="f-icon">✎</div>
          <h3 class="f-title">{{ $t('home.f4Title') }}</h3>
          <p class="f-desc">{{ $t('home.f4Desc') }}</p>
        </div>
      </div>
    </section>

    <!-- 控制台 -->
    <section class="console-section" ref="consoleRef">
      <div class="lg-bg console-bg">
        <div class="lg-glow g3 cg-left"></div>
        <div class="lg-glow g4 cg-top"></div>
        <div class="lg-glow g2 cg-right"></div>
        <div class="lg-glow g1 cg-bottom"></div>
      </div>
      <div class="console-head">
        <h2 class="section-title">{{ $t('home.consoleTitle') }}</h2>
        <div class="mode-tabs">
          <button class="mode-tab" :class="{ active: activeMode === 'world' }" @click="activeMode = 'world'">
            {{ $t('home.modeWorld') }}
          </button>
          <button v-if="mediaModeEnabled" class="mode-tab" :class="{ active: activeMode === 'media' }" @click="activeMode = 'media'">
            {{ $t('home.modeMedia') }}
          </button>
        </div>
        <button class="media-toggle" @click="toggleMediaMode">
          {{ mediaModeEnabled ? $t('home.hideMediaMode') : $t('home.showMediaMode') }}
        </button>
      </div>

      <div class="console-card liquid-glass">
        <!-- ===== 媒体分析（可隐藏） ===== -->
        <template v-if="mediaModeEnabled && activeMode === 'media'">
          <div class="form-row">
            <label class="field-label">{{ $t('home.realitySeed') }}<span class="field-meta">{{ $t('home.supportedFormats') }}</span></label>
            <div class="upload-zone" :class="{ 'drag-over': isDragOver, 'has-files': files.length > 0 }"
              @dragover.prevent="handleDragOver" @dragleave.prevent="handleDragLeave"
              @drop.prevent="handleDrop" @click="triggerFileInput">
              <input ref="fileInput" type="file" multiple accept=".pdf,.md,.txt" @change="handleFileSelect" style="display: none" :disabled="loading" />
              <div v-if="files.length === 0" class="upload-placeholder">
                <div class="upload-icon">↑</div>
                <div class="upload-title">{{ $t('home.dragToUpload') }}</div>
                <div class="upload-hint">{{ $t('home.orBrowse') }}</div>
              </div>
              <div v-else class="file-list">
                <div v-for="(file, index) in files" :key="index" class="file-item">
                  <span class="file-icon">📄</span>
                  <span class="file-name">{{ file.name }}</span>
                  <button @click.stop="removeFile(index)" class="remove-btn">×</button>
                </div>
              </div>
            </div>
          </div>

          <div class="form-row">
            <label class="field-label">{{ $t('home.taskGoal') }}<span class="field-meta">{{ $t('home.taskGoalMeta') }}</span></label>
            <textarea v-model="formData.simulationRequirement" class="field-input" rows="2"
              :placeholder="$t('home.taskGoalPlaceholder')" :disabled="loading"></textarea>
          </div>

          <div class="form-row">
            <label class="field-label">{{ $t('home.extraContext') }}<span class="field-meta">{{ $t('home.extraContextMeta') }}</span></label>
            <textarea v-model="formData.additionalContext" class="field-input" rows="3"
              :placeholder="$t('home.extraContextPlaceholder')" :disabled="loading"></textarea>
          </div>

          <div class="form-actions">
            <div v-if="modelConfigAlert" class="model-config-alert">
              <span class="mc-text">⚠ {{ modelConfigAlert }}</span>
              <button class="mc-link" type="button" @click="openModelSettings">{{ $t('home.configureModel') }}</button>
            </div>
            <div v-if="error" class="world-error">{{ error }}</div>
            <button class="btn btn-primary btn-lg" @click="startSimulation"
              :class="{ 'btn-disabled': !canSubmit }" :disabled="loading"
              :title="!canSubmit ? $t('home.mediaEmptyHint') : ''">
              <span v-if="!loading">{{ $t('home.startEngine') }}</span>
              <span v-else>{{ $t('home.initializing') }}</span>
              <span class="btn-arrow">→</span>
            </button>
          </div>
        </template>

        <!-- ===== 世界模拟 ===== -->
        <template v-else>
          <div class="form-row">
            <label class="field-label">{{ $t('home.worldBgLabel') }}<span class="field-meta">{{ $t('home.supportedFormats') }}</span></label>
            <div class="upload-zone compact" :class="{ 'drag-over': bgDragOver, 'has-files': worldBgFiles.length > 0 }"
              @dragover.prevent="bgDragOver = true" @dragleave.prevent="bgDragOver = false"
              @drop.prevent="handleWorldDrop($event, 'bg')" @click="triggerWorldInput('bg')">
              <input ref="bgFileInput" type="file" multiple accept=".pdf,.md,.txt" @change="handleWorldFiles($event, 'bg')" style="display: none" :disabled="loading" />
              <div v-if="worldBgFiles.length === 0" class="upload-placeholder">
                <div class="upload-icon">↑</div>
                <div class="upload-title">{{ $t('home.worldBgUpload') }}</div>
                <div class="upload-hint">{{ $t('home.orBrowse') }}</div>
              </div>
              <div v-else class="file-list">
                <div v-for="(file, index) in worldBgFiles" :key="index" class="file-item">
                  <span class="file-icon">📄</span>
                  <span class="file-name">{{ file.name }}</span>
                  <button @click.stop="removeWorldFile(index, 'bg')" class="remove-btn">×</button>
                </div>
              </div>
            </div>
            <textarea v-model="worldBgText" class="field-input" rows="2" :placeholder="$t('home.worldBgTextPlaceholder')" :disabled="loading"></textarea>
          </div>

          <div class="form-row">
            <label class="field-label">{{ $t('home.worldStoryLabel') }}<span class="field-meta">{{ $t('home.supportedFormats') }}</span></label>
            <div class="upload-zone compact" :class="{ 'drag-over': storyDragOver, 'has-files': worldStoryFiles.length > 0 }"
              @dragover.prevent="storyDragOver = true" @dragleave.prevent="storyDragOver = false"
              @drop.prevent="handleWorldDrop($event, 'story')" @click="triggerWorldInput('story')">
              <input ref="storyFileInput" type="file" multiple accept=".pdf,.md,.txt" @change="handleWorldFiles($event, 'story')" style="display: none" :disabled="loading" />
              <div v-if="worldStoryFiles.length === 0" class="upload-placeholder">
                <div class="upload-icon">↑</div>
                <div class="upload-title">{{ $t('home.worldStoryUpload') }}</div>
                <div class="upload-hint">{{ $t('home.orBrowse') }}</div>
              </div>
              <div v-else class="file-list">
                <div v-for="(file, index) in worldStoryFiles" :key="index" class="file-item">
                  <span class="file-icon">📄</span>
                  <span class="file-name">{{ file.name }}</span>
                  <button @click.stop="removeWorldFile(index, 'story')" class="remove-btn">×</button>
                </div>
              </div>
            </div>
            <textarea v-model="worldStoryText" class="field-input" rows="2" :placeholder="$t('home.worldStoryTextPlaceholder')" :disabled="loading"></textarea>
          </div>

          <div class="form-row">
            <label class="field-label">{{ $t('home.worldGoalLabel') }}<span class="field-meta">{{ $t('home.worldGoalMeta') }}</span></label>
            <textarea v-model="worldGoal" class="field-input" rows="2" :placeholder="$t('home.worldGoalPlaceholder')" :disabled="loading"></textarea>
          </div>

          <div class="form-row">
            <p class="world-divider">{{ $t('home.worldDivider') }}</p>
          </div>

          <div class="form-actions">
            <div v-if="worldError" class="world-error">{{ worldError }}</div>
            <div v-if="modelConfigAlert" class="model-config-alert">
              <span class="mc-text">⚠ {{ modelConfigAlert }}</span>
              <button class="mc-link" type="button" @click="openModelSettings">{{ $t('home.configureModel') }}</button>
            </div>
            <button class="btn btn-primary btn-lg" @click="createWorldProject"
              :class="{ 'btn-disabled': !canCreateWorld }" :disabled="loading"
              :title="!canCreateWorld ? $t('home.worldEmptyHint') : ''">
              <span v-if="!loading">{{ $t('home.createWorld') }}</span>
              <span v-else>{{ $t('home.creatingWorld') }}</span>
              <span class="btn-arrow">→</span>
            </button>
          </div>
        </template>
      </div>
    </section>

    <!-- 历史项目 -->
    <section class="history-section">
      <HistoryDatabase />
    </section>

    <footer class="footer">
      <span class="footer-note">© {{ year }} {{ BRAND.name }} · {{ $t('home.footerNote') }}</span>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import { BRAND } from '../config/brand'
import { createProject } from '../api/graph'
import { saveWorldInputMultipart } from '../api/world'
import { getModelRegistry } from '../api/models'

const router = useRouter()
const { t } = useI18n()

// 表单数据
const formData = ref({
  simulationRequirement: '',  // 任务目标（必填）
  additionalContext: ''       // 附加说明（可选）
})

// 文件列表
const files = ref([])

// 状态
const loading = ref(false)
const error = ref('')
const isDragOver = ref(false)
const consoleRef = ref(null)
const year = new Date().getFullYear()

// ============ 模型配置前置校验 ============
// 空字符串表示已通过；非空表示需要引导用户前往模型设置
const modelConfigAlert = ref('')

/**
 * 提交前校验：注册表中是否存在已通过连接验证（verified）的模型。
 * 媒体分析 / 世界模拟两种模式共用。
 * @return {Promise<boolean>} true=可用，可继续；false=无可用模型，已弹出引导
 */
const ensureModelConfigured = async () => {
  try {
    // 8 秒超时：避免模型注册表接口异常时按钮长时间无反馈
    const res = await Promise.race([
      getModelRegistry(),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000))
    ])
    const registry = res?.data || res || {}
    const models = registry.models || []
    const hasVerified = models.some(item => item.verified)
    if (hasVerified) {
      modelConfigAlert.value = ''
      return true
    }
    modelConfigAlert.value = t('home.modelConfigRequired')
    return false
  } catch (e) {
    // 查询失败/超时时同样视为未就绪并引导配置，避免提交后连接凭空失败
    modelConfigAlert.value = t('home.modelConfigCheckFailed')
    return false
  }
}

// 一键打开模型设置（App.vue 监听 open-model-settings 事件）
const openModelSettings = () => {
  window.dispatchEvent(new CustomEvent('open-model-settings'))
}

// ============ 模式选择：世界推演（第一优先）/ 舆情分析（第二，可隐藏） ============
const activeMode = ref('world')
const mediaModeEnabled = ref(localStorage.getItem('mirofish.mediaMode') !== 'hidden')
function toggleMediaMode() {
  mediaModeEnabled.value = !mediaModeEnabled.value
  if (!mediaModeEnabled.value && activeMode.value === 'media') activeMode.value = 'world'
  localStorage.setItem('mirofish.mediaMode', mediaModeEnabled.value ? 'visible' : 'hidden')
}

// 世界模拟：背景资料 / 章节正文（各支持多文件 + 直接文本）
const worldBgFiles = ref([])
const worldStoryFiles = ref([])
const worldBgText = ref('')
const worldStoryText = ref('')
const worldGoal = ref('')  // 任务目标（可选，世界推演的默认目标）
const worldError = ref('')
const bgDragOver = ref(false)
const storyDragOver = ref(false)
const bgFileInput = ref(null)
const storyFileInput = ref(null)

// 文件输入引用
const fileInput = ref(null)

// 计算属性:是否可以提交（媒体分析）
const canSubmit = computed(() => {
  return formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
})

// 计算属性：是否可以创建世界（背景/正文至少一项非空）
const canCreateWorld = computed(() => {
  return (
    worldBgFiles.value.length > 0 ||
    worldStoryFiles.value.length > 0 ||
    worldBgText.value.trim() !== '' ||
    worldStoryText.value.trim() !== ''
  )
})

// 触发文件选择
const triggerFileInput = () => {
  if (!loading.value) {
    fileInput.value?.click()
  }
}

// 处理文件选择
const handleFileSelect = (event) => {
  const selectedFiles = Array.from(event.target.files)
  addFiles(selectedFiles)
}

// 处理拖拽相关
const handleDragOver = (e) => {
  if (!loading.value) {
    isDragOver.value = true
  }
}

const handleDragLeave = (e) => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return

  const droppedFiles = Array.from(e.dataTransfer.files)
  addFiles(droppedFiles)
}

// 添加文件
const addFiles = (newFiles) => {
  const validFiles = newFiles.filter(file => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ['pdf', 'md', 'txt'].includes(ext)
  })
  files.value.push(...validFiles)
}

// 移除文件
const removeFile = (index) => {
  files.value.splice(index, 1)
}

// ============ 世界模拟模式：资料上传 ============
const triggerWorldInput = (kind) => {
  if (!loading.value) {
    if (kind === 'bg') bgFileInput.value?.click()
    else storyFileInput.value?.click()
  }
}

const handleWorldFiles = (event, kind) => {
  const target = kind === 'bg' ? worldBgFiles : worldStoryFiles
  const selected = Array.from(event.target.files).filter(file => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ['pdf', 'md', 'txt', 'markdown'].includes(ext)
  })
  target.value.push(...selected)
  // 允许再次选择同一文件
  event.target.value = ''
}

const handleWorldDrop = (e, kind) => {
  if (kind === 'bg') bgDragOver.value = false
  else storyDragOver.value = false
  if (loading.value) return
  const droppedFiles = Array.from(e.dataTransfer.files).filter(file => {
    const ext = file.name.split('.').pop().toLowerCase()
    return ['pdf', 'md', 'txt', 'markdown'].includes(ext)
  })
  const target = kind === 'bg' ? worldBgFiles : worldStoryFiles
  target.value.push(...droppedFiles)
}

const removeWorldFile = (index, kind) => {
  const target = kind === 'bg' ? worldBgFiles : worldStoryFiles
  target.value.splice(index, 1)
}

// 创建世界项目：建项目 → 上传资料 → 进入世界设定页
const createWorldProject = async () => {
  if (loading.value) return

  // 未填写任何资料：给出明确提示（按钮不再静默禁用）
  if (!canCreateWorld.value) {
    worldError.value = t('home.worldEmptyHint')
    return
  }

  // 提前占位，封住 ensureModelConfigured 8 秒校验窗口内的重复点击
  loading.value = true
  worldError.value = ''
  try {
    // 模型前置校验：无已验证模型时阻止创建并引导配置
    if (!(await ensureModelConfigured())) {
      loading.value = false
      return
    }

    const created = await createProject({ project_name: '世界模拟' })
    const pid = created?.data?.project_id
    if (!pid) throw new Error('项目创建失败')

    const formData = new FormData()
    worldBgFiles.value.forEach(f => formData.append('background_files', f))
    worldStoryFiles.value.forEach(f => formData.append('story_files', f))
    if (worldBgText.value.trim()) formData.append('background_text', worldBgText.value)
    if (worldStoryText.value.trim()) formData.append('story_text', worldStoryText.value)
    if (worldGoal.value.trim()) formData.append('goal', worldGoal.value.trim())

    await saveWorldInputMultipart(pid, formData)

    // 直达世界设定页（不再需要经过媒体分析流程）
    router.push(`/world/${pid}`)
  } catch (err) {
    worldError.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

// 滚动到控制台区域
const scrollToConsole = () => {
  consoleRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 明确进入"世界设定库"：切到世界模式并滚动到控制台/历史区
const openWorldLibrary = () => {
  activeMode.value = 'world'
  scrollToConsole()
}

// 开始模拟 - 立即跳转，API调用在Process页面进行
const startSimulation = async () => {
  if (loading.value) return

  // 未选择文件或未填写目标：给出明确提示
  if (!canSubmit.value) {
    error.value = t('home.mediaEmptyHint')
    return
  }

  // 模型前置校验：无已验证模型时阻止提交并引导配置
  error.value = ''
  if (!(await ensureModelConfigured())) return

  // 存储待上传的数据
  import('../store/pendingUpload.js').then(({ setPendingUpload }) => {
    setPendingUpload(
      files.value,
      formData.value.simulationRequirement,
      formData.value.additionalContext
    )

    // 立即跳转到Process页面（使用特殊标识表示新建项目）
    router.push({
      name: 'Process',
      params: { projectId: 'new' }
    })
  })
}
</script>

<style scoped>
/* ============ Apple 极简白 + 柑橘橙 ============ */
.home {
  --canvas: #ffffff;
  --canvas-alt: #f5f5f7;
  --ink: #1d1d1f;
  --ink-muted: #6e6e73;
  --ink-subtle: #86868b;
  --hairline: #d2d2d7;
  --accent: #a1c50a;        /* 柑橘色（用户指定） */
  --accent-hover: #8fae09;
  --accent-soft: #f3f7e6;
  --card-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  --radius: 16px;
  background: var(--canvas);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'PingFang SC',
    'Noto Sans SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  letter-spacing: -0.01em;
}

/* ---------- 导航 ---------- */
.nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 40px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--hairline);
}
.nav-brand {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ink);
}
.nav-right {
  display: flex;
  align-items: center;
  gap: 24px;
}
.nav-link {
  font-size: 13px;
  font-weight: 400;
  color: var(--ink-muted);
  text-decoration: none;
}
.nav-link:hover { color: var(--ink); }
.nav-link .arrow { margin-left: 2px; font-size: 12px; }
.nav-btn {
  background: none;
  border: 1px solid rgba(0,0,0,0.12);
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.2s, color 0.2s;
}
.nav-btn:hover { border-color: var(--ink); color: var(--ink); }

/* ---------- Hero ---------- */
.hero {
  padding: 96px 40px 0;
  text-align: center;
}
.hero-kicker {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.08em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 20px;
}
.hero-title {
  font-size: clamp(44px, 7vw, 80px);
  font-weight: 600;
  line-height: 1.06;
  letter-spacing: -0.02em;
  margin: 0 auto 24px;
  max-width: 16em;
  color: var(--ink);
}
.hero-title .accent { color: var(--accent); }
.hero-desc {
  font-size: 19px;
  line-height: 1.6;
  color: var(--ink-muted);
  max-width: 640px;
  margin: 0 auto 36px;
}
.hero-cta { margin-bottom: 80px; }

/* ---------- 按钮 ---------- */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: none;
  border-radius: 980px;
  cursor: pointer;
  font-family: inherit;
  font-size: 15px;
  font-weight: 500;
  padding: 10px 22px;
  transition: background 0.18s ease, transform 0.12s ease, box-shadow 0.18s ease;
}
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-disabled { opacity: 0.55; cursor: not-allowed; }
.btn-disabled:hover:not(:disabled) { background: var(--accent); opacity: 0.55; }
.btn-primary {
  background: var(--accent);
  color: #fff;
}
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-primary:active:not(:disabled) { transform: scale(0.98); }
.btn-lg { padding: 14px 30px; font-size: 16px; }
.btn-arrow { font-size: 15px; }

/* ---------- Hero 视觉：时间线示意图 ---------- */
.hero-visual {
  position: relative;
  background: linear-gradient(135deg, rgba(255,240,214,0.55), rgba(217,220,255,0.55) 45%, rgba(210,250,236,0.55));
  border: 1px solid rgba(255,255,255,0.55);
  border-radius: 24px;
  padding: 64px 24px;
  max-width: 900px;
  margin: 0 auto 96px;
  overflow: hidden;
  box-shadow: 0 12px 40px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.7);
}
.hero-visual::before {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 15% 20%, rgba(255,183,107,0.35), transparent 45%),
    radial-gradient(circle at 85% 75%, rgba(158,167,255,0.35), transparent 45%),
    radial-gradient(circle at 60% 15%, rgba(107,240,198,0.25), transparent 45%);
  pointer-events: none;
}
.tl-demo { position: relative; z-index: 1; }
.tl-main {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 56px;
  position: relative;
  padding: 12px 0;
}
.tl-main::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 6%;
  right: 6%;
  height: 2px;
  background: var(--hairline);
}
.dot {
  position: relative;
  z-index: 1;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--ink);
}
.dot.now {
  width: 18px;
  height: 18px;
  background: var(--accent);
  box-shadow: 0 0 0 6px rgba(161, 197, 10, 0.18);
}
.dot.future {
  background: transparent;
  border: 2px solid var(--ink-subtle);
}
.tl-branch {
  position: absolute;
  top: -8px;
  left: 50%;
  transform: translateX(-16px);
  display: flex;
  align-items: center;
  gap: 28px;
  z-index: 2;
}
.tl-branch::before {
  content: '';
  position: absolute;
  top: -34px;
  left: 7px;
  width: 2px;
  height: 30px;
  background: var(--accent);
}
.branch-line-h {
  width: 42px;
  height: 2px;
  background: var(--accent);
}
.branch-node {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
}
.branch-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--accent);
  margin-left: 4px;
}
.tl-caption {
  display: flex;
  justify-content: space-between;
  max-width: 70%;
  margin: 28px auto 0;
  font-size: 13px;
  color: var(--ink-subtle);
}
.tl-caption .now-label::before {
  content: '● ';
  color: var(--accent);
}
.tl-caption .future-label::before {
  content: '○ ';
}

/* ---------- 特性 ---------- */
.features {
  position: relative;
  padding: 0 40px 96px;
  max-width: 1100px;
  margin: 0 auto;
}
.features-bg {
  position: absolute;
  inset: 0;
  margin: auto;
  max-width: 1100px;
  min-height: 100%;
}
.fg-left { width: 380px; height: 380px; left: -160px; top: -60px; }
.fg-right { width: 420px; height: 420px; right: -180px; bottom: -80px; }
.features-head {
  position: relative;
  z-index: 1;
  text-align: center;
  margin-bottom: 56px;
}
.section-title {
  font-size: 40px;
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 12px;
  color: var(--ink);
}
.section-desc {
  font-size: 17px;
  color: var(--ink-muted);
  margin: 0;
}
.feature-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}
.feature-card {
  background: rgba(255,255,255,0.60);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 32px 24px;
  transition: box-shadow 0.2s ease, transform 0.2s ease, background 0.2s ease;
}
.feature-card:hover {
  box-shadow: var(--card-shadow);
  transform: translateY(-2px);
  background: rgba(255,255,255,0.72);
}
.f-icon {
  font-size: 26px;
  color: var(--accent);
  margin-bottom: 16px;
  line-height: 1;
}
.f-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 10px;
  color: var(--ink);
}
.f-desc {
  font-size: 14px;
  line-height: 1.55;
  color: var(--ink-muted);
  margin: 0;
}

/* ---------- 控制台 ---------- */
.console-section {
  position: relative;
  background: var(--canvas-alt);
  padding: 96px 40px;
}
.console-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.cg-left  { width: 460px; height: 460px; left: -140px;  top: 20%;  }
.cg-top   { width: 340px; height: 340px; left: 30%;     top: -140px; }
.cg-right { width: 420px; height: 420px; right: -160px; bottom: 10%; }
.cg-bottom{ width: 360px; height: 360px; left: 12%;     bottom: -140px; opacity: 0.4; }
.console-head {
  position: relative;
  z-index: 1;
  max-width: 900px;
  margin: 0 auto 40px;
  text-align: center;
}
.mode-tabs {
  display: inline-flex;
  gap: 4px;
  background: #ececee;
  border-radius: 980px;
  padding: 4px;
  margin-top: 20px;
}
.mode-tab {
  border: none;
  background: transparent;
  border-radius: 980px;
  padding: 8px 22px;
  font-size: 14px;
  font-family: inherit;
  color: var(--ink-muted);
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease;
}
.mode-tab.active {
  background: #fff;
  color: var(--ink);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.media-toggle {
  margin-top: 20px;
  margin-left: 12px;
  border: 1px solid rgba(0,0,0,0.12);
  background: #fff;
  border-radius: 980px;
  padding: 6px 14px;
  font-size: 12px;
  font-family: inherit;
  color: var(--ink-muted);
  cursor: pointer;
}
.media-toggle:hover {
  border-color: var(--ink);
  color: var(--ink);
}
.console-card {
  position: relative;
  z-index: 1;
  background: rgba(255,255,255,0.50);
  border-radius: 24px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.08), inset 0 1px 0 rgba(255,255,255,0.72);
  border: 1px solid rgba(255,255,255,0.60);
  backdrop-filter: saturate(200%) blur(26px);
  -webkit-backdrop-filter: saturate(200%) blur(26px);
  max-width: 900px;
  margin: 0 auto;
  padding: 48px;
}
.form-row { margin-bottom: 32px; }
.field-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 12px;
}
.field-meta {
  font-size: 12px;
  font-weight: 400;
  color: var(--ink-subtle);
}
.upload-zone {
  border: 1.5px dashed var(--hairline);
  border-radius: var(--radius);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
  margin-bottom: 12px;
}
.upload-zone:hover, .upload-zone.drag-over {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.upload-zone.has-files { text-align: left; padding: 16px 20px; }
.upload-icon {
  font-size: 22px;
  color: var(--ink-muted);
  margin-bottom: 8px;
}
.upload-title { font-size: 15px; font-weight: 500; color: var(--ink); }
.upload-hint { font-size: 13px; color: var(--ink-subtle); margin-top: 4px; }
.file-list { display: flex; flex-wrap: wrap; gap: 8px; }
.file-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--canvas-alt);
  border-radius: 980px;
  padding: 6px 12px;
  font-size: 13px;
  color: var(--ink);
}
.remove-btn {
  border: none;
  background: transparent;
  color: var(--ink-subtle);
  font-size: 14px;
  cursor: pointer;
  line-height: 1;
}
.remove-btn:hover { color: var(--accent); }
.field-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 15px;
  font-family: inherit;
  color: var(--ink);
  background: #fff;
  resize: vertical;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.field-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(161, 197, 10, 0.15);
}
.field-input::placeholder { color: var(--ink-subtle); }
.form-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding-top: 8px;
}
.model-config-alert {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--accent-soft);
  border: 1px solid rgba(161, 197, 10, 0.35);
  border-radius: 12px;
  padding: 10px 16px;
  font-size: 13px;
  color: #5f7008;
  max-width: 100%;
}
.mc-link {
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  text-decoration: underline;
  white-space: nowrap;
}
.world-error { color: #d70015; font-size: 13px; }
.world-divider {
  font-size: 13px;
  color: var(--ink-subtle);
  text-align: center;
  margin: 0;
}

/* ---------- 历史项目 ---------- */
.history-section { padding: 96px 40px 0; }

/* ---------- Footer ---------- */
.footer {
  border-top: 1px solid var(--hairline);
  padding: 36px 40px 48px;
  text-align: center;
  margin-top: 96px;
}
.footer-note {
  font-size: 12px;
  color: var(--ink-subtle);
}

/* ---------- 响应式 ---------- */
@media (max-width: 900px) {
  .feature-grid { grid-template-columns: repeat(2, 1fr); }
  .hero { padding: 72px 20px 0; }
  .features { padding: 0 20px 72px; }
  .console-section, .history-section { padding-left: 20px; padding-right: 20px; }
  .console-card { padding: 32px 24px; }
  .nav { padding: 14px 20px; }
}
@media (max-width: 560px) {
  .feature-grid { grid-template-columns: 1fr; }
  .tl-main { gap: 28px; }
  .tl-branch { display: none; }
}
</style>

<style>
/* 全局字体基线（非 scoped，作用于整站） */
body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'PingFang SC',
    'Noto Sans SC', 'Helvetica Neue', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
}
</style>
