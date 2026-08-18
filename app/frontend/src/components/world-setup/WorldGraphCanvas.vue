<template>
  <div v-if="graphInfo && graphNodes.length" class="graph-viz-wrap" :class="{ fullscreen: isGraphFullscreen }">
    <!-- 顶部地图工具栏：搜索、缩放、聚焦、全屏 -->
    <div class="graph-toolbar">
      <div class="graph-search-box">
        <span class="search-icon">🔍</span>
        <input
          v-model="graphSearchQuery"
          type="text"
          class="graph-search-input"
          placeholder="搜索图谱实体节点 (回车定位)..."
          @keyup.enter="focusSearchedNode"
        />
        <button
          v-if="graphSearchQuery"
          type="button"
          class="graph-search-clear"
          @click="graphSearchQuery = ''; selectedGraphNode = null"
        >✕</button>
      </div>

      <div v-if="graphSearchResults.length > 0 && graphSearchQuery.trim()" class="graph-search-dropdown">
        <div
          v-for="sn in graphSearchResults.slice(0, 6)"
          :key="sn.uuid"
          class="search-result-item"
          :class="{ active: selectedGraphNode && selectedGraphNode.uuid === sn.uuid }"
          @click="locateAndSelectNode(sn)"
        >
          <span class="sn-dot" :style="{ background: graphNodeColor(sn) }"></span>
          <span class="sn-name">{{ sn.name }}</span>
          <span class="sn-type">{{ graphNodeType(sn) }}</span>
        </div>
      </div>

      <div class="graph-legend-bar">
        <span v-if="graphBuilding" class="badge processing pulse-growing" style="margin-right: 8px; font-weight: bold; background: rgba(52, 152, 219, 0.2); border: 1px solid #3498db; color: #5dade2;">
          🌱 正在实时抽取并生长图谱... (已点亮 {{ graphNodes.length }} 实体)
        </span>
        <button
          type="button"
          class="legend-tag setting-tag"
          :class="{ active: sourceFilter === 'all' || sourceFilter === 'setting' }"
          @click="toggleSourceFilter('setting')"
          title="点击按来源筛选"
        >
          <span class="legend-ring setting-ring"></span> 设定基石实体
        </button>
        <button
          type="button"
          class="legend-tag dynamic-tag"
          :class="{ active: sourceFilter === 'all' || sourceFilter === 'dynamic' }"
          @click="toggleSourceFilter('dynamic')"
          title="点击按来源筛选"
        >
          <span class="legend-ring dynamic-ring"></span> 正文/推演衍生
        </button>
      </div>

      <div class="graph-controls">
        <span class="graph-zoom-label">{{ Math.round(graphZoom * 100) }}%</span>
        <button type="button" class="graph-ctrl-btn" title="放大" @click="zoomGraph(0.2)">➕</button>
        <button type="button" class="graph-ctrl-btn" title="缩小" @click="zoomGraph(-0.2)">➖</button>
        <button type="button" class="graph-ctrl-btn" title="重置地图视角" @click="resetGraphView">🎯 复位</button>
        <button type="button" class="graph-ctrl-btn" :title="isGraphFullscreen ? '退出全屏' : '全屏地图'" @click="toggleGraphFullscreen">
          {{ isGraphFullscreen ? '🗗 退出' : '⛶ 全屏' }}
        </button>
      </div>
    </div>

    <!-- 地图主体画布容器（支持鼠标拖动画布、滚轮缩放、节点高亮关系） -->
    <div
      ref="graphCanvasWrap"
      class="graph-canvas-viewport"
      :class="{ dragging: isPanningGraph }"
      @mousedown="startPanGraph"
      @wheel.prevent="handleGraphWheel"
    >
      <svg
        ref="graphSvg"
        :viewBox="`0 0 ${GV_W} ${GV_H}`"
        class="graph-svg"
      >
        <defs>
          <!-- 坐标网格底纹：赋予地图空间感 -->
          <pattern id="graph-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(148, 163, 184, 0.08)" stroke-width="1" />
            <circle cx="40" cy="40" r="1.2" fill="rgba(148, 163, 184, 0.18)" />
          </pattern>
          <!-- 关系连线流动光效 / 箭头 -->
          <marker id="edge-arrow" viewBox="0 -5 10 10" refX="22" refY="0" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,-4L10,0L0,4" fill="rgba(148, 163, 184, 0.5)" />
          </marker>
          <marker id="edge-arrow-active" viewBox="0 -5 10 10" refX="22" refY="0" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,-4L10,0L0,4" fill="#a1c50a" />
          </marker>
        </defs>

        <!-- 网格背景层 -->
        <rect width="100%" height="100%" fill="url(#graph-grid)" />

        <!-- 可平移缩放的内容主容器 -->
        <g :transform="`translate(${graphPan.x}, ${graphPan.y}) scale(${graphZoom})`">
          <!-- 连线层 -->
          <g class="graph-edges-layer">
            <g v-for="(e, i) in graphEdges" :key="'e' + i" class="edge-group">
              <line
                :x1="graphNodeX(e.source)"
                :y1="graphNodeY(e.source)"
                :x2="graphNodeX(e.target)"
                :y2="graphNodeY(e.target)"
                class="graph-edge"
                :class="{
                  highlight: isEdgeConnected(e),
                  dimmed: isEdgeDimmed(e) || (sourceFilter !== 'all' && (!isNodeMatchingSource(e.source) || !isNodeMatchingSource(e.target)))
                }"
                :marker-end="isEdgeConnected(e) ? 'url(#edge-arrow-active)' : 'url(#edge-arrow)'"
              />
              <!-- 边关系名称标签（带有半透明背景框与完整事实悬浮提示，杜绝文字堆叠重合） -->
              <g
                v-if="e.fact && (isEdgeConnected(e) || graphZoom >= 1.15)"
                class="edge-label-badge"
              >
                <!-- 标签背景胶囊气泡，防止与连线或多条关系发生字体重叠 -->
                <rect
                  :x="(graphNodeX(e.source) + graphNodeX(e.target)) / 2 - (e.fact.length * 5.5 + 6)"
                  :y="(graphNodeY(e.source) + graphNodeY(e.target)) / 2 - 11"
                  :width="e.fact.length * 11 + 12"
                  height="18"
                  rx="9"
                  class="edge-label-bg"
                  :class="{ active: isEdgeConnected(e) }"
                />
                <text
                  :x="(graphNodeX(e.source) + graphNodeX(e.target)) / 2"
                  :y="(graphNodeY(e.source) + graphNodeY(e.target)) / 2 + 2"
                  class="graph-edge-label"
                  :class="{ active: isEdgeConnected(e) }"
                  text-anchor="middle"
                >
                  {{ e.fact }}
                </text>
                <title>{{ e.full_fact || e.fact }}</title>
              </g>
            </g>
          </g>

          <!-- 节点层 -->
          <g class="graph-nodes-layer">
            <g
              v-for="(n, i) in graphNodes"
              :key="'n' + i"
              v-memo="[n.uuid, graphPos[n.uuid]?.x, graphPos[n.uuid]?.y, selectedGraphNode?.uuid === n.uuid, isNodeConnectedToSelected(n.uuid), sourceFilter]"
              :transform="`translate(${graphNodeX(n.uuid)},${graphNodeY(n.uuid)})`"
              class="node-group"
              :class="{
                selected: selectedGraphNode && selectedGraphNode.uuid === n.uuid,
                connected: isNodeConnectedToSelected(n.uuid),
                dimmed: isNodeDimmed(n.uuid) || (sourceFilter !== 'all' && !isNodeMatchingSource(n.uuid)),
                'is-setting-node': isSettingNode(n),
                'is-dynamic-node': !isSettingNode(n)
              }"
              @click.stop="toggleSelectGraphNode(n)"
              @mousedown.stop="startDragNode(n, $event)"
            >
              <!-- 选中节点光晕涟漪 -->
              <circle
                v-if="selectedGraphNode && selectedGraphNode.uuid === n.uuid"
                :r="graphNodeR(n) + 10"
                class="node-halo"
              />
              <!-- 设定基石节点外层双环 / 菱角标识 -->
              <circle
                v-if="isSettingNode(n)"
                :r="graphNodeR(n) + 4"
                class="setting-node-outer"
              />
              <!-- 衍生实体节点外层虚线环 -->
              <circle
                v-else
                :r="graphNodeR(n) + 3"
                class="dynamic-node-outer"
              />
              <!-- 节点外圆主体 -->
              <circle
                :r="graphNodeR(n)"
                class="graph-node"
                :style="{ fill: graphNodeColor(n) }"
              />
              <!-- 节点源头徽标（金星代表设定基石） -->
              <text
                v-if="isSettingNode(n)"
                class="setting-badge-icon"
                text-anchor="middle"
                dy=".35em"
              >✦</text>

              <!-- 节点主体名称 -->
              <text
                class="graph-node-label"
                text-anchor="middle"
                :y="graphNodeR(n) + 14"
              >
                {{ n.name }}
              </text>
              <!-- 节点类型小标（放大或选中时展示） -->
              <text
                v-if="graphZoom >= 1.1 || (selectedGraphNode && selectedGraphNode.uuid === n.uuid)"
                class="graph-node-sublabel"
                text-anchor="middle"
                :y="graphNodeR(n) + 25"
              >
                {{ graphNodeType(n) }}
              </text>
            </g>
          </g>
        </g>
      </svg>

      <!-- 节点关系分析悬浮面板 -->
      <div v-if="selectedGraphNode" class="graph-node-info-panel">
        <div class="panel-head">
          <div class="panel-title-wrap">
            <span class="panel-dot" :style="{ background: graphNodeColor(selectedGraphNode) }"></span>
            <span class="panel-title">{{ selectedGraphNode.name }}</span>
            <span class="panel-type-badge">{{ graphNodeType(selectedGraphNode) }}</span>
            <span
              class="panel-source-badge"
              :class="isSettingNode(selectedGraphNode) ? 'badge-setting' : 'badge-dynamic'"
            >
              {{ isSettingNode(selectedGraphNode) ? '✦ 设定基石' : '⚡ 演化衍生' }}
            </span>
          </div>
          <button type="button" class="panel-close-btn" @click="selectedGraphNode = null">✕</button>
        </div>

        <div v-if="selectedGraphNode.summary" class="panel-summary">
          {{ selectedGraphNode.summary }}
        </div>

        <!-- 与其他节点的直接联系网络 -->
        <div class="panel-relations">
          <div class="relations-title">
            🔗 关联关系 ({{ selectedNodeConnections.length }})
          </div>
          <div v-if="!selectedNodeConnections.length" class="empty-relations">
            该实体在当前章节尚未建立直接关系边
          </div>
          <div v-else class="relations-list">
            <div
              v-for="(rel, ri) in selectedNodeConnections"
              :key="ri"
              class="relation-item"
              @click="locateAndSelectNode(rel.targetNode)"
            >
              <div class="rel-item-header">
                <span class="rel-predicate">【{{ rel.fact || '关联' }}】</span>
                <span class="rel-target-name">👉 {{ rel.targetNode.name }}</span>
                <span class="rel-target-type">({{ graphNodeType(rel.targetNode) }})</span>
              </div>
              <div v-if="rel.full_fact && rel.full_fact !== rel.fact" class="rel-full-text">
                {{ rel.full_fact }}
              </div>
            </div>
          </div>
        </div>

        <div v-if="selectedGraphAttrs.length" class="panel-attrs">
          <div v-for="(row, ai) in selectedGraphAttrs" :key="ai" class="panel-attr-row">
            <span class="attr-k">{{ row[0] }}:</span>
            <span class="attr-v">{{ row[1] }}</span>
          </div>
        </div>

        <!-- 与选定实体交互（仅针对角色/人物提供深度访谈对话，非人物提供设定档案定位） -->
        <div class="panel-chat-action">
          <button
            v-if="isCharacterNode(selectedGraphNode)"
            type="button"
            class="panel-chat-btn"
            @click="$emit('open-interview', selectedGraphNode)"
          >
            💬 与 {{ selectedGraphNode.name }} 开启角色访谈对话
          </button>
          <div v-else class="non-char-tip">
            <span>🏛️ 此实体为【{{ graphNodeType(selectedGraphNode) }}】设定要素，已自动收录进世界法则数据库</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  graphInfo: {
    type: Object,
    default: null
  },
  graphBuilding: {
    type: Boolean,
    default: false
  },
  characters: {
    type: Array,
    default: () => []
  }
})

