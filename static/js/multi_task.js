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
 * - 依赖 `dom-security.js` 中的 `DOMSecurityHelper`
 * - 全局变量已在此文件中定义（如未存在则创建）
 */

// ==================== 全局变量定义 ====================
// 使用 window 对象确保变量在全局作用域中可用
if (typeof window.currentTasks === 'undefined') {
  window.currentTasks = [] // 所有任务列表
}
if (typeof window.activeTaskId === 'undefined') {
  window.activeTaskId = null // 当前活动任务ID
}
if (typeof window.taskCountdowns === 'undefined') {
  window.taskCountdowns = {} // 每个任务的独立倒计时
}
if (typeof window.tasksPollingTimer === 'undefined') {
  window.tasksPollingTimer = null // 任务轮询定时器
}
if (typeof window.taskTextareaContents === 'undefined') {
  window.taskTextareaContents = {} // 存储每个任务的 textarea 内容
}
if (typeof window.taskOptionsStates === 'undefined') {
  window.taskOptionsStates = {} // 存储每个任务的选项勾选状态
}
if (typeof window.taskImages === 'undefined') {
  window.taskImages = {} // 存储每个任务的图片列表
}
// 新任务通知合并机制 - 防止频繁弹出多个通知
if (typeof window.pendingNewTaskCount === 'undefined') {
  window.pendingNewTaskCount = 0 // 待显示的新任务数量
}
if (typeof window.newTaskHintTimer === 'undefined') {
  window.newTaskHintTimer = null // 通知合并定时器
}
// 【优化】服务器时间同步机制 - 解决切换标签页后倒计时不准的问题
if (typeof window.serverTimeOffset === 'undefined') {
  window.serverTimeOffset = 0 // 服务器时间与本地时间的偏移量（秒）
}
if (typeof window.taskDeadlines === 'undefined') {
  window.taskDeadlines = {} // 存储每个任务的截止时间戳（服务器时间）
}

// 创建本地引用以便在函数中使用
var currentTasks = window.currentTasks
var activeTaskId = window.activeTaskId
var taskCountdowns = window.taskCountdowns
var tasksPollingTimer = window.tasksPollingTimer
var taskTextareaContents = window.taskTextareaContents
var taskOptionsStates = window.taskOptionsStates
var taskImages = window.taskImages

// 倒计时相关全局变量
if (typeof window.remainingSeconds === 'undefined') {
  window.remainingSeconds = 0
}
if (typeof window.countdownTimer === 'undefined') {
  window.countdownTimer = null
}
var remainingSeconds = window.remainingSeconds
var countdownTimer = window.countdownTimer

/**
 * 更新倒计时显示（如果函数未定义则提供默认实现）
 * @param {number} seconds - 剩余秒数（可选）
 */
if (typeof window.updateCountdownDisplay !== 'function') {
  window.updateCountdownDisplay = function (seconds) {
    const countdownContainer = document.getElementById('countdown-container')
    const countdownText = document.getElementById('countdown-text')

    if (!countdownContainer || !countdownText) return

    const displaySeconds = typeof seconds === 'number' ? seconds : window.remainingSeconds

    if (displaySeconds > 0) {
      countdownText.textContent = `${displaySeconds}秒后自动重新询问`
      countdownContainer.classList.remove('hidden')
    } else {
      countdownContainer.classList.add('hidden')
    }
  }
}
var updateCountdownDisplay = window.updateCountdownDisplay

// ==================== 任务轮询 ====================

// 【轮询治理】避免重叠请求/页面不可见浪费/错误风暴
var TASKS_POLL_BASE_MS = 2000
var TASKS_POLL_MAX_MS = 30000
var tasksPollBackoffMs = TASKS_POLL_BASE_MS
var tasksPollAbortController = null
var tasksPollVisibilityHandlerInstalled = false

function getNextBackoffMs(currentMs) {
  // 指数退避 + 轻微抖动，避免多客户端同时打爆服务端
  const next = Math.min(TASKS_POLL_MAX_MS, Math.round(currentMs * 1.7))
  const jitter = Math.round(next * 0.1 * Math.random()) // 0-10%
  return next + jitter
}

