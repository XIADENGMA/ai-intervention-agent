/**
 * 多任务管理模块
 * 负责任务列表管理、标签页渲染、任务切换等功能
 */

// ==================== 任务轮询 ====================

/**
 * 启动任务列表轮询
 */
function startTasksPolling() {
  if (tasksPollingTimer) {
    clearInterval(tasksPollingTimer)
  }

  tasksPollingTimer = setInterval(async () => {
    try {
      const response = await fetch('/api/tasks')
      const data = await response.json()

      if (data.success) {
        updateTasksList(data.tasks)
        updateTasksStats(data.stats)
      }
    } catch (error) {
      console.error('轮询任务列表失败:', error)
    }
  }, 2000) // 每2秒轮询一次

  console.log('任务列表轮询已启动')
}

/**
 * 停止任务列表轮询
 */
function stopTasksPolling() {
  if (tasksPollingTimer) {
    clearInterval(tasksPollingTimer)
    tasksPollingTimer = null
    console.log('任务列表轮询已停止')
  }
}

// ==================== 任务列表更新 ====================

// 防止轮询与手动切换冲突的标志
let isManualSwitching = false

/**
 * 更新任务列表
 */
function updateTasksList(tasks) {
  const oldTaskIds = currentTasks.map(t => t.task_id)
  const newTaskIds = tasks.map(t => t.task_id)

  // 检测新任务
  const addedTasks = newTaskIds.filter(id => !oldTaskIds.includes(id))
  if (addedTasks.length > 0) {
    console.log(`✨ 检测到 ${addedTasks.length} 个新任务`)

    // 如果当前有活动任务,显示视觉提示
    if (activeTaskId) {
      showNewTaskVisualHint(addedTasks.length)
    }

    // 为所有新任务启动倒计时（包括pending任务）
    tasks.filter(t => addedTasks.includes(t.task_id)).forEach(task => {
      if (task.status !== 'completed' && !taskCountdowns[task.task_id]) {
        startTaskCountdown(task.task_id, task.auto_resubmit_timeout || 290)
        console.log(`已为新任务启动倒计时: ${task.task_id}`)
      }
    })
  }

  currentTasks = tasks

  // 从任务列表中找到active任务，同步activeTaskId
  const activeTask = tasks.find(t => t.status === 'active')
  if (activeTask && activeTask.task_id !== activeTaskId) {
    const oldActiveTaskId = activeTaskId
    activeTaskId = activeTask.task_id
    console.log(`同步activeTaskId: ${oldActiveTaskId} -> ${activeTaskId}`)

    // 更新圆环颜色
    updateCountdownRingColors(oldActiveTaskId, activeTaskId)
  } else if (!activeTaskId && tasks.length > 0) {
    // 如果activeTaskId为null，且有任务，自动设置第一个任务为active
    activeTaskId = tasks[0].task_id
    console.log(`自动设置第一个任务为active: ${activeTaskId}`)
  }

  // 更新标签页UI
  renderTaskTabs()

  // 如果正在手动切换，跳过自动加载
  if (isManualSwitching) {
    return
  }

  // 如果activeTaskId刚刚被同步更新，加载其详情
  // （activeTask已在上面定义，不重复声明）
  if (activeTask && activeTask.task_id === activeTaskId) {
    loadTaskDetails(activeTaskId)
  }
}

/**
 * 更新任务统计信息
 *
 * ⚠️ 注意：任务计数徽章已移除，此函数保留用于向后兼容
 */
function updateTasksStats(stats) {
  // 任务计数徽章已从UI中移除，此函数不再执行任何操作
  // 保留此函数是为了避免其他代码调用时出错
  return

  /* 旧代码已注释（徽章功能已移除）
  const badge = document.getElementById('task-count-badge')
  if (!badge) {
    console.warn('任务计数徽章元素未找到')
    return
  }
  if (stats.pending > 0) {
    badge.textContent = stats.pending
    badge.classList.remove('hidden')
  } else {
    badge.classList.add('hidden')
  }
  */
}

// ==================== 标签页渲染 ====================

/**
 * 渲染任务标签页（优化版：只更新必要的DOM）
 */
