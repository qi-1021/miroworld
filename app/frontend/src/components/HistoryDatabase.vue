<template>
  <div
    class="history-database"
    :class="{ 'no-projects': projects.length === 0 && !loading }"
    ref="historyContainer"
  >
    <!-- 标题区域 -->
    <div class="section-header">
      <div class="section-line"></div>
      <span class="section-title">{{ $t('history.title') }}</span>
      <div class="section-line"></div>
      <div class="hist-batch-ctl">
        <button
          class="hist-batch-btn"
          :class="{ active: favOnly }"
          @click="toggleFavOnly"
        >★ {{ favOnly ? $t('history.showAll') : $t('history.onlyFavorites') }}</button>
        <button v-if="projects.length" class="hist-batch-btn" :class="{ active: selectionMode }" @click="toggleSelectionMode">
          {{ selectionMode ? $t('history.batchExit') : $t('history.batchSelect') }}
        </button>
        <template v-if="selectionMode">
          <button class="hist-batch-btn" @click="toggleSelectAll">{{ allSelected ? $t('history.batchUnselectAll') : $t('history.batchSelectAll') }}</button>
          <span class="hist-batch-count">{{ $t('history.batchSelectedCount', { n: selectedIds.length }) }}</span>
          <button class="hist-batch-btn danger" :disabled="!selectedIds.length || batchDeleting" @click="runBatchDelete">
            <span v-if="batchDeleting" class="loading-spinner sm"></span>
            {{ $t('history.batchDelete') }}
          </button>
        </template>
      </div>
    </div>

    <!-- 历史项目加载失败告警 -->
    <div v-if="loadError && !loading" class="load-error-banner">
      <span class="load-error-icon">⚠</span>
      <span class="load-error-text">{{ loadError }}</span>
      <button class="load-error-retry" @click="loadHistory">{{ $t('history.retryLoad') }}</button>
    </div>

    <!-- 卡片容器（只在有项目时显示） -->
    <div v-if="projects.length > 0" class="cards-container" :class="{ expanded: isExpanded }" :style="containerStyle">
      <div
        v-for="(project, index) in projects"
        :key="project.simulation_id"
        class="project-card"
        :class="{ expanded: isExpanded, hovering: hoveringCard === index, sel: selectionMode && isSelected(project), selected: selectionMode && isSelected(project) }"
        :style="getCardStyle(index)"
        @mouseenter="hoveringCard = index"
        @mouseleave="hoveringCard = null"
        @click="onCardClick(project)"
      >
        <!-- 批量选择角标 -->
        <div v-if="selectionMode" class="card-sel-mark" @click.stop="toggleSelect(project)">
          <span class="sel-box" :class="{ checked: isSelected(project) }"></span>
        </div>
        <!-- 卡片头部：simulation_id 和 功能可用状态 -->
        <div class="card-header">
          <span class="card-id">{{ formatSimulationId(project.simulation_id) }}</span>
          <div class="card-status-icons">
            <span
              v-if="project.is_best_flow"
              class="badge-icon best"
              title="👑 最佳流向"
            >👑</span>
            <span
              v-if="project.favorite"
              class="badge-icon fav"
              :title="$t('history.favoriteHint')"
            >⭐</span>
            <span
              class="status-icon"
              :class="{ available: project.project_id, unavailable: !project.project_id }"
              :title="$t('history.graphBuild')"
            >◇</span>
            <span
              class="status-icon available"
              :title="$t('history.envSetup')"
            >◈</span>
            <span
              class="status-icon"
              :class="{ available: project.report_id, unavailable: !project.report_id }"
              :title="$t('history.analysisReport')"
            >◆</span>
          </div>
        </div>

        <!-- 文件列表区域 -->
        <div class="card-files-wrapper">
          <!-- 角落装饰 - 取景框风格 -->
          <div class="corner-mark top-left-only"></div>

          <!-- 文件列表 -->
          <div class="files-list" v-if="project.files && project.files.length > 0">
            <div
              v-for="(file, fileIndex) in project.files.slice(0, 3)"
              :key="fileIndex"
              class="file-item"
            >
              <span class="file-tag" :class="getFileType(file.filename)">{{ getFileTypeLabel(file.filename) }}</span>
              <span class="file-name">{{ truncateFilename(file.filename, 20) }}</span>
            </div>
            <!-- 如果有更多文件，显示提示 -->
            <div v-if="project.files.length > 3" class="files-more">
              {{ $t('history.moreFiles', { count: project.files.length - 3 }) }}
            </div>
          </div>
          <!-- 无文件时的占位 -->
          <div class="files-empty" v-else>
            <span class="empty-file-icon">◇</span>
            <span class="empty-file-text">{{ $t('history.noFiles') }}</span>
          </div>
        </div>

        <!-- 卡片标题（使用模拟需求的前20字作为标题） -->
        <h3 class="card-title">{{ getSimulationTitle(project.simulation_requirement) }}</h3>

        <!-- 卡片描述（模拟需求完整展示） -->
        <p class="card-desc">{{ truncateText(project.simulation_requirement, 55) }}</p>

        <!-- 卡片操作区（hover 时显现：收藏 / 世界标识 / 删除空模拟 / 重试失败 / 删除） -->
        <div class="card-actions">
          <button
            class="card-action-btn fav-toggle"
            :class="{ on: project.favorite }"
            :title="project.favorite ? $t('history.unfavoriteHint') : $t('history.favoriteHint')"
            @click="toggleFavorite(project, $event)"
          >{{ project.favorite ? '★' : '☆' }} {{ $t('history.favorite') }}</button>
          <span v-if="isWorldProject(project)" class="world-tag" title="世界模拟">◈ WORLD</span>
          <button
            v-if="isEmptySimulation(project)"
            class="card-action-btn empty"
            :title="$t('history.deleteEmptyHint')"
            @click="handleDeleteEmpty(project, $event)"
          >🗑 {{ $t('history.deleteEmpty') }}</button>
          <button
            v-if="isFailedProject(project)"
            class="card-action-btn retry"
            @click="handleRetryProject(project, $event)"
          >↻ {{ $t('history.retry') }}</button>
          <button
            class="card-action-btn delete"
            @click="handleDeleteProject(project, $event)"
          >× {{ $t('history.delete') }}</button>
        </div>

        <!-- 卡片底部 -->
        <div class="card-footer">
          <div class="card-datetime">
            <span class="card-date">{{ formatDate(project.created_at) }}</span>
            <span class="card-time">{{ formatTime(project.created_at) }}</span>
          </div>
          <span class="card-progress" :class="getProgressClass(project)">
            <span class="status-dot">●</span> {{ formatRounds(project) }}
          </span>
        </div>

        <!-- 底部装饰线 (hover时展开) -->
        <div class="card-bottom-line"></div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <span class="loading-spinner"></span>
      <span class="loading-text">{{ $t('history.loadingText') }}</span>
    </div>

    <!-- 历史回放详情弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="selectedProject" class="modal-overlay" @click.self="closeModal">
          <div class="modal-content">
            <!-- 弹窗头部 -->
            <div class="modal-header">
              <div class="modal-title-section">
                <span class="modal-id">{{ formatSimulationId(selectedProject.simulation_id) }}</span>
                <span class="modal-progress" :class="getProgressClass(selectedProject)">
                  <span class="status-dot">●</span> {{ formatRounds(selectedProject) }}
                </span>
                <span class="modal-create-time">{{ formatDate(selectedProject.created_at) }} {{ formatTime(selectedProject.created_at) }}</span>
              </div>
              <button class="modal-close" @click="closeModal">×</button>
            </div>

            <!-- 弹窗内容 -->
            <div class="modal-body">
              <!-- 模拟需求 -->
              <div class="modal-section">
                <div class="modal-label">{{ $t('history.simRequirement') }}</div>
                <div class="modal-requirement">{{ selectedProject.simulation_requirement || $t('common.none') }}</div>
              </div>

              <!-- 文件列表 -->
              <div class="modal-section">
                <div class="modal-label">{{ $t('history.relatedFiles') }}</div>
                <div class="modal-files" v-if="selectedProject.files && selectedProject.files.length > 0">
                  <div v-for="(file, index) in selectedProject.files" :key="index" class="modal-file-item">
                    <span class="file-tag" :class="getFileType(file.filename)">{{ getFileTypeLabel(file.filename) }}</span>
                    <span class="modal-file-name">{{ file.filename }}</span>
                  </div>
                </div>
                <div class="modal-empty" v-else>{{ $t('history.noRelatedFiles') }}</div>
              </div>

              <!-- 收藏管理：收藏 / 最佳流向 / 备注 -->
              <div class="modal-section modal-fav-section">
                <div class="modal-label">{{ $t('history.favorite') }}</div>
                <div class="modal-fav-row">
                  <button
                    class="modal-fav-btn"
                    :class="{ on: selectedProject.favorite }"
                    :title="$t('history.favoriteHint')"
                    @click="toggleFavorite(selectedProject)"
                  >{{ selectedProject.favorite ? '★' : '☆' }}
                    {{ selectedProject.favorite ? $t('history.favorite') : $t('history.favorite') }}</button>
                  <button
                    class="modal-fav-btn best"
                    :class="{ on: selectedProject.is_best_flow }"
                    :title="selectedProject.is_best_flow ? $t('history.removeBestHint') : $t('history.bestFlowHint')"
                    @click="toggleBestFlow(selectedProject)"
                  >👑 {{ $t('history.bestFlow') }}</button>
                </div>
                <div class="modal-best-hint">{{ $t('history.bestFlowOnly') }}</div>
                <div class="modal-remark">
                  <textarea
                    class="remark-input"
                    rows="2"
                    :placeholder="$t('history.remarkPlaceholder')"
                    :value="selectedProject.remark"
                    @blur="saveRemark(selectedProject, $event)"
                  ></textarea>
                </div>
              </div>
            </div>

            <!-- 推演回放分割线 -->
            <div class="modal-divider">
              <span class="divider-line"></span>
              <span class="divider-text">{{ $t('history.replayTitle') }}</span>
              <span class="divider-line"></span>
            </div>

            <!-- 导航按钮 -->
            <div class="modal-actions">
              <button
                class="modal-btn btn-project"
                @click="goToProject"
                :disabled="!selectedProject.project_id"
              >
                <span class="btn-step">Step1</span>
                <span class="btn-icon">◇</span>
                <span class="btn-text">{{ $t('history.step1Button') }}</span>
              </button>
              <button
                class="modal-btn btn-simulation"
                @click="goToSimulation"
              >
                <span class="btn-step">Step2</span>
                <span class="btn-icon">◈</span>
                <span class="btn-text">{{ $t('history.step2Button') }}</span>
              </button>
              <button
                class="modal-btn btn-report"
                @click="goToReport"
                :disabled="!selectedProject.report_id"
              >
                <span class="btn-step">Step4</span>
                <span class="btn-icon">◆</span>
                <span class="btn-text">{{ $t('history.step4Button') }}</span>
              </button>
            </div>
            <!-- 不可回放提示 -->
            <div class="modal-playback-hint">
              <span class="hint-text">{{ $t('history.replayHint') }}</span>
            </div>

            <!-- 数据管理 -->
            <div class="modal-manage">
              <button
                v-if="selectedProject && isEmptySimulation(selectedProject)"
                class="modal-manage-btn empty"
                @click="handleDeleteEmpty(selectedProject, $event)"
              >{{ $t('history.deleteEmpty') }}</button>
              <button
                class="modal-manage-btn danger"
                @click="handleDeleteProject(selectedProject, $event)"
              >{{ $t('history.delete') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onActivated, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSimulationHistory, deleteSimulation, updateSimulationFavorite } from '../api/simulation'
import { deleteProject, resetProject } from '../api/graph'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()

// 状态
const projects = ref([])
const loading = ref(true)
const isExpanded = ref(false)
const hoveringCard = ref(null)
const historyContainer = ref(null)
const selectedProject = ref(null)  // 当前选中的项目（用于弹窗）
const loadError = ref('')           // 历史项目加载失败的告警信息
const favOnly = ref(false)          // 只看收藏过滤
let observer = null
let isAnimating = false  // 动画锁，防止闪烁
let expandDebounceTimer = null  // 防抖定时器
let pendingState = null  // 记录待执行的目标状态

// ============ 收藏 / 最佳流向 / 备注 ============
const toggleFavOnly = () => {
  favOnly.value = !favOnly.value
  loadHistory()
}

// 卡片/详情切换收藏标记
const toggleFavorite = async (project, event) => {
  if (event) event.stopPropagation()
  const id = project && (project.simulation_id || project.id)
  if (!id) return
  const target = !project.favorite
  try {
    const res = await updateSimulationFavorite(id, { favorite: target })
    if (res && res.data) {
      project.favorite = res.data.favorite
      project.is_best_flow = res.data.is_best_flow || project.is_best_flow
      project.remark = res.data.remark !== undefined ? res.data.remark : project.remark
    } else {
      project.favorite = target
    }
  } catch (e) {
    alert(t('history.favoriteUpdateFailed') + '：' + (e?.message || t('history.favoriteError')))
  }
}

// 详情：切换最佳流向（同项目唯一，前端直接乐观更新本地）
const toggleBestFlow = async (project) => {
  const id = project && (project.simulation_id || project.id)
  if (!id) return
  const target = !project.is_best_flow
  const pid = project.project_id || undefined
  try {
    const res = await updateSimulationFavorite(id, { best_flow: target, ...(pid ? { project_id: pid } : {}) })
    if (res && res.data) {
      project.is_best_flow = res.data.is_best_flow
      // 同项目唯一互斥：本地把同项目其它条目的最佳标记同步清除
      if (res.data.is_best_flow && pid) {
        projects.value.forEach(p => {
          if (p !== project && p.project_id === pid) p.is_best_flow = false
        })
      }
    } else {
      project.is_best_flow = target
    }
  } catch (e) {
    alert(t('history.favoriteUpdateFailed') + '：' + (e?.message || t('history.favoriteError')))
  }
}

// 详情：保存备注（blur 触发）
const saveRemark = async (project, event) => {
  const id = project && (project.simulation_id || project.id)
  if (!id) return
  const val = (event && event.target && event.target.value) || ''
  if ((project.remark || '') === val) return
  project.remark = val
  try {
    await updateSimulationFavorite(id, { remark: val })
  } catch (e) {
    alert(t('history.favoriteUpdateFailed') + '：' + (e?.message || t('history.favoriteError')))
  }
}

// 卡片布局配置 - 动态响应式：按视口宽度决定每行列数与卡片宽度
const breakpoints = [
  { max: 380, cards: 1, width: 240 },
  { max: 560, cards: 1, width: 260 },
  { max: 768, cards: 2, width: 200 },
  { max: 900, cards: 2, width: 220 },
  { max: 1200, cards: 3, width: 240 },
  { max: Infinity, cards: 4, width: 280 }
]
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1200)
// 移动端断点：≤768px 走文档流静态布局（禁 JS 定位与位移动画）。
// 用 matchMedia 做分支比实时 window.innerWidth 更稳，地址栏收起/展开不触发重排。
const isMobile = ref(typeof window !== 'undefined' ? window.matchMedia('(max-width:768px)').matches : false)
function cardLayout() {
  const bp = breakpoints.find(b => viewportWidth.value <= b.max) || breakpoints[breakpoints.length - 1]
  return { cardsPerRow: bp.cards, cardWidth: bp.width }
}
const CARDS_PER_ROW = computed(() => cardLayout().cardsPerRow)
const CARD_WIDTH = computed(() => cardLayout().cardWidth)
const CARD_HEIGHT = 280
const CARD_GAP = 24
const containerWidth = ref(0)
function measureContainer() {
  if (historyContainer.value) {
    // 卡片定位基于最近的定位祖先（.cards-container），其宽度决定居中基准
    const el = historyContainer.value.querySelector('.cards-container')
    containerWidth.value = el ? el.clientWidth : window.innerWidth
  } else {
    containerWidth.value = window.innerWidth
  }
}
let resizeTimer = null
function onViewportResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    // 移动断点通过 matchMedia 判定，比 innerWidth 更稳
    const mobile = typeof window !== 'undefined' && window.matchMedia('(max-width:768px)').matches
    const newWidth = typeof window !== 'undefined' ? window.innerWidth : 1200
    if (mobile !== isMobile.value) {
      isMobile.value = mobile
    }
    // 只响应宽度真实变化；手机地址栏收起/展开只改高度时不重排
    if (newWidth !== viewportWidth.value) {
      viewportWidth.value = newWidth
      measureContainer()
    }
  }, 150)
}

