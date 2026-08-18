<template>
  <div v-if="event" class="assistant-modal-mask" @click.self="$emit('close')">
    <div class="assistant-modal event-detail-modal">
      <div class="assistant-head">
        <span class="assistant-title">{{ $t('world.eventDetailTitle') }}</span>
        <button class="assistant-close" @click="$emit('close')">×</button>
      </div>
      <div class="event-detail-body">
        <div class="event-detail-row"><span class="ed-label">{{ $t('world.simStepLabel', { step: event.step }) }}</span><span>{{ event.time }}</span></div>
        <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventWho') }}</span><span>{{ event.character_name }}</span></div>
        <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventWhere') }}</span><span>{{ event.location }}</span></div>
        <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventAction') }}</span><span>{{ event.action_desc }}</span></div>
        <div class="event-detail-row"><span class="ed-label">{{ $t('world.eventResult') }}</span><span>{{ event.result }}</span></div>
        <div v-if="event.links && event.links.length" class="event-detail-row">
          <span class="ed-label">{{ $t('world.eventLinks') }}</span><span>{{ event.links.join(', ') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  event: { type: Object, default: null }
})

defineEmits(['close'])
</script>

<style scoped>
.event-detail-modal {
  width: 560px;
  max-width: 94vw;
}
.event-detail-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.event-detail-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.ed-label {
  flex-shrink: 0;
  min-width: 60px;
  font-weight: 700;
  color: #666;
}
</style>
