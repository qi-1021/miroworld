<template>
  <div v-if="visible" class="causal-drawer-backdrop" @click.self="$emit('close')">
    <div class="causal-drawer">
      <div class="drawer-header">
        <div class="header-title">
          <span class="step-tag">Step {{ event?.step }}</span>
          <h4>🔗 双向因果追溯链</h4>
        </div>
        <button class="close-btn" @click="$emit('close')">×</button>
      </div>

      <div v-if="event" class="drawer-body">
        <!-- 核心聚焦事件 -->
        <div class="current-event-card">
          <div class="card-who">{{ event.character_name || event.agent_name }}</div>
          <div class="card-action">{{ event.action_desc || event.action }}</div>
          <div v-if="event.result" class="card-result">🎯 产生后果：{{ event.result }}</div>
          <div class="card-loc">📍 发生地点：{{ event.location }}</div>
        </div>

        <!-- 1. 前置因果溯源（前因：谁促成了此事件） -->
        <div class="chain-section">
          <div class="section-title">⬅️ 前置起因与诱发事件 (Causes / Antecedents)</div>
          <div v-if="causes.length" class="event-mini-list">
            <div
              v-for="c in causes"
              :key="c.id"
              class="event-mini-card cause"
              @click="$emit('select-event', c)"
            >
              <div class="mini-head">
                <span class="mini-step">Step {{ c.step }}</span>
                <span class="mini-who">{{ c.character_name || c.agent_name }}</span>
              </div>
              <div class="mini-desc">{{ c.action_desc || c.action }}</div>
            </div>
          </div>
          <div v-else class="empty-chain">
            （此事件为原初起点或由外界上帝干预直接触发，无内部前置因果）
          </div>
        </div>

        <!-- 2. 后续影响与引申结果（后果：此事件引出了哪些反应） -->
        <div class="chain-section">
          <div class="section-title">➡️ 后续引申反应与连锁后果 (Consequences / Effects)</div>
          <div v-if="effects.length" class="event-mini-list">
            <div
              v-for="e in effects"
              :key="e.id"
              class="event-mini-card effect"
              @click="$emit('select-event', e)"
            >
              <div class="mini-head">
                <span class="mini-step">Step {{ e.step }}</span>
                <span class="mini-who">{{ e.character_name || e.agent_name }}</span>
              </div>
              <div class="mini-desc">{{ e.action_desc || e.action }}</div>
            </div>
          </div>
          <div v-else class="empty-chain">
            （暂无后续连锁事件，或此事件为当前世界线最新进展）
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  visible: Boolean,
  event: {
    type: Object,
    default: null
  },
  allEvents: {
    type: Array,
    default: () => []
  }
})

defineEmits(['close', 'select-event'])

// 计算前置因果（links 包含的事件）
const causes = computed(() => {
  if (!props.event || !props.event.links || !props.event.links.length) return []
  return props.allEvents.filter(e => props.event.links.includes(e.id))
})

// 计算后续引申（哪些事件的 links 包含了当前事件）
const effects = computed(() => {
  if (!props.event) return []
  return props.allEvents.filter(e => e.links && e.links.includes(props.event.id))
})
</script>

<style scoped>
.causal-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: flex-end;
  z-index: 9999;
}
.causal-drawer {
  width: 480px;
  max-width: 90vw;
  height: 100%;
  background: #191920;
  border-left: 1px solid #333;
  color: #eee;
  display: flex;
  flex-direction: column;
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.8);
}
.drawer-header {
  padding: 16px;
  border-bottom: 1px solid #292934;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-title h4 {
  margin: 0;
  font-size: 15px;
  color: #fff;
}
.step-tag {
  background: #ffaa00;
  color: #111;
  font-size: 11px;
  font-weight: bold;
  padding: 2px 6px;
  border-radius: 4px;
}
.close-btn {
  background: transparent;
  border: none;
  color: #888;
  font-size: 20px;
  cursor: pointer;
}
.drawer-body {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}
.current-event-card {
  background: #232330;
  border: 1px solid #ffaa00;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 20px;
}
.card-who {
  font-weight: bold;
  color: #ffaa00;
  font-size: 14px;
  margin-bottom: 6px;
}
.card-action {
  font-size: 13px;
  line-height: 1.5;
  color: #eee;
  margin-bottom: 8px;
}
.card-result {
  font-size: 12px;
  color: #2ecc71;
  margin-bottom: 4px;
}
.card-loc {
  font-size: 11px;
  color: #888;
}
.chain-section {
  margin-bottom: 20px;
}
.section-title {
  font-size: 13px;
  font-weight: bold;
  color: #aaa;
  margin-bottom: 10px;
}
.event-mini-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.event-mini-card {
  background: #20202a;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s;
}
.event-mini-card:hover {
  background: #2b2b3a;
  border-color: #3498db;
}
.event-mini-card.cause {
  border-left: 3px solid #e67e22;
}
.event-mini-card.effect {
  border-left: 3px solid #3498db;
}
.mini-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 11px;
}
.mini-step {
  color: #ffaa00;
  font-weight: bold;
}
.mini-who {
  color: #ccc;
}
.mini-desc {
  font-size: 12px;
  color: #bbb;
  line-height: 1.4;
}
.empty-chain {
  color: #666;
  font-size: 12px;
  font-style: italic;
  padding: 8px 0;
}
</style>
