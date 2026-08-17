<template>
  <div v-if="visible" class="director-modal-backdrop" @click.self="$emit('close')">
    <div class="director-modal">
      <div class="modal-header">
        <h3>🎬 导演时间线规划 (Director Timeline)</h3>
        <button class="close-btn" @click="$emit('close')">×</button>
      </div>

      <div class="modal-body">
        <p class="modal-desc">
          预设在推演特定轮次（Step）自动注入的世界突发变数或动机重塑，无需实时紧盯即可实现精准剧情编排。
        </p>

        <!-- 已配置计划列表 -->
        <div v-if="schedules.length" class="schedule-list">
          <div v-for="(item, idx) in schedules" :key="idx" class="schedule-item">
            <span class="step-badge">第 {{ item.step }} 步</span>
            <span class="target-badge" :class="item.mode">{{ item.mode === 'world' ? '全域' : item.target }}</span>
            <span class="desc-text">{{ item.text }}</span>
            <button class="del-btn" @click="removeSchedule(idx)">🗑</button>
          </div>
        </div>
        <div v-else class="empty-tip">
          暂无预设计划，在下方添加在第 N 步自动触发的剧情事件
        </div>

        <!-- 添加新预设计划 -->
        <div class="add-schedule-box">
          <div class="input-row">
            <label>触发步数 (Step):</label>
            <input v-model.number="newStep" type="number" min="1" max="100" class="step-input" />
            
            <label>范围:</label>
            <select v-model="newMode" class="mode-select">
              <option value="world">全域世界变数</option>
              <option value="character">指定角色动机</option>
            </select>

            <select v-if="newMode === 'character'" v-model="newTarget" class="target-select">
              <option v-for="c in characters" :key="c" :value="c">{{ c }}</option>
            </select>
          </div>

          <textarea
            v-model="newText"
            class="event-textarea"
            placeholder="描述此轮自动施加的突发变数或动机指令（如：第 3 轮外围侦察小队遭遇不明精锐拦截...）"
            rows="2"
          ></textarea>

          <button class="add-btn" :disabled="!newText.trim() || newStep < 1" @click="addSchedule">
            + 添加预设指令
          </button>
        </div>
      </div>

      <div class="modal-footer">
        <button class="action-btn secondary" @click="$emit('close')">完成</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  visible: Boolean,
  characters: {
    type: Array,
    default: () => []
  },
  modelValue: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue', 'close'])

const schedules = ref([...props.modelValue])
const newStep = ref(3)
const newMode = ref('world')
const newTarget = ref(props.characters[0] || '')
const newText = ref('')

const addSchedule = () => {
  if (!newText.value.trim()) return
  schedules.value.push({
    step: newStep.value,
    mode: newMode.value,
    target: newMode.value === 'character' ? newTarget.value : null,
    text: newText.value.trim(),
    triggered: false
  })
  schedules.value.sort((a, b) => a.step - b.step)
  newText.value = ''
  newStep.value = (schedules.value[schedules.value.length - 1]?.step || 3) + 2
  emit('update:modelValue', schedules.value)
}

const removeSchedule = (index) => {
  schedules.value.splice(index, 1)
  emit('update:modelValue', schedules.value)
}
</script>

<style scoped>
.director-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}
.director-modal {
  background: #18181f;
  border: 1px solid #333;
  border-radius: 8px;
  width: 650px;
  max-width: 90vw;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.8);
  color: #eee;
}
.modal-header {
  padding: 16px;
  border-bottom: 1px solid #282830;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: #ffaa00;
}
.close-btn {
  background: transparent;
  border: none;
  color: #888;
  font-size: 20px;
  cursor: pointer;
}
.modal-body {
  padding: 16px;
  max-height: 70vh;
  overflow-y: auto;
}
.modal-desc {
  font-size: 12px;
  color: #999;
  margin-top: 0;
  margin-bottom: 16px;
}
.schedule-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.schedule-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #22222b;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
}
.step-badge {
  background: #ffaa00;
  color: #111;
  font-weight: bold;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.target-badge {
  background: #334;
  color: #8af;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
.target-badge.world {
  background: #443;
  color: #fa8;
}
.desc-text {
  flex: 1;
  color: #ddd;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.del-btn {
  background: transparent;
  border: none;
  color: #e74c3c;
  cursor: pointer;
}
.empty-tip {
  text-align: center;
  color: #666;
  font-size: 12px;
  padding: 16px;
  border: 1px dashed #333;
  border-radius: 6px;
  margin-bottom: 16px;
}
.add-schedule-box {
  background: #202028;
  border: 1px solid #3a3a46;
  border-radius: 6px;
  padding: 12px;
}
.input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
}
.step-input {
  width: 60px;
  background: #111;
  border: 1px solid #444;
  color: #fff;
  padding: 4px;
  border-radius: 4px;
}
.mode-select, .target-select {
  background: #111;
  border: 1px solid #444;
  color: #fff;
  padding: 4px;
  border-radius: 4px;
}
.event-textarea {
  width: 100%;
  background: #111;
  border: 1px solid #444;
  color: #fff;
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  box-sizing: border-box;
  margin-bottom: 10px;
}
.add-btn {
  background: #2980b9;
  color: #fff;
  border: none;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.modal-footer {
  padding: 12px 16px;
  border-top: 1px solid #282830;
  display: flex;
  justify-content: flex-end;
}
.action-btn.secondary {
  background: #333;
  color: #fff;
  border: 1px solid #555;
  padding: 6px 16px;
  border-radius: 4px;
  cursor: pointer;
}
</style>