function renderTaskTabs() {
  const tabsContainer = document.getElementById('task-tabs')
  const container = document.getElementById('task-tabs-container')

  // 【修复】添加null检查并延迟重试，防止DOM未加载时报错
  if (!container || !tabsContainer) {
    console.warn('标签栏容器未找到，可能DOM还未加载完成，将在100ms后重试')
    // 延迟100ms后重试一次
    setTimeout(() => {
      const retryContainer = document.getElementById('task-tabs-container')
      const retryTabsContainer = document.getElementById('task-tabs')
      if (retryContainer && retryTabsContainer) {
        console.log('✅ 重试成功，开始渲染标签栏')
        renderTaskTabs()
      } else {
        console.error('❌ 重试失败，标签栏容器仍然未找到')
      }
    }, 100)
    return
  }

  // 过滤出未完成的任务
  const incompleteTasks = currentTasks.filter(task => task.status !== 'completed')

  if (incompleteTasks.length === 0) {
    container.classList.add('hidden')
    return
  }

  container.classList.remove('hidden')

  // 优化：只更新active状态，不重建DOM
  const existingTabs = tabsContainer.querySelectorAll('.task-tab')
  const existingTaskIds = Array.from(existingTabs).map(tab => tab.dataset.taskId)
  const currentTaskIds = currentTasks.map(t => t.task_id)

  // 只比较未完成的任务
  const incompleteTaskIds = incompleteTasks.map(t => t.task_id)

  // 检查是否需要重建（任务列表变化）
  const needsRebuild = existingTaskIds.length !== incompleteTaskIds.length ||
                       existingTaskIds.some((id, i) => id !== incompleteTaskIds[i])

  if (needsRebuild) {
    // 任务列表变化，完全重建
    tabsContainer.innerHTML = ''
    // 只显示未完成的任务（pending 和 active）
    incompleteTasks.forEach(task => {
      const tab = createTaskTab(task)
      tabsContainer.appendChild(tab)
    })
  } else {
    // 仅更新active状态（极快）
    existingTabs.forEach(tab => {
      const taskId = tab.dataset.taskId
      const isActive = taskId === activeTaskId
      tab.classList.toggle('active', isActive)
    })
  }
}

/**
 * 创建单个任务标签
 */
function createTaskTab(task) {
  const tab = document.createElement('div')
  tab.className = 'task-tab'
  if (task.status === 'active') {
    tab.classList.add('active')
  }
  tab.dataset.taskId = task.task_id

  // 任务名称
  const textSpan = document.createElement('span')
  textSpan.className = 'task-tab-text'

  // 智能显示：前缀截断 + 完整数字
  // 例如: "ai-intervention-agent-2822" → "ai-interven... 2822"
  const taskParts = task.task_id.split('-')
  const lastPart = taskParts[taskParts.length - 1]  // 最后的数字
  const prefixParts = taskParts.slice(0, -1).join('-')  // 前面部分

  let displayName
  if (prefixParts.length > 12) {
    // 前缀过长，截断
    displayName = `${prefixParts.substring(0, 11)}... ${lastPart}`
  } else {
    displayName = `${prefixParts} ${lastPart}`
  }

  textSpan.textContent = displayName
  textSpan.title = task.task_id  // 悬停显示完整ID

  // 先添加文本（左边）
  tab.appendChild(textSpan)

  // SVG圆环倒计时（总是显示，在右边）
  if (task.status !== 'completed') {
    const countdownRing = document.createElement('div')
    countdownRing.className = 'countdown-ring'
    countdownRing.id = `countdown-${task.task_id}`

    // 使用已有的倒计时数据或任务的配置
    let remaining, total
    if (taskCountdowns[task.task_id]) {
      remaining = taskCountdowns[task.task_id].remaining
      total = taskCountdowns[task.task_id].timeout || 290
    } else {
      // 倒计时还未启动，使用任务配置的初始值
      remaining = task.auto_resubmit_timeout || 290
      total = task.auto_resubmit_timeout || 290
    }

    // SVG圆环实现
    const radius = 9  // 圆环半径
    const circumference = 2 * Math.PI * radius  // 圆周长
    const progress = (remaining / total)  // 进度（0-1）
    const offset = circumference * (1 - progress)  // dash-offset

    // 使用activeTaskId判断是否active，而不是task.status
    const isActive = (task.task_id === activeTaskId)
    const strokeColor = isActive ? 'rgba(255, 255, 255, 0.9)' : 'rgba(139, 92, 246, 0.9)'

    countdownRing.innerHTML = `
      <svg width="22" height="22" viewBox="0 0 22 22">
        <circle
          cx="11" cy="11" r="${radius}"
          stroke="${strokeColor}"
          stroke-width="3"
          fill="none"
          stroke-dasharray="${circumference}"
          stroke-dashoffset="${offset}"
          stroke-linecap="round"
        />
      </svg>
      <span class="countdown-number">${remaining}</span>
    `
    countdownRing.title = `剩余${remaining}秒`

    tab.appendChild(countdownRing)  // 在textSpan之后
  }

  // 点击标签切换任务
  tab.onclick = () => switchTask(task.task_id)

  return tab
}