// 动态计算容器高度样式（移动端走文档流，不由 JS 撑高）
const containerStyle = computed(() => {
  if (isMobile.value) return {}

  if (!isExpanded.value) {
    // 折叠态：固定高度
    return { minHeight: '420px' }
  }

  // 展开态：根据卡片数量动态计算高度
  const total = projects.value.length
  if (total === 0) {
    return { minHeight: '280px' }
  }

  const rows = Math.ceil(total / CARDS_PER_ROW.value)
  // 计算实际需要的高度：行数 * 卡片高度 + (行数-1) * 间距 + 少量底部间距
  const expandedHeight = rows * CARD_HEIGHT + (rows - 1) * CARD_GAP + 10

  return { minHeight: `${expandedHeight}px` }
})

// 获取卡片样式
const getCardStyle = (index) => {
  const total = projects.value.length
  // 移动端文档流布局：不返回 transform/transition，纯静态，交给 CSS 断点处理
  if (isMobile.value) return {}

  const cardsPerRow = CARDS_PER_ROW.value
  const cardWidth = CARD_WIDTH.value

  if (isExpanded.value) {
    // 展开态：网格布局
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const col = index % cardsPerRow
    const row = Math.floor(index / cardsPerRow)

    // 计算当前行的卡片数量，确保每行居中
    const currentRowStart = row * cardsPerRow
    const currentRowCards = Math.min(cardsPerRow, total - currentRowStart)

    const rowWidth = currentRowCards * cardWidth + (currentRowCards - 1) * CARD_GAP

    // 以容器宽度为基准居中整行（多卡/单卡都居中），适配手机窄屏
    const startX = Math.max(0, ((containerWidth.value || cardWidth) - rowWidth) / 2)
    const colInRow = index % cardsPerRow
    const x = startX + colInRow * (cardWidth + CARD_GAP)

    // 向下展开，增加与标题的间距
    const y = 20 + row * (CARD_HEIGHT + CARD_GAP)

    return {
      transform: `translate(${x}px, ${y}px) rotate(0deg) scale(1)`,
      zIndex: 100 + index,
      opacity: 1,
      transition: transition
    }
  } else {
    // 折叠态：扇形堆叠
    const transition = 'transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.3s ease, border-color 0.3s ease'

    const centerIndex = (total - 1) / 2
    const offset = index - centerIndex

    const x = offset * 35
    // 调整起始位置，靠近标题但保持适当间距
    const y = 25 + Math.abs(offset) * 8
    const r = offset * 3
    const s = 0.95 - Math.abs(offset) * 0.05

    return {
      transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(${s})`,
      zIndex: 10 + index,
      opacity: 1,
      transition: transition
    }
  }
}

// 根据轮数进度获取样式类
const getProgressClass = (simulation) => {
  const current = simulation.current_round || 0
  const total = simulation.total_rounds || 0

  if (total === 0 || current === 0) {
    // 未开始
    return 'not-started'
  } else if (current >= total) {
    // 已完成
    return 'completed'
  } else {
    // 进行中
    return 'in-progress'
  }
}

// 格式化日期（只显示日期部分）
const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toISOString().slice(0, 10)
  } catch {
    return dateStr?.slice(0, 10) || ''
  }
}

// 格式化时间（显示时:分）
const formatTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    const hours = date.getHours().toString().padStart(2, '0')
    const minutes = date.getMinutes().toString().padStart(2, '0')
    return `${hours}:${minutes}`
  } catch {
    return ''
  }
}

// 截断文本
const truncateText = (text, maxLength) => {
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) + '...' : text
}

// 从模拟需求生成标题（取前20字）
const getSimulationTitle = (requirement) => {
  if (!requirement) return t('history.untitledSimulation')
  const title = requirement.slice(0, 20)
  return requirement.length > 20 ? title + '...' : title
}

// 格式化 simulation_id 显示（截取前6位）
const formatSimulationId = (simulationId) => {
  if (!simulationId) return 'SIM_UNKNOWN'
  const prefix = simulationId.replace('sim_', '').slice(0, 6)
  return `SIM_${prefix.toUpperCase()}`
}

// 格式化轮数显示（当前轮/总轮数）
const formatRounds = (simulation) => {
  const current = simulation.current_round || 0
  const total = simulation.total_rounds || 0
  if (total === 0) return t('history.notStarted')
  return t('history.roundsProgress', { current, total })
}

// 获取文件类型（用于样式）
const getFileType = (filename) => {
  if (!filename) return 'other'
  const ext = filename.split('.').pop()?.toLowerCase()
  const typeMap = {
    'pdf': 'pdf',
    'doc': 'doc', 'docx': 'doc',
    'xls': 'xls', 'xlsx': 'xls', 'csv': 'xls',
    'ppt': 'ppt', 'pptx': 'ppt',
    'txt': 'txt', 'md': 'txt', 'json': 'code',
    'jpg': 'img', 'jpeg': 'img', 'png': 'img', 'gif': 'img',
    'zip': 'zip', 'rar': 'zip', '7z': 'zip'
  }
  return typeMap[ext] || 'other'
}

// 获取文件类型标签文本
const getFileTypeLabel = (filename) => {
  if (!filename) return 'FILE'
  const ext = filename.split('.').pop()?.toUpperCase()
  return ext || 'FILE'
}

// 截断文件名（保留扩展名）
const truncateFilename = (filename, maxLength) => {
  if (!filename) return t('history.unknownFile')
  if (filename.length <= maxLength) return filename

  const ext = filename.includes('.') ? '.' + filename.split('.').pop() : ''
  const nameWithoutExt = filename.slice(0, filename.length - ext.length)
  const truncatedName = nameWithoutExt.slice(0, maxLength - ext.length - 3) + '...'
  return truncatedName + ext
}

// 打开项目详情弹窗
const navigateToProject = (simulation) => {
  selectedProject.value = simulation
}

// 关闭弹窗
const closeModal = () => {
  selectedProject.value = null
}

// 导航到图谱构建页面（Project）
const goToProject = () => {
  if (selectedProject.value?.project_id) {
    // 世界项目直达世界设定页，其余走媒体分析 Process 页
    const target = isWorldProject(selectedProject.value)
      ? { name: 'WorldSetup', params: { projectId: selectedProject.value.project_id } }
      : { name: 'Process', params: { projectId: selectedProject.value.project_id } }
    router.push(target)
    closeModal()
  }
}

// 导航到环境配置页面（Simulation）
const goToSimulation = () => {
  const project = selectedProject.value
  if (!project) return

  // 世界项目：世界模拟不适用社交媒体环境搭建，直接进入世界设定页的推演模块
  if (isWorldProject(project)) {
    if (project.project_id) {
      router.push({
        name: 'WorldSetup',
        params: { projectId: project.project_id },
        query: { replay: '1' }
      })
      closeModal()
    }
    return
  }

  if (project.simulation_id) {
    router.push({
      name: 'Simulation',
      params: { simulationId: project.simulation_id }
    })
    closeModal()
  }
}

// 导航到分析报告页面（Report）
const goToReport = () => {
  if (selectedProject.value?.report_id) {
    router.push({
      name: 'Report',
      params: { reportId: selectedProject.value.report_id }
    })
    closeModal()
  }
}

// ============ 数据管理：删除 / 重试 ============

// 判断项目是否处于失败状态（后端可能以 status / error / last_error 暴露）
const isFailedProject = (project) => {
  if (!project) return false
  const status = String(project.status || project.graph_status || '')
  if (['failed', 'FAILED', 'error', 'ERROR'].some(s => status === s)) return true
  if (project.error || project.last_error || project.failed_reason) return true
  return false
}

// 判断项目是否为世界模拟项目（后端可能提供 history_type / mode / type 等字段）
const isWorldProject = (project) => {
  if (!project) return false
  const type = String(project.history_type || project.mode || project.type || project.kind || '')
  if (['world', 'WORLD', '世界模拟'].some(v => type === v)) return true
  if (project.world_project || project.has_world_data) return true
  return false
}

// 判断是否为「空模拟」：有 simulation_id（或 world_ 伪 id）但没有实际数据——
// 即没有项目容器、没有文件、没有需求、也没有世界正文的孤立运行记录。
// 前端据此显示「删除空模拟」入口，清理 data/world-sim 下未命名/无归属的残留。
const isEmptySimulation = (project) => {
  if (!project) return false
  const sid = project.simulation_id
  if (!sid) return false
  // 有真实项目容器或已挂靠世界数据 → 不是空模拟
  if (project.project_id) return false
  if (project.files && project.files.length > 0) return false
  if (project.simulation_requirement && String(project.simulation_requirement).trim()) return false
  if (project.has_world_data) return false
  // 其余情况（无项目、无文件、无需求）：视为空模拟
  return true
}

// 删除空模拟：优先调用模拟级删除接口；失败时回退到项目级删除
const handleDeleteEmpty = async (project, event) => {
  if (event) event.stopPropagation()
  const id = project && (project.simulation_id || project.id)
  if (!id) return
  if (!window.confirm(t('history.deleteEmptyConfirm'))) return
  try {
    await deleteSimulation(id)
  } catch (e) {
    // 模拟级删除 404/不可用：尝试项目级删除兜底
    const pid = project && (project.project_id || project.id)
    if (pid) {
      try {
        await deleteProject(pid)
      } catch (e2) {
        alert(e2?.message || t('history.deleteError'))
        return
      }
    } else {
      alert(e?.message || t('history.deleteError'))
      return
    }
  }
  // 从列表移除
  const idx = projects.value.findIndex(p => p === project)
  if (idx >= 0) projects.value.splice(idx, 1)
  if (selectedProject.value && selectedProject.value === project) {
    selectedProject.value = null
  }
}

// 根据项目身份判定重试后的跳转路由
const retryTarget = (project) => {
  const id = project && (project.project_id || project.id)
  if (!id) return null
  return isWorldProject(project)
    ? { name: 'WorldSetup', params: { projectId: id } }
    : { name: 'Process', params: { projectId: id } }
}

// 删除项目
const handleDeleteProject = async (project, event) => {
  if (event) event.stopPropagation()
  // 空模拟（无项目容器）走模拟级删除，普通项目走项目级删除
  if (isEmptySimulation(project)) {
    return handleDeleteEmpty(project)
  }
  const id = project && (project.project_id || project.id)
  if (!id) return
  if (!window.confirm(t('history.deleteConfirm'))) return
  try {
    await deleteProject(id)
    // 从列表移除
    const idx = projects.value.findIndex(p => p === project)
    if (idx >= 0) projects.value.splice(idx, 1)
    if (selectedProject.value && selectedProject.value === project) {
      selectedProject.value = null
    }
  } catch (e) {
    alert(e?.message || t('history.deleteError'))
  }
}

// 批量选择（历史卡片多选删除）
const selectionMode = ref(false)
const selectedIds = ref([])
const batchDeleting = ref(false)
function isSelected(project) {
  const id = project.simulation_id || project.id
  return selectedIds.value.includes(id)
}
function onCardClick(project) {
  if (selectionMode.value) {
    toggleSelect(project)
    return
  }
  navigateToProject(project)
}
function toggleSelect(project) {
  const id = project.simulation_id || project.id
  if (!id) return
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}
const allSelected = computed(() => {
  return projects.value.length > 0 && projects.value.every(p => isSelected(p))
})
function toggleSelectAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = projects.value.map(p => p.simulation_id || p.id).filter(Boolean)
  }
}
function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  if (!selectionMode.value) selectedIds.value = []
}
async function runBatchDelete() {
  const targets = projects.value.filter(p => isSelected(p))
  if (!targets.length || batchDeleting.value) return
  if (!window.confirm(t('history.batchDeleteConfirm', { n: targets.length }))) return
  batchDeleting.value = true
  let failed = 0
  for (const project of targets) {
    try {
      // 复用单删逻辑（空模拟走模拟级删除，普通项目走项目级删除）
      if (isEmptySimulation(project)) {
        await deleteSimulation(project.simulation_id || project.id)
      } else {
        await deleteProject(project.project_id || project.id)
      }
    } catch (e) {
      failed++
    }
  }
  batchDeleting.value = false
  const okCount = targets.length - failed
  alert(t('history.batchDeleteResult', { done: okCount, failed }))
  selectedIds.value = []
  await loadHistory()
}

// 重试失败项目
const handleRetryProject = async (project, event) => {
  if (event) event.stopPropagation()
  const id = project && (project.project_id || project.id)
  if (!id) return
  if (!window.confirm(t('history.retryConfirm'))) return
  try {
    await resetProject(id)
    const target = retryTarget(project) || { name: 'Process', params: { projectId: id } }
    closeModal()
    router.push(target)
  } catch (e) {
    alert(e?.message || t('history.retryError'))
  }
}

// 加载历史项目
const loadHistory = async () => {
  try {
    loading.value = true
    loadError.value = ''
    const response = await getSimulationHistory(20, favOnly.value ? 1 : null)
    if (response.success) {
      projects.value = response.data || []
    } else {
      projects.value = []
      loadError.value = response.message || response.error || t('history.loadFailed')
    }
  } catch (error) {
    console.error('加载历史项目失败:', error)
    projects.value = []
    // 404 等常规失败直接给出友好中文提示；其它情况透出原始错误信息
    const status = error?.response?.status
    loadError.value =
      (status && status >= 400) || !error?.message
        ? t('history.loadFailed')
        : error.message
  } finally {
    loading.value = false
  }
}

// 初始化 IntersectionObserver
const initObserver = () => {
  if (observer) {
    observer.disconnect()
  }

  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const shouldExpand = entry.isIntersecting

        // 更新待执行的目标状态（无论是否在动画中都要记录最新的目标状态）
        pendingState = shouldExpand

        // 清除之前的防抖定时器（新的滚动意图会覆盖旧的）
        if (expandDebounceTimer) {
          clearTimeout(expandDebounceTimer)
          expandDebounceTimer = null
        }

        // 如果正在动画中，只记录状态，等动画结束后处理
        if (isAnimating) return

        // 如果目标状态与当前状态相同，不需要处理
        if (shouldExpand === isExpanded.value) {
          pendingState = null
          return
        }

        // 使用防抖延迟状态切换，防止快速闪烁
        // 展开时延迟较短(50ms)，收起时延迟较长(200ms)以增加稳定性
        const delay = shouldExpand ? 50 : 200

        expandDebounceTimer = setTimeout(() => {
          // 检查是否正在动画
          if (isAnimating) return

          // 检查待执行状态是否仍需要执行（可能已被后续滚动覆盖）
          if (pendingState === null || pendingState === isExpanded.value) return

          // 设置动画锁
          isAnimating = true
          isExpanded.value = pendingState
          pendingState = null

          // 动画完成后解除锁定，并检查是否有待处理的状态变化
          setTimeout(() => {
            isAnimating = false

            // 动画结束后，检查是否有新的待执行状态
            if (pendingState !== null && pendingState !== isExpanded.value) {
              // 延迟一小段时间再执行，避免太快切换
              expandDebounceTimer = setTimeout(() => {
                if (pendingState !== null && pendingState !== isExpanded.value) {
                  isAnimating = true
                  isExpanded.value = pendingState
                  pendingState = null
                  setTimeout(() => {
                    isAnimating = false
                  }, 750)
                }
              }, 100)
            }
          }, 750)
        }, delay)
      })
    },
    {
      // 使用多个阈值，使检测更平滑
      threshold: [0.4, 0.6, 0.8],
      // 调整 rootMargin，视口底部向上收缩，需要滚动更多才触发展开
      rootMargin: '0px 0px -150px 0px'
    }
  )

  // 开始观察
  if (historyContainer.value) {
    observer.observe(historyContainer.value)
  }
}

// 监听路由变化，当返回首页时重新加载数据
watch(() => route.path, (newPath) => {
  if (newPath === '/') {
    loadHistory()
  }
})

// 向外暴露 reload：供其它页面（如世界设定页导入后）触发首页历史刷新
defineExpose({ reload: loadHistory })
const reloadHistoryListener = () => { loadHistory() }

onMounted(async () => {
  // 确保 DOM 渲染完成后再加载数据
  await nextTick()
  await loadHistory()

  // 测量卡片容器宽度，用于展开态居中布局
  await nextTick()
  measureContainer()

  // 事件驱动的刷新：其它页面（例如世界设定页导入新项目后）派发
  // 'miroworld:history-reload' 即可让首页历史列表即时更新。
  window.addEventListener('miroworld:history-reload', reloadHistoryListener)
  // 视口宽度变化时重算卡片布局
  window.addEventListener('resize', onViewportResize)

  // 等待 DOM 渲染后初始化观察器
  setTimeout(() => {
    initObserver()
  }, 100)
})

// 如果使用 keep-alive，在组件激活时重新加载数据
onActivated(() => {
  loadHistory()
})

onUnmounted(() => {
  // 清理 Intersection Observer
  if (observer) {
    observer.disconnect()
    observer = null
  }
  // 清理 event 监听
  window.removeEventListener('miroworld:history-reload', reloadHistoryListener)
  window.removeEventListener('resize', onViewportResize)
  // 清理防抖定时器
  if (expandDebounceTimer) {
    clearTimeout(expandDebounceTimer)
    expandDebounceTimer = null
  }
  if (resizeTimer) {
    clearTimeout(resizeTimer)
    resizeTimer = null
  }
})
</script>

<style scoped>
/* 容器 */
.history-database {
  position: relative;
  width: 100%;
  min-height: 280px;
  margin-top: 40px;
  padding: 35px 0 40px;
  overflow: visible;
}

/* 无项目时简化显示 */
.history-database.no-projects {
  min-height: auto;
  padding: 40px 0 20px;
}

/* 标题区域 */
.section-header {
  position: relative;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  margin-bottom: 24px;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  padding: 0 40px;
}

.section-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #E5E7EB, transparent);
  max-width: 300px;
}

.section-title {
  font-size: 0.8rem;
  font-weight: 500;
  color: #9CA3AF;
  letter-spacing: 3px;
  text-transform: uppercase;
}

/* 批量选择控制 */
.hist-batch-ctl {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hist-batch-btn {
  border: 1px solid #D1D5DB;
  background: #FFF;
  color: #374151;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
}
.hist-batch-btn:hover { border-color: #9CA3AF; }
.hist-batch-btn.active { background: #1f2937; color: #FFF; border-color: #1f2937; }
.hist-batch-btn.danger { color: #b91c1c; border-color: #fecaca; }
.hist-batch-btn.danger:disabled { opacity: 0.5; cursor: not-allowed; }
.hist-batch-count { font-size: 11px; color: #6B7280; }

.card-sel-mark {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 5;
}
.sel-box {
  display: block;
  width: 18px;
  height: 18px;
  border: 2px solid #9CA3AF;
  border-radius: 5px;
  background: rgba(255,255,255,0.9);
  cursor: pointer;
}
.sel-box.checked { background: #a1c50a; border-color: #a1c50a; position: relative; }
.sel-box.checked::after {
  content: '✓';
  position: absolute;
  inset: 0;
  color: #FFF;
  font-size: 12px;
  line-height: 14px;
  text-align: center;
}
.project-card.sel { outline: 2px solid #a1c50a; outline-offset: 1px; }

/* 卡片容器：
   卡片为 absolute + transform 定位，静态位置须锚定在容器左上，
   否则 flex 的 justify-content:center 会给 absolutely 子元素的
   left:auto 加一个 ~半宽的静态偏移，导致卡网格右移/错位。 */
.cards-container {
  position: relative;
  display: block;
  padding: 0 40px;
  transition: min-height 700ms cubic-bezier(0.23, 1, 0.32, 1);
  /* min-height 由 JS 动态计算，根据卡片数量自适应 */
}

/* 项目卡片 —— Liquid Glass 质感：更透明半透明 + 毛玻璃模糊 + 顶亮边 */
.project-card {
  position: absolute;
  width: 280px;
  background: rgba(255, 255, 255, 0.20);
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 14px;
  padding: 14px;
  cursor: pointer;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.05), inset 0 1px 0 rgba(255,255,255,0.85);
  backdrop-filter: saturate(180%) blur(16px);
  -webkit-backdrop-filter: saturate(180%) blur(16px);
  transition: box-shadow 0.3s ease, border-color 0.3s ease, transform 700ms cubic-bezier(0.23, 1, 0.32, 1), opacity 700ms cubic-bezier(0.23, 1, 0.32, 1), background 0.3s ease;
  overflow: hidden;
}
.project-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 6%;
  right: 6%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.95), transparent);
  pointer-events: none;
}

.project-card:hover {
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255,255,255,0.9);
  border-color: rgba(255, 255, 255, 0.95);
  background: rgba(255, 255, 255, 0.40);
  z-index: 1000 !important;
}

.project-card.hovering {
  z-index: 1000 !important;
}

/* 卡片头部 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F3F4F6;
  font-family: 'JetBrains Mono', 'SF Mono', monospace;
  font-size: 0.7rem;
}

.card-id {
  color: #6B7280;
  letter-spacing: 0.5px;
  font-weight: 500;
}

/* 功能状态图标组 */
.card-status-icons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-icon {
  font-size: 0.75rem;
  transition: all 0.2s ease;
  cursor: default;
}

.status-icon.available {
  opacity: 1;
}

/* 不同功能的颜色 */
.status-icon:nth-child(1).available { color: #3B82F6; } /* 图谱构建 - 蓝色 */
.status-icon:nth-child(2).available { color: #F59E0B; } /* 环境搭建 - 橙色 */
.status-icon:nth-child(3).available { color: #10B981; } /* 分析报告 - 绿色 */

.status-icon.unavailable {
  color: #D1D5DB;
  opacity: 0.5;
}

/* 收藏 / 最佳流向角标 */
.badge-icon {
  font-size: 0.8rem;
  line-height: 1;
  cursor: default;
}
.badge-icon.fav { color: #F59E0B; }
.badge-icon.best { color: #B45309; }

/* 轮数进度显示 */
.card-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 0.65rem;
}

.status-dot {
  font-size: 0.5rem;
}

/* 进度状态颜色 */
.card-progress.completed { color: #10B981; }    /* 已完成 - 绿色 */
.card-progress.in-progress { color: #F59E0B; }  /* 进行中 - 橙色 */
.card-progress.not-started { color: #9CA3AF; }  /* 未开始 - 灰色 */
.card-status.pending { color: #9CA3AF; }

/* 文件列表区域 */
.card-files-wrapper {
  position: relative;
  width: 100%;
  min-height: 48px;
  max-height: 110px;
  margin-bottom: 12px;
  padding: 8px 10px;
  background: linear-gradient(135deg, #f8f9fa 0%, #f1f3f4 100%);
  border-radius: 4px;
  border: 1px solid #e8eaed;
  overflow: hidden;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 更多文件提示 */
.files-more {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3px 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  color: #6B7280;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 3px;
  letter-spacing: 0.3px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 3px;
  transition: all 0.2s ease;
}

.file-item:hover {
  background: rgba(255, 255, 255, 1);
  transform: translateX(2px);
  border-color: #e5e7eb;
}

/* 简约文件标签样式 */
.file-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 16px;
  padding: 0 4px;
  border-radius: 2px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.55rem;
  font-weight: 600;
  line-height: 1;
  text-transform: uppercase;
  letter-spacing: 0.2px;
  flex-shrink: 0;
  min-width: 28px;
}

/* 低饱和度配色方案 - Morandi色系 */
.file-tag.pdf { background: #f2e6e6; color: #a65a5a; }
.file-tag.doc { background: #e6eff5; color: #5a7ea6; }
.file-tag.xls { background: #e6f2e8; color: #5aa668; }
.file-tag.ppt { background: #f5efe6; color: #a6815a; }
.file-tag.txt { background: #f0f0f0; color: #757575; }
.file-tag.code { background: #eae6f2; color: #815aa6; }
.file-tag.img { background: #e6f2f2; color: #5aa6a6; }
.file-tag.zip { background: #f2f0e6; color: #a69b5a; }
.file-tag.other { background: #f3f4f6; color: #6b7280; }

.file-name {
  font-family: 'Inter', sans-serif;
  font-size: 0.7rem;
  color: #4b5563;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.1px;
}

/* 无文件时的占位 */
.files-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 48px;
  color: #9CA3AF;
}

.empty-file-icon {
  font-size: 1rem;
  opacity: 0.5;
}

.empty-file-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  letter-spacing: 0.5px;
}

/* 悬停时文件区域效果 */
.project-card:hover .card-files-wrapper {
  border-color: #d1d5db;
  background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
}

/* 角落装饰 */
.corner-mark.top-left-only {
  position: absolute;
  top: 6px;
  left: 6px;
  width: 8px;
  height: 8px;
  border-top: 1.5px solid rgba(0, 0, 0, 0.4);
  border-left: 1.5px solid rgba(0, 0, 0, 0.4);
  pointer-events: none;
  z-index: 10;
}

/* 卡片标题 */
.card-title {
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 0.9rem;
  font-weight: 700;
  color: #111827;
  margin: 0 0 6px 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color 0.3s ease;
}

.project-card:hover .card-title {
  color: #2563EB;
}

/* 卡片描述 */
.card-desc {
  font-family: 'Inter', sans-serif;
  font-size: 0.75rem;
  color: #6B7280;
  margin: 0 0 16px 0;
  line-height: 1.5;
  height: 34px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 卡片底部 */
.card-footer {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #F3F4F6;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  color: #9CA3AF;
  font-weight: 500;
}

/* 日期时间组合 */
.card-datetime {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 底部轮数进度显示 */
.card-footer .card-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 0.65rem;
}

.card-footer .status-dot {
  font-size: 0.5rem;
}

/* 进度状态颜色 - 底部 */
.card-footer .card-progress.completed { color: #10B981; }
.card-footer .card-progress.in-progress { color: #F59E0B; }
.card-footer .card-progress.not-started { color: #9CA3AF; }

/* 卡片操作区 */
.card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0 10px;
  opacity: 0;
  transition: opacity 0.2s ease;
  min-height: 22px;
}

.project-card:hover .card-actions,
.project-card.hovering .card-actions {
  opacity: 1;
}

.world-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border: 1px solid #C7E7FF;
  background: #E6F4FF;
  color: #0B6FB8;
  border-radius: 3px;
  line-height: 1;
  flex-shrink: 0;
}

.card-action-btn {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 3px 8px;
  border: 1px solid #E5E7EB;
  border-radius: 3px;
  background: #FFFFFF;
  cursor: pointer;
  transition: all 0.15s ease;
  line-height: 1;
  margin-left: auto;
}

.card-action-btn.fav-toggle {
  color: #B45309;
  border-color: #F3D9A6;
  background: #FFF7E8;
  margin-left: 0;
}

.card-action-btn.fav-toggle.on {
  color: #92400E;
  border-color: #F5B861;
  background: #FDEBC8;
}

.card-action-btn.retry {
  color: #2563EB;
  border-color: #BFDBFE;
  background: #EFF6FF;
  margin-left: 0;
}

.card-action-btn.empty {
  color: #B45309;
  border-color: #FCD9A5;
  background: #f3f7e6;
  margin-left: 0;
}

.card-action-btn.empty:hover {
  background: #FEE9C7;
  border-color: #F5B861;
}

.card-action-btn.retry:hover {
  background: #DBEAFE;
  border-color: #93C5FD;
}

.card-action-btn.delete {
  color: #B91C1C;
  border-color: #FECACA;
  background: #FEF2F2;
}

.card-action-btn.delete:hover {
  background: #FEE2E2;
  border-color: #FCA5A5;
}

/* 历史加载失败告警 */
.load-error-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border: 1px solid #FECACA;
  background: #FEF2F2;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #B91C1C;
}

.load-error-icon {
  flex-shrink: 0;
  color: #DC2626;
}

.load-error-text {
  flex: 1;
  line-height: 1.4;
}

.load-error-retry {
  flex-shrink: 0;
  border: 1px solid #B91C1C;
  background: #FFFFFF;
  color: #B91C1C;
  padding: 5px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  border-radius: 3px;
}

.load-error-retry:hover {
  background: #B91C1C;
  color: #FFFFFF;
}

/* 底部装饰线 */
.card-bottom-line {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  width: 0;
  background-color: #000;
  transition: width 0.5s cubic-bezier(0.23, 1, 0.32, 1);
  z-index: 20;
}

.project-card:hover .card-bottom-line {
  width: 100%;
}

/* 空状态 */
.empty-state, .loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 48px;
  color: #9CA3AF;
}

.empty-icon {
  font-size: 2rem;
  opacity: 0.5;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid #E5E7EB;
  border-top-color: #6B7280;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 响应式（卡片布局由 JS 按视口宽度计算，这里同步 CSS 宽度保持一致性） */
@media (max-width: 1200px) {
  .project-card {
    width: 240px;
  }
}

@media (max-width: 900px) {
  .project-card {
    width: 220px;
  }
}

@media (max-width: 768px) {
  /* 移动端：禁 JS 定位与位移动画，改文档流静态布局（卡片纵向堆叠） */
  .cards-container {
    display: block;
    padding: 0 12px;
    min-height: 0 !important;
    transition: none;
  }
  .project-card {
    position: relative; /* 保留 relative 供卡内 absolute 装饰（勾选/取景框/底线）定位 */
    width: 100%;
    max-width: none;
    margin-bottom: 20px;
    /* 禁用 700ms 位移动画与 JS transform，避免滚动/地址栏抖动 */
    transform: none !important;
    opacity: 1 !important;
    transition: box-shadow 0.3s ease, border-color 0.3s ease, background 0.3s ease;
  }
}

@media (max-width: 560px) {
  .project-card {
    width: 100%;
    max-width: none;
    padding: 12px;
  }
  .section-header {
    padding: 0 16px;
    gap: 12px;
  }
  .section-title {
    font-size: 0.7rem;
  }
}

@media (max-width: 380px) {
  .project-card {
    width: 100%;
    max-width: none;
  }
}

@media (max-width: 480px) {
  /* 批量选择控制折行 */
  .hist-batch-ctl {
    flex-wrap: wrap;
    justify-content: center;
    gap: 6px;
  }
  .hist-batch-btn {
    padding: 4px 8px;
    font-size: 10px;
  }
  /* 卡片顶部状态图标 / 头部允许换行 */
  .card-header {
    flex-wrap: wrap;
    gap: 6px;
  }
}

/* ===== 历史回放详情弹窗样式 ===== */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.modal-content {
  background: #FFFFFF;
  width: 560px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
}

/* 动画过渡 */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-content {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.modal-leave-active .modal-content {
  transition: all 0.2s ease-in;
}

.modal-enter-from .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

.modal-leave-to .modal-content {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}

/* 弹窗头部 */
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 32px;
  border-bottom: 1px solid #F3F4F6;
  background: #FFFFFF;
}

.modal-title-section {
  display: flex;
  align-items: center;
  gap: 16px;
}

.modal-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1rem;
  font-weight: 600;
  color: #111827;
  letter-spacing: 0.5px;
}

.modal-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
  background: #F9FAFB;
}

.modal-progress.completed { color: #10B981; background: rgba(16, 185, 129, 0.1); }
.modal-progress.in-progress { color: #F59E0B; background: rgba(245, 158, 11, 0.1); }
.modal-progress.not-started { color: #9CA3AF; background: #F3F4F6; }

.modal-create-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #9CA3AF;
  letter-spacing: 0.3px;
}

.modal-close {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  font-size: 1.5rem;
  color: #9CA3AF;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  border-radius: 6px;
}

.modal-close:hover {
  background: #F3F4F6;
  color: #111827;
}

/* 弹窗内容 */
.modal-body {
  padding: 24px 32px;
}

.modal-section {
  margin-bottom: 24px;
}

.modal-section:last-child {
  margin-bottom: 0;
}

/* 收藏管理区块 */
.modal-fav-section {
  border-top: 1px solid #f3f4f6;
  padding-top: 20px;
  margin-top: 20px;
}
.modal-fav-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.modal-fav-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 8px 16px;
  border: 1px solid #F3D9A6;
  border-radius: 6px;
  background: #FFF7E8;
  color: #B45309;
  cursor: pointer;
  transition: all 0.15s ease;
}
.modal-fav-btn:hover {
  border-color: #F5B861;
  background: #FDEBC8;
}
.modal-fav-btn.on {
  color: #92400E;
  border-color: #F5B861;
  background: #FDEBC8;
}
.modal-fav-btn.best {
  border-color: #E7D7C4;
  background: #FBF5EE;
  color: #8A5A2B;
}
.modal-fav-btn.best.on {
  border-color: #D4AF7A;
  background: #F5E5CC;
  color: #6B4226;
}
.modal-best-hint {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  color: #9CA3AF;
  margin: 8px 0 12px;
  line-height: 1.4;
}
.remark-input {
  width: 100%;
  box-sizing: border-box;
  font-family: 'Inter', sans-serif;
  font-size: 0.85rem;
  color: #374151;
  padding: 10px 12px;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  background: #FFFFFF;
  resize: vertical;
  min-height: 40px;
}
.remark-input:focus {
  outline: none;
  border-color: #93C5FD;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.modal-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 10px;
  font-weight: 500;
}

.modal-requirement {
  font-size: 0.95rem;
  color: #374151;
  line-height: 1.6;
  padding: 16px;
  background: #F9FAFB;
  border: 1px solid #F3F4F6;
  border-radius: 8px;
}

.modal-files {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 4px;
}

/* 自定义滚动条样式 */
.modal-files::-webkit-scrollbar {
  width: 4px;
}

.modal-files::-webkit-scrollbar-track {
  background: #F3F4F6;
  border-radius: 2px;
}

.modal-files::-webkit-scrollbar-thumb {
  background: #D1D5DB;
  border-radius: 2px;
}

.modal-files::-webkit-scrollbar-thumb:hover {
  background: #9CA3AF;
}

.modal-file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.modal-file-item:hover {
  border-color: #D1D5DB;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}

.modal-file-name {
  font-size: 0.85rem;
  color: #4B5563;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-empty {
  font-size: 0.85rem;
  color: #9CA3AF;
  padding: 16px;
  background: #F9FAFB;
  border: 1px dashed #E5E7EB;
  border-radius: 6px;
  text-align: center;
}

/* 推演回放分割线 */
.modal-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 32px 0;
  background: #FFFFFF;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #E5E7EB, transparent);
}

.divider-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #9CA3AF;
  letter-spacing: 2px;
  text-transform: uppercase;
  white-space: nowrap;
}

/* 导航按钮 */
.modal-actions {
  display: flex;
  gap: 16px;
  padding: 20px 32px;
  background: #FFFFFF;
}

.modal-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  background: #FFFFFF;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.modal-btn:hover:not(:disabled) {
  border-color: #000000;
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.modal-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #F9FAFB;
}

.btn-step {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  font-weight: 500;
  color: #9CA3AF;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.btn-icon {
  font-size: 1.4rem;
  line-height: 1;
  transition: color 0.2s ease;
}

.btn-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: #4B5563;
}

.modal-btn.btn-project .btn-icon { color: #3B82F6; }
.modal-btn.btn-simulation .btn-icon { color: #F59E0B; }
.modal-btn.btn-report .btn-icon { color: #10B981; }

.modal-btn:hover:not(:disabled) .btn-text {
  color: #111827;
}

/* 不可回放提示 */
.modal-playback-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 32px 20px;
  background: #FFFFFF;
}

.hint-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #9CA3AF;
  letter-spacing: 0.3px;
  text-align: center;
  line-height: 1.5;
}

/* 弹窗内数据管理 */
.modal-manage {
  display: flex;
  justify-content: flex-end;
  padding: 0 32px 20px;
  background: #FFFFFF;
  border-top: 1px solid #F3F4F6;
}

.modal-manage-btn {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 7px 14px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.modal-manage-btn.danger {
  color: #B91C1C;
  border: 1px solid #FECACA;
  background: #FFFFFF;
}

.modal-manage-btn.danger:hover {
  border-color: #B91C1C;
  background: #FEF2F2;
}

.modal-manage-btn.empty {
  color: #B45309;
  border: 1px solid #FCD9A5;
  background: #FFFFFF;
  margin-right: 8px;
}

.modal-manage-btn.empty:hover {
  border-color: #F5B861;
  background: #f3f7e6;
}

/* ===== 手机端弹窗 / 布局响应式（置于末尾，确保覆盖上方基础样式） ===== */
@media (max-width: 480px) {
  .modal-content {
    width: 100%;
    max-width: 100vw;
    max-height: 94vh;
    border-radius: 0;
  }
  .modal-divider {
    margin-top: 16px;
  }
  .modal-actions {
    flex-direction: column;
  }
  .modal-actions .modal-btn {
    width: 100%;
  }
}

@media (max-width: 360px) {
  .modal-btn {
    padding: 10px 10px;
  }
  .modal-section {
    gap: 8px;
  }
}
</style>
