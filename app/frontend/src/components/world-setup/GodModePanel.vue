<template>
  <div class="god-mode-panel">
    <div class="god-panel-title">
      <span>👑 创作者上帝干预 (Author Interventions)</span>
      <span class="god-panel-sub">在此施加突发变数，将立即强制改写下一轮各角色的决策环境与世界格局</span>
    </div>

    <div class="god-input-row">
      <div class="god-target-select">
        <label class="god-label">干预范围：</label>
        <select v-model="targetMode" class="sim-input">
          <option value="world">全域世界天灾 / 突发异变</option>
          <option value="character">特定角色心境与动机篡改</option>
        </select>
      </div>
      <div v-if="targetMode === 'character'" class="god-target-select">
        <label class="god-label">目标角色：</label>
        <select v-model="targetCharacter" class="sim-input">
          <option v-for="c in characters" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
    </div>

    <!-- 突发变数描述 -->
    <div class="god-text-wrap">
      <textarea
        v-model="interventionText"
        class="god-textarea"
        :placeholder="targetMode === 'world' ? '描述全域突发变数（如：突发9级特大天灾源石风暴，所有对外通讯与雷达瞬间瘫痪，基地外部气温骤降至零下40度...）' : '描述强加给角色的突发动机或心境突变（如：突然收到一份绝密加密信件，发现自己信任多年的长官竟是宿敌派来的内线，内心信念瞬间崩塌并产生剧烈动摇...）'"
        rows="3"
      ></textarea>
    </div>

    <!-- 预设快捷模板 -->
    <div class="god-presets">
      <span class="preset-label">快捷预设：</span>
      <button
        v-for="(p, pi) in presets"
        :key="pi"
        type="button"
        class="preset-btn"
        @click="applyPreset(p)"
      >
        {{ p.title }}
      </button>
    </div>

    <div class="god-actions">
      <button
        type="button"
        class="action-btn god-submit-btn"
        :disabled="!interventionText.trim() || submitting"
        @click="submitIntervention"
      >
        <span v-if="submitting" class="spinner-sm"></span>
        ⚡ 广播突发变数并重塑推演
      </button>
      <span v-if="successMsg" class="god-success-tip">✓ {{ successMsg }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  characters: {
    type: Array,
    default: () => []
  },
  submitting: {
    type: Boolean,
    default: false
  },
  successMsg: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['submit'])

const targetMode = ref('world')
const targetCharacter = ref(props.characters[0] || '')
const interventionText = ref('')

watch(() => props.characters, (newVal) => {
  if (newVal && newVal.length && !targetCharacter.value) {
    targetCharacter.value = newVal[0]
  }
}, { immediate: true })

const presets = [
  { title: '🌪️ 极寒源石天灾', mode: 'world', text: '突发罕见的9级源石冰雹风暴，室外能见度降为零，所有无线电通讯全面瘫痪。' },
  { title: '🚨 警报：敌袭逼近', mode: 'world', text: '前哨阵地遭遇精锐未知武装部队围攻，防线已被撕开一道缺口，请求紧急回防！' },
  { title: '💌 绝密身份暴露', mode: 'character', text: '意外发现自己守护多年的机密文件被掉包，怀疑身边的核心同伴存在背叛者。' },
  { title: '💊 严重感染急发', mode: 'character', text: '矿石病体征突发剧烈恶化，神经系统受到强压迫，陷入严重的焦虑与生理痛苦。' }
]

const applyPreset = (p) => {
  targetMode.value = p.mode
  interventionText.value = p.text
}

const submitIntervention = () => {
  emit('submit', {
    mode: targetMode.value,
    target: targetMode.value === 'character' ? targetCharacter.value : null,
    text: interventionText.value.trim()
  })
}
</script>

<style scoped>
.god-mode-panel {
  background: #1e1e24;
  border: 1px solid #ffaa00;
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
  color: #fff;
}
.god-panel-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: bold;
}
.god-panel-sub {
  font-size: 11px;
  color: #bbb;
}
.god-input-row {
  display: flex;
  gap: 16px;
  margin-bottom: 10px;
}
.god-label {
  font-size: 12px;
  color: #ffaa00;
  margin-right: 6px;
}
.god-textarea {
  width: 100%;
  background: #111;
  color: #fff;
  border: 1px solid #444;
  border-radius: 4px;
  padding: 8px;
  font-size: 13px;
  resize: vertical;
  box-sizing: border-box;
}
.god-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 10px 0;
}
.preset-label {
  font-size: 11px;
  color: #aaa;
}
.preset-btn {
  background: #2b2b36;
  border: 1px solid #555;
  color: #ddd;
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}
.preset-btn:hover {
  background: #3c3c4d;
  color: #ffaa00;
  border-color: #ffaa00;
}
.god-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.god-submit-btn {
  background: linear-gradient(135deg, #ffaa00, #e67e22);
  color: #111;
  font-weight: bold;
  border: none;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
}
.god-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.god-success-tip {
  color: #2ecc71;
  font-size: 12px;
}
</style>