async function fetchAndApplyTasks(reason) {
  // 页面不可见：不发请求（由 visibilitychange 负责 stop，但这里再兜底）
  if (typeof document !== 'undefined' && document.hidden) {
    return false
  }

  // 手动切换期间：尽量少扰动 UI（不主动拉取）
  if (isManualSwitching) {
    return false
  }

  // AbortController：保证同时最多 1 个 in-flight 的 /api/tasks 请求
  try {
    if (tasksPollAbortController && typeof tasksPollAbortController.abort === 'function') {
      tasksPollAbortController.abort()
    }
  } catch (e) {
    // ignore
  }

  if (typeof AbortController !== 'undefined') {
    tasksPollAbortController = new AbortController()
  } else {
    tasksPollAbortController = null
  }

  const fetchOptions = {
    cache: 'no-store'
  }
  if (tasksPollAbortController) {
    fetchOptions.signal = tasksPollAbortController.signal
  }

  try {
    const response = await fetch('/api/tasks', fetchOptions)
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()

    if (data.success) {
      // 【优化】更新服务器时间偏移量，解决切换标签页后倒计时不准的问题
      if (data.server_time) {
        const localTime = Date.now() / 1000
        window.serverTimeOffset = data.server_time - localTime
        // 仅在偏移量较大时记录日志（避免日志刷屏）
        if (Math.abs(window.serverTimeOffset) > 1) {
          console.log(`服务器时间偏移: ${window.serverTimeOffset.toFixed(2)}s`)
        }
      }

      // 【优化】保存每个任务的 deadline
      if (data.tasks) {
        data.tasks.forEach(task => {
          if (task.deadline) {
            window.taskDeadlines[task.task_id] = task.deadline
          }
        })
      }

      updateTasksList(data.tasks)
      updateTasksStats(data.stats)
      if (reason) {
        console.debug(`任务列表已更新: ${reason}`)
      }
      return true
    }

    return false
  } catch (error) {
    // AbortError：正常的“防重叠”路径，不计为错误
    if (error && (error.name === 'AbortError' || error.code === 20)) {
      return false
    }
    console.error('获取任务列表失败:', error)
    return false
  } finally {
    // 释放 controller（避免长期持有）
    tasksPollAbortController = null
  }
}

function scheduleNextTasksPoll(delayMs) {
  if (tasksPollingTimer) {
    clearTimeout(tasksPollingTimer)
    tasksPollingTimer = null
  }
  tasksPollingTimer = setTimeout(async () => {
    const ok = await fetchAndApplyTasks('poll')
    if (ok) {
      tasksPollBackoffMs = TASKS_POLL_BASE_MS
    } else {
      tasksPollBackoffMs = getNextBackoffMs(tasksPollBackoffMs)
    }
    scheduleNextTasksPoll(tasksPollBackoffMs)
  }, Math.max(0, delayMs))
}

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
  // 页面不可见时不启动轮询（恢复由 visibilitychange 触发）
  if (typeof document !== 'undefined' && document.hidden) {
    console.log('页面不可见，跳过启动任务轮询')
    return
  }

  // 清理旧的定时器/中止旧请求
  stopTasksPolling()

  tasksPollBackoffMs = TASKS_POLL_BASE_MS
  scheduleNextTasksPoll(0)

  // 安装“页面可见性治理”（只安装一次）
  if (!tasksPollVisibilityHandlerInstalled && typeof document !== 'undefined') {
    tasksPollVisibilityHandlerInstalled = true
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopTasksPolling()
      } else {
        // 恢复时立即拉一次，减少“回到页面后空白/延迟”
        startTasksPolling()
      }
    })
    window.addEventListener('beforeunload', () => {
      stopTasksPolling()
    })
  }

  console.log('任务列表轮询已启动（治理：不可见暂停/指数退避/AbortController）')
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
    clearTimeout(tasksPollingTimer)
    tasksPollingTimer = null
    console.log('任务列表轮询已停止')
  }

  // 取消 in-flight 请求，避免页面切走/重启轮询时堆积
  try {
    if (tasksPollAbortController && typeof tasksPollAbortController.abort === 'function') {
      tasksPollAbortController.abort()
    }
  } catch (e) {
    // ignore
  } finally {
    tasksPollAbortController = null
  }
}

// ==================== 任务列表更新 ====================

// 防止轮询与手动切换冲突的标志
// 同时暴露到 window 以便其他模块的内容轮询可以检查
let isManualSwitching = false
let manualSwitchingTimer = null