// ==================== 任务切换 ====================

/**
 * 切换到指定任务
 */
async function switchTask(taskId) {
  // 设置手动切换标志，防止轮询干扰
  isManualSwitching = true

  // 立即更新UI，提升响应速度
  const oldActiveTaskId = activeTaskId
  activeTaskId = taskId
  renderTaskTabs() // 立即更新标签高亮

  // 立即更新圆环颜色，不等待DOM重建
  updateCountdownRingColors(oldActiveTaskId, taskId)

  try {
    // 并行执行：激活任务 + 加载详情
    const [activateResponse] = await Promise.all([
      fetch(`/api/tasks/${taskId}/activate`, { method: 'POST' }),
      loadTaskDetails(taskId) // 直接加载，不等待激活响应
    ])

    const data = await activateResponse.json()
    if (!data.success) {
      console.error('切换任务失败:', data.error)
    } else {
      console.log(`已切换到任务: ${taskId}`)
    }
  } catch (error) {
    console.error('切换任务失败:', error)
  } finally {
    // 200ms后解除标志，允许轮询恢复
    setTimeout(() => {
      isManualSwitching = false
    }, 200)
  }
}

/**
 * 更新圆环颜色（用于active状态切换）
 */
function updateCountdownRingColors(oldActiveTaskId, newActiveTaskId) {
  // 将旧active任务的圆环改为紫色
  if (oldActiveTaskId) {
    const oldRing = document.getElementById(`countdown-${oldActiveTaskId}`)
    if (oldRing) {
      const oldCircle = oldRing.querySelector('circle')
      if (oldCircle) {
        oldCircle.setAttribute('stroke', 'rgba(139, 92, 246, 0.9)')
      }
    }
  }

  // 将新active任务的圆环改为白色
  if (newActiveTaskId) {
    const newRing = document.getElementById(`countdown-${newActiveTaskId}`)
    if (newRing) {
      const newCircle = newRing.querySelector('circle')
      if (newCircle) {
        newCircle.setAttribute('stroke', 'rgba(255, 255, 255, 0.9)')
      }
    }
  }
}

/**
 * 加载任务详情
 */
async function loadTaskDetails(taskId) {
  try {
    const response = await fetch(`/api/tasks/${taskId}`)
    const data = await response.json()

    if (data.success) {
      const task = data.task

      // 更新页面内容
      updateTaskIdDisplay(task.task_id)
      updateDescriptionDisplay(task.prompt)
      updateOptionsDisplay(task.predefined_options)

      // 只在倒计时不存在时启动，避免切换标签时重置倒计时
      if (!taskCountdowns[task.task_id]) {
        startTaskCountdown(task.task_id, task.auto_resubmit_timeout)
        console.log(`首次启动倒计时: ${taskId}`)
      } else {
        console.log(`倒计时已存在，不重置: ${taskId}`)
      }

      console.log(`已加载任务详情: ${taskId}`)
    } else {
      console.error('加载任务详情失败:', data.error)
    }
  } catch (error) {
    console.error('加载任务详情失败:', error)
  }
}

/**
 * 更新描述显示
 */
async function updateDescriptionDisplay(prompt) {
  const descriptionElement = document.getElementById('description')
  if (!descriptionElement) return

  try {
    // 获取服务器端已渲染的 HTML
    const response = await fetch(`/api/tasks/${activeTaskId}`)
    const data = await response.json()

    if (data.success && data.task.prompt) {
      // 使用服务器端渲染的 markdown HTML
      const markdownHtml = await fetch('/api/config').then(r => r.json()).then(cfg => cfg.prompt_html || prompt)
      descriptionElement.innerHTML = markdownHtml

      // 立即触发 MathJax 渲染
      if (typeof window.MathJax !== 'undefined' && window.MathJax.typesetPromise) {
        try {
          await window.MathJax.typesetPromise([descriptionElement])
          console.log('✅ MathJax 渲染完成')
        } catch (mathError) {
          console.warn('MathJax 渲染失败:', mathError)
        }
      }
    }
  } catch (error) {
    console.error('更新描述失败:', error)
    descriptionElement.textContent = prompt
  }
}

