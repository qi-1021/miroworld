<template>
  <div class="step-card step-sim">
    <div class="card-header">
      <div class="step-info">
        <span class="step-num">3</span>
        <span class="step-title">{{ $t('world.simTitle') }}</span>
      </div>
      <div class="step-status">
        <span v-if="simStatus === 'running'" class="badge processing">{{ $t('world.simStatusRunning') }}</span>
        <span v-else-if="simStatus === 'completed'" class="badge success">{{ $t('world.simStatusCompleted') }}</span>
        <span v-else-if="simStatus === 'failed'" class="badge processing">{{ $t('world.simStatusFailed') }}</span>
        <span v-else class="badge hint">{{ $t('world.simStatusHint') }}</span>
      </div>
    </div>

    <p class="description">
      {{ $t('world.simDesc') }}
    </p>

    <!-- 推演进度 -->
    <div v-if="(simStatus === 'running' || simStatus === 'preparing' || simStatus === 'paused') && simProgress.total_steps" class="sim-progress">
      <div class="sim-progress-bar">
        <div class="sim-progress-fill" :style="{ width: Math.min(100, ((simProgress.current_step || 0) / simProgress.total_steps) * 100) + '%' }"></div>
      </div>
      <span class="sim-progress-text">{{ simProgress.message || $t('world.simProgress', { current: simProgress.current_step || 0, total: simProgress.total_steps }) }}</span>
    </div>

    <div class="sim-controls">
      <div class="sim-field sim-field-wide">
        <label class="sim-label">{{ $t('world.simGoalLabel') }}</label>
        <textarea
          :value="simGoal"
          class="sim-goal-input"
          rows="2"
          :placeholder="$t('world.simGoalPlaceholder')"
          @input="$emit('update:simGoal', $event.target.value)"
        ></textarea>
      </div>
      <div class="sim-field">
        <label class="sim-label">{{ $t('world.simStepsLabel') }}</label>
        <input
          :value="simSteps"
          type="number"
          min="1"
          max="30"
          class="sim-input"
          @input="$emit('update:simSteps', Number($event.target.value))"
        />
      </div>
      <div class="sim-field">
        <label class="sim-label">{{ $t('world.simTimeModeLabel') }}</label>
        <select
          :value="simTimeMode"
          class="sim-input"
          @change="$emit('update:simTimeMode', $event.target.value)"
        >
          <option value="minutes">{{ $t('world.simTimeModeMinutes') }}</option>
          <option value="narrative">{{ $t('world.simTimeModeNarrative') }}</option>
        </select>
      </div>
      <div v-if="simTimeMode === 'minutes'" class="sim-field">
        <label class="sim-label">{{ $t('world.simStepMinLabel') }}</label>
        <input
          :value="simStepMin"
          type="number"
          min="1"
          max="1440"
          class="sim-input"
          @input="$emit('update:simStepMin', Number($event.target.value))"
        />
      </div>
      <div v-else class="sim-field sim-field-wide">
        <label class="sim-label">{{ $t('world.simTimeJumpsLabel') }}</label>
        <input
          :value="simTimeJumps"
          class="sim-input"
          :placeholder="$t('world.simTimeJumpsPlaceholder')"
          @input="$emit('update:simTimeJumps', $event.target.value)"
        />
      </div>
      <div class="sim-field sim-field-wide">
        <label class="sim-label">
          <input
            :checked="simUseTimeline"
            type="checkbox"
            class="sim-check"
            @change="$emit('update:simUseTimeline', $event.target.checked)"
          />
          {{ $t('world.simUseTimeline') }}
        </label>
      </div>
      <div class="sim-field sim-field-wide">
        <label class="sim-label">
          <input
            :checked="simStorySummaryLlm"
            type="checkbox"
            class="sim-check"
            @change="$emit('update:simStorySummaryLlm', $event.target.checked)"
          />
          {{ $t('world.simStorySummaryLlm') }}
        </label>
      </div>
      <div class="sim-field">
        <label class="sim-label">{{ $t('world.simMaxConcurrencyLabel') }}</label>
        <input
          :value="simMaxConcurrency"
          type="number"
          min="1"
          max="8"
          class="sim-input"
          @input="$emit('update:simMaxConcurrency', Number($event.target.value))"
        />
      </div>
      <div class="sim-field sim-field-wide">
        <label class="sim-label">{{ $t('world.simStartEventLabel') }}</label>
        <select
          :value="simStartEventId"
          class="sim-input"
          @change="$emit('update:simStartEventId', $event.target.value)"
        >
          <option value="">{{ $t('world.simStartEventNone') }}</option>
          <option v-for="ev in simTimelineEvents" :key="ev.event_id" :value="ev.event_id">
            {{ ev.summary.length > 40 ? ev.summary.slice(0, 40) + '…' : ev.summary }}
          </option>
        </select>
      </div>
      <div class="sim-field sim-field-wide">
        <label class="sim-label">🤖 {{ $t('world.agentModelLabel') }}</label>
        <select
          :value="selectedAgentModel"
          class="sim-input"
          @change="$emit('update:selectedAgentModel', $event.target.value)"
        >
          <option value="">{{ $t('world.useDefaultModel') }}</option>
          <option v-for="m in availableModels" :key="m.model_id || m.id" :value="m.model_id">
            {{ m.display_name || m.model_id }} ({{ m.provider_type }})
          </option>
        </select>
      </div>
      <button class="action-btn sim-start" :disabled="simStarting || simStatus === 'running'" @click="$emit('start-sim')">
        <span v-if="simStarting" class="spinner-sm"></span>
        {{ simStarting ? $t('world.simStarting') : simStatus === 'running' ? $t('world.simRunning') : $t('world.simStartBtn') }}
      </button>
      <button
        v-if="simStatus === 'running' || simStarting"
        type="button"
        class="action-btn btn-danger-ghost"
        title="随时终止推演任务（已生成的轮次事件和世界线均会完整保留）"
        @click="$emit('control', 'stop')"
      >
        ⏹ 终止推演 (保留当前进展)
      </button>
    </div>

    <div v-if="simMsg" class="msg-line" :class="{ error: simMsgError }">{{ simMsg }}</div>

    <!-- 事件流（按 step 分组，更清晰） -->
    <div v-if="simEvents.length" class="sim-events">
      <div class="sim-events-title">{{ $t('world.eventStream') }}</div>
      <div v-if="simQualityIssues.length" class="sim-quality">
        <div v-for="(issue, i) in simQualityIssues" :key="i" class="sim-quality-item">⚠ {{ issue }}</div>
      </div>
      <div class="sim-playback">
        <button class="mini-btn" @click="$emit('playback-prev')">⏮</button>
        <button class="mini-btn" @click="$emit('playback-toggle')">{{ playbackPlaying ? '⏸' : '▶' }}</button>
        <button class="mini-btn" @click="$emit('playback-next')">⏭</button>
        <button class="mini-btn" :disabled="simStarting" @click="$emit('rollback-step')">↩ {{ $t('world.rollbackWorldline') }}</button>
        <span class="sim-playback-info">
          {{ $t('world.simStepLabel', { step: groupedSimEvents[playbackIndex]?.step || 0 }) }} / {{ groupedSimEvents.length }}
        </span>
      </div>
      <div v-if="stepSummaries.length" class="sim-summary">
        <div v-for="s in stepSummaries" :key="s.step" class="sim-summary-item">
          <span class="sim-summary-step">{{ $t('world.simStepLabel', { step: s.step }) }}</span>
          <span class="sim-summary-text">{{ s.text }}</span>
        </div>
      </div>
      <div v-for="(group, gi) in visibleSimGroups" :key="gi" class="sim-step-group" :class="{ active: gi === playbackIndex }">
        <div class="sim-step-head">
          {{ $t('world.simStepLabel', { step: group.step }) }} · {{ group.time }}
        </div>
        <div v-for="(e, ei) in group.events" :key="ei" class="sim-event clickable" @click="$emit('open-event-detail', e)">
          <span class="sim-event-who">{{ e.character_name }}</span>
          <span class="sim-event-where">{{ e.location }}</span>
          <span class="sim-event-what">{{ e.action_desc }}</span>
          <span class="sim-event-result">{{ e.result }}</span>
          <button
            type="button"
            class="mini-btn causal-btn"
            title="查看该事件的前因后果连锁链"
            @click.stop="$emit('open-causal-chain', e)"
          >
            🔗 因果链
          </button>
        </div>
      </div>
      <button v-if="simGroupLimit < groupedSimEvents.length" class="mini-btn sim-load-more" @click="$emit('load-more-groups')">
        {{ $t('world.loadMoreEvents') }}
      </button>
    </div>

    <!-- 事件因果图 -->
    <div v-if="eventGraphData.nodes && eventGraphData.nodes.length" class="sim-graph">
      <div class="sim-graph-title">
        <span>{{ $t('world.eventGraphTitle') }}</span>
        <select :value="graphFilterChar" class="sim-graph-filter" @change="$emit('update:graphFilterChar', $event.target.value)">
          <option value="">{{ $t('world.allCharacters') }}</option>
          <option v-for="c in graphCharacters" :key="c" :value="c">{{ c }}</option>
        </select>
        <button class="mini-btn ghost" @click="$emit('zoom-graph', -0.2)">−</button>
        <span class="sim-graph-zoom">{{ Math.round(simGraphZoom * 100) }}%</span>
        <button class="mini-btn ghost" @click="$emit('zoom-graph', 0.2)">+</button>
        <button class="mini-btn ghost" @click="$emit('export-graph')">{{ $t('world.exportGraph') }}</button>
      </div>
      <div class="sim-graph-zoom-wrap" :style="{ transform: 'scale(' + simGraphZoom + ')', transformOrigin: 'top left' }">
        <svg :viewBox="`0 0 ${eventGraphData.width} ${eventGraphData.height}`" class="sim-graph-svg">
          <line
            v-for="(ed, i) in eventGraphData.edges"
            :key="'e' + i"
            :x1="graphPosMap[ed.source]?.x"
            :y1="graphPosMap[ed.source]?.y"
            :x2="graphPosMap[ed.target]?.x"
            :y2="graphPosMap[ed.target]?.y"
            class="sim-graph-edge"
          />
          <g
            v-for="(n, i) in eventGraphData.nodes"
            :key="'n' + i"
            :transform="`translate(${n.x},${n.y})`"
            @click="$emit('select-graph-event', n.id)"
          >
            <circle r="6" class="sim-graph-node" :class="{ active: selectedGraphEvent === n.id }" />
            <text y="-10" text-anchor="middle" class="sim-graph-label">{{ n.label }}</text>
          </g>
        </svg>
      </div>
      <div v-if="selectedGraphEvent" class="sim-graph-detail">
        <template v-for="(n, i) in eventGraphData.nodes" :key="i">
          <div v-if="n.id === selectedGraphEvent" class="sim-graph-detail-inner">
            <span class="sim-graph-detail-step">{{ $t('world.simStepLabel', { step: n.step }) }}</span>
            <span class="sim-graph-detail-who">{{ n.event.character_name }}</span>
            <span class="sim-graph-detail-text">{{ n.event.action_desc }} → {{ n.event.result }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- 运行中控制（IPC）与创作者上帝干预 -->
    <div v-if="simStatus === 'running' || simStatus === 'paused'" class="sim-ctl">
      <div class="sim-ctl-head">
        <div class="sim-ctl-title">🎮 {{ $t('world.runControl') }} & 上帝干预</div>
        <span class="sim-ctl-badge" :class="simStatus">{{ simStatus === 'paused' ? '⏸ 暂停中（适合注入变数）' : '⚡ 实时演算中' }}</span>
      </div>
      <div class="sim-ctl-btns">
        <button
          class="mini-btn"
          :disabled="simStatus === 'paused'"
          @click="$emit('control', 'pause')"
        >⏸ {{ $t('world.pause') || '暂停' }}</button>
        <button
          class="mini-btn"
          :disabled="simStatus !== 'paused'"
          @click="$emit('control', 'resume')"
        >▶ {{ $t('world.resume') || '继续' }}</button>
        <button class="mini-btn danger" @click="$emit('control', 'stop')">⏹ {{ $t('world.stop') || '停止' }}</button>
        <button
          type="button"
          class="mini-btn"
          style="background: #2c3e50; border-color: #34495e; color: #fff;"
          @click="$emit('open-director')"
        >
          🎬 导演时间线规划
        </button>
        <button
          type="button"
          class="mini-btn god-mode-btn"
          :class="{ active: showGodModePanel }"
          @click="$emit('toggle-god-mode')"
        >
          👑 注入世界变数 / 动机篡改
        </button>
      </div>

      <!-- 抽离出的独立上帝干预控制面板 -->
      <GodModePanel
        v-if="showGodModePanel"
        :characters="characters"
        :submitting="godInjecting"
        :success-msg="godMsg"
        @submit="$emit('god-submit', $event)"
      />

      <div v-if="simCtlMsg" class="msg-line" :class="{ error: simCtlMsgError }">{{ simCtlMsg }}</div>
    </div>

    <!-- 角色采访 -->
    <div v-if="characters.length" class="sim-interview">
      <div class="sim-interview-title">{{ $t('world.interviewTitle') }}</div>
      <p class="sim-interview-hint">{{ $t('world.interviewHint') }}</p>
      <div class="sim-char-list">
        <button
          v-for="c in characters"
          :key="c"
          class="mini-btn"
          :class="{ active: interviewCharacter === c }"
          @click="$emit('select-character', c)"
        >{{ c }}</button>
      </div>
      <div v-if="interviewCharacter" class="interview-box">
        <div class="interview-char">{{ $t('world.interviewWith') }}{{ interviewCharacter }}</div>
        <textarea
          :value="interviewPrompt"
          class="interview-input"
          rows="2"
          :placeholder="$t('world.interviewPlaceholder')"
          @input="$emit('update:interviewPrompt', $event.target.value)"
        ></textarea>
        <button
          class="mini-btn active"
          :disabled="interviewing || !interviewPrompt.trim()"
          @click="$emit('send-interview')"
        >
          <span v-if="interviewing" class="spinner-xs"></span>
          {{ interviewing ? $t('world.interviewing') : $t('world.sendInterview') }}
        </button>
        <div v-if="interviewAnswer" class="interview-answer">
          <div class="interview-answer-label">{{ $t('world.interviewAnswerLabel') }}</div>
          <div class="interview-answer-text">{{ interviewAnswer }}</div>
        </div>
        <div v-if="interviewMsgError" class="msg-line error">{{ interviewMsg }}</div>
      </div>
    </div>

    <!-- 世界小说续写 -->
    <div v-if="reportSimulationId" class="sim-report">
      <div class="sim-report-head">
        <div class="sim-report-title">
          <span>{{ $t('world.novelTitle') }}</span>
          <span v-if="reportSimulationLabel" class="sim-report-sub">{{ reportSimulationLabel }}</span>
        </div>
        <button
          class="mini-btn"
          :disabled="reportGenerating"
          @click="$emit('generate-report')"
        >
          <span v-if="reportGenerating" class="spinner-xs"></span>
          {{ reportGenerating ? $t('world.novelGenerating') : reportText ? $t('world.novelRegenerate') : $t('world.novelGenerate') }}
        </button>
        <button v-if="reportText" class="mini-btn ghost" @click="$emit('export-report-html')">{{ $t('world.exportReportHtml') }}</button>
      </div>
      <div v-if="reportText" class="report-body">
        <div v-for="(block, bi) in reportBlocks" :key="bi" class="report-block">
          <div v-if="block.type === 'h2'" class="report-h2">{{ block.text }}</div>
          <div v-else-if="block.type === 'li'" class="report-li">· {{ block.text }}</div>
          <div v-else class="report-p">{{ block.text }}</div>
        </div>
      </div>
      <div v-else-if="reportEmptyNote" class="empty-note">{{ reportEmptyNote }}</div>
    </div>

    <!-- 世界线之树 -->
    <div v-if="worldTree.length" class="world-tree">
      <div class="world-tree-title">
        🌳 {{ $t('world.worldTreeTitle') }}
        <button v-if="metaUndoStack.length" class="mini-btn ghost" @click="$emit('undo-meta')">{{ $t('world.undoMeta') }}</button>
      </div>
      <div v-for="root in worldTree" :key="root.simulation_id" class="tree-node root">
        <div class="tree-node-row">
          <button class="mini-btn ghost" @click="$emit('toggle-root', root.simulation_id)">{{ collapsedRoots.has(root.simulation_id) ? '▶' : '▼' }}</button>
          <span class="tree-node-name">{{ root.result?.meta?.name || formatTime(root.created_at) }}</span>
          <span class="badge" :class="root.status">{{ statusLabel(root.status) }}</span>
          <span class="tree-node-count">{{ $t('world.eventCount', { count: (root.result || {}).event_count || 0 }) }}</span>
          <button class="mini-btn ghost" @click="$emit('edit-meta', root)">✎</button>
          <button class="mini-btn ghost" @click="$emit('load-sim', root)">{{ $t('world.loadSimulation') }}</button>
          <button class="mini-btn" :disabled="simStarting" @click="$emit('continue-sim', root)">{{ $t('world.continueSimulation') }}</button>
          <button class="mini-btn ghost" @click="$emit('export-sim', root)">{{ $t('world.exportSimulation') }}</button>
          <button class="mini-btn ghost" @click="$emit('copy-sim', root)">{{ $t('world.copyWorldline') }}</button>
          <button v-if="root.status === 'completed' && !((root.result || {}).meta || {}).whatif_question" class="mini-btn" @click="$emit('start-whatif', root)">{{ $t('world.whatifBtn') }}</button>
          <button v-if="root.status === 'completed' && !((root.result || {}).meta || {}).whatif_question" class="mini-btn ghost" @click="$emit('batch-whatif', root)">{{ $t('world.batchWhatif') }}</button>
          <button class="mini-btn danger" :title="$t('world.deleteWorldline')" @click.stop="$emit('delete-sim', root)">🗑️</button>
        </div>
        <div v-if="!collapsedRoots.has(root.simulation_id)">
          <div v-for="child in root.children" :key="child.simulation_id" class="tree-node child">
            <div class="tree-node-row">
              <span class="tree-branch">└─</span>
              <span class="tree-node-name">{{ child.result?.meta?.name || child.result?.meta?.whatif_question || formatTime(child.created_at) }}</span>
              <span class="badge" :class="child.status">{{ statusLabel(child.status) }}</span>
              <span class="tree-node-count">{{ $t('world.eventCount', { count: (child.result || {}).event_count || 0 }) }}</span>
              <button class="mini-btn ghost" @click="$emit('edit-meta', child)">✎</button>
              <button class="mini-btn ghost" @click="$emit('load-sim', child)">{{ $t('world.loadSimulation') }}</button>
              <button class="mini-btn" :disabled="simStarting" @click="$emit('continue-sim', child)">{{ $t('world.continueSimulation') }}</button>
              <button v-if="child.result?.meta?.whatif_question" class="mini-btn" :disabled="simStarting" @click="$emit('rerun-branch', child)">{{ $t('world.rerunBranchWithSettings') }}</button>
              <button class="mini-btn ghost" @click="$emit('export-sim', child)">{{ $t('world.exportSimulation') }}</button>
              <button class="mini-btn ghost" @click="$emit('copy-sim', child)">{{ $t('world.copyWorldline') }}</button>
              <button class="mini-btn danger" :title="$t('world.deleteWorldline')" @click.stop="$emit('delete-sim', child)">🗑️</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 历史模拟记录与批量管理 -->
    <div v-if="simHistory.length" class="sim-history">
      <div class="sim-history-title">
        <span>{{ $t('world.reportHistoryTitle') }}</span>
        <div class="sim-history-actions">
          <button class="mini-btn ghost" @click="$emit('toggle-batch-mode')">
            {{ simBatchMode ? '退出批量' : '批量管理' }}
          </button>
          <template v-if="simBatchMode">
            <button class="mini-btn ghost" @click="$emit('toggle-select-all')">
              {{ selectedSimIds.length === simHistory.length ? '取消全选' : '全选' }}
            </button>
            <button
              class="mini-btn danger"
              :disabled="!selectedSimIds.length || deletingSimBatch"
              @click="$emit('run-batch-delete')"
            >
              <span v-if="deletingSimBatch" class="spinner-xs"></span>
              🗑️ 批量删除 ({{ selectedSimIds.length }})
            </button>
          </template>
          <button class="mini-btn ghost" @click="$emit('export-all')">{{ $t('world.exportAllWorldlines') }}</button>
          <button v-if="simHistory.length >= 2" class="mini-btn ghost" @click="$emit('toggle-compare-mode')">
            {{ compareMode ? $t('world.cancel') : $t('world.compareWorldlines') }}
          </button>
          <button v-if="compareMode && compareSelected.length === 2" class="mini-btn" @click="$emit('open-compare')">
            {{ $t('world.compare') }}
          </button>
          <button v-if="compareMode && compareSelected.length === 2" class="mini-btn" @click="$emit('merge-selected')">
            {{ $t('world.mergeWorldlines') }}
          </button>
        </div>
      </div>
      <div v-for="(h, i) in simHistory" :key="i" class="sim-history-item" :class="{ 'batch-selected': selectedSimIds.includes(h.simulation_id) }">
        <input
          v-if="simBatchMode"
          type="checkbox"
          class="sim-compare-check"
          :checked="selectedSimIds.includes(h.simulation_id)"
          @change="$emit('toggle-select-sim', h.simulation_id)"
        />
        <input
          v-else-if="compareMode"
          type="checkbox"
          class="sim-compare-check"
          :checked="compareSelected.includes(h.simulation_id)"
          @change="$emit('toggle-compare-select', h)"
        />
        <template v-if="!compareMode">
          <span class="sim-history-time">{{ formatTime(h.created_at) }}</span>
          <span class="sim-history-status" :class="h.status">{{ statusLabel(h.status) }}</span>
          <span class="sim-history-count">{{ $t('world.eventCount', { count: (h.result || {}).event_count || 0 }) }}</span>
          <span v-if="(h.result || {}).meta && (h.result || {}).meta.whatif_question" class="sim-history-flag">{{ $t('world.whatifFlag') }}</span>
          <button class="mini-btn ghost" @click="$emit('load-sim', h)">{{ $t('world.loadSimulation') }}</button>
          <button class="mini-btn" :disabled="simStarting" @click="$emit('continue-sim', h)">{{ $t('world.continueSimulation') }}</button>
          <button class="mini-btn ghost" @click="$emit('export-sim', h)">{{ $t('world.exportSimulation') }}</button>
          <template v-if="h.status === 'completed' && !((h.result || {}).meta || {}).whatif_question">
            <button class="mini-btn" :disabled="whatIfing === h.simulation_id" @click="$emit('start-whatif', h)">
              <span v-if="whatIfing === h.simulation_id" class="spinner-xs"></span>
              {{ $t('world.whatifBtn') }}
            </button>
            <button class="mini-btn ghost" @click="$emit('open-chart-record', h)">{{ $t('world.chronicleBtn') }}</button>
          </template>
          <button class="mini-btn danger" :title="$t('world.deleteWorldline')" @click.stop="$emit('delete-sim', h)">🗑️</button>
        </template>
      </div>
      <!-- 当前模拟的 what-if 推演对话框 -->
      <div v-if="whatIfBaseId" class="whatif-box">
        <div class="whatif-title">
          {{ $t('world.whatifBaseTitle', { label: whatIfBaseLabel }) }}
        </div>
        <input
          :value="whatIfQuestion"
          class="whatif-input"
          :placeholder="$t('world.whatifPlaceholder')"
          @input="$emit('update:whatIfQuestion', $event.target.value)"
          @keyup.enter="$emit('confirm-whatif')"
        />
        <div class="whatif-btns">
          <button class="mini-btn active" :disabled="whatIfStarting || !whatIfQuestion.trim()" @click="$emit('confirm-whatif')">
            <span v-if="whatIfStarting" class="spinner-xs"></span>
            {{ whatIfStarting ? $t('world.whatifStarting') : $t('world.startWhatif') }}
          </button>
          <button class="mini-btn" @click="$emit('cancel-whatif')">{{ $t('world.cancel') }}</button>
        </div>
        <div v-if="whatIfMsgError" class="msg-line error">{{ whatIfMsg }}</div>
      </div>
      <!-- what-if 推演结果 -->
      <div v-if="whatIfActive" class="whatif-result">
        <div class="whatif-result-title">{{ $t('world.whatifResultTitle', { question: whatIfQuestionAsked }) }}</div>
        <div v-if="whatIfEvents.length" class="sim-events">
          <div class="sim-events-title">{{ $t('world.whatifEventStream') }}</div>
          <div v-for="(e, i) in whatIfEvents" :key="i" class="sim-event">
            <span class="sim-event-time">{{ e.time }}</span>
            <span class="sim-event-who">{{ e.character_name }}</span>
            <span class="sim-event-where">{{ e.location }}</span>
            <span class="sim-event-what">{{ e.action_desc }}</span>
            <span class="sim-event-result">{{ e.result }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import GodModePanel from './GodModePanel.vue'

defineProps({
  simStatus: { type: String, default: 'idle' },
  simProgress: { type: Object, default: () => ({}) },
  simGoal: { type: String, default: '' },
  simSteps: { type: Number, default: 6 },
  simTimeMode: { type: String, default: 'minutes' },
  simStepMin: { type: Number, default: 30 },
  simTimeJumps: { type: String, default: '' },
  simUseTimeline: { type: Boolean, default: false },
  simStorySummaryLlm: { type: Boolean, default: false },
  simMaxConcurrency: { type: Number, default: 1 },
  simStartEventId: { type: String, default: '' },
  simTimelineEvents: { type: Array, default: () => [] },
  availableModels: { type: Array, default: () => [] },
  selectedAgentModel: { type: String, default: '' },
  simStarting: { type: Boolean, default: false },
  simMsg: { type: String, default: '' },
  simMsgError: { type: Boolean, default: false },
  simEvents: { type: Array, default: () => [] },
  simQualityIssues: { type: Array, default: () => [] },
  playbackIndex: { type: Number, default: 0 },
  playbackPlaying: { type: Boolean, default: false },
  groupedSimEvents: { type: Array, default: () => [] },
  stepSummaries: { type: Array, default: () => [] },
  visibleSimGroups: { type: Array, default: () => [] },
  simGroupLimit: { type: Number, default: 50 },
  eventGraphData: { type: Object, default: () => ({ nodes: [], edges: [], width: 600, height: 400 }) },
  graphFilterChar: { type: String, default: '' },
  graphCharacters: { type: Array, default: () => [] },
  simGraphZoom: { type: Number, default: 1.0 },
  graphPosMap: { type: Object, default: () => ({}) },
  selectedGraphEvent: { type: String, default: null },
  showGodModePanel: { type: Boolean, default: false },
  characters: { type: Array, default: () => [] },
  godInjecting: { type: Boolean, default: false },
  godMsg: { type: String, default: '' },
  simCtlMsg: { type: String, default: '' },
  simCtlMsgError: { type: Boolean, default: false },
  interviewCharacter: { type: String, default: '' },
  interviewPrompt: { type: String, default: '' },
  interviewing: { type: Boolean, default: false },
  interviewAnswer: { type: String, default: '' },
  interviewMsg: { type: String, default: '' },
  interviewMsgError: { type: Boolean, default: false },
  reportSimulationId: { type: String, default: '' },
  reportSimulationLabel: { type: String, default: '' },
  reportGenerating: { type: Boolean, default: false },
  reportText: { type: String, default: '' },
  reportBlocks: { type: Array, default: () => [] },
  reportEmptyNote: { type: String, default: '' },
  worldTree: { type: Array, default: () => [] },
  collapsedRoots: { type: Object, default: () => new Set() },
  metaUndoStack: { type: Array, default: () => [] },
  simHistory: { type: Array, default: () => [] },
  simBatchMode: { type: Boolean, default: false },
  selectedSimIds: { type: Array, default: () => [] },
  deletingSimBatch: { type: Boolean, default: false },
  compareMode: { type: Boolean, default: false },
  compareSelected: { type: Array, default: () => [] },
  whatIfBaseId: { type: String, default: '' },
  whatIfBaseLabel: { type: String, default: '' },
  whatIfQuestion: { type: String, default: '' },
  whatIfStarting: { type: Boolean, default: false },
  whatIfMsg: { type: String, default: '' },
  whatIfMsgError: { type: Boolean, default: false },
  whatIfActive: { type: Boolean, default: false },
  whatIfQuestionAsked: { type: String, default: '' },
  whatIfEvents: { type: Array, default: () => [] },
  whatIfing: { type: String, default: '' }
})

const emit = defineEmits([
  'update:simGoal',
  'update:simSteps',
  'update:simTimeMode',
  'update:simStepMin',
  'update:simTimeJumps',
  'update:simUseTimeline',
  'update:simStorySummaryLlm',
  'update:simMaxConcurrency',
  'update:simStartEventId',
  'update:selectedAgentModel',
  'update:graphFilterChar',
  'update:interviewPrompt',
  'update:whatIfQuestion',
  'start-sim',
  'control',
  'playback-prev',
  'playback-toggle',
  'playback-next',
  'rollback-step',
  'open-event-detail',
  'open-causal-chain',
  'load-more-groups',
  'zoom-graph',
  'export-graph',
  'select-graph-event',
  'open-director',
  'toggle-god-mode',
  'god-submit',
  'select-character',
  'send-interview',
  'generate-report',
  'export-report-html',
  'undo-meta',
  'toggle-root',
  'edit-meta',
  'load-sim',
  'continue-sim',
  'export-sim',
  'copy-sim',
  'start-whatif',
  'batch-whatif',
  'delete-sim',
  'rerun-branch',
  'toggle-batch-mode',
  'toggle-select-all',
  'run-batch-delete',
  'export-all',
  'toggle-compare-mode',
  'toggle-select-sim',
  'toggle-compare-select',
  'open-compare',
  'merge-selected',
  'open-chart-record',
  'confirm-whatif',
  'cancel-whatif'
])

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
</script>
