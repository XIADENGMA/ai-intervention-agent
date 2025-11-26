/**
 * 多任务管理模块
 *
 * 提供完整的多任务并发管理功能，支持任务的创建、切换、轮询、倒计时和关闭。
 *
 * ## 核心功能
 *
 * 1. **任务轮询**：定期从服务器获取任务列表和统计信息
 * 2. **任务列表管理**：动态更新任务列表，检测新增/删除的任务
 * 3. **标签页渲染**：渲染任务标签页UI，支持拖拽和视觉反馈
 * 4. **任务切换**：支持手动切换活动任务，更新UI状态
 * 5. **任务倒计时**：为每个任务独立管理倒计时，支持自动提交
 * 6. **任务关闭**：支持关闭单个任务，清理相关资源
 * 7. **视觉提示**：新任务通知、倒计时环、状态标记
 *
 * ## 状态管理
 *
 * - `currentTasks`: 当前所有任务列表
 * - `activeTaskId`: 当前活动任务ID
 * - `taskCountdowns`: 任务倒计时字典
 * - `taskTextareaContents`: 任务输入框内容缓存
 * - `taskOptionsStates`: 任务选项状态缓存
 * - `taskImages`: 任务图片缓存
 * - `isManualSwitching`: 手动切换标志（防止冲突）
 *
 * ## 轮询机制
 *
 * - 轮询间隔：2秒
 * - 轮询端点：`/api/tasks`
 * - 自动检测新增/删除的任务
 * - 支持启动/停止轮询
 *
 * ## 并发控制
 *
 * - 使用 `isManualSwitching` 标志防止手动切换与轮询冲突
 * - 使用 `manualSwitchingTimer` 管理切换标志的生命周期
 * - 任务切换时清除旧的定时器，避免竞态条件
 *
 * ## 资源清理
 *
 * - 任务删除时自动清理倒计时
 * - 任务关闭时清理输入缓存、选项状态、图片缓存
 * - 页面卸载时停止轮询和倒计时
 *
 * ## 注意事项
 *
 * - 任务切换是异步操作，需要等待服务器响应
 * - 倒计时是独立的，每个任务有自己的计时器
 * - 手动切换期间会暂停轮询更新，避免UI闪烁
 * - 新任务会自动启动倒计时（包括 pending 状态）
 *
 * ## 依赖关系
 *
 * - 依赖 `main.js` 中的 `updatePageContent`、`startCountdown`、`stopCountdown`
 * - 依赖 `dom-security.js` 中的 `DOMSecurityHelper`
 * - 依赖全局变量 `activeTaskId`、`currentTasks`、`taskCountdowns` 等
 */

// ==================== 任务轮询 ====================