/**
 * 更新选项显示
 */
function updateOptionsDisplay(options) {
  const optionsContainer = document.getElementById('options-container')
  if (!optionsContainer) return

  // 保存当前选中状态
  const selectedStates = []
  const existingCheckboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
  existingCheckboxes.forEach((checkbox, index) => {
    selectedStates[index] = checkbox.checked
  })

  // 清空现有选项
  optionsContainer.innerHTML = ''

  if (options && options.length > 0) {
    options.forEach((option, index) => {
      const optionDiv = document.createElement('div')
      optionDiv.className = 'option-item'

      const checkbox = document.createElement('input')
      checkbox.type = 'checkbox'
      checkbox.id = `option-${index}`
      checkbox.value = option

      // 恢复选中状态（如果之前保存过）
      if (selectedStates[index]) {
        checkbox.checked = true
      }

      const label = document.createElement('label')
      label.htmlFor = `option-${index}`
      label.textContent = option

      optionDiv.appendChild(checkbox)
      optionDiv.appendChild(label)
      optionsContainer.appendChild(optionDiv)
    })

    optionsContainer.classList.remove('hidden')
    optionsContainer.classList.add('visible')

    const separator = document.getElementById('separator')
    if (separator) {
      separator.classList.remove('hidden')
      separator.classList.add('visible')
    }
  } else {
    optionsContainer.classList.add('hidden')
    optionsContainer.classList.remove('visible')
  }
}

/**
 * 关闭任务
 */
async function closeTask(taskId) {
  if (!confirm(`确定要关闭任务 ${taskId} 吗？`)) {
    return
  }

  try {
    // 停止该任务的倒计时
    if (taskCountdowns[taskId]) {
      clearInterval(taskCountdowns[taskId].timer)
      delete taskCountdowns[taskId]
    }

    // 从列表中移除
    currentTasks = currentTasks.filter(t => t.task_id !== taskId)

    // 重新渲染标签页
    renderTaskTabs()

    // 如果关闭的是活动任务，切换到下一个任务
    if (activeTaskId === taskId && currentTasks.length > 0) {
      switchTask(currentTasks[0].task_id)
    }

    console.log(`已关闭任务: ${taskId}`)
  } catch (error) {
    console.error('关闭任务失败:', error)
  }
}

// ==================== 独立倒计时管理 ====================

/**
 * 启动任务倒计时
 */
function startTaskCountdown(taskId, timeout) {
  // 停止该任务的旧倒计时
  if (taskCountdowns[taskId] && taskCountdowns[taskId].timer) {
    clearInterval(taskCountdowns[taskId].timer)
  }

  // 初始化倒计时数据
  taskCountdowns[taskId] = {
    remaining: timeout,
    timeout: timeout,  // 添加timeout字段，用于计算进度百分比
    timer: null
  }

  // 如果是活动任务，更新主倒计时显示
  if (taskId === activeTaskId) {
    updateCountdownDisplay(timeout)
  }

  // 启动定时器
  taskCountdowns[taskId].timer = setInterval(() => {
    taskCountdowns[taskId].remaining--

    // 更新SVG圆环倒计时
    const countdownRing = document.getElementById(`countdown-${taskId}`)
    if (countdownRing) {
      const remaining = taskCountdowns[taskId].remaining
      const total = taskCountdowns[taskId].timeout || 290
      const progress = (remaining / total)  // 进度（0-1）

      // 更新SVG circle的stroke-dashoffset
      const radius = 9
      const circumference = 2 * Math.PI * radius
      const offset = circumference * (1 - progress)

      const circle = countdownRing.querySelector('circle')
      const numberSpan = countdownRing.querySelector('.countdown-number')

      if (circle) {
        circle.setAttribute('stroke-dashoffset', offset)
      }
      if (numberSpan) {
        numberSpan.textContent = remaining
      }

      countdownRing.title = `剩余${remaining}秒`
    }

    // 如果是活动任务，也更新主倒计时
    if (taskId === activeTaskId) {
      updateCountdownDisplay(taskCountdowns[taskId].remaining)
    }

    // 倒计时结束
    if (taskCountdowns[taskId].remaining <= 0) {
      clearInterval(taskCountdowns[taskId].timer)
      if (taskId === activeTaskId) {
        autoSubmitTask(taskId)
      }
    }
  }, 1000)

  console.log(`已启动任务倒计时: ${taskId}, ${timeout}秒`)
}

/**
 * 格式化倒计时显示
 */
