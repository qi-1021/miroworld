<template>
  <div v-if="visible" class="assistant-modal-mask" @click.self="$emit('close')">
    <div class="assistant-modal compare-modal">
      <div class="assistant-head">
        <span class="assistant-title">{{ $t('world.compareWorldlines') }}</span>
        <button class="mini-btn ghost" @click="$emit('export-report')">{{ $t('world.exportCompare') }}</button>
        <button class="assistant-close" @click="$emit('close')">×</button>
      </div>
      <div class="compare-grid">
        <div v-for="(item, idx) in compareData" :key="idx" class="compare-col">
          <div class="compare-col-head">
            <span>{{ formatTime(item.created_at) }}</span>
            <span class="badge" :class="item.status">{{ statusLabel(item.status) }}</span>
            <span>{{ $t('world.eventCount', { count: item.event_count }) }}</span>
          </div>
          <div v-if="item.events && item.events.length" class="compare-events">
            <div v-for="(g, gi) in groupEventsByStep(item.events)" :key="gi" class="compare-step">
              <div class="compare-step-head">{{ $t('world.simStepLabel', { step: g.step }) }} · {{ g.time }}</div>
              <div v-for="(e, ei) in g.events" :key="ei" class="sim-event">
                <span class="sim-event-who">{{ e.character_name }}</span>
                <span class="sim-event-where">{{ e.location }}</span>
                <span class="sim-event-what">{{ e.action_desc }}</span>
                <span class="sim-event-result">{{ e.result }}</span>
              </div>
            </div>
          </div>
          <div v-else class="empty-note">{{ $t('world.noEvents') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  compareData: { type: Array, default: () => [] }
})

defineEmits(['close', 'export-report'])

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function statusLabel(s) {
  const map = {
    completed: '已完成',
    running: '推演中',
    failed: '失败',
    preparing: '准备中',
    paused: '已暂停'
  }
  return map[s] || s
}

function groupEventsByStep(events) {
  if (!events || !events.length) return []
  const map = new Map()
  events.forEach(e => {
    const step = e.step || 1
    if (!map.has(step)) {
      map.set(step, { step, time: e.time || `第${step}轮`, events: [] })
    }
    map.get(step).events.push(e)
  })
  return Array.from(map.values())
}
</script>

<style scoped>
.compare-modal {
  width: 900px;
  max-width: 95vw;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 14px;
}
@media (max-width: 768px) {
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
.compare-col {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  overflow: hidden;
}
.compare-col-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #f1f5f9;
  font-size: 12px;
  font-weight: 700;
  border-bottom: 1px solid #e2e8f0;
}
.compare-events {
  max-height: 500px;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.compare-step-head {
  font-size: 11px;
  font-weight: 700;
  color: #a1c50a;
  margin-bottom: 4px;
}
.empty-note {
  padding: 30px;
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
}
</style>