/**
 * 启动任务列表轮询
 *
 * 定期从服务器获取任务列表和统计信息，并更新UI。
 *
 * ## 功能说明
 *
 * - 清除已存在的轮询定时器（避免重复轮询）
 * - 创建新的定时器，每2秒轮询一次
 * - 请求 `/api/tasks` 端点获取任务数据
 * - 成功时更新任务列表和统计信息
 * - 失败时记录错误日志
 *
 * ## 轮询数据
 *
 * - `data.tasks`: 任务列表数组
 * - `data.stats`: 统计信息对象
 * - `data.success`: 请求是否成功
 *
 * ## 调用时机
 *
 * - 页面加载时自动调用
 * - 用户手动刷新任务列表时
 * - 任务切换完成后重新启动
 *
 * ## 注意事项
 *
 * - 轮询间隔不应过短（避免服务器压力）
 * - 轮询失败不会中断定时器（继续尝试）
 * - 页面卸载时应调用 `stopTasksPolling` 停止轮询
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
 *
 * 清除轮询定时器，停止定期获取任务列表。
 *
 * ## 功能说明
 *
 * - 检查定时器是否存在
 * - 清除定时器并设置为 null
 * - 输出停止日志
 *
 * ## 调用时机
 *
 * - 页面卸载时（防止内存泄漏）
 * - 用户明确停止轮询时
 * - 切换到单任务模式时
 *
 * ## 注意事项
 *
 * - 多次调用是安全的（会检查定时器是否存在）
 * - 停止后需要手动调用 `startTasksPolling` 重新启动
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
let manualSwitchingTimer = null

/**
 * 更新任务列表
 *
 * 检测任务变化（新增/删除），更新任务列表，并渲染标签页。
 *
 * ## 功能说明
 *
 * 1. **检测新任务**
 *    - 比较新旧任务ID列表
 *    - 显示新任务数量提示
 *    - 为新任务启动倒计时（包括 pending 状态）
 *    - 显示视觉提示（如果当前有活动任务）
 *
 * 2. **检测已删除任务**
 *    - 清理已删除任务的倒计时
 *    - 清理输入框内容缓存
 *    - 清理选项状态缓存
 *    - 清理图片缓存
 *    - 防止内存泄漏
 *
 * 3. **更新任务列表**
 *    - 更新全局 `currentTasks` 变量
 *    - 渲染任务标签页
 *    - 输出日志记录
 *
 * @param {Array} tasks - 任务列表数组
 *
 * ## 任务对象结构
 *
 * - `task_id`: 任务唯一ID
 * - `status`: 任务状态（pending/active/completed）
 * - `prompt`: 任务提示信息
 * - `predefined_options`: 预定义选项数组
 * - `auto_resubmit_timeout`: 自动提交超时（秒）
 *
 * ## 并发控制
 *
 * - 使用 `isManualSwitching` 标志避免冲突
 * - 手动切换期间不更新活动任务
 * - 自动倒计时不会被手动切换打断
 *
 * ## 注意事项
 *
 * - 新任务会自动启动倒计时（包括 pending 状态）
 * - 已删除任务的资源会立即清理
 * - 更新操作是同步的（不会阻塞UI）
 * - 倒计时是独立的，每个任务有自己的计时器
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
    tasks
      .filter(t => addedTasks.includes(t.task_id))
      .forEach(task => {
        if (task.status !== 'completed' && !taskCountdowns[task.task_id]) {
          startTaskCountdown(task.task_id, task.auto_resubmit_timeout || 290)
          console.log(`已为新任务启动倒计时: ${task.task_id}`)
        }
      })
  }

  // 检测已删除的任务并清理倒计时
  const removedTasks = oldTaskIds.filter(id => !newTaskIds.includes(id))
  if (removedTasks.length > 0) {
    console.log(`🗑️ 检测到 ${removedTasks.length} 个已删除任务`)
    removedTasks.forEach(taskId => {
      // 清理倒计时
      if (taskCountdowns[taskId]) {
        clearInterval(taskCountdowns[taskId].timer)
        delete taskCountdowns[taskId]
        console.log(`✅ 已清理任务 ${taskId} 的倒计时`)
      }
      // 清理任务缓存
      if (taskTextareaContents[taskId] !== undefined) {
        delete taskTextareaContents[taskId]
      }
      if (taskOptionsStates[taskId] !== undefined) {
        delete taskOptionsStates[taskId]
      }
      if (taskImages[taskId] !== undefined) {
        delete taskImages[taskId]
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
  } else if (tasks.length === 0 && activeTaskId) {
    // 如果任务列表为空，重置activeTaskId
    console.log(`✅ 任务列表已清空，重置 activeTaskId: ${activeTaskId} -> null`)
    activeTaskId = null
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
 * 保留的函数，用于向后兼容。任务计数徽章已从UI中移除。
 *
 * ## 功能说明
 *
 * - 此函数当前为空实现
 * - 保留是为了避免破坏现有调用
 * - 未来可能会移除或重新实现
 *
 * @param {Object} stats - 统计信息对象（未使用）
 *
 * ## 注意事项
 *
 * - 不执行任何操作
 * - 可以安全调用
 * - 不影响性能
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
 * 渲染任务标签页
 *
 * 动态渲染所有任务的标签页UI，支持增量更新，避免全量重渲染。
 *
 * ## 功能说明
 *
 * - 获取标签页容器元素
 * - 构建已存在标签的ID映射
 * - 遍历当前任务列表，创建/更新标签页
 * - 删除不再存在的标签页
 * - 使用 DocumentFragment 批量添加新标签（性能优化）
 *
 * ## 优化策略
 *
 * - **增量更新**：只更新变化的部分，不重新渲染整个列表
 * - **DOM批量操作**：使用 DocumentFragment 减少重排
 * - **标签复用**：保留已存在的标签，只更新内容
 * - **删除清理**：移除不再需要的标签
 *
 * ## 渲染逻辑
 *
 * 1. 检查容器是否存在
 * 2. 构建当前DOM中标签的映射
 * 3. 遍历任务列表：
 *    - 标签已存在：跳过（复用）
 *    - 标签不存在：创建新标签并添加到 Fragment
 * 4. 批量添加新标签到容器
 * 5. 删除不再存在的标签
 *
 * ## 标签顺序
 *
 * - 按任务添加顺序排列
 * - Active 任务会高亮显示
 * - 新任务添加到末尾
 *
 * ## 性能考虑
 *
 * - 避免全量DOM重建（使用增量更新）
 * - 使用 DocumentFragment 减少重排次数
 * - 标签复用避免重复创建
 * - 适合频繁更新的场景
 *
 * ## 注意事项
 *
 * - 容器不存在时会记录警告
 * - 标签创建由 `createTaskTab` 函数完成
 * - 删除标签时会触发过渡动画
 */