function formatCountdown(seconds) {
  if (seconds > 60) {
    return `${Math.floor(seconds / 60)}m`
  }
  return `${seconds}s`
}

/**
 * 自动提交任务
 */
async function autoSubmitTask(taskId) {
  console.log(`任务 ${taskId} 倒计时结束，自动提交`)
  // 使用固定的默认反馈文本
  const defaultMessage = '好的，代码先保持现状，然后重新调用 interactive_feedback 工具，调用interactive_feedback后会有一个窗口，我将在窗口中告诉你下一步指令，请先调用interactive_feedback工具'
  await submitTaskFeedback(taskId, defaultMessage, [])
}

/**
 * 提交任务反馈
 */
async function submitTaskFeedback(taskId, feedbackText, selectedOptions) {
  try {
    const formData = new FormData()
    formData.append('feedback_text', feedbackText)
    formData.append('selected_options', JSON.stringify(selectedOptions))

    const response = await fetch(`/api/tasks/${taskId}/submit`, {
      method: 'POST',
      body: formData
    })

    const data = await response.json()

    if (data.success) {
      console.log(`任务 ${taskId} 提交成功`)
      // 停止该任务的倒计时
      if (taskCountdowns[taskId]) {
        clearInterval(taskCountdowns[taskId].timer)
        delete taskCountdowns[taskId]
      }
    } else {
      console.error('提交任务失败:', data.error)
    }
  } catch (error) {
    console.error('提交任务反馈失败:', error)
  }
}

// ==================== 新任务通知 ====================

/**
 * 显示新任务视觉提示
 * 在标签栏旁边显示一个临时的视觉提示,提醒用户有新任务
 */
function showNewTaskVisualHint(count) {
  const container = document.getElementById('task-tabs-container')
  if (!container) return

  // 创建提示元素
  const hint = document.createElement('div')
  hint.id = 'new-task-hint'
  hint.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    font-size: 14px;
    font-weight: 500;
    z-index: 10000;
    animation: slideInRight 0.3s ease-out, fadeOutUp 0.3s ease-in 2.7s forwards;
    pointer-events: none;
  `
  hint.innerHTML = `✨ ${count} 个新任务已添加到标签栏`

  // 添加到页面
  document.body.appendChild(hint)

  // 3秒后自动移除
  setTimeout(() => {
    if (hint.parentNode) {
      hint.parentNode.removeChild(hint)
    }
  }, 3000)

  console.log(`显示新任务视觉提示: ${count} 个新任务`)
}

/**
 * 显示新任务通知 (保留用于向后兼容)
 */
function showNewTaskNotification(count) {
  // 使用新的视觉提示代替旧的通知
  showNewTaskVisualHint(count)

  // 可选: 显示浏览器通知（如果有通知管理器）
  if (typeof notificationManager !== 'undefined') {
    notificationManager
      .sendNotification('AI Intervention Agent', `收到 ${count} 个新任务`, {
        tag: 'new-tasks',
        requireInteraction: false
      })
      .catch(error => {
        console.warn('发送新任务通知失败:', error)
      })
  }
}

// ==================== 初始化 ====================

/**
 * 初始化多任务功能
 */
async function initMultiTaskSupport() {
  console.log('初始化多任务支持...')

  // 立即获取一次任务列表（不等待轮询）
  await refreshTasksList()

  // 启动定时轮询
  startTasksPolling()

  // 【修复】添加轮询健康检查机制
  // 每30秒检查一次轮询器是否还在运行,如果停止则重新启动
  setInterval(() => {
    if (!tasksPollingTimer) {
      console.warn('⚠️ 任务轮询已停止,自动重新启动')
      startTasksPolling()
    }
  }, 30000)

  console.log('多任务支持初始化完成 (包含轮询健康检查)')
}

/**
 * 手动触发任务列表更新（用于提交反馈后立即同步）
 */
async function refreshTasksList() {
  try {
    const response = await fetch('/api/tasks')
    const data = await response.json()

    if (data.success) {
      updateTasksList(data.tasks)
      updateTasksStats(data.stats)
      console.log('任务列表已手动刷新')
    }
  } catch (error) {
    console.error('手动刷新任务列表失败:', error)
  }
}

// 导出函数供外部使用
if (typeof window !== 'undefined') {
  window.multiTaskModule = {
    startTasksPolling,
    stopTasksPolling,
    switchTask,
    closeTask,
    initMultiTaskSupport,
    refreshTasksList  // 导出刷新函数
  }
}
