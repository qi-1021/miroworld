<template>
  <div class="graph-panel liquid-glass">
    <div class="panel-header">
      <div class="header-left">
        <span class="panel-title">{{ $t('graph.panelTitle') }}</span>
        <span v-if="graphData && totalNodesCount > 0" class="graph-count-badge">
          {{ visibleNodesCount }}/{{ totalNodesCount }}
        </span>
      </div>

      <!-- 顶部控制与工具栏 -->
      <div class="header-tools">
        <!-- 搜索实体 -->
        <div v-if="graphData && totalNodesCount > 0" class="graph-search-box">
          <Search :size="12" class="search-icon" />
          <input
            v-model.trim="searchQuery"
            type="text"
            :placeholder="$t('graph.searchPlaceholder')"
            @input="handleSearch"
          />
          <button v-if="searchQuery" type="button" class="clear-search-btn" @click="clearSearch">×</button>
        </div>

        <!-- 4 种布局模式切换 -->
        <div v-if="graphData && totalNodesCount > 0" class="layout-selector">
          <button
            v-for="layout in layoutOptions"
            :key="layout.id"
            type="button"
            class="layout-btn"
            :class="{ active: currentLayout === layout.id }"
            :title="$t(layout.labelKey)"
            @click="changeLayout(layout.id)"
          >
            <component :is="layout.icon" :size="12" />
            <span class="layout-text">{{ $t(layout.shortKey) }}</span>
          </button>
        </div>

        <!-- 关联度过滤滑块 (大图时显示) -->
        <div v-if="graphData && totalNodesCount > 8" class="degree-filter" :title="$t('graph.minDegreeFilter', { degree: minDegree })">
          <span class="filter-label">
            {{ minDegree > 0 ? `≥${minDegree}` : $t('graph.allDegrees') }}
          </span>
          <input
            v-model.number="minDegree"
            type="range"
            min="0"
            :max="Math.min(maxAvailableDegree, 6)"
            step="1"
            class="degree-slider"
          />
        </div>

        <!-- 视角复位居中 -->
        <button class="tool-btn icon-only" @click="fitView" :title="$t('graph.fitView')">
          <Focus :size="14" />
        </button>

        <!-- 刷新图谱 -->
        <button class="tool-btn" @click="$emit('refresh')" :disabled="loading" :title="$t('graph.refreshGraph')">
          <RefreshCw :size="14" :class="{ 'spinning': loading }" />
          <span class="btn-text">{{ $t('graph.refreshBtn') }}</span>
        </button>

        <!-- 最大化切换 -->
        <button class="tool-btn icon-only" @click="$emit('toggle-maximize')" :title="$t('graph.toggleMaximize')">
          <Maximize2 :size="14" />
        </button>
      </div>
    </div>

    <div class="graph-container" ref="graphContainer">
      <!-- 图谱可视化 -->
      <div v-if="graphData" class="graph-view">
        <svg ref="graphSvg" class="graph-svg" @click="handleSvgBackgroundClick"></svg>

        <!-- 邻域聚焦提示条 -->
        <div v-if="focusedNode" class="focus-banner">
          <span class="focus-text">{{ $t('graph.highlightedNeighbors', { name: focusedNode.name, count: focusedNeighborsCount }) }}</span>
          <button type="button" class="clear-focus-btn" @click="clearFocus">{{ $t('graph.clearFocus') }}</button>
        </div>

        <!-- 构建中/模拟中提示 -->
        <div v-if="currentPhase === 1 || isSimulating" class="graph-building-hint">
          <div class="memory-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="memory-icon">
              <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-4.04z" />
              <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-4.04z" />
            </svg>
          </div>
          {{ isSimulating ? $t('graph.graphMemoryRealtime') : $t('graph.realtimeUpdating') }}
        </div>

        <!-- 模拟结束后的提示 -->
        <div v-if="showSimulationFinishedHint" class="graph-building-hint finished-hint">
          <div class="hint-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hint-icon">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <span class="hint-text">{{ $t('graph.pendingContentHint') }}</span>
          <button class="hint-close-btn" @click="dismissFinishedHint" :title="$t('graph.closeHint')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <!-- 节点/边详情面板 -->
        <div v-if="selectedItem" class="detail-panel">
          <div class="detail-panel-header">
            <span class="detail-title">{{ selectedItem.type === 'node' ? $t('graph.nodeDetails') : $t('graph.relationship') }}</span>
            <span v-if="selectedItem.type === 'node'" class="detail-type-badge" :style="{ background: selectedItem.color, color: '#fff' }">
              {{ selectedItem.entityType }}
            </span>
            <button class="detail-close" @click="closeDetailPanel">×</button>
          </div>

          <!-- 节点详情 -->
          <div v-if="selectedItem.type === 'node'" class="detail-content">
            <div class="detail-row">
              <span class="detail-label">{{ $t('graph.name') }}:</span>
              <span class="detail-value">{{ selectedItem.data.name }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">{{ $t('graph.uuid') }}:</span>
              <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
            </div>
            <div class="detail-row" v-if="selectedItem.data.created_at">
              <span class="detail-label">{{ $t('graph.created') }}:</span>
              <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
            </div>

            <!-- Properties -->
            <div class="detail-section" v-if="selectedItem.data.attributes && Object.keys(selectedItem.data.attributes).length > 0">
              <div class="section-title">{{ $t('graph.properties') }}:</div>
              <div class="properties-list">
                <div v-for="(item) in displayAttributes" :key="item.key" class="property-item">
                  <span class="property-key">{{ item.key }}:</span>
                  <span class="property-value">{{ item.value || 'None' }}</span>
                </div>
              </div>
            </div>

            <!-- Summary -->
            <div class="detail-section" v-if="selectedItem.data.summary">
              <div class="section-title">{{ $t('graph.summary') }}:</div>
              <div class="summary-text">{{ selectedItem.data.summary }}</div>
            </div>

            <!-- Labels -->
            <div class="detail-section" v-if="selectedItem.data.labels && selectedItem.data.labels.length > 0">
              <div class="section-title">{{ $t('graph.labels') }}:</div>
              <div class="labels-list">
                <span v-for="label in selectedItem.data.labels" :key="label" class="label-tag">
                  {{ label }}
                </span>
              </div>
            </div>
          </div>

          <!-- 边详情 -->
          <div v-else class="detail-content">
            <!-- 自环组详情 -->
            <template v-if="selectedItem.data.isSelfLoopGroup">
              <div class="edge-relation-header self-loop-header">
                {{ selectedItem.data.source_name }} - {{ $t('graph.selfRelations') }}
                <span class="self-loop-count">{{ selectedItem.data.selfLoopCount }} {{ $t('graph.selfRelationsItems') }}</span>
              </div>

              <div class="self-loop-list">
                <div
                  v-for="(loop, idx) in selectedItem.data.selfLoopEdges"
                  :key="loop.uuid || idx"
                  class="self-loop-item"
                  :class="{ expanded: expandedSelfLoops.has(loop.uuid || idx) }"
                >
                  <div
                    class="self-loop-item-header"
                    @click="toggleSelfLoop(loop.uuid || idx)"
                  >
                    <span class="self-loop-index">#{{ idx + 1 }}</span>
                    <span class="self-loop-name">{{ loop.name || loop.fact_type || 'RELATED' }}</span>
                    <span class="self-loop-toggle">{{ expandedSelfLoops.has(loop.uuid || idx) ? '−' : '+' }}</span>
                  </div>

                  <div class="self-loop-item-content" v-show="expandedSelfLoops.has(loop.uuid || idx)">
                    <div class="detail-row" v-if="loop.uuid">
                      <span class="detail-label">{{ $t('graph.uuid') }}:</span>
                      <span class="detail-value uuid-text">{{ loop.uuid }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact">
                      <span class="detail-label">{{ $t('graph.fact') }}:</span>
                      <span class="detail-value fact-text">{{ loop.fact }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact_type">
                      <span class="detail-label">{{ $t('graph.type') }}:</span>
                      <span class="detail-value">{{ loop.fact_type }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.created_at">
                      <span class="detail-label">{{ $t('graph.created') }}:</span>
                      <span class="detail-value">{{ formatDateTime(loop.created_at) }}</span>
                    </div>
                    <div v-if="loop.episodes && loop.episodes.length > 0" class="self-loop-episodes">
                      <span class="detail-label">{{ $t('graph.episodes') }}:</span>
                      <div class="episodes-list compact">
                        <span v-for="ep in loop.episodes" :key="ep" class="episode-tag small">{{ ep }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- 普通边详情 -->
            <template v-else>
              <div class="edge-relation-header">
                {{ selectedItem.data.source_name }} → {{ selectedItem.data.name || 'RELATED_TO' }} → {{ selectedItem.data.target_name }}
              </div>
              <div class="detail-row" v-if="selectedItem.data.uuid">
                <span class="detail-label">{{ $t('graph.uuid') }}:</span>
                <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.fact_type">
                <span class="detail-label">{{ $t('graph.type') }}:</span>
                <span class="detail-value">{{ selectedItem.data.fact_type }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.fact">
                <span class="detail-label">{{ $t('graph.fact') }}:</span>
                <span class="detail-value fact-text">{{ selectedItem.data.fact }}</span>
              </div>

              <!-- Episodes -->
              <div class="detail-section" v-if="selectedItem.data.episodes && selectedItem.data.episodes.length > 0">
                <div class="section-title">{{ $t('graph.episodes') }}:</div>
                <div class="episodes-list">
                  <span v-for="ep in selectedItem.data.episodes" :key="ep" class="episode-tag">
                    {{ ep }}
                  </span>
                </div>
              </div>

              <div class="detail-row" v-if="selectedItem.data.created_at">
                <span class="detail-label">{{ $t('graph.created') }}:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.valid_at">
                <span class="detail-label">{{ $t('graph.validFrom') }}:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.valid_at) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-else-if="loading" class="graph-state">
        <div class="loading-spinner"></div>
        <p>{{ $t('graph.graphDataLoading') }}</p>
      </div>

      <!-- 等待/空状态 -->
      <div v-else class="graph-state">
        <div class="empty-icon">❖</div>
        <p class="empty-text">{{ $t('graph.waitingOntology') }}</p>
      </div>
    </div>

    <!-- 底部图例 (可点击过滤分类) -->
    <div v-if="graphData && entityTypes.length" class="graph-legend">
      <span class="legend-title">{{ $t('graph.entityTypes') }}</span>
      <div class="legend-items">
        <button
          v-for="type in entityTypes"
          :key="type.name"
          type="button"
          class="legend-item"
          :class="{ 'dimmed': hiddenTypes.has(type.name) }"
          :title="$t('graph.toggleTypeHint')"
          @click="toggleType(type.name)"
        >
          <span class="legend-dot" :style="{ background: type.color }"></span>
          <span class="legend-label">{{ type.name }}</span>
          <span class="legend-count">({{ type.count }})</span>
        </button>
      </div>
    </div>

    <!-- 显示边标签开关 -->
    <div v-if="graphData" class="edge-labels-toggle">
      <label class="toggle-switch">
        <input type="checkbox" v-model="showEdgeLabels" @change="handleEdgeLabelsToggle" />
        <span class="slider"></span>
      </label>
      <span class="toggle-label">{{ $t('graph.showEdgeLabels') }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed, markRaw } from 'vue'
import { useI18n } from 'vue-i18n'
import * as d3 from 'd3'
import {
  Search,
  RefreshCw,
  Maximize2,
  Focus,
  Network,
  Layers,
  Target,
  CircleDot
} from '@lucide/vue'

const props = defineProps({
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean
})

const emit = defineEmits(['refresh', 'toggle-maximize'])
const { t } = useI18n()

const graphContainer = ref(null)
const graphSvg = ref(null)
const selectedItem = ref(null)

const layoutOptions = [
  { id: 'force', labelKey: 'graph.layoutForce', shortKey: 'graph.layoutForceShort', icon: markRaw(Network) },
  { id: 'cluster', labelKey: 'graph.layoutCluster', shortKey: 'graph.layoutClusterShort', icon: markRaw(Layers) },
  { id: 'radial', labelKey: 'graph.layoutRadial', shortKey: 'graph.layoutRadialShort', icon: markRaw(Target) },
  { id: 'concentric', labelKey: 'graph.layoutConcentric', shortKey: 'graph.layoutConcentricShort', icon: markRaw(CircleDot) }
]

const currentLayout = ref('force')
const searchQuery = ref('')
const minDegree = ref(0)
const hiddenTypes = ref(new Set())
const focusedNodeId = ref(null)
const showEdgeLabels = ref(true)
const expandedSelfLoops = ref(new Set())
const showSimulationFinishedHint = ref(false)
const wasSimulating = ref(false)

let currentSimulation = null
let currentZoom = null
let currentSvgSelection = null
let currentGSelection = null
let nodeSelectionRef = null
let linkSelectionRef = null
let linkLabelsRef = null
let linkLabelBgRef = null
let rawNodeMap = {}
let currentActiveNodes = []
let currentActiveEdges = []

const displayAttributes = computed(() => {
  const attrs = selectedItem.value?.data?.attributes || {}
  return Object.entries(attrs)
    .filter(([k]) => !String(k).toLowerCase().includes('embedding'))
    .map(([key, value]) => ({ key, value }))
})

const totalNodesCount = computed(() => props.graphData?.nodes?.length || 0)
const visibleNodesCount = computed(() => currentActiveNodes.length)

const maxAvailableDegree = computed(() => {
  if (!props.graphData?.nodes || !props.graphData?.edges) return 1
  const counts = {}
  props.graphData.edges.forEach(e => {
    counts[e.source_node_uuid] = (counts[e.source_node_uuid] || 0) + 1
    counts[e.target_node_uuid] = (counts[e.target_node_uuid] || 0) + 1
  })
  const vals = Object.values(counts)
  return vals.length ? Math.max(...vals, 1) : 1
})

const entityTypes = computed(() => {
  if (!props.graphData?.nodes) return []
  const typeMap = {}
  const ACCENT = '#a1c50a'
  const GRAYS = ['#374a63', '#536078', '#7b879e', '#9aa5b8', '#67748a']

  props.graphData.nodes.forEach(node => {
    const type = node.labels?.find(l => l !== 'Entity') || 'Entity'
    if (!typeMap[type]) {
      const idx = Object.keys(typeMap).length
      const color = type.toLowerCase().includes('conflict') || type.toLowerCase().includes('异常') || type.toLowerCase().includes('冲突')
        ? '#c5283d'
        : (idx === 0 ? ACCENT : GRAYS[(idx - 1) % GRAYS.length])
      typeMap[type] = { name: type, count: 0, color }
    }
    typeMap[type].count++
  })
  return Object.values(typeMap)
})

const focusedNode = computed(() => {
  if (!focusedNodeId.value) return null
  return currentActiveNodes.find(n => n.id === focusedNodeId.value) || null
})

const focusedNeighborsCount = computed(() => {
  if (!focusedNodeId.value) return 0
  const neighbors = new Set()
  currentActiveEdges.forEach(e => {
    const sId = typeof e.source === 'object' ? e.source.id : e.source
    const tId = typeof e.target === 'object' ? e.target.id : e.target
    if (sId === focusedNodeId.value && tId !== focusedNodeId.value) neighbors.add(tId)
    if (tId === focusedNodeId.value && sId !== focusedNodeId.value) neighbors.add(sId)
  })
  return neighbors.size
})

const toggleType = (typeName) => {
  const s = new Set(hiddenTypes.value)
  if (s.has(typeName)) {
    s.delete(typeName)
  } else {
    if (s.size < entityTypes.value.length - 1) {
      s.add(typeName)
    }
  }
  hiddenTypes.value = s
  nextTick(renderGraph)
}

const changeLayout = (layoutId) => {
  currentLayout.value = layoutId
  nextTick(renderGraph)
}

const handleSearch = () => {
  if (!searchQuery.value) {
    clearFocus()
    return
  }
  const q = searchQuery.value.toLowerCase()
  const matched = currentActiveNodes.find(n => (n.name || '').toLowerCase().includes(q))
  if (matched) {
    setFocusNode(matched.id)
  }
}

const clearSearch = () => {
  searchQuery.value = ''
  clearFocus()
}

const setFocusNode = (nodeId) => {
  focusedNodeId.value = nodeId
  updateNeighborhoodHighlight()
}

const clearFocus = () => {
  focusedNodeId.value = null
  updateNeighborhoodHighlight()
}

const updateNeighborhoodHighlight = () => {
  if (!nodeSelectionRef || !linkSelectionRef) return
  if (!focusedNodeId.value) {
    nodeSelectionRef.style('opacity', 1)
    linkSelectionRef.style('opacity', 1).attr('stroke', '#C0C0C0').attr('stroke-width', 1.5)
    if (linkLabelsRef) linkLabelsRef.style('opacity', showEdgeLabels.value ? 1 : 0)
    if (linkLabelBgRef) linkLabelBgRef.style('opacity', showEdgeLabels.value ? 1 : 0)
    return
  }

  const targetId = focusedNodeId.value
  const connectedNodes = new Set([targetId])
  const connectedEdgeIndices = new Set()

  currentActiveEdges.forEach((e, idx) => {
    const sId = typeof e.source === 'object' ? e.source.id : e.source
    const tId = typeof e.target === 'object' ? e.target.id : e.target
    if (sId === targetId || tId === targetId) {
      connectedNodes.add(sId)
      connectedNodes.add(tId)
      connectedEdgeIndices.add(idx)
    }
  })

  nodeSelectionRef.style('opacity', d => connectedNodes.has(d.id) ? 1 : 0.12)

  linkSelectionRef.each(function(d, idx) {
    const isConn = connectedEdgeIndices.has(idx)
    d3.select(this)
      .style('opacity', isConn ? 1 : 0.08)
      .attr('stroke', isConn ? '#a1c50a' : '#C0C0C0')
      .attr('stroke-width', isConn ? 2.5 : 1)
  })

  if (linkLabelsRef && linkLabelBgRef) {
    linkLabelsRef.style('opacity', (d, idx) => (showEdgeLabels.value && connectedEdgeIndices.has(idx)) ? 1 : 0)
    linkLabelBgRef.style('opacity', (d, idx) => (showEdgeLabels.value && connectedEdgeIndices.has(idx)) ? 1 : 0)
  }
}

const handleEdgeLabelsToggle = () => {
  if (linkLabelsRef && linkLabelBgRef) {
    const display = showEdgeLabels.value ? 'block' : 'none'
    linkLabelsRef.style('display', display)
    linkLabelBgRef.style('display', display)
  }
}

const fitView = () => {
  if (!currentSvgSelection || !currentZoom || !currentActiveNodes.length) return
  const container = graphContainer.value
  if (!container) return
  const width = container.clientWidth
  const height = container.clientHeight

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  currentActiveNodes.forEach(n => {
    if (n.x !== undefined && n.y !== undefined) {
      if (n.x < minX) minX = n.x
      if (n.x > maxX) maxX = n.x
      if (n.y < minY) minY = n.y
      if (n.y > maxY) maxY = n.y
    }
  })

  if (!isFinite(minX)) return

  const padding = 80
  const dx = Math.max(maxX - minX, 100)
  const dy = Math.max(maxY - minY, 100)
  const midX = (minX + maxX) / 2
  const midY = (minY + maxY) / 2

  const scale = Math.min(Math.max(0.2, Math.min(width / (dx + padding * 2), height / (dy + padding * 2))), 1.6)
  const transform = d3.zoomIdentity
    .translate(width / 2, height / 2)
    .scale(scale)
    .translate(-midX, -midY)

  currentSvgSelection.transition().duration(600).call(currentZoom.transform, transform)
}

const dismissFinishedHint = () => {
  showSimulationFinishedHint.value = false
}

watch(() => props.isSimulating, (newValue, oldValue) => {
  if (wasSimulating.value && !newValue) {
    showSimulationFinishedHint.value = true
  }
  wasSimulating.value = newValue
}, { immediate: true })

const toggleSelfLoop = (id) => {
  const newSet = new Set(expandedSelfLoops.value)
  if (newSet.has(id)) newSet.delete(id)
  else newSet.add(id)
  expandedSelfLoops.value = newSet
}

const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    })
  } catch {
    return dateStr
  }
}

const closeDetailPanel = () => {
  selectedItem.value = null
  expandedSelfLoops.value = new Set()
  clearFocus()
}

const handleSvgBackgroundClick = (event) => {
  if (event.target.tagName === 'svg' || event.target.classList.contains('graph-svg')) {
    closeDetailPanel()
  }
}

const renderGraph = () => {
  if (!graphSvg.value || !props.graphData) return
  if (currentSimulation) currentSimulation.stop()

  const container = graphContainer.value
  const width = container.clientWidth || 800
  const height = container.clientHeight || 600

  const svg = d3.select(graphSvg.value)
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)

  svg.selectAll('*').remove()
  currentSvgSelection = svg

  const rawNodes = props.graphData.nodes || []
  const rawEdges = props.graphData.edges || []
  if (rawNodes.length === 0) {
    currentActiveNodes = []
    currentActiveEdges = []
    return
  }

  rawNodeMap = {}
  rawNodes.forEach(n => rawNodeMap[n.uuid] = n)

  const fullDegreeMap = {}
  rawEdges.forEach(e => {
    fullDegreeMap[e.source_node_uuid] = (fullDegreeMap[e.source_node_uuid] || 0) + 1
    fullDegreeMap[e.target_node_uuid] = (fullDegreeMap[e.target_node_uuid] || 0) + 1
  })

  const filteredNodes = rawNodes.filter(n => {
    const type = n.labels?.find(l => l !== 'Entity') || 'Entity'
    if (hiddenTypes.value.has(type)) return false
    const degree = fullDegreeMap[n.uuid] || 0
    if (minDegree.value > 0 && degree < minDegree.value) return false
    return true
  })

  const visibleIds = new Set(filteredNodes.map(n => n.uuid))

  const nodes = filteredNodes.map(n => ({
    id: n.uuid,
    name: n.name || 'Unnamed',
    type: n.labels?.find(l => l !== 'Entity') || 'Entity',
    rawData: n,
    edgeCount: fullDegreeMap[n.uuid] || 0
  }))

  const nodeMap = {}
  nodes.forEach(n => nodeMap[n.id] = n)

  const edgePairCount = {}
  const selfLoopEdges = {}
  const tempEdges = rawEdges.filter(e => visibleIds.has(e.source_node_uuid) && visibleIds.has(e.target_node_uuid))

  tempEdges.forEach(e => {
    if (e.source_node_uuid === e.target_node_uuid) {
      if (!selfLoopEdges[e.source_node_uuid]) selfLoopEdges[e.source_node_uuid] = []
      selfLoopEdges[e.source_node_uuid].push({
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      })
    } else {
      const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
      edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
    }
  })

  const edgePairIndex = {}
  const processedSelfLoopNodes = new Set()
  const edges = []

  tempEdges.forEach(e => {
    const isSelfLoop = e.source_node_uuid === e.target_node_uuid
    if (isSelfLoop) {
      if (processedSelfLoopNodes.has(e.source_node_uuid)) return
      processedSelfLoopNodes.add(e.source_node_uuid)
      const allSelfLoops = selfLoopEdges[e.source_node_uuid] || []
      const nodeName = nodeMap[e.source_node_uuid]?.name || 'Unknown'
      edges.push({
        source: e.source_node_uuid,
        target: e.target_node_uuid,
        type: 'SELF_LOOP',
        name: `Self (${allSelfLoops.length})`,
        curvature: 0,
        isSelfLoop: true,
        rawData: {
          isSelfLoopGroup: true,
          source_name: nodeName,
          target_name: nodeName,
          selfLoopCount: allSelfLoops.length,
          selfLoopEdges: allSelfLoops
        }
      })
      return
    }

    const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
    const totalCount = edgePairCount[pairKey]
    const currentIndex = edgePairIndex[pairKey] || 0
    edgePairIndex[pairKey] = currentIndex + 1
    const isReversed = e.source_node_uuid > e.target_node_uuid

    let curvature = 0
    if (totalCount > 1) {
      const curvatureRange = Math.min(1.2, 0.6 + totalCount * 0.15)
      curvature = ((currentIndex / (totalCount - 1)) - 0.5) * curvatureRange * 2
      if (isReversed) curvature = -curvature
    }

    edges.push({
      source: e.source_node_uuid,
      target: e.target_node_uuid,
      type: e.fact_type || e.name || 'RELATED',
      name: e.name || e.fact_type || 'RELATED',
      curvature,
      isSelfLoop: false,
      pairIndex: currentIndex,
      pairTotal: totalCount,
      rawData: {
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      }
    })
  })

  currentActiveNodes = nodes
  currentActiveEdges = edges

  const maxDegree = nodes.length ? Math.max(...nodes.map(n => n.edgeCount), 1) : 1
  const hub = nodes.reduce((a, b) => (b.edgeCount > (a?.edgeCount || -1) ? b : a), null)
  if (hub && hub.edgeCount >= 2) hub.isHub = true

  nodes.forEach(n => {
    if (n.isHub) {
      n.size = 26
      return
    }
    const ratio = n.edgeCount / maxDegree
    n.size = 11 + Math.round(9 * ratio)
  })

  const colorMap = {}
  entityTypes.value.forEach(t => colorMap[t.name] = t.color)
  const getColor = (type) => colorMap[type] || '#7b879e'

  const resetNodeShapes = (sel) => {
    if (!sel) return
    sel.selectAll('.node-shape')
      .attr('stroke', d => (d && d.isHub ? '#10203a' : '#fff'))
      .attr('stroke-width', 1.5)
  }

  const layout = currentLayout.value
  let simulation

  if (layout === 'cluster') {
    const uniqueTypes = [...new Set(nodes.map(n => n.type))]
    const clusterCenters = {}
    const clusterRadius = Math.min(width, height) * 0.32
    uniqueTypes.forEach((t, i) => {
      const angle = (i / uniqueTypes.length) * 2 * Math.PI - Math.PI / 2
      clusterCenters[t] = {
        x: width / 2 + clusterRadius * Math.cos(angle),
        y: height / 2 + clusterRadius * Math.sin(angle)
      }
    })

    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(60).strength(0.15))
      .force('charge', d3.forceManyBody().strength(-180))
      .force('collide', d3.forceCollide().radius(d => (d.size || 12) + 8))
      .force('clusterX', d3.forceX(d => clusterCenters[d.type]?.x || width / 2).strength(0.35))
      .force('clusterY', d3.forceY(d => clusterCenters[d.type]?.y || height / 2).strength(0.35))
  } else if (layout === 'radial') {
    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(d => 80 + (d.pairTotal || 1) * 20).strength(0.25))
      .force('charge', d3.forceManyBody().strength(-240))
      .force('collide', d3.forceCollide().radius(d => (d.size || 12) + 10))
      .force('r', d3.forceRadial(d => {
        if (d.isHub) return 0
        if (d.edgeCount >= 3) return Math.min(width, height) * 0.22
        if (d.edgeCount >= 1) return Math.min(width, height) * 0.36
        return Math.min(width, height) * 0.46
      }, width / 2, height / 2).strength(0.4))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.08))

    if (hub) {
      hub.fx = width / 2
      hub.fy = height / 2
    }
  } else if (layout === 'concentric') {
    const sorted = [...nodes].sort((a, b) => b.edgeCount - a.edgeCount)
    const ringCount = Math.max(2, Math.ceil(sorted.length / 12))
    const ringCapacities = [1, 6, 12, 18, 24, 30]
    let nodeIdx = 0

    ringCapacities.forEach((cap, rIdx) => {
      const radius = (rIdx / ringCount) * Math.min(width, height) * 0.44
      const count = Math.min(cap, sorted.length - nodeIdx)
      for (let i = 0; i < count; i++) {
        if (nodeIdx >= sorted.length) break
        const n = sorted[nodeIdx]
        const angle = (i / Math.max(count, 1)) * 2 * Math.PI - Math.PI / 2
        n.fx = width / 2 + radius * Math.cos(angle)
        n.fy = height / 2 + radius * Math.sin(angle)
        nodeIdx++
      }
    })

    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).strength(0.05))
  } else {
    const repulsionStrength = Math.max(-650, -220 - (nodes.length * 8))
    simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(d => 110 + (d.pairTotal || 1) * 25))
      .force('charge', d3.forceManyBody().strength(repulsionStrength))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide().radius(d => (d.size || 12) + 12))
      .force('x', d3.forceX(width / 2).strength(0.04))
      .force('y', d3.forceY(height / 2).strength(0.04))

    if (hub && nodes.length > 5) {
      hub.fx = width / 2
      hub.fy = height / 2
    }
  }

  currentSimulation = simulation

  const g = svg.append('g').attr('class', 'graph-main-g')
  currentGSelection = g

  const zoom = d3.zoom()
    .extent([[0, 0], [width, height]])
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      g.attr('transform', event.transform)
    })

  svg.call(zoom)
  currentZoom = zoom

  const linkGroup = g.append('g').attr('class', 'links')

  const getLinkPath = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y

    if (d.isSelfLoop) {
      const loopRadius = 26
      const x1 = sx + 8, y1 = sy - 4
      const x2 = sx + 8, y2 = sy + 4
      return `M${x1},${y1} A${loopRadius},${loopRadius} 0 1,1 ${x2},${y2}`
    }

    if (d.curvature === 0) {
      return `M${sx},${sy} L${tx},${ty}`
    }

    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.22 + pairTotal * 0.04
    const baseOffset = Math.max(30, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY

    return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`
  }

  const getLinkMidpoint = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y

    if (d.isSelfLoop) return { x: sx + 60, y: sy }
    if (d.curvature === 0) return { x: (sx + tx) / 2, y: (sy + ty) / 2 }

    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.22 + pairTotal * 0.04
    const baseOffset = Math.max(30, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY

    return {
      x: 0.25 * sx + 0.5 * cx + 0.25 * tx,
      y: 0.25 * sy + 0.5 * cy + 0.25 * ty
    }
  }

  const link = linkGroup.selectAll('path')
    .data(edges)
    .enter().append('path')
    .attr('stroke', '#C0C0C0')
    .attr('stroke-width', 1.5)
    .attr('fill', 'none')
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      linkGroup.selectAll('path').attr('stroke', '#C0C0C0').attr('stroke-width', 1.5)
      d3.select(event.target).attr('stroke', '#a1c50a').attr('stroke-width', 3)
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  linkSelectionRef = link

  const linkLabelBg = linkGroup.selectAll('rect')
    .data(edges)
    .enter().append('rect')
    .attr('fill', 'rgba(255,255,255,0.92)')
    .attr('rx', 3)
    .attr('ry', 3)
    .style('cursor', 'pointer')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      linkGroup.selectAll('path').attr('stroke', '#C0C0C0').attr('stroke-width', 1.5)
      link.filter(l => l === d).attr('stroke', '#a1c50a').attr('stroke-width', 3)
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  const linkLabels = linkGroup.selectAll('text')
    .data(edges)
    .enter().append('text')
    .text(d => d.name)
    .attr('font-size', '8.5px')
    .attr('fill', '#666')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .style('cursor', 'pointer')
    .style('font-family', 'system-ui, sans-serif')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      linkGroup.selectAll('path').attr('stroke', '#C0C0C0').attr('stroke-width', 1.5)
      link.filter(l => l === d).attr('stroke', '#a1c50a').attr('stroke-width', 3)
      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  linkLabelsRef = linkLabels
  linkLabelBgRef = linkLabelBg

  const nodeGroup = g.append('g').attr('class', 'nodes')

  const shapeTypeIdx = d => {
    const s = d.type || 'entity'
    let h = 0
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
    return h % 3
  }

  const node = nodeGroup.selectAll('g.node')
    .data(nodes)
    .enter().append('g')
    .attr('class', d => (d.isHub ? 'node hub-node' : 'node'))
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => {
        if (d.isHub && layout !== 'concentric') return
        d.fx = d.x
        d.fy = d.y
        d._dragStartX = event.x
        d._dragStartY = event.y
        d._isDragging = false
      })
      .on('drag', (event, d) => {
        const dx = event.x - d._dragStartX
        const dy = event.y - d._dragStartY
        if (!d._isDragging && Math.sqrt(dx * dx + dy * dy) > 3) {
          d._isDragging = true
          simulation.alphaTarget(0.3).restart()
        }
        if (d._isDragging) {
          d.fx = event.x
          d.fy = event.y
        }
      })
      .on('end', (event, d) => {
        if (d._isDragging) simulation.alphaTarget(0)
        if (layout !== 'concentric') {
          d.fx = null
          d.fy = null
        }
        d._isDragging = false
      })
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      resetNodeShapes(node)
      d3.select(event.currentTarget).selectAll('.node-shape')
        .attr('stroke', '#a1c50a').attr('stroke-width', 3.5)

      selectedItem.value = {
        type: 'node',
        data: d.rawData,
        entityType: d.type,
        color: getColor(d.type)
      }

      setFocusNode(d.id)
    })
    .on('mouseenter', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        d3.select(event.currentTarget).selectAll('.node-shape').attr('stroke', '#10203a').attr('stroke-width', 2.5)
      }
    })
    .on('mouseleave', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        resetNodeShapes(node)
      }
    })

  nodeSelectionRef = node

  node.each(function(d) {
    const ng = d3.select(this)
    ng.append('title').text(() => `${d.name} (${d.type}) · 关联数: ${d.edgeCount}`)
    const r = d.size || 12
    const isHub = !!d.isHub
    const shape = isHub ? 3 : shapeTypeIdx(d)

    if (shape === 0) {
      ng.append('circle')
        .attr('class', 'node-shape')
        .attr('r', r)
        .attr('fill', d => getColor(d.type))
        .attr('fill-opacity', isHub ? 0.9 : 0.4)
        .attr('stroke', '#fff')
        .attr('stroke-width', isHub ? 2 : 1.5)
    } else if (shape === 1) {
      ng.append('rect')
        .attr('class', 'node-shape')
        .attr('x', -r).attr('y', -r)
        .attr('width', r * 2).attr('height', r * 2)
        .attr('rx', 4)
        .attr('fill', d => getColor(d.type))
        .attr('fill-opacity', 0.4)
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
    } else if (shape === 2) {
      ng.append('polygon')
        .attr('class', 'node-shape')
        .attr('points', `0,${-r} ${r * 0.8},0 0,${r} ${-r * 0.8},0`)
        .attr('fill', d => getColor(d.type))
        .attr('fill-opacity', 0.4)
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
    } else {
      ng.append('circle')
        .attr('class', 'node-shape hub-ring')
        .attr('r', r)
        .attr('fill', 'rgba(255,255,255,0.95)')
        .attr('stroke', '#10203a')
        .attr('stroke-width', 2.5)
      ng.append('circle')
        .attr('class', 'node-shape')
        .attr('r', r * 0.62)
        .attr('fill', '#a1c50a')
        .attr('fill-opacity', 0.9)
        .attr('stroke', 'none')
    }
  })

  nodeGroup.selectAll('text')
    .data(nodes)
    .enter().append('text')
    .text(d => d.name.length > 9 ? d.name.substring(0, 9) + '…' : d.name)
    .attr('font-size', d => (d.isHub ? 12 : 10) + 'px')
    .attr('font-weight', d => (d.isHub ? 700 : 500))
    .attr('fill', '#10203a')
    .attr('x', d => (d.size || 12) + 6)
    .attr('y', 3.5)
    .style('pointer-events', 'none')
    .style('font-family', 'system-ui, sans-serif')

  simulation.on('tick', () => {
    link.attr('d', d => getLinkPath(d))

    linkLabels.each(function(d) {
      const mid = getLinkMidpoint(d)
      d3.select(this).attr('x', mid.x).attr('y', mid.y)
    })

    linkLabelBg.each(function(d, i) {
      const mid = getLinkMidpoint(d)
      const textEl = linkLabels.nodes()[i]
      if (textEl) {
        const bbox = textEl.getBBox()
        d3.select(this)
          .attr('x', mid.x - bbox.width / 2 - 3)
          .attr('y', mid.y - bbox.height / 2 - 2)
          .attr('width', bbox.width + 6)
          .attr('height', bbox.height + 4)
      }
    })

    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })

  if (focusedNodeId.value) {
    updateNeighborhoodHighlight()
  }
}

watch(() => props.graphData, () => {
  nextTick(renderGraph)
}, { deep: true })

watch(minDegree, () => {
  nextTick(renderGraph)
})

const handleResize = () => {
  nextTick(renderGraph)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (currentSimulation) currentSimulation.stop()
})
</script>

<style scoped>
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  background: #fdfdfd;
  background-image: radial-gradient(rgba(0,0,0,0.03) 1px, transparent 1px);
  background-size: 20px 20px;
  overflow: hidden;
  border-radius: 12px;
}

.panel-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 16px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  background: linear-gradient(to bottom, rgba(255,255,255,0.96), rgba(255,255,255,0.85) 75%, rgba(255,255,255,0));
  pointer-events: none;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  pointer-events: auto;
}

.panel-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--mf-ink, #10203a);
}

.graph-count-badge {
  padding: 2px 6px;
  background: #f0f3e8;
  color: #4e6400;
  border: 1px solid #d2e49c;
  font-size: 9px;
  font-weight: 800;
  border-radius: 4px;
}

.header-tools {
  pointer-events: auto;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.graph-search-box {
  position: relative;
  display: flex;
  align-items: center;
  background: #fff;
  border: 1px solid #d0d0d0;
  border-radius: 5px;
  padding: 0 6px;
  height: 28px;
}

.graph-search-box input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 10px;
  width: 90px;
  color: #333;
}

.search-icon {
  color: #888;
  margin-right: 4px;
}

.clear-search-btn {
  border: none;
  background: transparent;
  color: #999;
  cursor: pointer;
  font-size: 12px;
  padding: 0 2px;
}

.layout-selector {
  display: flex;
  background: #eee;
  padding: 2px;
  border-radius: 6px;
  gap: 2px;
}

.layout-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border: none;
  background: transparent;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  color: #666;
  cursor: pointer;
  transition: all 0.15s;
}

.layout-btn.active {
  background: #fff;
  color: #10203a;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.layout-btn:hover:not(.active) {
  color: #222;
}

.degree-filter {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #fff;
  border: 1px solid #d0d0d0;
  padding: 0 6px;
  height: 28px;
  border-radius: 5px;
}

.filter-label {
  font-size: 9px;
  font-weight: 700;
  color: #555;
  white-space: nowrap;
}

.degree-slider {
  width: 50px;
  height: 4px;
  cursor: pointer;
  accent-color: #a1c50a;
}

.tool-btn {
  height: 28px;
  padding: 0 9px;
  border: 1px solid #d0d0d0;
  background: #FFF;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  cursor: pointer;
  color: #555;
  transition: all 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  font-size: 11px;
}

.tool-btn.icon-only {
  padding: 0;
  width: 28px;
}

.tool-btn:hover {
  background: #F8F8F8;
  color: #10203a;
  border-color: #aaa;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.focus-banner {
  position: absolute;
  top: 54px;
  left: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(16, 32, 58, 0.88);
  color: #fff;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 10px;
  box-shadow: 0 3px 10px rgba(0,0,0,0.15);
  z-index: 9;
}

.clear-focus-btn {
  border: none;
  background: #a1c50a;
  color: #10203a;
  padding: 2px 6px;
  font-size: 9px;
  font-weight: 800;
  border-radius: 3px;
  cursor: pointer;
}

.graph-container {
  width: 100%;
  height: 100%;
}

.graph-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #999;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.2;
}

.graph-legend {
  position: absolute;
  bottom: 16px;
  left: 16px;
  background: rgba(255,255,255,0.96);
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid #EAEAEA;
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
  z-index: 10;
}

.legend-title {
  display: block;
  font-size: 10px;
  font-weight: 700;
  color: var(--mf-ink, #10203a);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.legend-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  max-width: 320px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px;
  border: 1px solid #e2e2e0;
  background: #fafaf8;
  border-radius: 4px;
  font-size: 10px;
  color: #444;
  cursor: pointer;
  transition: all 0.15s;
}

.legend-item:hover {
  background: #f0f0ee;
  border-color: #bbb;
}

.legend-item.dimmed {
  opacity: 0.35;
  text-decoration: line-through;
  background: #ececec;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-count {
  font-size: 9px;
  color: #888;
}

.edge-labels-toggle {
  position: absolute;
  bottom: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255,255,255,0.94);
  padding: 6px 12px;
  border-radius: 20px;
  border: 1px solid #E0E0E0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  z-index: 10;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 34px;
  height: 18px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #E0E0E0;
  border-radius: 18px;
  transition: 0.3s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

input:checked + .slider {
  background-color: #a1c50a;
}

input:checked + .slider:before {
  transform: translateX(16px);
}

.toggle-label {
  font-size: 10px;
  font-weight: 600;
  color: #555;
}

.detail-panel {
  position: absolute;
  top: 52px;
  right: 16px;
  width: 320px;
  max-height: calc(100% - 70px);
  background: rgba(255,255,255,0.97);
  border-radius: 10px;
  border: 1px solid #E0E0E0;
  box-shadow: 0 6px 24px rgba(0,0,0,0.1);
  overflow-y: auto;
  z-index: 12;
  padding: 14px;
}

.detail-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eee;
  margin-bottom: 12px;
}

.detail-title {
  font-size: 13px;
  font-weight: 700;
  color: #222;
}

.detail-type-badge {
  padding: 2px 7px;
  font-size: 9px;
  font-weight: 700;
  border-radius: 3px;
}

.detail-close {
  border: none;
  background: transparent;
  font-size: 18px;
  color: #999;
  cursor: pointer;
  line-height: 1;
}

.detail-close:hover {
  color: #333;
}

.detail-content {
  font-size: 11px;
}

.detail-row {
  display: flex;
  margin-bottom: 6px;
  line-height: 1.4;
}

.detail-label {
  width: 65px;
  flex-shrink: 0;
  color: #888;
  font-weight: 600;
}

.detail-value {
  color: #333;
  word-break: break-all;
}

.uuid-text {
  font-family: monospace;
  font-size: 10px;
  color: #666;
}

.fact-text {
  background: #f8f8f6;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: #333;
}

.detail-section {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}

.section-title {
  font-size: 10px;
  font-weight: 700;
  color: #777;
  text-transform: uppercase;
  margin-bottom: 5px;
}

.summary-text {
  background: #f9f9f8;
  padding: 6px 8px;
  border-radius: 4px;
  line-height: 1.45;
  color: #444;
}

.labels-list, .episodes-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.label-tag, .episode-tag {
  padding: 2px 6px;
  background: #eef2f7;
  color: #355070;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 600;
}

.edge-relation-header {
  flex-shrink: 0;
}

.hint-close-btn:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: scale(1.1);
}

/* Loading spinner */
.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #E0E0E0;
  border-top-color: #a1c50a;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

/* Self-loop styles */
.self-loop-header {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #f3f7e6 0%, #eef2e6 100%);
  border: 1px solid #dbe3c8;
}

.self-loop-count {
  margin-left: auto;
  font-size: 11px;
  color: #666;
  background: rgba(255,255,255,0.8);
  padding: 2px 8px;
  border-radius: 10px;
}

.self-loop-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-loop-item {
  background: #FAFAFA;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
}

.self-loop-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #F5F5F5;
  cursor: pointer;
  transition: background 0.2s;
}

.self-loop-item-header:hover {
  background: #EEEEEE;
}

.self-loop-item.expanded .self-loop-item-header {
  background: #E8E8E8;
}

.self-loop-index {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  padding: 2px 6px;
  border-radius: 4px;
}

.self-loop-name {
  font-size: 12px;
  font-weight: 500;
  color: #333;
  flex: 1;
}

.self-loop-toggle {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #888;
  background: #E0E0E0;
  border-radius: 4px;
  transition: all 0.2s;
}

.self-loop-item.expanded .self-loop-toggle {
  background: #D0D0D0;
  color: #666;
}

.self-loop-item-content {
  padding: 12px;
  border-top: 1px solid #EAEAEA;
}

.self-loop-item-content .detail-row {
  margin-bottom: 8px;
}

.self-loop-item-content .detail-label {
  font-size: 11px;
  min-width: 60px;
}

.self-loop-item-content .detail-value {
  font-size: 12px;
}

.self-loop-episodes {
  margin-top: 8px;
}

.episodes-list.compact {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px;
}

.episode-tag.small {
  padding: 3px 6px;
  font-size: 9px;
}
</style>