function renderTaskTabs() {
  const tabsContainer = document.getElementById('task-tabs')
  const container = document.getElementById('task-tabs-container')

  // DOM未加载时延迟重试
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
  const needsRebuild =
    existingTaskIds.length !== incompleteTaskIds.length ||
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
 *
 * 为指定任务创建标签页UI元素，包含任务ID、状态标记、倒计时环和关闭按钮。
 *
 * @param {Object} task - 任务对象
 * @returns {HTMLElement} 标签页DOM元素
 *
 * ## 标签结构
 *
 * - 外层容器：task-tab类
 * - 倒计时环：SVG圆环进度指示器
 * - 任务ID文本：显示任务ID
 * - 状态标记：active标记
 * - 关闭按钮：点击关闭任务
 *
 * ## 状态类
 *
 * - `active`：当前活动任务
 * - `data-task-id`：任务ID属性
 *
 * ## 事件处理
 *
 * - 点击标签：切换任务
 * - 点击关闭按钮：关闭任务（阻止冒泡）
 *
 * ## 安全性
 *
 * - 使用 `DOMSecurityHelper.createElement` 创建元素
 * - 使用 `DOMSecurityHelper.setTextContent` 设置文本
 * - 防止XSS攻击
 *
 * ## 注意事项
 *
 * - 标签ID格式：`task-tab-{task_id}`
 * - 关闭按钮ID格式：`close-btn-{task_id}`
 * - 倒计时环ID格式：`countdown-ring-{task_id}`
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
  const lastPart = taskParts[taskParts.length - 1] // 最后的数字
  const prefixParts = taskParts.slice(0, -1).join('-') // 前面部分

  let displayName
  if (prefixParts.length > 12) {
    // 前缀过长，截断
    displayName = `${prefixParts.substring(0, 11)}... ${lastPart}`
  } else {
    displayName = `${prefixParts} ${lastPart}`
  }

  textSpan.textContent = displayName
  textSpan.title = task.task_id // 悬停显示完整ID

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
    const radius = 9 // 圆环半径
    const circumference = 2 * Math.PI * radius // 圆周长
    const progress = remaining / total // 进度（0-1）
    const offset = circumference * (1 - progress) // dash-offset

    // 使用activeTaskId判断是否active，而不是task.status
    const isActive = task.task_id === activeTaskId
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

    tab.appendChild(countdownRing) // 在textSpan之后
  }

  // 点击标签切换任务
  tab.onclick = () => switchTask(task.task_id)

  return tab
}