defineEmits(['open-interview'])

const GV_W = 1400
const GV_H = 800
const graphPos = ref({})
const selectedGraphNode = ref(null)
const sourceFilter = ref('all')
const graphPan = ref({ x: 0, y: 0 })
const graphZoom = ref(1.0)
const isPanningGraph = ref(false)
const isGraphFullscreen = ref(false)
const graphSearchQuery = ref('')
const graphCanvasWrap = ref(null)
let panStart = { x: 0, y: 0, origX: 0, origY: 0 }
let activeDraggingNode = null
let dragStartPos = { x: 0, y: 0, nodeOrigX: 0, nodeOrigY: 0 }

const GRAPH_COLORS = [
  '#6366F1', '#06B6D4', '#10B981', '#F59E0B',
  '#EC4899', '#8B5CF6', '#EF4444', '#14B8A6', '#F97316'
]

function cleanEdgeFact(raw) {
  if (!raw || typeof raw !== 'string') return '关联'
  let s = raw.trim()
  s = s.replace(/^[“"']|[”"']$/g, '').trim()
  const PREDICATE_PATTERNS = [
    { reg: /(?:隶属|从属|归属|属于|是.*的成员|加入)/i, label: '隶属于' },
    { reg: /(?:出生|成长|定居|来自)/i, label: '出生于' },
    { reg: /(?:驻扎|派驻|驻守|工作于|位于|地处)/i, label: '驻扎于' },
    { reg: /(?:师承|跟随|指导|教导|学习)/i, label: '师承' },
    { reg: /(?:持有|拥有|控制|佩戴|保管|使用)/i, label: '持有' },
    { reg: /(?:对立|敌对|冲突|开战|作战|交战|反抗)/i, label: '对立于' },
    { reg: /(?:覆灭|毁灭|消灭|摧毁|击败)/i, label: '覆灭' },
    { reg: /(?:结盟|同盟|合作|援助|救助)/i, label: '结盟' },
    { reg: /(?:领导|指挥|统率|管辖)/i, label: '领导' },
    { reg: /(?:影响|改变|塑造|波及)/i, label: '影响' },
    { reg: /(?:创造|建立|创立|研发|制造)/i, label: '创立' },
    { reg: /(?:连接|通往|穿梭)/i, label: '连接' },
    { reg: /(?:亲属|父母|子女|兄弟|姐妹|母亲|父亲|孩子)/i, label: '亲属' }
  ]
  for (const p of PREDICATE_PATTERNS) {
    if (p.reg.test(s)) return p.label
  }
  s = s.replace(/^(在|从|由|被|与|和|对|向|关于|因为|由于)/, '')
  if (s.length > 6) s = s.slice(0, 5)
  return s || '关联'
}

const graphNodes = computed(() => (props.graphInfo && props.graphInfo.nodes) || [])
const graphEdges = computed(() => {
  if (!props.graphInfo || !props.graphInfo.edges) return []
  return props.graphInfo.edges.map(e => {
    const rawFact = e.fact || e.name || ''
    return {
      source: e.source_node_uuid,
      target: e.target_node_uuid,
      fact: cleanEdgeFact(rawFact),
      full_fact: rawFact
    }
  })
})

function graphNodeType(n) {
  const labels = (n.labels || []).filter(l => l !== 'Entity')
  return labels.join(' / ') || '实体'
}

function isCharacterNode(n) {
  if (!n) return false
  const labels = (n.labels || []).map(l => String(l).toLowerCase())
  const typeStr = graphNodeType(n).toLowerCase()
  const nameStr = (n.name || '').toLowerCase()
  const attrs = (n.attributes && typeof n.attributes === 'object') ? n.attributes : {}
  
  const nonCharKeywords = [
    '物品', '器物', '法宝', '武器', '炸弹', '酒类', '道具', '药剂', '装备', '材料',
    '国家', '地点', '城市', '建筑', '区域', '星门', '场所', '遗迹',
    '事件', '战役', '故事', '灾难', '历史',
    '概念', '法则', '境界', '疾病', '矿石病', '知识', '技术',
    'item', 'weapon', 'location', 'place', 'city', 'country', 'event', 'concept'
  ]
  if (labels.some(l => nonCharKeywords.some(k => l.includes(k)))) return false
  if (nonCharKeywords.some(k => typeStr.includes(k))) return false
  if (nonCharKeywords.some(k => nameStr.includes(k))) return false

  const charArr = props.characters || []
  if (charArr.some(c => {
    const cName = typeof c === 'string' ? c : (c?.name || '')
    return cName && n.name && cName.trim() === n.name.trim()
  })) return true

  const charKeywords = [
    '个人', '个体', '人类', '人物', '角色', '职业', '医生', '干员', '领袖', '主角', '配角', 
    '指挥官', '老师', '居民', '神祇', '英雄', '生物', '人', 'person', 'character', 'agent', 'npc', 'individual', 'human'
  ]
  if (labels.some(l => charKeywords.some(k => l.includes(k)))) return true
  if (charKeywords.some(k => typeStr.includes(k))) return true
  
  if (attrs.role || attrs.full_name || attrs.profession_name || attrs.key_trait) {
    return true
  }

  return false
}

function graphNodeColor(n) {
  const type = graphNodeType(n)
  let hash = 0
  for (const ch of type) hash = (hash * 31 + ch.codePointAt(0)) >>> 0
  return GRAPH_COLORS[hash % GRAPH_COLORS.length]
}

function graphNodeR(n) {
  const name = (n.name || '').length
  const isSelected = selectedGraphNode.value && selectedGraphNode.value.uuid === n.uuid
  const baseR = name > 6 ? 15 : 12
  return isSelected ? baseR + 3 : baseR
}

function graphNodeX(uuid) {
  const p = graphPos.value[uuid]
  return p ? p.x : GV_W / 2
}

function graphNodeY(uuid) {
  const p = graphPos.value[uuid]
  return p ? p.y : GV_H / 2
}

const selectedGraphAttrs = computed(() => {
  const n = selectedGraphNode.value
  if (!n || !n.attributes) return []
  return Object.entries(n.attributes).filter(([k, v]) => {
    if (typeof v === 'string' && v.length > 200) return false
    return true
  }).slice(0, 12)
})

function isSettingNode(n) {
  if (!n) return false
  if (n.source_type === 'setting' || n.is_setting || n.source === 'setting') return true
  const charArr = props.characters || []
  const inCharList = charArr.some(c => {
    const cName = typeof c === 'string' ? c : (c?.name || '')
    return cName && n.name && cName.trim() === n.name.trim()
  })
  if (inCharList) return true
  if (n.attributes && typeof n.attributes === 'object') {
    if (n.attributes.is_setting || n.attributes.source === 'world_bible' || n.attributes.origin === 'setting') {
      return true
    }
  }
  if (n.summary && typeof n.summary === 'string' && (n.summary.includes('设定') || n.summary.includes('世界观') || n.summary.includes('背景'))) {
    return true
  }
  return false
}

function isNodeMatchingSource(uuid) {
  if (sourceFilter.value === 'all') return true
  const node = graphNodes.value.find(n => n.uuid === uuid)
  if (!node) return true
  const isSet = isSettingNode(node)
  return sourceFilter.value === 'setting' ? isSet : !isSet
}

function toggleSourceFilter(type) {
  sourceFilter.value = sourceFilter.value === type ? 'all' : type
}

const graphSearchResults = computed(() => {
  const q = graphSearchQuery.value.trim().toLowerCase()
  if (!q || !graphNodes.value.length) return []
  return graphNodes.value.filter(n => {
    const nameMatch = (n.name || '').toLowerCase().includes(q)
    const typeMatch = graphNodeType(n).toLowerCase().includes(q)
    const summaryMatch = (n.summary || '').toLowerCase().includes(q)
    return nameMatch || typeMatch || summaryMatch
  })
})

const selectedNodeConnections = computed(() => {
  const sn = selectedGraphNode.value
  if (!sn || !graphEdges.value.length) return []
  const list = []
  const nodeMap = new Map(graphNodes.value.map(n => [n.uuid, n]))
  graphEdges.value.forEach(e => {
    if (e.source === sn.uuid) {
      const target = nodeMap.get(e.target)
      if (target) list.push({ edge: e, fact: e.fact, full_fact: e.full_fact, targetNode: target, direction: 'out' })
    } else if (e.target === sn.uuid) {
      const target = nodeMap.get(e.source)
      if (target) list.push({ edge: e, fact: e.fact, full_fact: e.full_fact, targetNode: target, direction: 'in' })
    }
  })
  return list
})

const connectedNodeUuids = computed(() => {
  const sn = selectedGraphNode.value
  if (!sn) return new Set()
  const set = new Set([sn.uuid])
  selectedNodeConnections.value.forEach(c => set.add(c.targetNode.uuid))
  return set
})

function toggleSelectGraphNode(n) {
  if (selectedGraphNode.value && selectedGraphNode.value.uuid === n.uuid) {
    selectedGraphNode.value = null
  } else {
    selectedGraphNode.value = n
  }
}

function isNodeConnectedToSelected(uuid) {
  if (!selectedGraphNode.value) return false
  return connectedNodeUuids.value.has(uuid)
}

function isNodeDimmed(uuid) {
  if (!selectedGraphNode.value) return false
  return !connectedNodeUuids.value.has(uuid)
}

function isEdgeConnected(e) {
  if (!selectedGraphNode.value) return false
  const sUuid = selectedGraphNode.value.uuid
  return e.source === sUuid || e.target === sUuid
}

function isEdgeDimmed(e) {
  if (!selectedGraphNode.value) return false
  const sUuid = selectedGraphNode.value.uuid
  return e.source !== sUuid && e.target !== sUuid
}

function startPanGraph(evt) {
  if (evt.target.closest('.node-group') || evt.target.closest('.graph-controls') || evt.target.closest('.graph-node-info-panel')) return
  isPanningGraph.value = true
  panStart = { x: evt.clientX, y: evt.clientY, origX: graphPan.value.x, origY: graphPan.value.y }
  const onMouseMove = (e) => {
    if (!isPanningGraph.value) return
    graphPan.value = {
      x: Math.round(panStart.origX + (e.clientX - panStart.x)),
      y: Math.round(panStart.origY + (e.clientY - panStart.y))
    }
  }
  const onMouseUp = () => {
    isPanningGraph.value = false
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function handleGraphWheel(evt) {
  const delta = evt.deltaY > 0 ? -0.1 : 0.1
  zoomGraph(delta)
}

function zoomGraph(delta) {
  const nextZoom = Math.min(2.5, Math.max(0.4, Number((graphZoom.value + delta).toFixed(2))))
  graphZoom.value = nextZoom
}

function resetGraphView() {
  graphPan.value = { x: 0, y: 0 }
  graphZoom.value = 1.0
  selectedGraphNode.value = null
}

function toggleGraphFullscreen() {
  isGraphFullscreen.value = !isGraphFullscreen.value
}

function locateAndSelectNode(n) {
  if (!n) return
  selectedGraphNode.value = n
  const p = graphPos.value[n.uuid]
  if (p) {
    graphPan.value = {
      x: Math.round(GV_W / 2 - p.x * graphZoom.value),
      y: Math.round(GV_H / 2 - p.y * graphZoom.value)
    }
  }
}

function focusSearchedNode() {
  if (graphSearchResults.value.length > 0) {
    locateAndSelectNode(graphSearchResults.value[0])
    graphSearchQuery.value = ''
  }
}

function startDragNode(n, evt) {
  activeDraggingNode = n
  const p = graphPos.value[n.uuid] || { x: GV_W / 2, y: GV_H / 2 }
  dragStartPos = {
    x: evt.clientX,
    y: evt.clientY,
    nodeOrigX: p.x,
    nodeOrigY: p.y
  }
  const onMouseMove = (e) => {
    if (!activeDraggingNode) return
    const dx = (e.clientX - dragStartPos.x) / graphZoom.value
    const dy = (e.clientY - dragStartPos.y) / graphZoom.value
    graphPos.value[activeDraggingNode.uuid] = {
      x: Math.round(dragStartPos.nodeOrigX + dx),
      y: Math.round(dragStartPos.nodeOrigY + dy)
    }
  }
  const onMouseUp = () => {
    activeDraggingNode = null
    window.removeEventListener('mousemove', onMouseMove)
    window.removeEventListener('mouseup', onMouseUp)
  }
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
}

function layoutGraph(nodes, edges) {
  if (!nodes || !nodes.length) return {}
  const pos = {}
  const count = nodes.length
  const existingPos = graphPos.value || {}

  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  let hasNewNodes = false
  nodes.forEach((n, i) => {
    if (existingPos[n.uuid] && typeof existingPos[n.uuid].x === 'number') {
      pos[n.uuid] = { x: existingPos[n.uuid].x, y: existingPos[n.uuid].y }
    } else {
      hasNewNodes = true
      const r = Math.sqrt(i + 1) * 55 + 90
      const theta = i * goldenAngle
      pos[n.uuid] = {
        x: GV_W / 2 + Math.cos(theta) * (r * 1.1),
        y: GV_H / 2 + Math.sin(theta) * (r * 0.8)
      }
    }
  })

  if (!hasNewNodes && Object.keys(existingPos).length === count) {
    return pos
  }

  const maxIters = count > 150 ? 8 : count > 60 ? 15 : 25
  for (let iter = 0; iter < maxIters; iter++) {
    const cooling = Math.max(0.05, 1 - (iter / maxIters))
    const step = count > 120 ? 2 : 1
    for (let i = 0; i < count; i += step) {
      for (let j = i + 1; j < count; j += step) {
        const uA = nodes[i].uuid
        const uB = nodes[j].uuid
        const a = pos[uA]
        const b = pos[uB]
        if (!a || !b) continue
        let dx = a.x - b.x
        let dy = a.y - b.y
        let d = Math.sqrt(dx * dx + dy * dy) || 1
        const minDist = 80
        if (d < minDist * 2) {
          const force = (Math.pow(minDist * 2 - d, 2) / 120) * cooling
          dx /= d
          dy /= d
          a.x += dx * force
          a.y += dy * force
          b.x -= dx * force
          b.y -= dy * force
        }
      }
    }

    edges.forEach(e => {
      const a = pos[e.source]
      const b = pos[e.target]
      if (a && b) {
        let dx = b.x - a.x
        let dy = b.y - a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const targetLen = 140
        const force = ((d - targetLen) / 15) * cooling
        dx /= d
        dy /= d
        a.x += dx * force
        a.y += dy * force
        b.x -= dx * force
        b.y -= dy * force
      }
    })
  }

  nodes.forEach(n => {
    const p = pos[n.uuid]
    if (p) {
      p.x = Math.max(80, Math.min(GV_W - 80, p.x))
      p.y = Math.max(60, Math.min(GV_H - 60, p.y))
    }
  })
  return pos
}

watch(
  () => props.graphInfo,
  (newInfo) => {
    if (newInfo && newInfo.nodes) {
      const edges = (newInfo.edges || []).map(e => ({
        source: e.source_node_uuid,
        target: e.target_node_uuid
      }))
      graphPos.value = layoutGraph(newInfo.nodes, edges)
    }
  },
  { immediate: true, deep: true }
)
</script>

<style scoped>
.graph-viz-wrap {
  border: 1px solid #E2E8F0;
  border-radius: 12px;
  background: #0f172a;
  position: relative;
  overflow: hidden;
  box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.15), 0 8px 10px -6px rgba(15, 23, 42, 0.1);
  display: flex;
  flex-direction: column;
}
.graph-viz-wrap.fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 9999;
  border-radius: 0;
}
.graph-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #1e293b;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  position: relative;
  z-index: 20;
  gap: 12px;
  flex-wrap: wrap;
}
.graph-search-box {
  display: flex;
  align-items: center;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 4px 8px;
  width: 240px;
  position: relative;
}
.graph-search-input {
  background: transparent;
  border: none;
  color: #f8fafc;
  font-size: 11.5px;
  outline: none;
  width: 100%;
  padding-left: 4px;
}
.graph-search-input::placeholder {
  color: #64748b;
}
.search-icon {
  font-size: 12px;
  color: #94a3b8;
}
.graph-search-clear {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  font-size: 11px;
}
.graph-search-dropdown {
  position: absolute;
  top: 48px;
  left: 16px;
  width: 260px;
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
  z-index: 50;
  overflow: hidden;
}
.search-result-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 11.5px;
}
.search-result-item:hover, .search-result-item.active {
  background: rgba(161, 197, 10, 0.15);
}
.sn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.sn-name {
  color: #f8fafc;
  font-weight: 600;
}
.sn-type {
  color: #94a3b8;
  font-size: 10.5px;
}
.graph-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.graph-zoom-label {
  color: #94a3b8;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  min-width: 38px;
  text-align: right;
  margin-right: 4px;
}
.graph-ctrl-btn {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.graph-ctrl-btn:hover {
  background: #a1c50a;
  color: #0f172a;
  border-color: #a1c50a;
}
.graph-canvas-viewport {
  position: relative;
  width: 100%;
  height: 480px;
  overflow: hidden;
  cursor: grab;
  user-select: none;
}
.graph-viz-wrap.fullscreen .graph-canvas-viewport {
  height: calc(100vh - 54px);
}
.graph-canvas-viewport.dragging {
  cursor: grabbing;
}
.graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}
.graph-edge {
  stroke: rgba(148, 163, 184, 0.35);
  stroke-width: 1.4;
  transition: all 0.25s ease;
}
.graph-edge.highlight {
  stroke: #a1c50a;
  stroke-width: 2.5;
  stroke-dasharray: 6 3;
  animation: edge-flow 1s linear infinite;
  filter: drop-shadow(0 0 6px rgba(161, 197, 10, 0.7));
}
.graph-edge.dimmed {
  stroke: rgba(148, 163, 184, 0.08);
  stroke-width: 0.8;
}
@keyframes edge-flow {
  from { stroke-dashoffset: 9; }
  to { stroke-dashoffset: 0; }
}
.edge-label-badge {
  cursor: pointer;
  transition: all 0.2s ease;
}
.edge-label-bg {
  fill: rgba(15, 23, 42, 0.88);
  stroke: rgba(148, 163, 184, 0.28);
  stroke-width: 1px;
  backdrop-filter: blur(4px);
  transition: all 0.2s ease;
}
.edge-label-bg.active {
  fill: rgba(15, 23, 42, 0.96);
  stroke: #a1c50a;
  stroke-width: 1.5px;
  filter: drop-shadow(0 0 6px rgba(161, 197, 10, 0.4));
}
.graph-edge-label {
  font-size: 9.5px;
  fill: #94a3b8;
  font-weight: 600;
  pointer-events: none;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  letter-spacing: 0.2px;
}
.graph-edge-label.active {
  fill: #e2f47c;
  font-weight: 700;
  font-size: 10.5px;
}
.graph-legend-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.legend-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #94a3b8;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.2s;
}
.legend-tag.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f8fafc;
  border-color: rgba(255, 255, 255, 0.25);
}
.legend-ring {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.setting-ring {
  background: #f59e0b;
  box-shadow: 0 0 6px #f59e0b;
}
.dynamic-ring {
  background: #06b6d4;
  border: 1px dashed #fff;
}
.setting-node-outer {
  fill: none;
  stroke: #f59e0b;
  stroke-width: 1.6;
  stroke-dasharray: 2 2;
  animation: rotate-ring 12s linear infinite;
  transform-origin: center;
}
.dynamic-node-outer {
  fill: none;
  stroke: #06b6d4;
  stroke-width: 1.2;
  opacity: 0.7;
}
@keyframes rotate-ring {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.setting-badge-icon {
  fill: #f59e0b;
  font-size: 10px;
  font-weight: bold;
  pointer-events: none;
}
.node-group {
  cursor: pointer;
  transition: transform 0.1s ease-out;
}
.node-group.selected .graph-node {
  stroke: #fff;
  stroke-width: 3.5;
  filter: drop-shadow(0 0 10px rgba(161, 197, 10, 0.9));
}
.node-group.connected:not(.selected) .graph-node {
  stroke: #a1c50a;
  stroke-width: 2.5;
}
.graph-node-label {
  font-size: 11px;
  font-weight: 700;
  fill: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  pointer-events: none;
  paint-order: stroke;
  stroke: #0f172a;
  stroke-width: 3px;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.graph-node-sublabel {
  font-size: 9.5px;
  fill: #a1c50a;
  font-weight: 600;
  pointer-events: none;
  paint-order: stroke;
  stroke: #0f172a;
  stroke-width: 2.5px;
}
.graph-node-info-panel {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 320px;
  max-height: calc(100% - 32px);
  background: rgba(30, 41, 59, 0.95);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  padding: 14px;
  color: #f8fafc;
  box-shadow: 0 14px 35px rgba(0, 0, 0, 0.45);
  z-index: 25;
  overflow-y: auto;
  animation: fadeInRight 0.2s ease;
}
@keyframes fadeInRight {
  from { opacity: 0; transform: translateX(12px); }
  to { opacity: 1; transform: translateX(0); }
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.panel-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #fff;
}
.panel-type-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(161, 197, 10, 0.2);
  color: #a1c50a;
  font-weight: 600;
}
.panel-source-badge {
  font-size: 9.5px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.badge-setting {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}
.badge-dynamic {
  background: rgba(6, 182, 212, 0.2);
  color: #06b6d4;
}
.panel-close-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
}
.panel-close-btn:hover {
  color: #fff;
}
.panel-summary {
  font-size: 12px;
  line-height: 1.6;
  color: #cbd5e1;
  margin-bottom: 10px;
  background: rgba(15, 23, 42, 0.6);
  padding: 8px;
  border-radius: 6px;
}
.panel-relations {
  margin-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 8px;
}
.relations-title {
  font-size: 11.5px;
  font-weight: 700;
  color: #a1c50a;
  margin-bottom: 6px;
}
.empty-relations {
  font-size: 11px;
  color: #64748b;
  font-style: italic;
}
.relations-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.relation-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.04);
  border-left: 2px solid rgba(56, 189, 248, 0.5);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.relation-item:hover {
  background: rgba(161, 197, 10, 0.15);
  border-left-color: #a1c50a;
  transform: translateX(2px);
}
.rel-item-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.rel-full-text {
  font-size: 10px;
  color: #94a3b8;
  line-height: 1.4;
  background: rgba(15, 23, 42, 0.4);
  padding: 4px 6px;
  border-radius: 3px;
  margin-top: 2px;
}
.rel-predicate {
  color: #38bdf8;
  font-weight: 600;
}
.rel-target-name {
  color: #f1f5f9;
  font-weight: 600;
}
.rel-target-type {
  color: #94a3b8;
  font-size: 10px;
}
.panel-attrs {
  margin-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.panel-attr-row {
  display: flex;
  gap: 6px;
  font-size: 11px;
}
.panel-attr-row .attr-k {
  color: #94a3b8;
  min-width: 60px;
}
.panel-attr-row .attr-v {
  color: #e2e8f0;
  word-break: break-all;
}
.panel-chat-action {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed rgba(255, 255, 255, 0.15);
}
.panel-chat-btn {
  width: 100%;
  background: linear-gradient(135deg, #a1c50a, #84a205);
  color: #0f172a;
  border: none;
  font-weight: 700;
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.panel-chat-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(161, 197, 10, 0.35);
}
.non-char-tip {
  font-size: 11px;
  color: #94a3b8;
  text-align: center;
  padding: 4px;
}
</style>