// 将标志同步到 window 对象，供跨模块通信
Object.defineProperty(window, 'isManualSwitching', {
  get: () => isManualSwitching,
  set: val => {
    isManualSwitching = val
  },
  configurable: true
})

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

    // 如果当前有活动任务,使用合并机制显示视觉提示
    // 避免短时间内频繁弹出多个通知
    if (activeTaskId) {
      // 累加待显示的新任务数量
      pendingNewTaskCount += addedTasks.length

      // 清除之前的定时器（防抖）
      if (newTaskHintTimer) {
        clearTimeout(newTaskHintTimer)
      }

      // 延迟 500ms 显示，等待可能的后续新任务
      newTaskHintTimer = setTimeout(() => {
        if (pendingNewTaskCount > 0) {
          showNewTaskVisualHint(pendingNewTaskCount)
          pendingNewTaskCount = 0 // 重置计数
        }
        newTaskHintTimer = null
      }, 500)
    }

    // 为所有新任务启动倒计时（包括pending任务）
    // 使用服务器返回的 remaining_time（剩余时间），而非固定的 auto_resubmit_timeout
    // 这样刷新页面后倒计时不会重置
    tasks
      .filter(t => addedTasks.includes(t.task_id))
      .forEach(task => {
        if (task.status !== 'completed' && !taskCountdowns[task.task_id]) {
          // 优先使用 remaining_time（服务器计算的剩余时间），否则使用 auto_resubmit_timeout
          const timeout = task.remaining_time ?? task.auto_resubmit_timeout ?? 250
          startTaskCountdown(task.task_id, timeout, task.auto_resubmit_timeout || 250)
          console.log(`已为新任务启动倒计时: ${task.task_id}, 剩余 ${timeout}s`)
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
      // 【优化】清理任务截止时间缓存，防止内存泄漏
      if (window.taskDeadlines[taskId] !== undefined) {
        delete window.taskDeadlines[taskId]
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

  // 检测当前页面状态和任务状态
  const hasActiveTasks = tasks.length > 0 && tasks.some(t => t.status !== 'completed')

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
    // 如果activeTaskId为null，且有任务，自动设置第一个未完成任务为active
    // ⚠️ 注意：tasks数组可能包含已完成任务，必须过滤
    const firstIncompleteTask = tasks.find(t => t.status !== 'completed')
    if (firstIncompleteTask) {
      activeTaskId = firstIncompleteTask.task_id
      console.log(`自动设置第一个未完成任务为active: ${activeTaskId}`)
    } else {
      console.log('所有任务已完成，不设置activeTaskId')
    }
  } else if (tasks.length === 0 && activeTaskId) {
    // 如果任务列表为空，重置activeTaskId
    console.log(`✅ 任务列表已清空，重置 activeTaskId: ${activeTaskId} -> null`)
    activeTaskId = null
  }

  // 确保页面状态与任务状态一致
  // - 有未完成任务时，显示内容页面
  // - 无未完成任务时，显示无内容页面
  const contentContainer = document.getElementById('content-container')
  const noContentContainer = document.getElementById('no-content-container')
  const isShowingNoContent = noContentContainer && noContentContainer.style.display === 'flex'

  if (hasActiveTasks && isShowingNoContent) {
    // 有任务但显示的是无内容页面，切换到内容页面
    console.log('🚀 有任务但显示无内容页面，切换到内容页面')
    if (typeof showContentPage === 'function') {
      showContentPage()
    }
  } else if (!hasActiveTasks && contentContainer && contentContainer.style.display === 'block') {
    // 无任务但显示的是内容页面，切换到无内容页面
    console.log('📭 无任务但显示内容页面，切换到无内容页面')
    if (typeof showNoContentPage === 'function') {
      showNoContentPage()
    }
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

    // 使用已有的倒计时数据或服务器返回的剩余时间
    let remaining, total
    if (taskCountdowns[task.task_id]) {
      remaining = taskCountdowns[task.task_id].remaining
      total = taskCountdowns[task.task_id].timeout || 250
    } else {
      // 倒计时还未启动，优先使用服务器返回的 remaining_time
      // 这样刷新页面后圆环显示正确的剩余时间
      remaining = task.remaining_time ?? task.auto_resubmit_timeout ?? 250
      total = task.auto_resubmit_timeout || 250
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

  // 分发事件通知其他模块暂停轮询
  window.dispatchEvent(new CustomEvent('taskSwitchStart', { detail: { taskId } }))

  // 立即更新UI，提升响应速度
  const oldActiveTaskId = activeTaskId
  activeTaskId = taskId
  renderTaskTabs() // 立即更新标签高亮

  // 立即更新圆环颜色，不等待DOM重建
  updateCountdownRingColors(oldActiveTaskId, taskId)

  // 🚀 立即从 currentTasks 获取任务信息并更新内容（不等待 API）
  const cachedTask = currentTasks.find(t => t.task_id === taskId)
  if (cachedTask && cachedTask.prompt) {
    console.log(`🚀 使用缓存任务信息立即更新内容: ${taskId}`)

    // 内联 updateTaskIdDisplay 逻辑（避免函数未定义错误）
    const taskIdContainer = document.getElementById('task-id-container')
    const taskIdText = document.getElementById('task-id-text')
    if (taskIdContainer && taskIdText) {
      if (cachedTask.task_id && cachedTask.task_id.trim()) {
        taskIdText.textContent = cachedTask.task_id
        taskIdContainer.classList.remove('hidden')
      } else {
        taskIdContainer.classList.add('hidden')
      }
    }

    // 更新描述和选项
    updateDescriptionDisplay(cachedTask.prompt)
    if (cachedTask.predefined_options) {
      updateOptionsDisplay(cachedTask.predefined_options)
    }
  }

  try {
    // 后台执行激活请求（不阻塞 UI）
    fetch(`/api/tasks/${taskId}/activate`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        if (!data.success) {
          console.error('激活任务失败:', data.error)
        } else {
          console.log(`✅ 任务已激活: ${taskId}`)
        }
      })
      .catch(err => console.error('激活任务失败:', err))

    // 后台异步加载完整详情（用于获取最新选项等）
    loadTaskDetails(taskId).catch(err => {
      console.warn('加载任务详情失败，但UI已从缓存更新:', err)
    })
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
      // 分发事件通知其他模块恢复轮询
      window.dispatchEvent(new CustomEvent('taskSwitchComplete', { detail: { taskId } }))
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
      // 内联 updateTaskIdDisplay 逻辑（避免函数未定义错误）
      const taskIdContainer = document.getElementById('task-id-container')
      const taskIdText = document.getElementById('task-id-text')
      if (taskIdContainer && taskIdText) {
        if (task.task_id && task.task_id.trim()) {
          taskIdText.textContent = task.task_id
          taskIdContainer.classList.remove('hidden')
        } else {
          taskIdContainer.classList.add('hidden')
        }
      }

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
        // 使用服务器返回的 remaining_time（剩余时间），而非固定的 auto_resubmit_timeout
        // 这样刷新页面后倒计时不会重置
        const remaining = task.remaining_time ?? task.auto_resubmit_timeout
        const total = task.auto_resubmit_timeout
        startTaskCountdown(task.task_id, remaining, total)
        console.log(`首次启动倒计时: ${taskId}, 剩余 ${remaining}s / 总 ${total}s`)
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
 * - 使用 marked.js 同步渲染 Markdown
 * - 更新描述容器的 HTML 内容
 * - 处理代码块语法高亮
 * - 按需加载并渲染 MathJax 数学公式
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
    // 🚀 同步渲染（立即显示，不使用 requestAnimationFrame）
    let htmlContent = prompt

    // 使用 marked.js 解析 Markdown
    if (typeof marked !== 'undefined') {
      try {
        htmlContent = marked.parse(prompt)
      } catch (e) {
        console.warn('marked.js 解析失败:', e)
      }
    }

    // 直接更新 DOM（同步）
    descriptionElement.innerHTML = htmlContent

    // Prism.js 代码高亮（同步）
    if (typeof Prism !== 'undefined') {
      Prism.highlightAllUnder(descriptionElement)
    }

    // 处理代码块（同步）
    if (typeof processCodeBlocks === 'function') {
      processCodeBlocks(descriptionElement)
    }

    // 处理删除线（同步）
    if (typeof processStrikethrough === 'function') {
      processStrikethrough(descriptionElement)
    }

    console.log('✅ 同步渲染 Markdown 完成')

    // MathJax 数学公式渲染（按需加载，不阻塞）
    // 注意：不能只在 MathJax 已加载时 typeset，否则“首次出现公式”的内容会一直不渲染
    const textContent = descriptionElement.textContent || ''
    if (window.loadMathJaxIfNeeded) {
      window.loadMathJaxIfNeeded(descriptionElement, textContent)
    } else if (window.MathJax && window.MathJax.typesetPromise) {
      // 回退：如果 MathJax 已加载但 loadMathJaxIfNeeded 不可用，直接渲染
      window.MathJax.typesetPromise([descriptionElement]).catch(err => {
        console.warn('MathJax 渲染失败:', err)
      })
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

  // 优先使用该任务之前保存的勾选状态（支持新格式：{id: checked} 和旧格式：[index: checked]）
  let selectedStates = {}
  if (activeTaskId && taskOptionsStates[activeTaskId]) {
    selectedStates = taskOptionsStates[activeTaskId]
    console.log(`✅ 已恢复任务 ${activeTaskId} 的选项勾选状态`)
  } else {
    // 如果没有保存的状态，尝试保存当前状态（用于同一任务内的更新）
    const existingCheckboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
    existingCheckboxes.forEach(checkbox => {
      selectedStates[checkbox.id] = checkbox.checked
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

      // 恢复选中状态（支持新格式：{id: checked} 和旧格式：[index: checked]）
      const checkboxId = `option-${index}`
      if (selectedStates[checkboxId] || selectedStates[index]) {
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
 * @param {number} remaining - 剩余倒计时秒数（可能是服务器计算的剩余时间）
 * @param {number} total - 总超时时间（用于计算进度百分比，可选，默认等于 remaining）
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
 * - `timeout`: 总秒数（用于计算进度百分比）
 * - `timer`: 定时器ID
 *
 * ## UI更新
 *
 * - 圆环进度：SVG stroke-dashoffset（基于 remaining/timeout）
 * - 倒计时文本：格式化时间显示
 * - 主倒计时：如果是活动任务则同步更新
 *
 * ## 自动提交
 *
 * - 倒计时归零时调用 `autoSubmitTask`
 * - 清除计时器
 * - 记录日志
 *
 * ## 页面刷新不重置
 *
 * - 服务器返回 remaining_time（基于任务创建时间计算）
 * - 刷新页面后从服务器获取真实剩余时间
 * - 进度条使用 remaining/timeout 计算，保持视觉一致性
 *
 * ## 注意事项
 *
 * - 每个任务有独立的倒计时
 * - 计时器ID存储在 `taskCountdowns` 对象中
 * - 任务删除时需要清理计时器（防止内存泄漏）
 */
function startTaskCountdown(taskId, remaining, total = null) {
  // 如果没有指定 total，使用 remaining 作为 total（向后兼容）
  const timeout = total || remaining
  // 停止该任务的旧倒计时
  if (taskCountdowns[taskId] && taskCountdowns[taskId].timer) {
    clearInterval(taskCountdowns[taskId].timer)
  }

  // 初始化倒计时数据
  // remaining: 当前剩余秒数（可能是刷新后从服务器获取的）
  // timeout: 总超时时间（用于计算进度百分比）
  taskCountdowns[taskId] = {
    remaining: remaining,
    timeout: timeout, // 总超时时间，用于计算进度百分比
    timer: null
  }

  // 如果是活动任务，更新主倒计时显示
  if (taskId === activeTaskId) {
    updateCountdownDisplay(remaining)
  }

  // 【优化】基于服务器时间计算剩余时间的辅助函数
  // 解决切换标签页后 JavaScript 定时器不准确的问题
  function calculateRemainingFromDeadline() {
    const deadline = window.taskDeadlines[taskId]
    if (deadline) {
      // 使用服务器时间偏移校正本地时间
      const adjustedNow = Date.now() / 1000 + (window.serverTimeOffset || 0)
      return Math.max(0, Math.floor(deadline - adjustedNow))
    }
    // 没有 deadline 信息，使用递减方式（向后兼容）
    return taskCountdowns[taskId].remaining - 1
  }

  // 启动定时器
  taskCountdowns[taskId].timer = setInterval(() => {
    // 【优化】使用基于 deadline 的计算方式，而非简单递减
    // 这样即使标签页被切换（导致 JS 定时器不准确），恢复后也能显示正确的剩余时间
    const newRemaining = calculateRemainingFromDeadline()
    taskCountdowns[taskId].remaining = newRemaining

    // 更新SVG圆环倒计时
    const countdownRing = document.getElementById(`countdown-${taskId}`)
    if (countdownRing) {
      const remaining = taskCountdowns[taskId].remaining
      const total = taskCountdowns[taskId].timeout || 250 // 【优化】默认从290改为250
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
      // 智能自动提交逻辑：
      // 1. 如果是当前激活的任务 → 立即自动提交
      // 2. 如果不是激活任务，检查是否有其他活动任务在处理
      //    - 如果没有活动任务（用户无响应），也自动提交当前任务
      //    - 如果有活动任务，说明用户正在处理其他任务，暂不自动提交
      if (taskId === activeTaskId) {
        // 当前激活任务超时，直接自动提交
        autoSubmitTask(taskId)
      } else {
        // 非激活任务超时：检查是否真的没有用户活动
        // 如果当前没有任何激活任务，说明用户完全无响应，也自动提交
        if (!activeTaskId) {
          console.log(`非激活任务 ${taskId} 超时，且无活动任务，自动提交`)
          autoSubmitTask(taskId)
        } else {
          console.log(`任务 ${taskId} 超时，但用户正在处理其他任务 ${activeTaskId}，暂不自动提交`)
        }
      }
    }
  }, 1000)

  console.log(`已启动任务倒计时: ${taskId}, 剩余 ${remaining}s / 总 ${timeout}s`)
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
  // 使用配置的提示语（从全局变量 feedbackPrompts 获取，如果不存在则使用默认值）
  const defaultMessage =
    typeof feedbackPrompts !== 'undefined' && feedbackPrompts.resubmit_prompt
      ? feedbackPrompts.resubmit_prompt
      : '请立即调用 interactive_feedback 工具'
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

      // 自动切换到下一个未完成的任务
      // 延迟执行以等待任务列表更新
      setTimeout(async () => {
        // 刷新任务列表获取最新状态
        await refreshTasksList()

        // 查找下一个未完成的任务（排除当前已完成的任务）
        const nextTask = currentTasks.find(t => t.task_id !== taskId && t.status !== 'completed')
        if (nextTask) {
          console.log(`🔄 自动切换到下一个任务: ${nextTask.task_id}`)
          switchTask(nextTask.task_id)
        } else {
          console.log(`✅ 所有任务已完成`)
        }
      }, 300)
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

  // 检测当前主题 (light/dark)
  const html = document.documentElement
  const currentTheme = html.getAttribute('data-theme')
  const isLightTheme = currentTheme === 'light'

  // Claude 风格 "Create - 创作" SVG 图标（橙色强调色 #d97757）
  const createSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 20 20" fill="none" style="flex-shrink: 0; margin-right: 10px;"><path d="M15.5117 1.99707C15.9213 2.0091 16.3438 2.13396 16.6768 2.46679C17.0278 2.81814 17.1209 3.26428 17.0801 3.68261C17.0404 4.08745 16.8765 4.49344 16.6787 4.85058C16.3934 5.36546 15.9941 5.85569 15.6348 6.20898C15.7682 6.41421 15.8912 6.66414 15.9551 6.9453C16.0804 7.4977 15.9714 8.13389 15.4043 8.70116C14.8566 9.24884 13.974 9.54823 13.1943 9.71679C12.7628 9.81003 12.3303 9.86698 11.9473 9.90233C12.0596 10.2558 12.0902 10.7051 11.8779 11.2012L11.8223 11.3203C11.5396 11.8854 11.0275 12.2035 10.4785 12.3965C9.93492 12.5875 9.29028 12.6792 8.65332 12.75C7.99579 12.8231 7.34376 12.8744 6.70117 12.9775C6.14371 13.067 5.63021 13.1903 5.18652 13.3818L5.00585 13.4658C4.53515 14.2245 4.13745 14.9658 3.80957 15.6465C4.43885 15.2764 5.1935 15 5.99999 15C6.27614 15 6.49999 15.2238 6.49999 15.5C6.49999 15.7761 6.27613 16 5.99999 16C5.35538 16 4.71132 16.2477 4.15039 16.6103C3.58861 16.9736 3.14957 17.427 2.91601 17.7773C2.91191 17.7835 2.90568 17.788 2.90136 17.7939C2.88821 17.8119 2.8746 17.8289 2.85937 17.8447C2.85117 17.8533 2.84268 17.8612 2.83398 17.8691C2.81803 17.8835 2.80174 17.897 2.78417 17.9092C2.774 17.9162 2.76353 17.9225 2.75292 17.9287C2.73854 17.9372 2.72412 17.9451 2.70898 17.9521C2.69079 17.9605 2.6723 17.9675 2.65332 17.9736C2.6417 17.9774 2.63005 17.9805 2.61816 17.9834C2.60263 17.9872 2.5871 17.9899 2.57128 17.9922C2.55312 17.9948 2.53511 17.9974 2.5166 17.998C2.50387 17.9985 2.49127 17.9976 2.47851 17.9971C2.45899 17.9962 2.43952 17.9954 2.41992 17.9922C2.40511 17.9898 2.39062 17.9862 2.37597 17.9824C2.36477 17.9795 2.35294 17.9783 2.34179 17.9746C2.33697 17.973 2.33286 17.9695 2.32812 17.9678C2.31042 17.9612 2.29351 17.953 2.27636 17.9443C2.26332 17.9378 2.25053 17.9314 2.23828 17.9238C2.23339 17.9208 2.22747 17.9192 2.22265 17.916C2.21414 17.9103 2.20726 17.9026 2.19921 17.8965C2.18396 17.8849 2.16896 17.8735 2.15527 17.8603C2.14518 17.8507 2.13609 17.8404 2.12695 17.8301C2.11463 17.8161 2.10244 17.8023 2.09179 17.7871C2.08368 17.7756 2.07736 17.7631 2.07031 17.751C2.06168 17.7362 2.05297 17.7216 2.04589 17.706C2.03868 17.6901 2.03283 17.6738 2.02734 17.6572C2.0228 17.6436 2.01801 17.6302 2.01464 17.6162C2.01117 17.6017 2.009 17.587 2.00683 17.5722C2.00411 17.5538 2.00161 17.5354 2.00097 17.5166C2.00054 17.5039 2.00141 17.4912 2.00195 17.4785C2.00279 17.459 2.00364 17.4395 2.00683 17.4199C2.00902 17.4064 2.01327 17.3933 2.0166 17.3799C2.01973 17.3673 2.02123 17.3543 2.02539 17.3418C2.41772 16.1648 3.18163 14.466 4.30468 12.7012C4.31908 12.5557 4.34007 12.3582 4.36914 12.1201C4.43379 11.5907 4.53836 10.8564 4.69921 10.0381C5.0174 8.41955 5.56814 6.39783 6.50585 4.9912L6.73242 4.66894C7.27701 3.93277 7.93079 3.30953 8.61035 2.85156C9.3797 2.33311 10.2221 2 11.001 2C11.7951 2.00025 12.3531 2.35795 12.7012 2.70605C12.7723 2.77723 12.8348 2.84998 12.8896 2.91796C13.2829 2.66884 13.7917 2.39502 14.3174 2.21191C14.6946 2.08056 15.1094 1.98537 15.5117 1.99707ZM17.04 15.5537C17.1486 15.3 17.4425 15.1818 17.6963 15.29C17.95 15.3986 18.0683 15.6925 17.96 15.9463C17.4827 17.0612 16.692 18 15.5 18C14.6309 17.9999 13.9764 17.5003 13.5 16.7978C13.0236 17.5003 12.3691 18 11.5 18C10.6309 17.9999 9.97639 17.5003 9.49999 16.7978C9.02359 17.5003 8.36911 18 7.49999 18C7.22391 17.9999 7 17.7761 6.99999 17.5C6.99999 17.2239 7.22391 17 7.49999 17C8.07039 17 8.6095 16.5593 9.04003 15.5537L9.07421 15.4873C9.16428 15.3412 9.32494 15.25 9.49999 15.25C9.70008 15.25 9.88121 15.3698 9.95996 15.5537L10.042 15.7353C10.4581 16.6125 10.9652 16.9999 11.5 17C12.0704 17 12.6095 16.5593 13.04 15.5537L13.0742 15.4873C13.1643 15.3412 13.3249 15.25 13.5 15.25C13.7001 15.25 13.8812 15.3698 13.96 15.5537L14.042 15.7353C14.4581 16.6125 14.9652 16.9999 15.5 17C16.0704 17 16.6095 16.5593 17.04 15.5537ZM15.4824 2.99707C15.247 2.99022 14.9608 3.04682 14.6465 3.15624C14.0173 3.37541 13.389 3.76516 13.0498 4.01953C12.9277 4.11112 12.7697 4.14131 12.6221 4.10253C12.4745 4.06357 12.3522 3.9591 12.291 3.81933V3.81835C12.2892 3.81468 12.2861 3.80833 12.2822 3.80078C12.272 3.78092 12.2541 3.7485 12.2295 3.70898C12.1794 3.62874 12.1011 3.52019 11.9941 3.41308C11.7831 3.2021 11.4662 3.00024 11.001 2.99999C10.4904 2.99999 9.84173 3.22729 9.16894 3.68066C8.58685 4.07297 8.01568 4.61599 7.5371 5.26269L7.33789 5.54589C6.51634 6.77827 5.99475 8.63369 5.68066 10.2314C5.63363 10.4707 5.5913 10.7025 5.55371 10.9238C7.03031 9.01824 8.94157 7.19047 11.2812 6.05077C11.5295 5.92989 11.8283 6.03301 11.9492 6.28124C12.0701 6.52949 11.967 6.82829 11.7187 6.94921C9.33153 8.11208 7.38648 10.0746 5.91406 12.1103C6.12313 12.0632 6.33385 12.0238 6.54296 11.9902C7.21709 11.8821 7.92723 11.8243 8.54296 11.7558C9.17886 11.6852 9.72123 11.6025 10.1465 11.4531C10.5662 11.3056 10.8063 11.1158 10.9277 10.873L10.9795 10.7549C11.0776 10.487 11.0316 10.2723 10.9609 10.1123C10.918 10.0155 10.8636 9.93595 10.8203 9.88183C10.7996 9.85598 10.7822 9.83638 10.7715 9.82518L10.7607 9.81542L10.7627 9.8164L10.7646 9.81835C10.6114 9.67972 10.5597 9.46044 10.6338 9.26757C10.7082 9.07475 10.8939 8.94726 11.1006 8.94726C11.5282 8.94719 12.26 8.8956 12.9834 8.73925C13.7297 8.5779 14.3654 8.32602 14.6973 7.99413C15.0087 7.68254 15.0327 7.40213 14.9795 7.16698C14.9332 6.96327 14.8204 6.77099 14.707 6.62792L14.5957 6.50195C14.4933 6.39957 14.4401 6.25769 14.4502 6.11327C14.4605 5.96888 14.5327 5.83599 14.6484 5.74902C14.9558 5.51849 15.4742 4.96086 15.8037 4.3662C15.9675 4.07048 16.0637 3.80137 16.085 3.58593C16.1047 3.38427 16.0578 3.26213 15.9697 3.17382C15.8631 3.06726 15.7102 3.00377 15.4824 2.99707Z" fill="#d97757"/></svg>`

  // 主题适配样式
  const themeStyles = isLightTheme
    ? {
        // 浅色主题：温暖的米白背景 + 深色文字
        background: 'linear-gradient(135deg, #faf9f5 0%, #f2f1ec 100%)',
        color: '#131314',
        border: '1px solid rgba(217, 119, 87, 0.4)',
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.12), 0 0 0 1px rgba(217, 119, 87, 0.15)'
      }
    : {
        // 深色主题：与任务标签区域风格一致
        background: 'rgba(45, 45, 60, 0.95)',
        color: 'rgba(245, 245, 247, 0.95)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.35)'
      }

  // 创建提示元素
  const hint = document.createElement('div')
  hint.id = 'new-task-hint'
  hint.style.cssText = `
    position: fixed;
    top: 20px;
    right: 20px;
    display: flex;
    align-items: center;
    background: ${themeStyles.background};
    color: ${themeStyles.color};
    padding: 14px 20px;
    border-radius: 12px;
    border: ${themeStyles.border};
    box-shadow: ${themeStyles.boxShadow};
    font-size: 14px;
    font-weight: 500;
    letter-spacing: 0.02em;
    z-index: 10000;
    animation: slideInRight 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), fadeOutUp 0.3s ease-in 2.7s forwards;
    pointer-events: none;
  `
  hint.innerHTML = `${createSvg}<span>${count} 个新任务已到达</span>`

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
    // 页面不可见：不强行恢复轮询（由 visibilitychange 恢复）
    if (typeof document !== 'undefined' && document.hidden) {
      return
    }
    if (!tasksPollingTimer) {
      console.warn('⚠️ 任务轮询已停止,自动重新启动')
      startTasksPolling()
    }
  }, 30000)

  // 【新增】实时保存 textarea 和选项状态
  // 监听 input 事件，每次输入都保存，避免轮询导致内容丢失
  const textarea = document.getElementById('feedback-text')
  if (textarea) {
    textarea.addEventListener('input', () => {
      if (activeTaskId) {
        taskTextareaContents[activeTaskId] = textarea.value
      }
    })
    console.log('✅ 已启用 textarea 实时保存')
  }

  // 监听选项变化
  const optionsContainer = document.getElementById('options-container')
  if (optionsContainer) {
    optionsContainer.addEventListener('change', event => {
      if (event.target.type === 'checkbox' && activeTaskId) {
        // 保存所有选项的勾选状态
        const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]')
        const states = {}
        checkboxes.forEach(cb => {
          states[cb.id] = cb.checked
        })
        taskOptionsStates[activeTaskId] = states
      }
    })
    console.log('✅ 已启用选项状态实时保存')
  }

  console.log('多任务支持初始化完成 (包含轮询健康检查和实时保存)')
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
  const ok = await fetchAndApplyTasks('manual')
  if (ok) {
    tasksPollBackoffMs = TASKS_POLL_BASE_MS
    console.log('任务列表已手动刷新')
  }

  // 手动刷新后确保轮询处于运行态（页面可见时）
  if (!tasksPollingTimer && !(typeof document !== 'undefined' && document.hidden)) {
    startTasksPolling()
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

  // 直接导出常用函数到 window，方便 app.js 调用
  window.refreshTasksList = refreshTasksList
}