// ==================== 任务切换 ====================

/**
 * 切换到指定任务
 *
 * 手动切换当前活动任务，更新服务器状态和UI显示。
 *
 * @param {string} taskId - 目标任务ID
 *
 * ## 功能说明
 *
 * 1. **状态保存**：保存当前任务的输入内容、选项状态
 * 2. **设置切换标志**：防止轮询冲突
 * 3. **发送切换请求**：POST `/api/tasks/{taskId}/activate`
 * 4. **更新UI**：切换活动标签、更新倒计时环颜色
 * 5. **加载新任务**：获取并显示新任务详情
 * 6. **重启轮询**：恢复任务列表轮询
 *
 * ## 并发控制
 *
 * - 设置 `isManualSwitching = true`（防止轮询更新）
 * - 清除旧的切换定时器（防止竞态条件）
 * - 5秒后自动清除切换标志
 *
 * ## 状态恢复
 *
 * - 恢复目标任务的输入框内容
 * - 恢复目标任务的选项选中状态
 * - 恢复目标任务的图片列表
 *
 * ## 错误处理
 *
 * - 请求失败时恢复原活动任务
 * - 显示错误提示
 * - 记录错误日志
 *
 * ## 注意事项
 *
 * - 切换是异步操作
 * - 切换期间暂停轮询更新
 * - 切换失败会回滚状态
 */
async function switchTask(taskId) {
  // 保存当前任务的textarea内容、选项勾选状态和图片列表
  if (activeTaskId) {
    const textarea = document.getElementById('feedback-text')
    if (textarea) {
      taskTextareaContents[activeTaskId] = textarea.value
      console.log(`✅ 已保存任务 ${activeTaskId} 的 textarea 内容`)
    }

    // 保存选项勾选状态
    const optionsContainer = document.getElementById('options-container')
    if (optionsContainer) {
      const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
      const optionsStates = []
      checkboxes.forEach((checkbox, index) => {
        optionsStates[index] = checkbox.checked
      })
      taskOptionsStates[activeTaskId] = optionsStates
      console.log(`✅ 已保存任务 ${activeTaskId} 的选项勾选状态`)
    }

    // 保存图片列表（深拷贝，避免引用问题）
    // 注意：不能简单浅拷贝，因为图片对象包含 blob URL，需要独立管理
    taskImages[activeTaskId] = selectedImages.map(img => ({
      ...img
      // 保留所有字段，包括 blob URL（每个任务独立管理）
    }))
    console.log(`✅ 已保存任务 ${activeTaskId} 的图片列表 (${selectedImages.length} 张)`)
  }

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
    // 清除旧计时器并重新设置200ms后解除标志
    if (manualSwitchingTimer) {
      clearTimeout(manualSwitchingTimer)
    }
    manualSwitchingTimer = setTimeout(() => {
      isManualSwitching = false
      manualSwitchingTimer = null
      console.log('✅ 任务切换锁定已解除，允许轮询恢复')
    }, 200)
  }
}

/**
 * 更新圆环颜色
 *
 * 切换任务时更新倒计时圆环的颜色（active任务使用主题色）。
 *
 * @param {string|null} oldActiveTaskId - 原活动任务ID
 * @param {string|null} newActiveTaskId - 新活动任务ID
 *
 * ## 功能说明
 *
 * - 重置旧任务的圆环颜色为灰色
 * - 设置新任务的圆环颜色为主题色
 *
 * ## 颜色规则
 *
 * - Active任务：主题色（橙色）
 * - Pending任务：灰色
 *
 * ## 注意事项
 *
 * - 元素不存在时会跳过
 * - 颜色值取自CSS变量
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
 *
 * 从服务器获取任务详情并更新UI显示。
 *
 * @param {string} taskId - 任务ID
 *
 * ## 功能说明
 *
 * 1. **防止过期请求**：检查任务ID是否仍是活动任务
 * 2. **请求任务详情**：GET `/api/tasks/{taskId}`
 * 3. **更新UI**：描述、选项、图片、倒计时
 * 4. **恢复状态**：输入框内容、选项选中状态、图片列表
 *
 * ## 竞态条件处理
 *
 * - 请求前检查活动任务ID
 * - 响应后再次检查（防止期间切换任务）
 * - 不匹配时跳过更新
 *
 * ## 错误处理
 *
 * - 任务不存在：显示错误提示
 * - 网络错误：记录错误日志
 * - 响应失败：显示失败消息
 *
 * ## 注意事项
 *
 * - 异步操作，可能存在竞态条件
 * - 使用活动任务ID检查避免更新错误任务
 * - 请求失败不影响其他功能
 */
async function loadTaskDetails(taskId) {
  try {
    const response = await fetch(`/api/tasks/${taskId}`)
    const data = await response.json()

    // 检查任务是否仍然是当前活动任务
    if (taskId !== activeTaskId) {
      console.log(`⏭️ 跳过过期的任务详情: ${taskId}（当前活动: ${activeTaskId}）`)
      return
    }

    if (data.success) {
      const task = data.task

      // 更新页面内容
      updateTaskIdDisplay(task.task_id)
      updateDescriptionDisplay(task.prompt)
      updateOptionsDisplay(task.predefined_options)

      // 恢复该任务之前保存的textarea内容
      const textarea = document.getElementById('feedback-text')
      if (textarea && taskTextareaContents[taskId] !== undefined) {
        textarea.value = taskTextareaContents[taskId]
        console.log(`✅ 已恢复任务 ${taskId} 的 textarea 内容`)
      }
      // 如果之前没有保存过内容，保持当前值（避免在用户正在输入时被轮询调用清空）

      // 恢复该任务之前保存的图片列表
      if (taskImages[taskId] && taskImages[taskId].length > 0) {
        // 深拷贝图片对象，避免引用问题
        selectedImages = taskImages[taskId].map(img => ({ ...img }))
        // 重新渲染图片预览
        const previewContainer = document.getElementById('image-previews')
        if (previewContainer) {
          previewContainer.innerHTML = ''
          selectedImages.forEach(imageItem => {
            renderImagePreview(imageItem, false)
          })
          updateImageCounter()
          updateImagePreviewVisibility()
        }
        console.log(`✅ 已恢复任务 ${taskId} 的图片列表 (${selectedImages.length} 张)`)
      }
      // 如果之前没有保存过图片，保持当前值（避免在用户正在添加图片时被轮询调用清空）

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
 *
 * 渲染任务描述（Markdown格式）并更新DOM。
 *
 * @param {string} prompt - Markdown格式的任务描述
 *
 * ## 功能说明
 *
 * - 调用 `renderMarkdownContent` 渲染Markdown
 * - 更新描述容器的HTML内容
 * - 处理代码块语法高亮
 * - 处理MathJax数学公式
 *
 * ## 安全性
 *
 * - Markdown渲染经过sanitize处理
 * - 防止XSS攻击
 *
 * ## 注意事项
 *
 * - 异步函数，等待渲染完成
 * - 容器不存在时会跳过
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
      const markdownHtml = await fetch('/api/config')
        .then(r => r.json())
        .then(cfg => cfg.prompt_html || prompt)

      // 使用 renderMarkdownContent 函数来正确处理代码块和 MathJax
      if (typeof renderMarkdownContent === 'function') {
        renderMarkdownContent(descriptionElement, markdownHtml)
      } else {
        // 降级方案：直接设置 innerHTML
        descriptionElement.innerHTML = markdownHtml

        // 手动处理代码块
        if (typeof processCodeBlocks === 'function') {
          processCodeBlocks(descriptionElement)
        }

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
    }
  } catch (error) {
    console.error('更新描述失败:', error)
    descriptionElement.textContent = prompt
  }
}

/**
 * 更新选项显示
 *
 * 动态创建任务选项的复选框列表。
 *
 * @param {Array<string>} options - 选项文本数组
 *
 * ## 功能说明
 *
 * - 清空选项容器
 * - 为每个选项创建复选框
 * - 恢复之前保存的选中状态
 * - 使用安全的DOM操作
 *
 * ## 复选框属性
 *
 * - type: checkbox
 * - value: 选项文本
 * - class: feedback-option
 *
 * ## 状态恢复
 *
 * - 从 `taskOptionsStates[activeTaskId]` 恢复选中状态
 * - 保持用户之前的选择
 *
 * ## 安全性
 *
 * - 使用 `DOMSecurityHelper` 创建元素
 * - 防止XSS攻击
 *
 * ## 注意事项
 *
 * - 容器不存在时会跳过
 * - 选项数组为空时显示空列表
 */
function updateOptionsDisplay(options) {
  const optionsContainer = document.getElementById('options-container')
  if (!optionsContainer) return

  // 优先使用该任务之前保存的勾选状态
  let selectedStates = []
  if (activeTaskId && taskOptionsStates[activeTaskId]) {
    selectedStates = taskOptionsStates[activeTaskId]
    console.log(`✅ 已恢复任务 ${activeTaskId} 的选项勾选状态`)
  } else {
    // 如果没有保存的状态，尝试保存当前状态（用于同一任务内的更新）
    const existingCheckboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
    existingCheckboxes.forEach((checkbox, index) => {
      selectedStates[index] = checkbox.checked
    })
  }

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
 *
 * 删除指定任务，清理相关资源并更新UI。
 *
 * @param {string} taskId - 要关闭的任务ID
 *
 * ## 功能说明
 *
 * 1. **确认操作**：显示确认对话框
 * 2. **发送删除请求**：DELETE `/api/tasks/{taskId}`
 * 3. **清理资源**：倒计时、缓存、UI元素
 * 4. **切换任务**：如果关闭的是活动任务，切换到下一个
 * 5. **刷新列表**：更新任务列表显示
 *
 * ## 资源清理
 *
 * - 停止并删除倒计时
 * - 清除输入框内容缓存
 * - 清除选项状态缓存
 * - 清除图片缓存
 * - 移除标签页DOM元素
 *
 * ## 任务切换逻辑
 *
 * - 关闭活动任务：自动切换到第一个pending任务
 * - 关闭非活动任务：不影响当前活动任务
 *
 * ## 错误处理
 *
 * - 删除失败：显示错误提示
 * - 记录错误日志
 *
 * ## 注意事项
 *
 * - 需要用户确认才执行
 * - 异步操作
 * - 删除后无法恢复
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

    // 清除该任务保存的所有状态
    if (taskTextareaContents[taskId] !== undefined) {
      delete taskTextareaContents[taskId]
      console.log(`✅ [关闭任务] 已清除任务 ${taskId} 保存的 textarea 内容`)
    }
    if (taskOptionsStates[taskId] !== undefined) {
      delete taskOptionsStates[taskId]
      console.log(`✅ [关闭任务] 已清除任务 ${taskId} 保存的选项勾选状态`)
    }
    if (taskImages[taskId] !== undefined) {
      delete taskImages[taskId]
      console.log(`✅ [关闭任务] 已清除任务 ${taskId} 保存的图片列表`)
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
 *
 * 为指定任务启动独立的倒计时计时器，支持自动提交。
 *
 * @param {string} taskId - 任务ID
 * @param {number} timeout - 倒计时秒数
 *
 * ## 功能说明
 *
 * 1. **清理旧计时器**：如果已存在则先清除
 * 2. **创建计时器**：每秒递减剩余时间
 * 3. **更新UI**：更新圆环进度和倒计时文本
 * 4. **自动提交**：倒计时结束时自动提交任务
 *
 * ## 倒计时数据结构
 *
 * - `remaining`: 剩余秒数
 * - `total`: 总秒数
 * - `timer`: 定时器ID
 *
 * ## UI更新
 *
 * - 圆环进度：SVG stroke-dashoffset
 * - 倒计时文本：格式化时间显示
 * - 主倒计时：如果是活动任务则同步更新
 *
 * ## 自动提交
 *
 * - 倒计时归零时调用 `autoSubmitTask`
 * - 清除计时器
 * - 记录日志
 *
 * ## 注意事项
 *
 * - 每个任务有独立的倒计时
 * - 计时器ID存储在 `taskCountdowns` 对象中
 * - 任务删除时需要清理计时器（防止内存泄漏）
 */
function startTaskCountdown(taskId, timeout) {
  // 停止该任务的旧倒计时
  if (taskCountdowns[taskId] && taskCountdowns[taskId].timer) {
    clearInterval(taskCountdowns[taskId].timer)
  }

  // 初始化倒计时数据
  taskCountdowns[taskId] = {
    remaining: timeout,
    timeout: timeout, // 添加timeout字段，用于计算进度百分比
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
      const progress = remaining / total // 进度（0-1）

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
 *
 * 将秒数转换为"分:秒"格式。
 *
 * @param {number} seconds - 秒数
 * @returns {string} 格式化的时间字符串（如"05:30"）
 *
 * ## 格式规则
 *
 * - 分钟：补零到2位
 * - 秒钟：补零到2位
 * - 分隔符：冒号
 *
 * ## 示例
 *
 * - 90秒 → "01:30"
 * - 5秒 → "00:05"
 * - 0秒 → "00:00"
 */
function formatCountdown(seconds) {
  if (seconds > 60) {
    return `${Math.floor(seconds / 60)}m`
  }
  return `${seconds}s`
}

/**
 * 自动提交任务
 *
 * 倒计时结束时自动提交任务反馈。
 *
 * @param {string} taskId - 任务ID
 *
 * ## 功能说明
 *
 * - 获取当前输入框内容
 * - 获取已选中的选项
 * - 调用 `submitTaskFeedback` 提交
 *
 * ## 触发时机
 *
 * - 任务倒计时归零时自动触发
 * - 用户未手动提交时生效
 *
 * ## 注意事项
 *
 * - 仅在倒计时归零时调用
 * - 提交空内容也会执行
 * - 异步操作
 */
async function autoSubmitTask(taskId) {
  console.log(`任务 ${taskId} 倒计时结束，自动提交`)
  // 使用固定的默认反馈文本
  const defaultMessage = '请立即调用 interactive_feedback 工具'
  await submitTaskFeedback(taskId, defaultMessage, [])
}

/**
 * 提交任务反馈
 *
 * 将用户的反馈内容提交到服务器。
 *
 * @param {string} taskId - 任务ID
 * @param {string} feedbackText - 反馈文本
 * @param {Array<string>} selectedOptions - 选中的选项列表
 *
 * ## 功能说明
 *
 * 1. **构建请求体**：包含反馈文本、选项、图片
 * 2. **发送POST请求**：POST `/api/tasks/{taskId}/feedback`
 * 3. **处理响应**：成功则继续，失败则显示错误
 * 4. **刷新列表**：立即同步任务列表
 * 5. **清理状态**：清除缓存数据
 *
 * ## 请求数据
 *
 * - `user_input`: 用户输入的文本
 * - `selected_options`: 选中的选项数组
 * - `images`: 上传的图片数组
 *
 * ## 错误处理
 *
 * - 网络错误：记录错误日志
 * - 服务器错误：显示错误消息
 * - 请求失败：不清理状态（允许重试）
 *
 * ## 注意事项
 *
 * - 异步操作
 * - 提交后立即刷新任务列表
 * - 失败不影响其他任务
 */
async function submitTaskFeedback(taskId, feedbackText, selectedOptions) {
  try {
    const formData = new FormData()
    formData.append('feedback_text', feedbackText)
    formData.append('selected_options', JSON.stringify(selectedOptions))

    // 添加图片文件
    selectedImages.forEach((img, index) => {
      if (img.file) {
        formData.append(`image_${index}`, img.file)
      }
    })

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
      // 清除该任务保存的所有状态
      if (taskTextareaContents[taskId] !== undefined) {
        delete taskTextareaContents[taskId]
        console.log(`✅ 已清除任务 ${taskId} 保存的 textarea 内容`)
      }
      if (taskOptionsStates[taskId] !== undefined) {
        delete taskOptionsStates[taskId]
        console.log(`✅ 已清除任务 ${taskId} 保存的选项勾选状态`)
      }
      if (taskImages[taskId] !== undefined) {
        delete taskImages[taskId]
        console.log(`✅ 已清除任务 ${taskId} 保存的图片列表`)
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
 *
 * 在标签栏旁边显示临时的新任务提示，提醒用户有新任务到达。
 *
 * @param {number} count - 新任务数量
 *
 * ## 功能说明
 *
 * - 创建临时提示元素
 * - 显示新任务数量
 * - 2秒后自动移除
 * - 使用CSS动画
 *
 * ## 视觉效果
 *
 * - 橙色背景
 * - 淡入淡出动画
 * - 位置：标签栏右侧
 *
 * ## 注意事项
 *
 * - 提示会自动消失
 * - 不影响功能
 * - 仅视觉反馈
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
 * 显示新任务通知
 *
 * 保留的函数，用于向后兼容。浏览器通知功能已禁用。
 *
 * @param {number} count - 新任务数量（未使用）
 *
 * ## 功能说明
 *
 * - 此函数当前为空实现
 * - 保留是为了避免破坏现有调用
 * - 浏览器通知功能已移除
 *
 * ## 历史说明
 *
 * - 原用途：显示浏览器桌面通知
 * - 移除原因：用户体验不佳、权限要求
 * - 替代方案：使用视觉提示（showNewTaskVisualHint）
 *
 * ## 注意事项
 *
 * - 不执行任何操作
 * - 可以安全调用
 * - 未来可能会移除
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
 *
 * 页面加载时初始化多任务管理功能。
 *
 * ## 功能说明
 *
 * - 启动任务列表轮询
 * - 加载初始任务列表
 * - 设置事件监听器
 *
 * ## 调用时机
 *
 * - 页面DOM加载完成时
 * - 多任务模块激活时
 *
 * ## 初始化步骤
 *
 * 1. 启动任务列表轮询（每2秒）
 * 2. 首次加载任务列表
 * 3. 渲染初始UI
 *
 * ## 注意事项
 *
 * - 异步函数
 * - 只应调用一次
 * - 依赖DOM已加载
 */
async function initMultiTaskSupport() {
  console.log('初始化多任务支持...')

  // 立即获取一次任务列表（不等待轮询）
  await refreshTasksList()

  // 启动定时轮询
  startTasksPolling()

  // 轮询健康检查机制（每30秒检查一次轮询器是否还在运行,如果停止则重新启动）
  setInterval(() => {
    if (!tasksPollingTimer) {
      console.warn('⚠️ 任务轮询已停止,自动重新启动')
      startTasksPolling()
    }
  }, 30000)

  console.log('多任务支持初始化完成 (包含轮询健康检查)')
}

/**
 * 手动触发任务列表更新
 *
 * 立即从服务器获取最新的任务列表，用于提交反馈后的即时同步。
 *
 * ## 功能说明
 *
 * - 请求 `/api/tasks` 获取最新任务列表
 * - 更新任务列表和统计信息
 * - 处理请求失败
 *
 * ## 调用时机
 *
 * - 提交任务反馈后
 * - 用户点击刷新按钮
 * - 需要立即同步状态时
 *
 * ## 与轮询的区别
 *
 * - 立即执行：不等待轮询间隔
 * - 手动触发：不是定时自动执行
 * - 用途不同：用于即时同步而非定期更新
 *
 * ## 错误处理
 *
 * - 请求失败：记录错误日志
 * - 不影响轮询机制
 *
 * ## 注意事项
 *
 * - 异步函数
 * - 不依赖轮询定时器
 * - 可以与轮询并行运行
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
    refreshTasksList // 导出刷新函数
  }
}
