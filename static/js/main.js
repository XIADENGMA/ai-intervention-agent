let config = null

// 反馈提示语配置（从 API 获取，支持自定义）
let feedbackPrompts = {
  resubmit_prompt: '请立即调用 interactive_feedback 工具',  // 默认值
  prompt_suffix: '\n请积极调用 interactive_feedback 工具'   // 默认值
}

/**
 * 加载反馈提示语配置
 * 从 /api/get-feedback-prompts 获取配置的提示语
 * 用于自动提交时使用配置的默认消息
 */
async function loadFeedbackPrompts() {
  try {
    const response = await fetch('/api/get-feedback-prompts')
    if (response.ok) {
      const data = await response.json()
      if (data.status === 'success' && data.config) {
        feedbackPrompts = {
          resubmit_prompt: data.config.resubmit_prompt || feedbackPrompts.resubmit_prompt,
          prompt_suffix: data.config.prompt_suffix || feedbackPrompts.prompt_suffix
        }
        console.log('反馈提示语配置已加载')
      }
    }
  } catch (error) {
    console.warn('加载反馈提示语配置失败，使用默认值:', error)
  }
}

/**
 * 初始化 marked.js 配置
 * 配置 GFM、表格、代码高亮等功能
 * 兼容 marked.js v5+ API
 */
function initMarkedConfig() {
  if (typeof marked === 'undefined') {
    console.warn('marked.js 未加载，将使用服务端渲染的 HTML')
    return false
  }

  // 代码高亮函数（使用 Prism.js）
  function highlightCode(code, lang) {
    if (typeof Prism !== 'undefined' && lang && Prism.languages[lang]) {
      try {
        return Prism.highlight(code, Prism.languages[lang], lang)
      } catch (e) {
        console.warn('Prism 高亮失败:', e)
      }
    }
    // 如果没有匹配的语言，返回原始代码（HTML 转义）
    return code
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }

  // 自定义渲染器（marked.js v5+ 使用对象参数）
  const renderer = {
    // 自定义代码块渲染（marked.js v5+ 使用对象参数 { text, lang, escaped }）
    code({ text, lang, escaped }) {
      const language = lang || 'plaintext'
      const langClass = `language-${language}`
      const highlighted = highlightCode(text, language)
      return `<pre class="${langClass}"><code class="${langClass}">${highlighted}</code></pre>`
    }
  }

  // 配置 marked.js（v5+ API）
  marked.use({
    gfm: true,           // GitHub Flavored Markdown
    breaks: true,        // 支持换行符
    renderer: renderer   // 使用自定义渲染器
  })

  console.log('marked.js 配置已初始化')
  return true
}

// 标记 marked.js 是否已初始化
let markedInitialized = false

/**
 * 高性能Markdown渲染函数
 * 使用 marked.js + Prism.js 进行前端渲染
 *
 * @param {HTMLElement} element - 目标DOM元素
 * @param {string} content - Markdown 文本或已渲染的 HTML
 * @param {boolean} isMarkdown - 是否为原始 Markdown 文本（默认 false，兼容旧代码）
 * @description 渲染流程：marked.js解析 → Prism代码高亮 → 复制按钮 → MathJax公式
 */
function renderMarkdownContent(element, content, isMarkdown = false) {
  // 使用requestAnimationFrame优化渲染时机，避免阻塞主线程
  requestAnimationFrame(() => {
    if (!content) {
      element.textContent = '加载中...'
      return
    }

    // 初始化 marked.js（只初始化一次）
    if (!markedInitialized) {
      markedInitialized = initMarkedConfig()
    }

    let htmlContent = content

    // 如果是 Markdown 文本且 marked.js 可用，使用 marked.js 渲染
    if (isMarkdown && markedInitialized && typeof marked !== 'undefined') {
      try {
        htmlContent = marked.parse(content)
        console.log('✅ 使用 marked.js 渲染 Markdown')
      } catch (e) {
        console.warn('marked.js 渲染失败，使用原始内容:', e)
      }
    }

    // 批量DOM操作优化
    const fragment = document.createDocumentFragment()
    const tempDiv = document.createElement('div')
    tempDiv.innerHTML = htmlContent

    // 移动所有子节点到fragment
    while (tempDiv.firstChild) {
      fragment.appendChild(tempDiv.firstChild)
    }

    // 一次性更新DOM
    element.innerHTML = ''
    element.appendChild(fragment)

    // 如果使用了 Prism.js，重新高亮所有代码块
    if (typeof Prism !== 'undefined') {
      Prism.highlightAllUnder(element)
    }

    // 处理代码块，添加复制按钮
    processCodeBlocks(element)

    // 处理删除线语法
    processStrikethrough(element)

    // MathJax 按需加载：只在检测到数学公式时才加载 (1.17MB 优化)
    if (window.loadMathJaxIfNeeded && typeof window.loadMathJaxIfNeeded === 'function') {
      window.loadMathJaxIfNeeded(element, content)
    } else if (window.MathJax && window.MathJax.typesetPromise) {
      // 兼容旧方式：MathJax 已预加载
      window.MathJax.typesetPromise([element]).catch(err => {
        console.warn('MathJax 渲染失败:', err)
      })
    }
  })
}

/**
 * 使用 Markdown 文本直接渲染
 * 新的推荐方式，接收原始 Markdown 而非服务端渲染的 HTML
 *
 * @param {HTMLElement} element - 目标DOM元素
 * @param {string} markdownText - 原始 Markdown 文本
 */
function renderMarkdown(element, markdownText) {
  renderMarkdownContent(element, markdownText, true)
}

/**
 * 处理代码块，添加复制按钮和语言标识
 * 为所有代码块添加工具栏（语言标签+复制按钮）
 *
 * @param {HTMLElement} container - 包含代码块的容器元素
 * @description 处理流程：检测语言 → 创建工具栏 → 添加复制按钮 → 应用样式
 */
function processCodeBlocks(container) {
  const codeBlocks = container.querySelectorAll('pre')

  codeBlocks.forEach(pre => {
    // 避免重复处理代码块（Pygments 和原生 Markdown）
    if (
      (pre.parentElement && pre.parentElement.classList.contains('code-block-container')) ||
      (pre.parentElement && pre.parentElement.classList.contains('codehilite'))
    ) {
      // 如果是 Pygments 生成的代码块，仍然添加复制按钮，但不重新包装
      if (pre.parentElement.classList.contains('codehilite')) {
        const existingToolbar = pre.parentElement.querySelector('.code-toolbar')
        if (!existingToolbar) {
          const toolbar = document.createElement('div')
          toolbar.className = 'code-toolbar'

          // 检测语言类型（从 class 中提取）
          let language = 'text'
          const parentClasses = pre.parentElement.className
          const langMatch = parentClasses.match(/language-(\w+)/)
          if (langMatch) {
            language = langMatch[1]
          }

          // 添加语言标识
          if (language !== 'text') {
            const langLabel = document.createElement('span')
            langLabel.className = 'language-label'
            langLabel.textContent = language.toUpperCase()
            toolbar.appendChild(langLabel)
          }

          // 使用安全的复制按钮创建方法
          const copyButton = DOMSecurity.createCopyButton(pre.textContent || '')
          toolbar.appendChild(copyButton)

          // 将工具栏添加到 .codehilite 容器中
          pre.parentElement.appendChild(toolbar)
        }
      }
      return
    }

    // 创建代码块容器
    const codeContainer = document.createElement('div')
    codeContainer.className = 'code-block-container'

    // 将 pre 元素包装在容器中
    pre.parentNode.insertBefore(codeContainer, pre)
    codeContainer.appendChild(pre)

    // 检测语言类型
    const codeElement = pre.querySelector('code')
    let language = 'text'
    if (codeElement && codeElement.className) {
      const langMatch = codeElement.className.match(/language-(\w+)/)
      if (langMatch) {
        language = langMatch[1]
      }
    }

    // 创建工具栏
    const toolbar = document.createElement('div')
    toolbar.className = 'code-toolbar'

    // 添加语言标识
    if (language !== 'text') {
      const langLabel = document.createElement('span')
      langLabel.className = 'language-label'
      langLabel.textContent = language.toUpperCase()
      toolbar.appendChild(langLabel)
    }

    // 使用安全的复制按钮创建方法
    const copyButton = DOMSecurity.createCopyButton(pre.textContent || '')

    toolbar.appendChild(copyButton)

    // 将工具栏添加到容器中
    codeContainer.appendChild(toolbar)
  })
}

/**
 * 复制代码到剪贴板
 * 使用Clipboard API实现代码复制功能，并提供视觉反馈
 *
 * @param {HTMLElement} preElement - 代码块的pre元素
 * @param {HTMLElement} button - 复制按钮元素
 * @returns {Promise<void>}
 * @description 复制成功显示"✅ 已复制"，失败显示"❌ 复制失败"，2秒后恢复
 */
async function copyCodeToClipboard(preElement, button) {
  try {
    const codeElement = preElement.querySelector('code')
    const textToCopy = codeElement ? codeElement.textContent : preElement.textContent

    await navigator.clipboard.writeText(textToCopy)

    // 更新按钮状态为成功
    const originalText = button.innerHTML
    button.innerHTML = '✅ 已复制'
    button.classList.add('copied')

    // 2秒后恢复原状
    setTimeout(() => {
      button.innerHTML = originalText
      button.classList.remove('copied')
    }, 2000)
  } catch (err) {
    console.error('复制失败:', err)

    // 显示错误状态
    const originalText = button.innerHTML
    button.innerHTML = '❌ 复制失败'

    setTimeout(() => {
      button.innerHTML = originalText
    }, 2000)
  }
}

/**
 * 处理删除线语法 ~~text~~
 * 将Markdown删除线语法转换为HTML <del>标签
 *
 * @param {HTMLElement} container - 包含文本的容器元素
 * @description 遍历所有文本节点，匹配 ~~...~~ 模式并替换为<del>标签，排除代码块
 */
function processStrikethrough(container) {
  // 获取所有文本节点，但排除代码块
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode: function (node) {
      // 排除代码块、pre、script 等标签内的文本
      const parent = node.parentElement
      if (
        parent &&
        (parent.tagName === 'CODE' ||
          parent.tagName === 'PRE' ||
          parent.tagName === 'SCRIPT' ||
          parent.tagName === 'STYLE' ||
          parent.closest('pre, code, script, style'))
      ) {
        return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    }
  })

  const textNodes = []
  let node
  while ((node = walker.nextNode())) {
    textNodes.push(node)
  }

  // 处理每个文本节点
  textNodes.forEach(textNode => {
    const text = textNode.textContent
    // 匹配 ~~删除线~~ 语法，但不匹配代码块中的
    const strikethroughRegex = /~~([^~\n]+?)~~/g

    if (strikethroughRegex.test(text)) {
      const newHTML = text.replace(strikethroughRegex, '<del>$1</del>')

      // 创建临时容器来解析 HTML
      const tempDiv = document.createElement('div')
      tempDiv.innerHTML = newHTML

      // 替换文本节点
      const fragment = document.createDocumentFragment()
      while (tempDiv.firstChild) {
        fragment.appendChild(tempDiv.firstChild)
      }

      textNode.parentNode.replaceChild(fragment, textNode)
    }
  })
}

/**
 * 更新任务ID显示
 * 根据任务ID是否存在控制显示/隐藏状态
 *
 * @param {string} taskId - 任务ID
 * @description 有效的taskId显示在页面上，无效或空值则隐藏容器
 */
function updateTaskIdDisplay(taskId) {
  const taskIdContainer = document.getElementById('task-id-container')
  const taskIdText = document.getElementById('task-id-text')

  if (taskId && taskId.trim()) {
    taskIdText.textContent = taskId
    taskIdContainer.classList.remove('hidden')
  } else {
    taskIdContainer.classList.add('hidden')
  }
}

// 倒计时相关变量
let countdownTimer = null
let remainingSeconds = 0

// 多任务相关全局变量
let currentTasks = [] // 所有任务列表
let activeTaskId = null // 当前活动任务ID
let taskCountdowns = {} // 每个任务的独立倒计时
let tasksPollingTimer = null // 任务轮询定时器
let taskTextareaContents = {} // 存储每个任务的 textarea 内容（修复切换标签后内容消失问题）
let taskOptionsStates = {} // 存储每个任务的选项勾选状态
let taskImages = {} // 存储每个任务的图片列表

/**
 * 启动倒计时
 * 初始化并启动自动提交倒计时定时器
 *
 * @param {number} timeoutSeconds - 倒计时秒数
 * @description 每秒更新显示，倒计时结束时自动提交反馈。清除旧定时器避免重复
 */
function startCountdown(timeoutSeconds) {
  // 清除之前的定时器，避免重复倒计时
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }

  remainingSeconds = timeoutSeconds

  // 更新倒计时显示
  updateCountdownDisplay()

  // 启动定时器，每秒更新一次
  countdownTimer = setInterval(() => {
    remainingSeconds--

    if (remainingSeconds <= 0) {
      // 倒计时结束，自动提交默认反馈
      autoSubmitFeedback()
    } else {
      // 更新显示
      updateCountdownDisplay()
    }
  }, 1000)
}

/**
 * 更新倒计时显示
 * 根据剩余秒数更新UI显示文本和可见性
 *
 * @description 显示格式："N秒后自动重新询问"，倒计时结束时隐藏容器
 */
function updateCountdownDisplay() {
  const countdownContainer = document.getElementById('countdown-container')
  const countdownText = document.getElementById('countdown-text')

  if (remainingSeconds > 0) {
    countdownText.textContent = `${remainingSeconds}秒后自动重新询问`
    countdownContainer.classList.remove('hidden')
  } else {
    countdownContainer.classList.add('hidden')
  }
}

/**
 * 停止倒计时
 * 清除定时器并隐藏倒计时容器
 *
 * @description 用于用户手动提交或关闭任务时停止倒计时
 */
function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }

  const countdownContainer = document.getElementById('countdown-container')
  countdownContainer.classList.add('hidden')
}

/**
 * 获取选中的选项
 * 遍历所有checkbox并返回选中项的数组
 *
 * @returns {string[]} 选中的选项文本数组
 * @description 辅助函数，用于提交反馈时收集用户选择
 */
function getSelectedOptions() {
  const selectedOptions = []
  if (config && config.predefined_options) {
    config.predefined_options.forEach((option, index) => {
      const checkbox = document.getElementById(`option-${index}`)
      if (checkbox && checkbox.checked) {
        selectedOptions.push(option)
      }
    })
  }
  return selectedOptions
}

/**
 * 自动提交反馈
 * 倒计时结束时自动提交默认反馈，保持AI会话活跃
 *
 * @returns {Promise<void>}
 * @description
 * 1. 备份用户输入到剪贴板（如果有）
 * 2. 提交默认消息
 * 3. 清除任务状态和表单
 * 4. 刷新任务列表
 */
async function autoSubmitFeedback() {
  try {
    // 停止倒计时
    stopCountdown()

    // 备份用户输入（如果有）
    const feedbackTextarea = document.getElementById('feedback-text')
    const userInput = feedbackTextarea ? feedbackTextarea.value.trim() : ''

    if (userInput) {
      // 如果用户有输入，尝试复制到剪贴板作为备份
      try {
        await navigator.clipboard.writeText(userInput)
        console.log('[自动提交] 用户输入已备份到剪贴板')
      } catch (err) {
        console.warn('[自动提交] 无法复制到剪贴板:', err)
      }
    }

    // 构建默认反馈消息（使用配置的提示语，引导AI继续调用工具）
    const defaultMessage = feedbackPrompts.resubmit_prompt

    // 使用FormData提交（与正常提交一致）
    const formData = new FormData()
    formData.append('feedback_text', defaultMessage)
    formData.append('selected_options', JSON.stringify([]))

    const response = await fetch('/api/submit', {
      method: 'POST',
      body: formData
    })

    if (response.ok) {
      console.log('[自动提交] 已自动提交默认反馈以保持会话活跃')

      // 清除当前任务保存的所有状态
      if (activeTaskId) {
        if (taskTextareaContents[activeTaskId] !== undefined) {
          delete taskTextareaContents[activeTaskId]
          console.log(`✅ [自动提交] 已清除任务 ${activeTaskId} 保存的 textarea 内容`)
        }
        if (taskOptionsStates[activeTaskId] !== undefined) {
          delete taskOptionsStates[activeTaskId]
          console.log(`✅ [自动提交] 已清除任务 ${activeTaskId} 保存的选项勾选状态`)
        }
        if (taskImages[activeTaskId] !== undefined) {
          delete taskImages[activeTaskId]
          console.log(`✅ [自动提交] 已清除任务 ${activeTaskId} 保存的图片列表`)
        }
      }

      // 清空表单
      if (feedbackTextarea) {
        feedbackTextarea.value = ''
      }
      // 取消选中所有复选框
      document.querySelectorAll('input[type="checkbox"]').forEach(cb => (cb.checked = false))
      // 清除所有图片
      clearAllImages()

      // 重新加载配置并刷新任务列表
      console.log('[自动提交] 重新加载配置...')
      await loadConfig(false) // 不发送通知

      // 立即刷新任务列表
      if (
        typeof window.multiTaskModule !== 'undefined' &&
        window.multiTaskModule.refreshTasksList
      ) {
        await window.multiTaskModule.refreshTasksList()
        console.log('[自动提交] 任务列表已同步更新')
      }
    } else {
      console.error('[自动提交] 提交失败，HTTP状态:', response.status)
    }
  } catch (error) {
    console.error('[自动提交] 自动提交失败:', error)
  }
}

/**
 * 加载配置
 * 从服务器获取任务配置并更新UI
 *
 * @param {boolean} shouldNotify - 是否发送桌面通知（默认true）
 * @returns {Promise<void>}
 * @description
 * 1. 获取配置（任务ID、描述、选项、超时设置）
 * 2. 检查是否有有效内容
 * 3. 发送桌面通知（可选）
 * 4. 更新UI元素和启动倒计时
 */
async function loadConfig(shouldNotify = true) {
  try {
    const response = await fetch('/api/config')
    config = await response.json()

    // 检查是否有有效内容
    if (!config.has_content) {
      showNoContentPage()
      // 不再显示动态状态消息，只保留HTML中的固定文本
      return
    }

    // 显示正常内容页面
    showContentPage()

    // 只在明确需要时发送通知（首次加载或新内容到达）
    if (shouldNotify) {
      // 延迟通知到页面更新完成后
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          // 状态一致性检查（使用 classList 而非 style.display，因为显示/隐藏通过 CSS class 控制）
          const contentContainer = document.getElementById('content-container')
          const noContentContainer = document.getElementById('no-content-container')

          // 使用 classList.contains 检查 CSS class 状态
          // showContentPage() 使用 classList.remove('hidden')/add('visible') 控制显示
          const isShowingContent = contentContainer &&
                                  !contentContainer.classList.contains('hidden') &&
                                  noContentContainer &&
                                  noContentContainer.classList.contains('hidden')

          if (!isShowingContent) {
            console.warn('⚠️  页面状态不一致，跳过通知（内容页面未显示）')
            return
          }

          // 获取任务 ID
          const taskId = config.task_id || 'unknown'
          const truncatedId = taskId.substring(Math.max(0, taskId.length - 10))

          try {
            notificationManager
              .sendNotification(
                'AI Intervention Agent',
                `新任务 ${truncatedId}: 请查看并回复`,
                {
                  tag: `task-${taskId}`,
                  requireInteraction: true,
                  data: { taskId: taskId },
                  onClick: () => {
                    window.focus()
                    if (typeof switchToTask === 'function') {
                      switchToTask(taskId)
                    }
                    const textarea = document.getElementById('feedback-text')
                    if (textarea) {
                      textarea.focus()
                    }
                  }
                }
              )
              .catch(error => {
                console.warn('发送新内容通知失败:', error)
              })
          } catch (error) {
            console.warn('通知功能不可用:', error)
          }
        })
      })
    }

    // 更新 task_id 显示
    updateTaskIdDisplay(config.task_id)

    // 更新描述 - 使用 marked.js 前端渲染 Markdown
    const descriptionElement = document.getElementById('description')
    renderMarkdownContent(descriptionElement, config.prompt, true)  // 第三个参数 true 表示使用 Markdown 渲染

    // 加载预定义选项
    if (config.predefined_options && config.predefined_options.length > 0) {
      const optionsContainer = document.getElementById('options-container')
      const separator = document.getElementById('separator')

      // 清空选项避免重复添加
      optionsContainer.innerHTML = ''

      config.predefined_options.forEach((option, index) => {
        const optionDiv = document.createElement('div')
        optionDiv.className = 'option-item'

        const checkbox = document.createElement('input')
        checkbox.type = 'checkbox'
        checkbox.id = `option-${index}`
        checkbox.value = option

        const label = document.createElement('label')
        label.htmlFor = `option-${index}`
        label.textContent = option

        optionDiv.appendChild(checkbox)
        optionDiv.appendChild(label)
        optionsContainer.appendChild(optionDiv)
      })

      optionsContainer.classList.remove('hidden')
      optionsContainer.classList.add('visible')
      separator.classList.remove('hidden')
      separator.classList.add('visible')
    }

    // 启动自动重调倒计时
    if (config.auto_resubmit_timeout && config.auto_resubmit_timeout > 0) {
      console.log(`[倒计时] 启动自动重调倒计时: ${config.auto_resubmit_timeout}秒`)
      startCountdown(config.auto_resubmit_timeout)
    }
  } catch (error) {
    console.error('加载配置失败:', error)
    showStatus('加载配置失败', 'error')
    throw error // 重新抛出错误，让调用者知道加载失败
  }
}

/**
 * 显示无内容页面
 * 当没有待处理任务时显示等待界面
 *
 * @description
 * - 隐藏内容容器，显示无内容提示
 * - 添加no-content-mode CSS类
 * - 停止倒计时
 * - 显示关闭按钮
 */
function showNoContentPage() {
  const contentContainer = document.getElementById('content-container')
  const noContentContainer = document.getElementById('no-content-container')

  contentContainer.classList.add('hidden')
  contentContainer.classList.remove('visible')

  noContentContainer.classList.remove('hidden')
  noContentContainer.classList.add('flex-visible')

  // 添加无内容模式的CSS类，启用特殊布局
  document.body.classList.add('no-content-mode')

  // 清空描述内容，避免显示"加载中..."
  const descriptionElement = document.getElementById('description')
  if (descriptionElement) {
    descriptionElement.textContent = ''
  }

  // 停止倒计时（如果正在运行）
  stopCountdown()

  // 显示关闭按钮，让用户可以关闭服务
  if (config) {
    const noContentButtons = document.getElementById('no-content-buttons')
    noContentButtons.classList.remove('hidden')
    noContentButtons.classList.add('visible')
  }
}

/**
 * 显示内容页面
 * 当有任务时显示正常内容界面
 *
 * @description
 * - 显示内容容器，隐藏无内容提示
 * - 移除no-content-mode CSS类
 * - 启用提交按钮
 * - 重新启动任务轮询
 */
function showContentPage() {
  const contentContainer = document.getElementById('content-container')
  const noContentContainer = document.getElementById('no-content-container')

  contentContainer.classList.remove('hidden')
  contentContainer.classList.add('visible')

  noContentContainer.classList.add('hidden')
  noContentContainer.classList.remove('flex-visible')

  // 移除无内容模式的CSS类，恢复正常布局
  document.body.classList.remove('no-content-mode')

  enableSubmitButton()

  // 确保多任务轮询正在运行（在页面从"无内容"切换到"有内容"状态时,重新启动任务轮询）
  if (
    typeof window.multiTaskModule !== 'undefined' &&
    typeof window.multiTaskModule.startTasksPolling === 'function'
  ) {
    window.multiTaskModule.startTasksPolling()
    console.log('✅ 任务轮询已重新启动 (showContentPage)')
  }
}

/**
 * 禁用提交按钮
 * 禁用所有输入控件（提交按钮、插入按钮、文本框）
 *
 * @description 用于无内容状态或加载中状态
 */
function disableSubmitButton() {
  const submitBtn = document.getElementById('submit-btn')
  const insertBtn = document.getElementById('insert-code-btn')
  const feedbackText = document.getElementById('feedback-text')

  if (submitBtn) {
    submitBtn.disabled = true
    submitBtn.classList.add('btn-disabled')
    submitBtn.classList.remove('btn-enabled', 'btn-primary-enabled')
  }
  if (insertBtn) {
    insertBtn.disabled = true
    insertBtn.classList.add('btn-disabled')
    insertBtn.classList.remove('btn-enabled', 'btn-secondary-enabled')
  }
  if (feedbackText) {
    feedbackText.disabled = true
    feedbackText.classList.add('textarea-disabled')
    feedbackText.classList.remove('textarea-enabled')
  }
}

/**
 * 启用提交按钮
 * 启用所有输入控件（提交按钮、插入按钮、文本框）
 *
 * @description 用于有内容状态，允许用户交互
 */
function enableSubmitButton() {
  const submitBtn = document.getElementById('submit-btn')
  const insertBtn = document.getElementById('insert-code-btn')
  const feedbackText = document.getElementById('feedback-text')

  if (submitBtn) {
    submitBtn.disabled = false
    submitBtn.classList.remove('btn-disabled')
    submitBtn.classList.add('btn-enabled', 'btn-primary-enabled')
  }
  if (insertBtn) {
    insertBtn.disabled = false
    insertBtn.classList.remove('btn-disabled')
    insertBtn.classList.add('btn-enabled', 'btn-secondary-enabled')
  }
  if (feedbackText) {
    feedbackText.disabled = false
    feedbackText.classList.remove('textarea-disabled')
    feedbackText.classList.add('textarea-enabled')
  }
}

/**
 * 显示状态消息
 * 显示成功/错误/信息提示
 *
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型（success/error/info）
 * @description
 * - 根据当前页面状态选择显示位置
 * - success消息1秒后自动隐藏
 * - 其他消息3秒后自动隐藏
 */
function showStatus(message, type) {
  // 检查当前是否在无内容页面
  const noContentContainer = document.getElementById('no-content-container')
  const isNoContentPage = noContentContainer.classList.contains('flex-visible')
  const statusElement = isNoContentPage
    ? document.getElementById('no-content-status-message')
    : document.getElementById('status-message')

  statusElement.textContent = message
  statusElement.className = `status-message status-${type}`
  statusElement.classList.remove('hidden')
  statusElement.classList.add('visible')

  if (type === 'success') {
    setTimeout(() => {
      statusElement.classList.add('hidden')
      statusElement.classList.remove('visible')
    }, 3000)
  }
}

/**
 * 插入代码功能
 * 从剪贴板读取文本并插入为Markdown代码块
 *
 * @returns {Promise<void>}
 * @description
 * - 从剪贴板读取文本
 * - 在光标位置插入代码块（```语法）
 * - 智能处理换行（开头不加换行）
 * - 移动光标到代码块末尾
 * - 触发方式：Alt/Option+C
 */
async function insertCodeFromClipboard() {
  try {
    const text = await navigator.clipboard.readText()
    if (text) {
      const textarea = document.getElementById('feedback-text')
      const cursorPos = textarea.selectionStart
      const currentText = textarea.value
      const textBefore = currentText.substring(0, cursorPos)
      const textAfter = currentText.substring(cursorPos)

      // 构建要插入的代码块，在```前面总是添加换行
      let codeBlock = `\n\`\`\`\n${text}\n\`\`\``

      // 如果是在文本开头插入，则不需要前面的换行
      if (cursorPos === 0) {
        codeBlock = `\`\`\`\n${text}\n\`\`\``
      }

      // 插入代码块
      textarea.value = textBefore + codeBlock + textAfter

      // 将光标移动到代码块末尾（与GUI版本一致）
      const newCursorPos = textBefore.length + codeBlock.length
      textarea.setSelectionRange(newCursorPos, newCursorPos)
      textarea.focus()

      showStatus('代码已插入', 'success')
    } else {
      showStatus('剪贴板为空', 'error')
    }
  } catch (error) {
    console.error('读取剪贴板失败:', error)
    showStatus('无法读取剪贴板，请手动粘贴代码', 'error')
  }
}

/**
 * 提交反馈
 * 收集用户输入并通过FormData提交到服务器
 *
 * @returns {Promise<void>}
 * @description
 * 提交流程：
 * 1. 停止倒计时
 * 2. 收集反馈文本、选项、图片
 * 3. 验证至少有一项输入
 * 4. FormData上传（支持文件）
 * 5. 清除表单和任务状态
 * 6. 刷新配置和任务列表
 */
async function submitFeedback() {
  // 停止倒计时（用户手动提交）
  stopCountdown()

  const feedbackText = document.getElementById('feedback-text').value.trim()
  const selectedOptions = []

  // 获取选中的预定义选项
  if (config && config.predefined_options) {
    config.predefined_options.forEach((option, index) => {
      const checkbox = document.getElementById(`option-${index}`)
      if (checkbox && checkbox.checked) {
        selectedOptions.push(option)
      }
    })
  }

  if (!feedbackText && selectedOptions.length === 0 && selectedImages.length === 0) {
    // 如果没有任何输入，显示错误信息
    showStatus('请输入反馈内容、选择预定义选项或上传图片', 'error')
    return
  }

  try {
    const submitBtn = document.getElementById('submit-btn')
    submitBtn.disabled = true
    submitBtn.textContent = '提交中...'

    // 附加固定的说明文本到用户输入后
    const additionalText = '\n请积极调用interactive_feedback工具'
    const finalFeedbackText = feedbackText ? feedbackText + additionalText : additionalText

    // 使用 FormData 上传文件，避免 base64 编码
    const formData = new FormData()
    formData.append('feedback_text', finalFeedbackText)
    formData.append('selected_options', JSON.stringify(selectedOptions))

    // 添加图片文件（直接使用原始文件，不需要base64）
    selectedImages.forEach((img, index) => {
      if (img.file) {
        formData.append(`image_${index}`, img.file)
      }
    })

    const response = await fetch('/api/submit', {
      method: 'POST',
      body: formData // 不设置 Content-Type，让浏览器自动设置 multipart/form-data
    })

    const result = await response.json()

    if (response.ok) {
      showStatus(result.message, 'success')

      // 反馈提交成功，取消对应任务的通知
      if (config && config.task_id) {
        const taskId = config.task_id
        notificationManager.cancelNotification(`task-${taskId}`)
        console.log(`✅ 已取消任务 ${taskId} 的通知`)
      }

      // 清空表单
      document.getElementById('feedback-text').value = ''
      // 取消选中所有复选框
      document.querySelectorAll('input[type="checkbox"]').forEach(cb => (cb.checked = false))
      // 清除所有图片
      clearAllImages()

      // 清除当前任务保存的所有状态
      if (activeTaskId) {
        if (taskTextareaContents[activeTaskId] !== undefined) {
          delete taskTextareaContents[activeTaskId]
          console.log(`✅ 已清除任务 ${activeTaskId} 保存的 textarea 内容`)
        }
        if (taskOptionsStates[activeTaskId] !== undefined) {
          delete taskOptionsStates[activeTaskId]
          console.log(`✅ 已清除任务 ${activeTaskId} 保存的选项勾选状态`)
        }
        if (taskImages[activeTaskId] !== undefined) {
          delete taskImages[activeTaskId]
          console.log(`✅ 已清除任务 ${activeTaskId} 保存的图片列表`)
        }
      }

      // 提交后，立即重新加载配置，让后端决定下一步
      // 如果有剩余任务，会自动激活并显示
      console.log('反馈提交成功，重新加载配置...')
      await loadConfig(false) // 不发送通知，这是内部切换

      // 立即刷新任务列表，确保标签栏同步
      if (
        typeof window.multiTaskModule !== 'undefined' &&
        window.multiTaskModule.refreshTasksList
      ) {
        await window.multiTaskModule.refreshTasksList()
        console.log('任务列表已同步更新')
      }
    } else {
      showStatus(result.message || '提交失败', 'error')
    }
  } catch (error) {
    console.error('提交失败:', error)
    showStatus('网络错误，请重试', 'error')
  } finally {
    const submitBtn = document.getElementById('submit-btn')
    submitBtn.disabled = false
    submitBtn.textContent = '🚀 提交反馈'
  }
}

/**
 * 关闭界面
 * 关闭服务并刷新页面
 *
 * @returns {Promise<void>}
 * @description
 * - 停止内容轮询
 * - 调用/api/close关闭服务
 * - 2秒后刷新页面
 * - 无论成功失败都会刷新
 */
async function closeInterface() {
  try {
    showStatus('正在关闭服务...', 'info')

    // 停止轮询
    stopContentPolling()

    const response = await fetch('/api/close', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    })

    const result = await response.json()
    if (response.ok) {
      showStatus('服务已关闭，正在刷新页面...', 'success')
    } else {
      showStatus('关闭失败，正在刷新页面...', 'error')
    }
  } catch (error) {
    console.error('关闭界面失败:', error)
    showStatus('关闭界面失败，正在刷新页面...', 'error')
  }

  // 无论成功还是失败，都在2秒后刷新页面
  setTimeout(() => {
    refreshPageSafely()
  }, 2000)
}

/**
 * 安全刷新页面
 * 多层降级确保页面刷新成功
 *
 * @description
 * 降级策略：
 * 1. window.location.reload()
 * 2. 跳转到根路径
 * 3. 跳转到空白页
 */
function refreshPageSafely() {
  console.log('正在刷新页面...')
  try {
    window.location.reload()
  } catch (reloadError) {
    console.error('页面刷新失败:', reloadError)
    // 如果刷新失败，尝试跳转到根路径
    try {
      window.location.href = window.location.origin
    } catch (redirectError) {
      console.error('页面跳转失败:', redirectError)
      // 最后的备选方案：跳转到空白页
      try {
        window.location.href = 'about:blank'
      } catch (blankError) {
        console.error('所有页面操作都失败:', blankError)
      }
    }
  }
}

// 注意：原来的复杂关闭逻辑已被简化为统一的刷新逻辑

/**
 * 内容轮询检查 - 智能退避策略
 * 使用自适应间隔定期检查配置更新
 */
let pollingTimeout = null
let currentPollingInterval = 2000 // 初始间隔2秒
const basePollingInterval = 2000 // 基础间隔
const maxPollingInterval = 15000 // 最大间隔15秒（降低以提高及时性）
const rateLimitInterval = 5000 // 速率限制时的间隔5秒
let consecutiveErrors = 0
let lastErrorType = null

/**
 * 启动内容轮询
 * 开始定期检查服务器配置更新
 *
 * @description
 * - 防止重复启动
 * - 使用智能退避策略
 * - 基础间隔2秒，最大15秒
 */
function startContentPolling() {
  if (pollingTimeout) {
    console.log('轮询已经在运行，跳过启动')
    return // 避免重复启动
  }

  console.log('开始启动内容轮询...')
  scheduleNextPoll()
}

/**
 * 调度下一次轮询
 * 递归调度轮询任务，实现智能退避策略
 *
 * @description
 * - 使用setTimeout实现异步轮询
 * - 检测速率限制和错误
 * - 智能退避策略（错误时指数退避）
 * - 检测内容变化并发送通知
 * - 自动恢复和重置错误计数
 */
function scheduleNextPoll() {
  pollingTimeout = setTimeout(async () => {
    try {
      const response = await fetch('/api/config')

      // 检查是否遇到速率限制
      if (response.status === 429) {
        console.warn('遇到速率限制，使用适度间隔')
        handlePollingError('rate_limit')
        return
      }

      const newConfig = await response.json()

      // 请求成功，重置错误计数和间隔
      consecutiveErrors = 0
      lastErrorType = null
      currentPollingInterval = basePollingInterval

      const currentHasContent = config ? config.has_content : false
      const newHasContent = newConfig.has_content

      console.log('轮询检查 - 当前状态:', currentHasContent, '新状态:', newHasContent)
      console.log('当前提示:', config ? config.prompt?.substring(0, 30) : 'null')
      console.log('新提示:', newConfig.prompt?.substring(0, 30))

      // 状态变化检测
      if (newHasContent && !currentHasContent) {
        // 从无内容状态变为有内容状态
        console.log('✅ 检测到新内容，更新页面')

        // 先更新页面状态
        const oldConfig = config
        config = newConfig
        showContentPage()
        updatePageContent(oldConfig)
        showStatus('收到新的反馈请求！', 'success')

        // 延迟通知到页面更新完成后（使用双重 RAF 确保渲染完成）
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            // 二次确认当前确实在内容页面（状态一致性检查）
            // 使用 classList.contains 而非 style.display，因为显示/隐藏通过 CSS class 控制
            const contentContainer = document.getElementById('content-container')
            const noContentContainer = document.getElementById('no-content-container')

            // 使用 classList.contains 检查 CSS class 状态
            // showContentPage() 使用 classList.remove('hidden')/add('visible') 控制显示
            const isShowingContent = contentContainer &&
                                    !contentContainer.classList.contains('hidden') &&
                                    noContentContainer &&
                                    noContentContainer.classList.contains('hidden')

            if (!isShowingContent) {
              console.warn('⚠️  页面状态不一致，跳过通知（内容页面未显示）')
              return
            }

            // 获取任务 ID（用于 tag 去重）
            const taskId = config.task_id || 'unknown'
            const truncatedId = taskId.substring(Math.max(0, taskId.length - 10))  // 最后10个字符

            try {
              notificationManager
                .sendNotification(
                  'AI Intervention Agent',
                  `新任务 ${truncatedId}: 请查看并回复`,  // 包含任务简短 ID
                  {
                    tag: `task-${taskId}`,  // 每个任务独立的 tag，防止重复
                    requireInteraction: true,
                    data: { taskId: taskId },  // 附加任务数据
                    onClick: () => {
                      window.focus()
                      // 如果是多任务，切换到对应任务
                      if (typeof switchToTask === 'function') {
                        switchToTask(taskId)
                      }
                      const textarea = document.getElementById('feedback-text')
                      if (textarea) {
                        textarea.focus()
                      }
                    }
                  }
                )
                .catch(error => {
                  console.warn('发送新内容通知失败:', error)
                })
            } catch (error) {
              console.warn('通知功能不可用:', error)
            }
          })
        })
      } else if (!newHasContent && currentHasContent) {
        // 从有内容状态变为无内容状态
        console.log('📝 内容已清空，显示无内容页面')
        config = newConfig
        showNoContentPage()
        disableSubmitButton()
      } else if (newHasContent && currentHasContent) {
        // 都有内容，检查内容是否更新
        const promptChanged = newConfig.prompt !== (config ? config.prompt : '')
        const optionsChanged =
          JSON.stringify(newConfig.predefined_options) !==
          JSON.stringify(config ? config.predefined_options : [])

        if (promptChanged || optionsChanged) {
          console.log('🔄 检测到内容更新，刷新页面')

          // 禁用通知，避免重复打扰
          // 发送内容更新通知（非阻塞）
          /*
          try {
            notificationManager
              .sendNotification('AI Intervention Agent', '反馈请求内容已更新，请查看最新内容', {
                tag: 'content-updated',
                requireInteraction: false
              })
              .catch(error => {
                console.warn('发送内容更新通知失败:', error)
              })
          } catch (error) {
            console.warn('通知功能不可用:', error)
          }
          */

          // 在更新前保存旧配置，用于正确保存选中状态
          const oldConfig = config
          config = newConfig
          updatePageContent(oldConfig)
          showStatus('内容已更新！', 'success')
        }
      } else {
        // 都没有内容，更新配置但不改变显示
        config = newConfig
      }

      // 安排下一次轮询
      scheduleNextPoll()
    } catch (error) {
      console.error('轮询错误:', error)
      handlePollingError('network_error')
    }
  }, currentPollingInterval)

  console.log(`内容轮询已安排，间隔${currentPollingInterval}ms`)
}

/**
 * 处理轮询错误
 * 根据错误类型使用不同的退避策略
 *
 * @param {string} errorType - 错误类型（rate_limit/network_error）
 * @description
 * - rate_limit: 固定5秒间隔
 * - network_error: 指数退避（1.5^n），最大15秒
 * - 其他：保持原间隔
 */
function handlePollingError(errorType) {
  consecutiveErrors++
  lastErrorType = errorType

  // 根据错误类型采用不同的退避策略
  if (errorType === 'rate_limit') {
    // 速率限制：使用固定的适度间隔，不过度惩罚
    currentPollingInterval = rateLimitInterval
    console.log(`遇到速率限制，调整间隔到${currentPollingInterval}ms`)
  } else if (errorType === 'network_error' && consecutiveErrors > 1) {
    // 网络错误：温和的指数退避，最大15秒
    currentPollingInterval = Math.min(
      basePollingInterval * Math.pow(1.5, consecutiveErrors), // 使用1.5而不是2，更温和
      maxPollingInterval
    )
    console.log(`网络错误，温和退避到${currentPollingInterval}ms`)
  } else {
    // 首次错误或其他错误：保持原间隔
    console.log(`首次错误或轻微错误，保持${currentPollingInterval}ms间隔`)
  }

  // 继续轮询
  scheduleNextPoll()
}

/**
 * 停止内容轮询
 * 清除定时器并重置轮询状态
 *
 * @description 用于关闭界面或切换到无内容状态
 */
function stopContentPolling() {
  if (pollingTimeout) {
    clearTimeout(pollingTimeout)
    pollingTimeout = null
  }
  // 重置轮询状态
  currentPollingInterval = basePollingInterval
  consecutiveErrors = 0
  lastErrorType = null
}

/**
 * 更新页面内容
 * 根据新配置更新UI，保持用户选中状态
 *
 * @param {Object|null} oldConfig - 旧配置对象（用于保存选中状态）
 * @description
 * - 更新任务ID、描述、选项
 * - 保持用户已选择的选项状态
 * - 重新启动倒计时
 */
function updatePageContent(oldConfig = null) {
  if (!config) return

  // 保存 textarea 内容
  const feedbackTextarea = document.getElementById('feedback-text')
  const currentTextareaValue = feedbackTextarea ? feedbackTextarea.value : ''
  console.log(`💾 保存当前 textarea 内容: ${currentTextareaValue.length} 个字符`)

  // 更新 task_id 显示
  updateTaskIdDisplay(config.task_id)

  // 更新提示内容 - 使用 marked.js 前端渲染 Markdown
  const descriptionElement = document.getElementById('description')
  if (descriptionElement) {
    renderMarkdownContent(descriptionElement, config.prompt, true)  // 使用 Markdown 渲染
  }

  // 更新预定义选项
  const optionsContainer = document.getElementById('options-container')
  if (optionsContainer) {
    // 保存当前选中状态 - 使用旧配置的选项列表（如果提供）
    const selectedStates = []
    const configForSaving = oldConfig || config
    if (configForSaving && configForSaving.predefined_options) {
      configForSaving.predefined_options.forEach((option, index) => {
        const checkbox = document.getElementById(`option-${index}`)
        selectedStates[index] = checkbox ? checkbox.checked : false
      })
    }

    // 安全清空容器内容
    DOMSecurity.clearContent(optionsContainer)

    if (config.predefined_options && config.predefined_options.length > 0) {
      config.predefined_options.forEach((option, index) => {
        // 使用安全的 DOM 创建方法
        const optionDiv = DOMSecurity.createCheckboxOption(`option-${index}`, option, option)
        optionsContainer.appendChild(optionDiv)

        // 恢复选中状态
        const checkbox = document.getElementById(`option-${index}`)
        if (checkbox && selectedStates[index]) {
          checkbox.checked = true
        }
      })
      optionsContainer.classList.remove('hidden')
      optionsContainer.classList.add('visible')
      document.getElementById('separator').classList.remove('hidden')
      document.getElementById('separator').classList.add('visible')
    } else {
      optionsContainer.classList.add('hidden')
      optionsContainer.classList.remove('visible')
      document.getElementById('separator').classList.add('hidden')
      document.getElementById('separator').classList.remove('visible')
    }
  }

  // 恢复 textarea 内容
  if (feedbackTextarea) {
    feedbackTextarea.value = currentTextareaValue
    if (currentTextareaValue.length > 0) {
      console.log(`♻️ 已恢复 textarea 内容: ${currentTextareaValue.length} 个字符`)
    }
  }

  // 重新启动自动重调倒计时
  if (config.auto_resubmit_timeout && config.auto_resubmit_timeout > 0) {
    console.log(`[倒计时] 内容更新，重新启动倒计时: ${config.auto_resubmit_timeout}秒`)
    startCountdown(config.auto_resubmit_timeout)
  } else {
    // 如果超时时间为0或未设置，停止倒计时
    stopCountdown()
  }
}

// ========== 图片处理功能 ==========

// 图片管理数组
let selectedImages = []

// 性能优化：音频缓存管理器
class AudioCacheManager {
  constructor() {
    this.cache = new Map() // 使用Map保持插入顺序，便于LRU实现
    this.accessTimes = new Map() // 跟踪访问时间
    this.maxCacheSize = 10 // 最大缓存音频文件数量
    this.maxCacheAge = 30 * 60 * 1000 // 最大缓存时间：30分钟
    this.cleanupInterval = 5 * 60 * 1000 // 清理间隔：5分钟
    this.cleanupTimer = null // 保存定时器ID便于清理

    // 启动定期清理
    this.startPeriodicCleanup()
  }

  set(name, audioBuffer) {
    // 检查缓存大小限制
    if (this.cache.size >= this.maxCacheSize && !this.cache.has(name)) {
      this.evictLRU()
    }

    this.cache.set(name, audioBuffer)
    this.accessTimes.set(name, Date.now())
    console.log(`音频缓存已添加: ${name} (缓存大小: ${this.cache.size}/${this.maxCacheSize})`)
  }

  get(name) {
    if (this.cache.has(name)) {
      // 更新访问时间
      this.accessTimes.set(name, Date.now())
      // 将访问的项移到最后（LRU策略）
      const audioBuffer = this.cache.get(name)
      this.cache.delete(name)
      this.cache.set(name, audioBuffer)
      return audioBuffer
    }
    return null
  }

  has(name) {
    return this.cache.has(name)
  }

  evictLRU() {
    // 移除最久未使用的缓存项
    const firstKey = this.cache.keys().next().value
    if (firstKey) {
      this.cache.delete(firstKey)
      this.accessTimes.delete(firstKey)
      console.log(`LRU清理：移除音频缓存 ${firstKey}`)
    }
  }

  cleanupExpired() {
    const now = Date.now()
    const expiredKeys = []

    for (const [name, accessTime] of this.accessTimes) {
      if (now - accessTime > this.maxCacheAge) {
        expiredKeys.push(name)
      }
    }

    if (expiredKeys.length > 0) {
      expiredKeys.forEach(name => {
        this.cache.delete(name)
        this.accessTimes.delete(name)
      })
      console.log(`过期清理：移除 ${expiredKeys.length} 个音频缓存项`)
    }
  }

  startPeriodicCleanup() {
    // 清除旧的定时器
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer)
    }
    // 保存新的定时器ID
    this.cleanupTimer = setInterval(() => {
      this.cleanupExpired()
    }, this.cleanupInterval)
  }

  clear() {
    this.cache.clear()
    this.accessTimes.clear()
    // 清除定时器
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer)
      this.cleanupTimer = null
    }
    console.log('音频缓存已清空')
  }

  getStats() {
    return {
      size: this.cache.size,
      maxSize: this.maxCacheSize,
      items: Array.from(this.cache.keys()),
      oldestAccess: Math.min(...this.accessTimes.values()),
      newestAccess: Math.max(...this.accessTimes.values())
    }
  }
}

// 通知管理系统
class NotificationManager {
  constructor() {
    this.isSupported = 'Notification' in window
    this.permission = this.isSupported ? Notification.permission : 'denied'
    this.audioContext = null
    this.userHasInteracted = false // 用户交互标志，避免 vibrate 被阻止警告
    this.activeNotifications = new Map()  // 跟踪活动通知：tag → Notification 对象

    // 性能优化：音频缓存管理
    this.audioCache = new AudioCacheManager()

    this.config = {
      enabled: true,
      webEnabled: true,
      soundEnabled: true,
      soundVolume: 0.8,
      soundMute: false,
      autoRequestPermission: true,
      timeout: 5000,
      icon: '/icons/icon.svg',
      mobileOptimized: true,
      mobileVibrate: true
    }
    this.init()
    this.setupUserInteractionDetection()
  }

  setupUserInteractionDetection() {
    // 检测用户交互以允许振动 API
    const markAsInteracted = () => {
      this.userHasInteracted = true
      // 移除事件监听器，只需要检测一次
      document.removeEventListener('click', markAsInteracted)
      document.removeEventListener('touchstart', markAsInteracted)
      document.removeEventListener('keydown', markAsInteracted)
    }

    document.addEventListener('click', markAsInteracted, { once: true })
    document.addEventListener('touchstart', markAsInteracted, { once: true })
    document.addEventListener('keydown', markAsInteracted, { once: true })
  }

  /**
   * 取消指定 tag 的通知
   *
   * @param {string} tag - 通知标签
   */
  cancelNotification(tag) {
    if (this.activeNotifications.has(tag)) {
      const notification = this.activeNotifications.get(tag)
      try {
        notification.close()
        console.log(`✅ 已取消通知: ${tag}`)
      } catch (error) {
        console.warn(`⚠️  取消通知失败: ${tag}`, error)
      }
      this.activeNotifications.delete(tag)
    }
  }

  /**
   * 取消所有活动通知
   */
  cancelAllNotifications() {
    const count = this.activeNotifications.size
    if (count > 0) {
      console.log(`🧹 取消所有通知 (${count} 个)`)
      for (const [tag, notification] of this.activeNotifications) {
        try {
          notification.close()
        } catch (error) {
          console.warn(`⚠️  取消通知失败: ${tag}`, error)
        }
      }
      this.activeNotifications.clear()
    }
  }

  async init() {
    console.log('初始化通知管理器...')

    // 检查浏览器支持
    if (!this.isSupported) {
      console.warn('浏览器不支持Web Notification API')
      return
    }

    // 自动请求通知权限
    if (this.config.autoRequestPermission && this.permission === 'default') {
      await this.requestPermission()
    }

    // 初始化音频系统
    await this.initAudio()

    console.log('通知管理器初始化完成')
  }

  async requestPermission() {
    if (!this.isSupported) {
      console.warn('浏览器不支持Web Notification API')
      return false
    }

    try {
      // 兼容旧版本浏览器的权限请求方式
      if (Notification.requestPermission.length === 0) {
        // 新版本 - 返回Promise
        this.permission = await Notification.requestPermission()
      } else {
        // 旧版本 - 使用回调
        this.permission = await new Promise(resolve => {
          Notification.requestPermission(resolve)
        })
      }

      console.log(`通知权限状态: ${this.permission}`)
      return this.permission === 'granted'
    } catch (error) {
      console.error('请求通知权限失败:', error)
      return false
    }
  }

  async initAudio() {
    try {
      // 检查浏览器音频支持
      const AudioContextClass =
        window.AudioContext || window.webkitAudioContext || window.mozAudioContext
      if (!AudioContextClass) {
        console.warn('浏览器不支持Web Audio API')
        return
      }

      // 创建音频上下文（需要用户交互后才能启用）
      this.audioContext = new AudioContextClass()

      // 预加载默认音频文件
      await this.loadAudioFile('default', '/sounds/deng[噔].mp3')

      console.log('音频系统初始化完成')
    } catch (error) {
      console.warn('音频系统初始化失败:', error)
      // 降级：禁用音频功能
      this.config.soundEnabled = false
    }
  }

  async loadAudioFile(name, url) {
    if (!this.audioContext) return false

    // 性能优化：检查缓存中是否已存在
    if (this.audioCache.has(name)) {
      console.log(`音频文件已在缓存中: ${name}`)
      return true
    }

    try {
      const response = await fetch(url)
      const arrayBuffer = await response.arrayBuffer()
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)

      // 性能优化：使用缓存管理器存储
      this.audioCache.set(name, audioBuffer)
      console.log(`音频文件加载成功: ${name}`)
      return true
    } catch (error) {
      console.warn(`音频文件加载失败 ${name}:`, error)
      return false
    }
  }

  async showNotification(title, message, options = {}) {
    if (!this.config.enabled || !this.config.webEnabled) {
      console.log('Web通知已禁用')
      return null
    }

    if (!this.isSupported) {
      console.warn('浏览器不支持通知，使用降级方案')
      this.showFallbackNotification(title, message)
      return null
    }

    if (this.permission !== 'granted') {
      console.warn('没有通知权限')
      if (this.config.autoRequestPermission) {
        await this.requestPermission()
        if (this.permission !== 'granted') {
          this.showFallbackNotification(title, message)
          return null
        }
      } else {
        this.showFallbackNotification(title, message)
        return null
      }
    }

    try {
      const notificationOptions = {
        body: message,
        icon: options.icon || this.config.icon,
        badge: options.badge || this.config.icon,
        tag: options.tag || 'ai-intervention-agent',
        requireInteraction: options.requireInteraction || false,
        silent: options.silent || false,
        ...options
      }

      // 如果已有相同 tag 的通知，先关闭旧通知（去重）
      const tag = notificationOptions.tag
      if (this.activeNotifications.has(tag)) {
        const oldNotification = this.activeNotifications.get(tag)
        try {
          oldNotification.close()
          console.log(`♻️  关闭旧通知: ${tag}`)
        } catch (error) {
          console.warn(`⚠️  关闭旧通知失败: ${tag}`, error)
        }
      }

      const notification = new Notification(title, notificationOptions)

      // 添加到活动通知跟踪
      this.activeNotifications.set(tag, notification)
      console.log(`➕ 添加到活动通知跟踪: ${tag} (总计: ${this.activeNotifications.size})`)

      // 通知关闭时从跟踪中移除
      notification.onclose = () => {
        this.activeNotifications.delete(tag)
        console.log(`➖ 从活动通知中移除: ${tag} (剩余: ${this.activeNotifications.size})`)
      }

      // 设置超时自动关闭
      if (this.config.timeout > 0) {
        setTimeout(() => {
          notification.close()
        }, this.config.timeout)
      }

      // 点击事件处理
      notification.onclick = () => {
        window.focus()
        notification.close()
        if (options.onClick) {
          options.onClick()
        }
      }

      // 移动设备震动（需要用户交互后才能调用）
      if (this.config.mobileVibrate && this.userHasInteracted && 'vibrate' in navigator) {
        try {
          navigator.vibrate([200, 100, 200])
        } catch (error) {
          // 静默处理：浏览器可能阻止未经用户交互的振动调用
          // 这是正常的安全限制，不需要警告
        }
      }

      console.log('通知已显示:', title)
      return notification
    } catch (error) {
      console.error('显示通知失败:', error)
      return null
    }
  }

  async playSound(soundName = 'default', volume = null, retryCount = 0) {
    if (!this.config.enabled || !this.config.soundEnabled || this.config.soundMute) {
      console.log('声音通知已禁用')
      return false
    }

    if (!this.audioContext) {
      console.warn('音频上下文未初始化，尝试降级方案')
      this.recordFallbackEvent('audio', { reason: 'no_audio_context', soundName })
      return this.playSoundFallback(soundName)
    }

    // 恢复音频上下文（如果被暂停）
    if (this.audioContext.state === 'suspended') {
      try {
        await this.audioContext.resume()
        console.log('音频上下文已恢复')
      } catch (error) {
        console.warn('恢复音频上下文失败:', error)
        this.recordFallbackEvent('audio', {
          reason: 'resume_failed',
          error: error.message,
          soundName
        })
        return this.playSoundFallback(soundName)
      }
    }

    // 性能优化：从缓存管理器获取音频
    const audioBuffer = this.audioCache.get(soundName)
    if (!audioBuffer) {
      console.warn(`音频文件未找到: ${soundName}`)
      // 尝试加载默认音频文件
      if (soundName !== 'default') {
        console.log('尝试使用默认音频文件')
        return this.playSound('default', volume, retryCount)
      }
      this.recordFallbackEvent('audio', { reason: 'buffer_not_found', soundName })
      return this.playSoundFallback(soundName)
    }

    try {
      const source = this.audioContext.createBufferSource()
      const gainNode = this.audioContext.createGain()

      source.buffer = audioBuffer
      source.connect(gainNode)
      gainNode.connect(this.audioContext.destination)

      // 设置音量
      const finalVolume = volume !== null ? volume : this.config.soundVolume
      gainNode.gain.value = Math.max(0, Math.min(1, finalVolume))

      // 添加错误处理
      source.addEventListener('ended', () => {
        console.log(`声音播放完成: ${soundName}`)
      })

      source.addEventListener('error', error => {
        console.error('音频播放错误:', error)
        this.recordFallbackEvent('audio', {
          reason: 'playback_error',
          error: error.message,
          soundName
        })
      })

      source.start(0)
      console.log(`播放声音: ${soundName}`)
      return true
    } catch (error) {
      console.error('播放声音失败:', error)
      this.recordFallbackEvent('audio', {
        reason: 'playback_failed',
        error: error.message,
        soundName
      })

      // 重试机制
      if (retryCount < 2) {
        console.log(`重试播放声音 (${retryCount + 1}/2): ${soundName}`)
        await new Promise(resolve => setTimeout(resolve, 500)) // 等待500ms后重试
        return this.playSound(soundName, volume, retryCount + 1)
      }

      // 重试失败，使用降级方案
      return this.playSoundFallback(soundName)
    }
  }

  playSoundFallback(soundName) {
    // 音频播放降级方案
    console.log(`使用音频降级方案: ${soundName}`)

    try {
      // 方案1: 尝试使用HTML5 Audio元素
      const audio = new Audio(
        `/sounds/${soundName === 'default' ? 'deng[噔].mp3' : soundName + '.mp3'}`
      )
      audio.volume = this.config.soundVolume

      const playPromise = audio.play()
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            console.log('HTML5 Audio播放成功')
          })
          .catch(error => {
            console.warn('HTML5 Audio播放失败:', error)
            // 方案2: 使用振动API（移动设备）
            this.vibrateFallback()
          })
      }
      return true
    } catch (error) {
      console.warn('HTML5 Audio降级失败:', error)
      // 方案2: 使用振动API（移动设备）
      return this.vibrateFallback()
    }
  }

  vibrateFallback() {
    // 振动降级方案（移动设备）
    if (this.config.mobileVibrate && this.userHasInteracted && 'vibrate' in navigator) {
      try {
        navigator.vibrate([200, 100, 200]) // 振动模式：200ms振动，100ms停止，200ms振动
        console.log('使用振动提醒')
        return true
      } catch (error) {
        // 静默处理：浏览器可能阻止未经用户交互的振动调用
        // 这是正常的安全限制，不需要警告
      }
    }

    console.log('所有音频降级方案都失败了')
    return false
  }

  async sendNotification(title, message, options = {}) {
    const results = []

    // 同时执行Web通知和音频播放，确保同步
    const promises = []

    // 显示Web通知
    if (this.config.webEnabled) {
      promises.push(
        this.showNotification(title, message, options).then(notification => ({
          type: 'web',
          success: notification !== null
        }))
      )
    }

    // 播放声音
    if (this.config.soundEnabled) {
      promises.push(
        this.playSound(options.sound).then(soundSuccess => ({
          type: 'sound',
          success: soundSuccess
        }))
      )
    }

    // 等待所有通知方式完成
    if (promises.length > 0) {
      try {
        const promiseResults = await Promise.all(promises)
        results.push(...promiseResults)
      } catch (error) {
        console.warn('通知执行过程中出现错误:', error)
      }
    }

    return results
  }

  showFallbackNotification(title, message, options = {}) {
    // 增强的降级方案：使用多种方式确保用户能收到通知
    console.log(`降级通知: ${title} - ${message}`)

    // 1. 尝试使用页面状态消息
    if (typeof showStatus === 'function') {
      showStatus(`${title}: ${message}`, 'info')
    }

    // 2. 尝试使用浏览器标题闪烁
    this.flashTitle(title)

    // 3. 尝试使用页面内弹窗（如果没有其他方式）
    if (!this.isSupported || this.permission === 'denied') {
      this.showInPageNotification(title, message, options)
    }

    // 4. 尝试使用控制台样式输出
    console.log(`%c🔔 ${title}`, 'color: #0084ff; font-weight: bold; font-size: 14px;')
    console.log(`%c${message}`, 'color: #666; font-size: 12px;')

    // 5. 记录降级事件用于统计
    this.recordFallbackEvent('notification', {
      title,
      message,
      reason: options.reason || 'unknown'
    })
  }

  flashTitle(message) {
    // 标题闪烁提醒
    const originalTitle = document.title
    let flashCount = 0
    const maxFlashes = 6

    const flashInterval = setInterval(() => {
      document.title = flashCount % 2 === 0 ? `🔔 ${message}` : originalTitle
      flashCount++

      if (flashCount >= maxFlashes) {
        clearInterval(flashInterval)
        document.title = originalTitle
      }
    }, 1000)
  }

  updateConfig(newConfig) {
    this.config = { ...this.config, ...newConfig }
    console.log('通知配置已更新:', this.config)
  }

  getStatus() {
    return {
      supported: this.isSupported,
      permission: this.permission,
      audioContext: this.audioContext ? this.audioContext.state : 'unavailable',
      config: this.config
    }
  }

  showInPageNotification(title, message, options = {}) {
    // 创建页面内通知元素
    // 使用安全的通知创建方法
    const notification = DOMSecurity.createNotification(title, message)

    // 添加CSS类
    notification.classList.add('in-page-notification')

    // 获取内容元素（CSS样式已在样式表中定义）
    const titleEl = notification.querySelector('.in-page-notification-title')
    const messageEl = notification.querySelector('.in-page-notification-message')
    const closeEl = notification.querySelector('.in-page-notification-close')

    // 添加到页面
    document.body.appendChild(notification)

    // 关闭按钮事件
    closeEl.addEventListener('click', () => {
      notification.classList.add('hide')
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification)
        }
      }, 300)
    })

    // 入场动画
    setTimeout(() => {
      notification.classList.add('show')
    }, 10)

    // 自动关闭
    setTimeout(() => {
      if (notification.parentNode) {
        closeEl.click()
      }
    }, options.timeout || 5000)

    return notification
  }

  recordFallbackEvent(type, data) {
    // 记录降级事件用于分析和改进
    const event = {
      type,
      data,
      timestamp: Date.now(),
      userAgent: navigator.userAgent,
      url: window.location.href
    }

    // 性能优化：存储到本地存储（用于调试）
    try {
      const storageKey = 'ai-intervention-fallback-events'
      const events = JSON.parse(localStorage.getItem(storageKey) || '[]')

      // 性能优化：清理过期事件（保留7天）
      const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
      const validEvents = events.filter(e => e.timestamp > sevenDaysAgo)

      validEvents.push(event)

      // 性能优化：只保留最近50个事件（从100减少到50）
      if (validEvents.length > 50) {
        validEvents.splice(0, validEvents.length - 50)
      }

      localStorage.setItem(storageKey, JSON.stringify(validEvents))

      // 性能优化：监控存储空间使用
      this.monitorLocalStorageUsage(storageKey)
    } catch (error) {
      console.warn('无法记录降级事件:', error)
      // 如果存储失败，尝试清理存储空间
      this.cleanupLocalStorage()
    }

    if (this.config.debug) {
      console.log('降级事件记录:', event)
    }
  }

  // 性能优化：监控localStorage使用情况
  monitorLocalStorageUsage(key) {
    try {
      const data = localStorage.getItem(key)
      if (data) {
        const sizeInBytes = new Blob([data]).size
        const sizeInKB = (sizeInBytes / 1024).toFixed(2)

        if (sizeInBytes > 100 * 1024) {
          // 超过100KB时警告
          console.warn(`localStorage事件记录过大: ${sizeInKB}KB，建议清理`)
        }

        if (this.config.debug) {
          console.log(`localStorage事件记录大小: ${sizeInKB}KB`)
        }
      }
    } catch (error) {
      console.warn('无法监控localStorage使用情况:', error)
    }
  }

  // 性能优化：清理localStorage
  cleanupLocalStorage() {
    try {
      const storageKey = 'ai-intervention-fallback-events'
      const events = JSON.parse(localStorage.getItem(storageKey) || '[]')

      // 只保留最近24小时的事件
      const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000
      const recentEvents = events.filter(e => e.timestamp > oneDayAgo)

      // 进一步限制到最多20个事件
      if (recentEvents.length > 20) {
        recentEvents.splice(0, recentEvents.length - 20)
      }

      localStorage.setItem(storageKey, JSON.stringify(recentEvents))
      console.log(`localStorage清理完成，保留 ${recentEvents.length} 个事件`)
    } catch (error) {
      console.error('localStorage清理失败:', error)
      // 最后手段：清空事件记录
      try {
        localStorage.removeItem('ai-intervention-fallback-events')
        console.log('已清空localStorage事件记录')
      } catch (clearError) {
        console.error('无法清空localStorage:', clearError)
      }
    }
  }
}

// 创建全局通知管理器实例
const notificationManager = new NotificationManager()

// 设置管理器
class SettingsManager {
  constructor() {
    this.storageKey = 'ai-intervention-agent-settings'
    this.defaultSettings = {
      enabled: true,
      webEnabled: true,
      autoRequestPermission: true,
      soundEnabled: true,
      soundMute: false,
      soundVolume: 80,
      mobileOptimized: true,
      mobileVibrate: true,
      barkEnabled: false,
      barkUrl: 'https://api.day.app/push',
      barkDeviceKey: '',
      barkIcon: '',
      barkAction: 'none'
    }
    this.init()
  }

  async init() {
    this.settings = await this.loadSettings()
    this.initEventListeners()
  }

  async loadSettings() {
    try {
      // 优先从服务器加载配置
      const response = await fetch('/api/get-notification-config')
      if (response.ok) {
        const result = await response.json()
        if (result.status === 'success') {
          // 将服务器配置映射到前端格式
          const serverConfig = result.config
          const settings = {
            enabled: serverConfig.enabled ?? this.defaultSettings.enabled,
            webEnabled: serverConfig.web_enabled ?? this.defaultSettings.webEnabled,
            autoRequestPermission:
              serverConfig.auto_request_permission ?? this.defaultSettings.autoRequestPermission,
            soundEnabled: serverConfig.sound_enabled ?? this.defaultSettings.soundEnabled,
            soundMute: serverConfig.sound_mute ?? this.defaultSettings.soundMute,
            soundVolume: serverConfig.sound_volume ?? this.defaultSettings.soundVolume,
            mobileOptimized: serverConfig.mobile_optimized ?? this.defaultSettings.mobileOptimized,
            mobileVibrate: serverConfig.mobile_vibrate ?? this.defaultSettings.mobileVibrate,
            barkEnabled: serverConfig.bark_enabled ?? this.defaultSettings.barkEnabled,
            barkUrl: serverConfig.bark_url ?? this.defaultSettings.barkUrl,
            barkDeviceKey: serverConfig.bark_device_key ?? this.defaultSettings.barkDeviceKey,
            barkIcon: serverConfig.bark_icon ?? this.defaultSettings.barkIcon,
            barkAction: serverConfig.bark_action ?? this.defaultSettings.barkAction
          }
          console.log('从服务器加载配置成功')
          return settings
        }
      }
    } catch (error) {
      console.warn('从服务器加载配置失败，尝试localStorage:', error)
    }

    // 回退到localStorage
    try {
      const stored = localStorage.getItem(this.storageKey)
      if (stored) {
        const parsed = JSON.parse(stored)
        return { ...this.defaultSettings, ...parsed }
      }
    } catch (error) {
      console.warn('加载设置失败，使用默认设置:', error)
    }
    return { ...this.defaultSettings }
  }

  saveSettings() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.settings))
      console.log('设置已保存')
    } catch (error) {
      console.error('保存设置失败:', error)
    }
  }

  updateSetting(key, value) {
    this.settings[key] = value
    this.saveSettings()
    this.applySettings()
    console.log(`设置已更新: ${key} = ${value}`)
  }

  applySettings() {
    // 更新前端通知管理器配置
    if (notificationManager) {
      notificationManager.updateConfig({
        enabled: this.settings.enabled,
        webEnabled: this.settings.webEnabled,
        autoRequestPermission: this.settings.autoRequestPermission,
        soundEnabled: this.settings.soundEnabled,
        soundMute: this.settings.soundMute,
        soundVolume: this.settings.soundVolume / 100,
        mobileOptimized: this.settings.mobileOptimized,
        mobileVibrate: this.settings.mobileVibrate,
        barkEnabled: this.settings.barkEnabled,
        barkUrl: this.settings.barkUrl,
        barkDeviceKey: this.settings.barkDeviceKey,
        barkIcon: this.settings.barkIcon,
        barkAction: this.settings.barkAction
      })
    }

    // 同步配置到后端
    this.syncConfigToBackend()
  }

  async syncConfigToBackend() {
    try {
      const response = await fetch('/api/update-notification-config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(this.settings)
      })

      const result = await response.json()
      if (response.ok && result.status === 'success') {
        console.log('后端通知配置已同步')
      } else {
        console.warn('同步后端配置失败:', result.message)
      }
    } catch (error) {
      console.error('同步后端配置失败:', error)
    }
  }

  resetSettings() {
    this.settings = { ...this.defaultSettings }
    this.saveSettings()
    this.updateUI()
    this.applySettings()
    console.log('设置已重置为默认值')
  }

  updateUI() {
    // 更新设置面板中的控件状态
    document.getElementById('notification-enabled').checked = this.settings.enabled
    document.getElementById('web-notification-enabled').checked = this.settings.webEnabled
    document.getElementById('auto-request-permission').checked = this.settings.autoRequestPermission
    document.getElementById('sound-notification-enabled').checked = this.settings.soundEnabled
    document.getElementById('sound-mute').checked = this.settings.soundMute
    document.getElementById('sound-volume').value = this.settings.soundVolume
    document.querySelector('.volume-value').textContent = `${this.settings.soundVolume}%`
    document.getElementById('mobile-optimized').checked = this.settings.mobileOptimized
    document.getElementById('mobile-vibrate').checked = this.settings.mobileVibrate

    // 更新 Bark 设置
    document.getElementById('bark-notification-enabled').checked = this.settings.barkEnabled
    document.getElementById('bark-url').value = this.settings.barkUrl
    document.getElementById('bark-device-key').value = this.settings.barkDeviceKey
    document.getElementById('bark-icon').value = this.settings.barkIcon
    document.getElementById('bark-action').value = this.settings.barkAction
  }

  updateStatus() {
    // 更新状态信息
    const browserSupport = notificationManager.isSupported ? '✅ 支持' : '❌ 不支持'
    const permission =
      notificationManager.permission === 'granted'
        ? '✅ 已授权'
        : notificationManager.permission === 'denied'
        ? '❌ 已拒绝'
        : '⚠️ 未请求'

    // 音频状态中文化
    let audioState = '❌ 不可用'
    if (notificationManager.audioContext) {
      const state = notificationManager.audioContext.state
      switch (state) {
        case 'running':
          audioState = '✅ 运行中'
          break
        case 'suspended':
          audioState = '⏸️ 已暂停'
          break
        case 'closed':
          audioState = '❌ 已关闭'
          break
        default:
          audioState = `⚠️ ${state}`
      }
    }

    document.getElementById('browser-support-status').textContent = browserSupport
    document.getElementById('notification-permission-status').textContent = permission
    document.getElementById('audio-status').textContent = audioState
  }

  initEventListeners() {
    // 设置按钮点击事件
    document.addEventListener('click', e => {
      if (e.target.id === 'settings-btn') {
        this.showSettings()
      } else if (e.target.id === 'settings-close-btn') {
        this.hideSettings()
      } else if (e.target.id === 'test-notification-btn') {
        this.testNotification()
      } else if (e.target.id === 'test-bark-notification-btn') {
        this.testBarkNotification()
      } else if (e.target.id === 'reset-settings-btn') {
        this.resetSettings()
      }
    })

    // 设置面板背景点击关闭
    document.addEventListener('click', e => {
      if (e.target.id === 'settings-panel') {
        this.hideSettings()
      }
    })

    // 设置项变更事件
    document.addEventListener('change', e => {
      const settingMap = {
        'notification-enabled': 'enabled',
        'web-notification-enabled': 'webEnabled',
        'auto-request-permission': 'autoRequestPermission',
        'sound-notification-enabled': 'soundEnabled',
        'sound-mute': 'soundMute',
        'mobile-optimized': 'mobileOptimized',
        'mobile-vibrate': 'mobileVibrate',
        'bark-notification-enabled': 'barkEnabled'
      }

      if (settingMap[e.target.id]) {
        this.updateSetting(settingMap[e.target.id], e.target.checked)
      } else if (e.target.id === 'sound-volume') {
        this.updateSetting('soundVolume', parseInt(e.target.value))
        document.querySelector('.volume-value').textContent = `${e.target.value}%`
      } else if (e.target.id === 'bark-url') {
        this.updateSetting('barkUrl', e.target.value)
      } else if (e.target.id === 'bark-device-key') {
        this.updateSetting('barkDeviceKey', e.target.value)
      } else if (e.target.id === 'bark-icon') {
        this.updateSetting('barkIcon', e.target.value)
      } else if (e.target.id === 'bark-action') {
        this.updateSetting('barkAction', e.target.value)
      }
    })
  }

  showSettings() {
    this.updateUI()
    this.updateStatus()
    // 同步当前设置到后端
    this.syncConfigToBackend()
    const panel = document.getElementById('settings-panel')
    panel.classList.add('show')
    panel.classList.remove('hidden')
  }

  hideSettings() {
    const panel = document.getElementById('settings-panel')
    panel.classList.remove('show')
    panel.classList.add('hidden')
  }

  async testNotification() {
    try {
      await notificationManager.sendNotification(
        '设置测试',
        '这是一个测试通知，用于验证当前设置是否正常工作',
        {
          tag: 'settings-test',
          requireInteraction: false
        }
      )
      showStatus('测试通知已发送', 'success')
    } catch (error) {
      console.error('测试通知失败:', error)
      showStatus('测试通知失败: ' + error.message, 'error')
    }
  }

  async testBarkNotification() {
    try {
      if (!this.settings.barkEnabled) {
        showStatus('请先启用 Bark 通知', 'warning')
        return
      }

      if (!this.settings.barkUrl || !this.settings.barkDeviceKey) {
        showStatus('请先配置 Bark URL 和 Device Key', 'warning')
        return
      }

      // 显示发送中状态
      showStatus('正在发送 Bark 测试通知...', 'info')

      // 通过后端API发送Bark通知，避免CORS问题
      const response = await fetch('/api/test-bark', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          bark_url: this.settings.barkUrl,
          bark_device_key: this.settings.barkDeviceKey,
          bark_icon: this.settings.barkIcon,
          bark_action: this.settings.barkAction
        })
      })

      const result = await response.json()

      if (response.ok && result.status === 'success') {
        showStatus(result.message, 'success')
        console.log('Bark 通知发送成功:', result)
      } else {
        showStatus(result.message || 'Bark 通知发送失败', 'error')
        console.error('Bark 通知发送失败:', result)
      }
    } catch (error) {
      console.error('Bark 测试通知失败:', error)
      showStatus('Bark 测试通知失败: ' + error.message, 'error')
    }
  }
}

// 创建全局设置管理器实例
const settingsManager = new SettingsManager()

// 性能优化工具函数

/**
 * 防抖函数
 * 延迟执行，只在最后一次调用后执行
 *
 * @param {Function} func - 待防抖的函数
 * @param {number} wait - 延迟时间（毫秒）
 * @returns {Function} 防抖后的函数
 * @description
 * - 多次调用只执行最后一次
 * - 常用于搜索框输入、窗口resize
 * - 避免频繁触发高成本操作
 */
function debounce(func, wait) {
  let timeout
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout)
      func(...args)
    }
    clearTimeout(timeout)
    timeout = setTimeout(later, wait)
  }
}

/**
 * 节流函数
 * 限制函数调用频率，性能优化
 *
 * @param {Function} func - 待节流的函数
 * @param {number} limit - 节流时间间隔（毫秒）
 * @returns {Function} 节流后的函数
 * @description 在limit时间内只执行一次，常用于高频事件（scroll、resize、drag）
 */
function throttle(func, limit) {
  let inThrottle
  return function (...args) {
    if (!inThrottle) {
      func.apply(this, args)
      inThrottle = true
      setTimeout(() => (inThrottle = false), limit)
    }
  }
}

/**
 * RAF优化的更新函数
 * 使用requestAnimationFrame优化DOM更新性能
 *
 * @param {Function} callback - 更新回调
 * @description 优先使用RAF，降级使用setTimeout（60fps）
 */
function rafUpdate(callback) {
  if (window.requestAnimationFrame) {
    requestAnimationFrame(callback)
  } else {
    setTimeout(callback, 16) // 降级为60fps
  }
}

// 支持的图片格式
const SUPPORTED_IMAGE_TYPES = [
  'image/jpeg',
  'image/jpg',
  'image/png',
  'image/gif',
  'image/webp',
  'image/bmp',
  'image/svg+xml'
]
const MIN_IMAGE_SIZE = 100 // 100字节（防止空文件/损坏文件）
const MAX_IMAGE_SIZE = 10 * 1024 * 1024 // 10MB
const MAX_IMAGE_COUNT = 10
const MAX_IMAGE_DIMENSION = 1920 // 最大宽度或高度
const COMPRESS_QUALITY = 0.8 // 压缩质量 (0.1-1.0)

/**
 * 验证图片文件
 * 执行多层安全验证（类型、大小、文件名、可疑扩展）
 *
 * @param {File} file - 待验证的文件对象
 * @returns {string[]} 错误消息数组，空数组表示验证通过
 * @description
 * 验证项：
 * - 文件对象有效性
 * - 类型白名单（SUPPORTED_IMAGE_TYPES）
 * - 大小范围（100B - 10MB）
 * - 文件名长度（≤255字符）
 * - 可疑扩展名检测（.exe, .bat等）
 */
function validateImageFile(file) {
  const errors = []

  // 基础文件检查
  if (!file || !file.type) {
    errors.push('无效的文件对象')
    return errors
  }

  // 文件类型验证
  if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errors.push(`不支持的文件格式: ${file.type}`)
  }

  // 文件大小验证
  if (file.size < MIN_IMAGE_SIZE) {
    errors.push(`文件太小，可能是空文件或损坏文件: ${file.size}字节 < ${MIN_IMAGE_SIZE}字节`)
  }

  if (file.size > MAX_IMAGE_SIZE) {
    errors.push(`文件大小超过限制: ${(file.size / 1024 / 1024).toFixed(2)}MB > 10MB`)
  }

  // 文件名验证（防止XSS）
  if (file.name && file.name.length > 255) {
    errors.push('文件名过长')
  }

  // 基本安全检查
  const suspiciousExtensions = [
    '.exe',
    '.bat',
    '.cmd',
    '.scr',
    '.com',
    '.pif',
    '.vbs',
    '.js',
    '.jar'
  ]
  if (suspiciousExtensions.some(ext => file.name.toLowerCase().endsWith(ext))) {
    errors.push('检测到可疑文件类型')
  }

  return errors
}

/**
 * 安全的文件名清理
 * 移除特殊字符，防止XSS和文件系统攻击
 *
 * @param {string} fileName - 原始文件名
 * @returns {string} 清理后的安全文件名
 * @description 清理规则：移除<>:"/\|?*，空格转下划线，限制100字符
 */
function sanitizeFileName(fileName) {
  return fileName
    .replace(/[<>:"/\\|?*]/g, '') // 移除特殊字符
    .replace(/\s+/g, '_') // 空格替换为下划线
    .trim()
    .substring(0, 100) // 限制长度
}

// 注意：已移除 fileToBase64 函数，现在直接使用文件对象上传

// 改进的内存管理跟踪：防止内存泄漏
let objectURLs = new Set()
let urlToFileMap = new WeakMap() // 使用WeakMap跟踪URL与文件的关联
let urlCreationTime = new Map() // 跟踪URL创建时间，用于自动清理
let urlCleanupTimer = null

/**
 * 创建安全的Object URL
 * 为文件创建临时URL并跟踪，防止内存泄漏
 *
 * @param {File|Blob} file - 文件或Blob对象
 * @returns {string|null} 对象URL，失败返回null
 * @description 自动跟踪URL生命周期，30分钟后自动清理未释放的URL
 */
function createObjectURL(file) {
  try {
    const url = URL.createObjectURL(file)
    objectURLs.add(url)
    urlToFileMap.set(file, url)
    urlCreationTime.set(url, Date.now())

    // 设置自动清理定时器（30分钟后自动清理）
    setTimeout(() => {
      if (objectURLs.has(url)) {
        console.warn(`自动清理过期的URL对象: ${url}`)
        revokeObjectURL(url)
      }
    }, 30 * 60 * 1000) // 30分钟

    return url
  } catch (error) {
    console.error('创建Object URL失败:', error)
    return null
  }
}

/**
 * 清理Object URL
 * 释放单个Blob URL并从跟踪集合中移除
 *
 * @param {string} url - 待释放的Object URL
 * @description
 * - 释放Blob URL
 * - 从跟踪集合移除
 * - 防止内存泄漏
 * - 安全处理无效URL
 */
function revokeObjectURL(url) {
  if (!url) return

  try {
    if (objectURLs.has(url)) {
      URL.revokeObjectURL(url)
      objectURLs.delete(url)
      urlCreationTime.delete(url)
      console.debug(`已清理URL对象: ${url}`)
    }
  } catch (error) {
    console.error('清理URL对象失败:', error)
  }
}

// 清理所有Object URLs
/**
 * 清理所有已创建的Object URLs
 * 释放所有Blob URL并清除定时器
 *
 * @description
 * - 遍历释放所有URL
 * - 清除跟踪Map
 * - 停止定期清理定时器
 * - 记录性能指标
 */
function cleanupAllObjectURLs() {
  console.log(`开始清理 ${objectURLs.size} 个URL对象`)
  const startTime = performance.now()

  objectURLs.forEach(url => {
    try {
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error(`清理URL失败: ${url}`, error)
    }
  })

  objectURLs.clear()
  urlCreationTime.clear()

  // 清除定期清理定时器
  if (urlCleanupTimer) {
    clearInterval(urlCleanupTimer)
    urlCleanupTimer = null
  }

  const endTime = performance.now()
  console.log(`URL对象清理完成，耗时: ${(endTime - startTime).toFixed(2)}ms`)
}

/**
 * 定期清理过期的URL对象
 * 每5分钟检查并释放超过20分钟的Object URL
 *
 * @description 防止长时间运行时的内存泄漏，自动管理URL生命周期
 */
function startPeriodicCleanup() {
  // 清除旧的定时器
  if (urlCleanupTimer) {
    clearInterval(urlCleanupTimer)
  }

  // 保存新的定时器ID
  urlCleanupTimer = setInterval(() => {
    const now = Date.now()
    const expiredUrls = []

    urlCreationTime.forEach((creationTime, url) => {
      // 清理超过20分钟的URL对象
      if (now - creationTime > 20 * 60 * 1000) {
        expiredUrls.push(url)
      }
    })

    if (expiredUrls.length > 0) {
      console.log(`定期清理 ${expiredUrls.length} 个过期URL对象`)
      expiredUrls.forEach(url => revokeObjectURL(url))
    }
  }, 5 * 60 * 1000) // 每5分钟检查一次
}

/**
 * 优化的图片压缩函数
 * 智能压缩图片，根据文件大小自适应压缩策略
 *
 * @param {File} file - 原始图片文件
 * @returns {Promise<File>} 压缩后的文件（如果压缩失败或无需压缩则返回原文件）
 * @description
 * - SVG和GIF不压缩
 * - 大文件（>5MB）使用更激进的压缩
 * - 自动调整尺寸（≤1920px）和质量
 * - 使用RAF优化，避免阻塞UI
 */
function compressImage(file) {
  return new Promise(resolve => {
    // SVG 图片和 GIF 不进行压缩
    if (file.type === 'image/svg+xml' || file.type === 'image/gif') {
      resolve(file)
      return
    }

    // 大文件使用分步压缩
    const isLargeFile = file.size > 5 * 1024 * 1024 // 5MB

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d', {
      alpha: file.type === 'image/png',
      willReadFrequently: false
    })
    const img = new Image()

    const objectURL = createObjectURL(file)

    img.onload = () => {
      // 计算压缩后的尺寸
      let { width, height } = img
      const originalArea = width * height

      // 大图片使用更激进的压缩
      let maxDimension = MAX_IMAGE_DIMENSION
      if (isLargeFile || originalArea > 4000000) {
        // 4MP
        maxDimension = Math.min(MAX_IMAGE_DIMENSION, 1200)
      }

      if (width > maxDimension || height > maxDimension) {
        const ratio = Math.min(maxDimension / width, maxDimension / height)
        width = Math.floor(width * ratio)
        height = Math.floor(height * ratio)
      }

      canvas.width = width
      canvas.height = height

      // 优化的绘制设置
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'

      // 使用RAF进行非阻塞绘制
      rafUpdate(() => {
        ctx.drawImage(img, 0, 0, width, height)

        // 根据文件大小调整压缩质量
        let quality = COMPRESS_QUALITY
        if (isLargeFile) {
          quality = Math.max(0.6, COMPRESS_QUALITY - 0.2)
        }

        // 转换为 Blob
        canvas.toBlob(
          blob => {
            // 清理资源
            revokeObjectURL(objectURL)

            if (blob && blob.size < file.size) {
              const compressedFile = new File([blob], file.name, {
                type: file.type,
                lastModified: file.lastModified
              })
              console.log(
                `图片压缩: ${file.name} ${(file.size / 1024).toFixed(2)}KB → ${(
                  blob.size / 1024
                ).toFixed(2)}KB (压缩率: ${((1 - blob.size / file.size) * 100).toFixed(1)}%)`
              )
              resolve(compressedFile)
            } else {
              resolve(file)
            }
          },
          file.type === 'image/png' ? 'image/png' : 'image/jpeg',
          quality
        )
      })
    }

    img.onerror = () => {
      revokeObjectURL(objectURL)
      resolve(file)
    }

    img.src = objectURL
  })
}

/**
 * 添加图片到列表
 * 验证、压缩并添加图片到selectedImages数组
 *
 * @param {File} file - 图片文件对象
 * @returns {Promise<boolean>} 成功返回true，失败返回false
 * @description
 * 处理流程：
 * 1. 验证数量限制（≤10张）
 * 2. 验证文件（类型、大小、安全性）
 * 3. 检查重复
 * 4. 压缩图片
 * 5. 创建预览URL
 * 6. 渲染预览
 */
async function addImageToList(file) {
  // 验证图片数量
  if (selectedImages.length >= MAX_IMAGE_COUNT) {
    showStatus(`最多只能上传 ${MAX_IMAGE_COUNT} 张图片`, 'error')
    return false
  }

  // 验证文件
  const errors = validateImageFile(file)
  if (errors.length > 0) {
    showStatus(errors.join('; '), 'error')
    return false
  }

  // 检查是否已经添加过相同文件
  const isDuplicate = selectedImages.some(
    img =>
      img.name === file.name && img.size === file.size && img.lastModified === file.lastModified
  )
  if (isDuplicate) {
    showStatus('该图片已经添加过了', 'error')
    return false
  }

  const imageId = Date.now() + Math.random()
  const timestamp = Date.now()

  try {
    // 创建加载占位符
    const imageItem = {
      id: imageId,
      file: file,
      name: file.name,
      size: file.size,
      base64: null,
      timestamp: timestamp,
      lastModified: file.lastModified
    }

    selectedImages.push(imageItem)
    renderImagePreview(imageItem, true) // true表示显示加载状态
    updateImageCounter()

    // 压缩图片（如果需要）
    const processedFile = await compressImage(file)

    // 更新文件信息
    imageItem.file = processedFile
    imageItem.size = processedFile.size

    // 创建安全的预览 URL
    const previewUrl = createObjectURL(processedFile)
    if (previewUrl) {
      imageItem.previewUrl = previewUrl
    } else {
      throw new Error('创建预览URL失败')
    }

    // 更新预览
    renderImagePreview(imageItem, false)

    console.log('图片添加成功:', file.name, `(${(imageItem.size / 1024).toFixed(2)}KB)`)
    return true
  } catch (error) {
    console.error('图片处理失败:', error)
    showStatus('图片处理失败: ' + error.message, 'error')
    // 从列表中移除失败的图片
    selectedImages = selectedImages.filter(img => img.id !== imageId)
    updateImageCounter()
    return false
  }
}

// 批量DOM更新队列
let domUpdateQueue = []
let domUpdateScheduled = false

/**
 * 批量处理DOM更新
 * 将多个DOM操作合并到一个RAF周期内执行
 *
 * @param {Function} callback - DOM更新回调函数
 * @description
 * - 收集多个更新操作到队列
 * - 使用RAF批量执行，减少重排重绘
 * - 使用DocumentFragment优化性能
 * - 避免DOM抖动和卡顿
 */
function scheduleDOMUpdate(callback) {
  domUpdateQueue.push(callback)
  if (!domUpdateScheduled) {
    domUpdateScheduled = true
    rafUpdate(() => {
      const fragment = document.createDocumentFragment()
      domUpdateQueue.forEach(callback => callback(fragment))
      domUpdateQueue = []
      domUpdateScheduled = false
    })
  }
}

/**
 * 优化的图片预览渲染
 * 使用RAF和安全DOM操作渲染图片预览
 *
 * @param {Object} imageItem - 图片对象（包含id, name, size, previewUrl等）
 * @param {boolean} isLoading - 是否显示加载状态（默认false）
 * @description
 * - 使用RAF优化性能，避免阻塞
 * - 通过DOMSecurity确保安全
 * - 延迟加载图片
 * - 支持加载状态显示
 */
function renderImagePreview(imageItem, isLoading = false) {
  rafUpdate(() => {
    const previewContainer = document.getElementById('image-previews')
    let previewElement = document.getElementById(`preview-${imageItem.id}`)

    if (!previewElement) {
      previewElement = document.createElement('div')
      previewElement.id = `preview-${imageItem.id}`
      previewElement.className = 'image-preview-item'
      previewContainer.appendChild(previewElement)
    }

    // 使用安全的图片预览创建方法
    const newPreviewElement = DOMSecurity.createImagePreview(imageItem, isLoading)
    DOMSecurity.replaceContent(previewElement, newPreviewElement.firstChild || newPreviewElement)

    if (!isLoading && imageItem.previewUrl) {
      // 延迟加载图片以优化性能
      const img = new Image()
      img.onload = () => {
        rafUpdate(() => {
          const updatedPreviewElement = DOMSecurity.createImagePreview(imageItem, false)
          DOMSecurity.replaceContent(
            previewElement,
            updatedPreviewElement.firstChild || updatedPreviewElement
          )
        })
      }
      img.src = imageItem.previewUrl
    }
  })
}

/**
 * 文本安全化函数
 * 防止XSS攻击，将文本转义为安全HTML
 *
 * @param {string} text - 待清理的文本
 * @returns {string} 转义后的安全HTML
 * @description 使用textContent确保特殊字符被正确转义
 */
function sanitizeText(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

/**
 * 删除图片
 * 从列表中移除图片并释放相关资源
 *
 * @param {number|string} imageId - 图片ID
 * @description
 * - 释放Blob URL避免内存泄漏
 * - 移除DOM元素
 * - 更新计数器和可见性
 */
function removeImage(imageId) {
  // 找到要删除的图片并安全释放 URL
  const imageToRemove = selectedImages.find(img => img.id == imageId)
  if (imageToRemove && imageToRemove.previewUrl && imageToRemove.previewUrl.startsWith('blob:')) {
    revokeObjectURL(imageToRemove.previewUrl)
  }

  selectedImages = selectedImages.filter(img => img.id != imageId)
  const previewElement = document.getElementById(`preview-${imageId}`)
  if (previewElement) {
    previewElement.remove()
  }
  updateImageCounter()
  updateImagePreviewVisibility()
}

/**
 * 清除所有图片
 * 移除所有图片并释放所有相关资源
 *
 * @description
 * - 释放所有Blob URL
 * - 清空selectedImages数组
 * - 清理DOM
 * - 尝试触发垃圾回收（开发环境）
 */
function clearAllImages() {
  // 清理内存中的 Object URLs
  selectedImages.forEach(img => {
    if (img.previewUrl && img.previewUrl.startsWith('blob:')) {
      revokeObjectURL(img.previewUrl)
    }
  })

  selectedImages = []
  const previewContainer = document.getElementById('image-previews')
  // 安全清空容器内容
  DOMSecurity.clearContent(previewContainer)
  updateImageCounter()
  updateImagePreviewVisibility()

  // 强制垃圾回收提示（仅在开发环境）
  if (window.gc && typeof window.gc === 'function') {
    setTimeout(() => window.gc(), 1000)
  }

  console.log('所有图片已清除，内存已释放')
}

/**
 * 页面卸载时的清理
 * 在页面关闭或刷新时释放所有资源
 *
 * @description
 * - 清理所有Object URLs
 * - 清除所有图片数据
 * - 防止内存泄漏
 * - 绑定到beforeunload事件
 */
function cleanupOnUnload() {
  cleanupAllObjectURLs()
  clearAllImages()
}

// 监听页面卸载事件
window.addEventListener('beforeunload', cleanupOnUnload)
window.addEventListener('pagehide', cleanupOnUnload)

/**
 * 更新图片计数
 * 显示当前已选图片数量
 *
 * @description 更新页面上的图片计数器显示
 */
function updateImageCounter() {
  const countElement = document.getElementById('image-count')
  if (countElement) {
    countElement.textContent = selectedImages.length
  }
}

/**
 * 更新图片预览区域可见性
 * 根据图片数量控制预览容器的显示/隐藏
 *
 * @description 有图片时显示容器，无图片时隐藏
 */
function updateImagePreviewVisibility() {
  const container = document.getElementById('image-preview-container')
  if (selectedImages.length > 0) {
    container.classList.remove('hidden')
    container.classList.add('visible')
  } else {
    container.classList.add('hidden')
    container.classList.remove('visible')
  }
}

/**
 * 优化的批量文件处理
 * 并发处理多个文件上传，带进度反馈
 *
 * @param {FileList|File[]} files - 文件列表
 * @returns {Promise<void>}
 * @description
 * - 预检查数量限制
 * - 限制并发数（3个）
 * - 显示处理进度
 * - 批量统计成功/失败
 */
async function handleFileUpload(files) {
  const fileArray = Array.from(files)

  // 预检查防止超过数量限制
  const totalCount = selectedImages.length + fileArray.length
  if (totalCount > MAX_IMAGE_COUNT) {
    showStatus(
      `最多只能上传 ${MAX_IMAGE_COUNT} 张图片（当前 ${selectedImages.length} 张，尝试添加 ${fileArray.length} 张）`,
      'error'
    )
    return
  }

  const maxConcurrent = 3 // 限制并发处理数量
  let processed = 0
  let successful = 0

  // 显示批量处理进度
  if (fileArray.length > 1) {
    showStatus(`正在处理 ${fileArray.length} 个文件...`, 'info')
  }

  // 分批处理文件，避免内存溢出
  for (let i = 0; i < fileArray.length; i += maxConcurrent) {
    const batch = fileArray.slice(i, i + maxConcurrent)

    const batchPromises = batch.map(async file => {
      try {
        const success = await addImageToList(file)
        if (success) successful++
        processed++

        // 更新进度
        if (fileArray.length > 1) {
          showStatus(`处理进度: ${processed}/${fileArray.length}`, 'info')
        }

        return success
      } catch (error) {
        console.error('文件处理失败:', file.name, error)
        processed++
        return false
      }
    })

    // 等待当前批次完成
    await Promise.all(batchPromises)

    // 批次间添加小延迟，避免阻塞UI
    if (i + maxConcurrent < fileArray.length) {
      await new Promise(resolve => setTimeout(resolve, 50))
    }
  }

  updateImagePreviewVisibility()

  // 显示最终结果
  if (fileArray.length > 1) {
    showStatus(
      `完成处理: ${successful}/${fileArray.length} 个文件成功`,
      successful > 0 ? 'success' : 'error'
    )
  } else if (fileArray.length === 1) {
    showStatus(
      successful > 0 ? '文件处理成功' : '文件处理失败',
      successful > 0 ? 'success' : 'error'
    )
  }
}

// 优化的拖放功能实现
/**
 * 初始化拖拽功能
 * 支持拖拽文件到页面上传
 *
 * @description
 * - 阻止默认拖拽行为
 * - 显示拖拽遮罩层
 * - 使用节流优化性能
 * - 支持文件数量预检查
 */
function initializeDragAndDrop() {
  const textarea = document.getElementById('feedback-text')
  const dragOverlay = document.getElementById('drag-overlay')
  let dragCounter = 0
  let dragTimer = null

  // 阻止默认的拖放行为
  ;['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    document.addEventListener(eventName, preventDefaults, { passive: false })
  })

  /**
   * 阻止默认行为
   * 阻止浏览器默认的拖拽行为（如打开文件）
   *
   * @param {DragEvent} e - 拖拽事件
   * @description
   * - 阻止默认行为（打开文件等）
   * - 停止事件冒泡
   * - 确保自定义拖拽逻辑生效
   */
  function preventDefaults(e) {
    e.preventDefault()
    e.stopPropagation()
  }

  // 节流的拖拽处理函数
  const throttledDragEnter = throttle(e => {
    dragCounter++
    if (e.dataTransfer.types.includes('Files')) {
      rafUpdate(() => {
        dragOverlay.classList.remove('hidden')
        dragOverlay.classList.add('flex-visible')
        textarea.classList.add('textarea-drag-over')
      })
    }
  }, 100)

  const throttledDragLeave = throttle(e => {
    dragCounter--
    if (dragCounter <= 0) {
      dragCounter = 0
      clearTimeout(dragTimer)
      dragTimer = setTimeout(() => {
        rafUpdate(() => {
          dragOverlay.classList.add('hidden')
          dragOverlay.classList.remove('flex-visible')
          textarea.classList.remove('textarea-drag-over')
        })
      }, 100)
    }
  }, 50)

  const throttledDragOver = throttle(e => {
    if (e.dataTransfer.types.includes('Files')) {
      e.dataTransfer.dropEffect = 'copy'
    }
  }, 50)

  // 拖拽事件监听
  document.addEventListener('dragenter', throttledDragEnter)
  document.addEventListener('dragleave', throttledDragLeave)
  document.addEventListener('dragover', throttledDragOver)

  // 拖拽放下
  document.addEventListener('drop', function (e) {
    dragCounter = 0
    clearTimeout(dragTimer)

    rafUpdate(() => {
      dragOverlay.classList.add('hidden')
      dragOverlay.classList.remove('flex-visible')
      textarea.classList.remove('textarea-drag-over')
    })

    if (e.dataTransfer.files.length > 0) {
      // 验证文件数量限制
      const totalFiles = selectedImages.length + e.dataTransfer.files.length
      if (totalFiles > MAX_IMAGE_COUNT) {
        showStatus(`最多只能上传 ${MAX_IMAGE_COUNT} 张图片`, 'error')
        return
      }

      handleFileUpload(e.dataTransfer.files)
    }
  })
}

/**
 * 初始化粘贴功能
 * 支持从剪贴板粘贴图片
 *
 * @description
 * - 监听paste事件
 * - 预检查数量限制
 * - 批量处理图片
 * - 显示处理结果
 */
function initializePasteFunction() {
  document.addEventListener('paste', async function (e) {
    const clipboardData = e.clipboardData
    if (!clipboardData) return

    const items = Array.from(clipboardData.items)
    const imageItems = items.filter(item => item.type.startsWith('image/'))

    if (imageItems.length > 0) {
      e.preventDefault() // 阻止默认粘贴行为

      // 预先检查图片数量限制
      const totalCount = selectedImages.length + imageItems.length
      if (totalCount > MAX_IMAGE_COUNT) {
        showStatus(
          `最多只能上传 ${MAX_IMAGE_COUNT} 张图片（当前 ${selectedImages.length} 张，尝试添加 ${imageItems.length} 张）`,
          'error'
        )
        return
      }

      // 统计成功和失败数量
      let successCount = 0
      for (const item of imageItems) {
        const file = item.getAsFile()
        if (file) {
          const success = await addImageToList(file)
          if (success) successCount++
        }
      }

      updateImagePreviewVisibility()
      // 显示添加结果
      if (successCount > 0) {
        showStatus(
          successCount === imageItems.length
            ? `从剪贴板添加了 ${successCount} 张图片`
            : `从剪贴板添加了 ${successCount}/${imageItems.length} 张图片`,
          successCount === imageItems.length ? 'success' : 'warning'
        )
      } else {
        showStatus('图片添加失败', 'error')
      }
    }
  })
}

/**
 * 初始化文件选择功能
 * 绑定上传按钮和文件input事件
 *
 * @description
 * - 点击按钮触发文件选择
 * - 选择后自动上传
 * - 清空input支持重复选择
 */
function initializeFileSelection() {
  const fileInput = document.getElementById('file-upload-input')
  const uploadBtn = document.getElementById('upload-image-btn')

  uploadBtn.addEventListener('click', () => {
    fileInput.click()
  })

  fileInput.addEventListener('change', e => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files)
      // 清空input，允许重复选择相同文件
      e.target.value = ''
    }
  })
}

/**
 * 打开图片模态框
 * 全屏查看图片详情
 *
 * @param {string} base64 - 图片base64或URL
 * @param {string} name - 文件名
 * @param {number} size - 文件大小（字节）
 * @description
 * - 显示图片和信息
 * - 支持ESC键关闭
 * - 点击背景关闭
 */
function openImageModal(base64, name, size) {
  const modal = document.getElementById('image-modal')
  const modalImage = document.getElementById('modal-image')
  const modalInfo = document.getElementById('modal-info')

  modalImage.src = base64
  modalImage.alt = name
  modalInfo.textContent = `${name} (${(size / 1024).toFixed(2)}KB)`

  modal.classList.add('show')

  // 添加键盘事件监听
  document.addEventListener('keydown', handleModalKeydown)

  // 点击模态框背景关闭
  modal.addEventListener('click', function (e) {
    if (e.target === modal) {
      closeImageModal()
    }
  })
}

/**
 * 关闭图片模态框
 * 隐藏模态框并清理事件监听
 *
 * @description 移除键盘事件监听，防止内存泄漏
 */
function closeImageModal() {
  const modal = document.getElementById('image-modal')
  modal.classList.remove('show')

  // 移除键盘事件监听
  document.removeEventListener('keydown', handleModalKeydown)
}

/**
 * 处理模态框键盘事件
 * ESC键关闭模态框
 *
 * @param {KeyboardEvent} event - 键盘事件
 */
function handleModalKeydown(event) {
  if (event.key === 'Escape') {
    closeImageModal()
  }
}

/**
 * 移动设备检测
 * 检测是否为移动设备或平板
 *
 * @returns {boolean} 是否为移动设备
 * @description
 * - 检测UserAgent
 * - 检测触摸点数量（iPad检测）
 */
function isMobileDevice() {
  return (
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints &&
      navigator.maxTouchPoints > 2 &&
      /MacIntel/.test(navigator.platform))
  )
}

/**
 * 平台检测
 * 检测操作系统类型（Mac/Windows/Linux）
 *
 * @returns {string} 平台类型（'mac'/'windows'/'linux'）
 * @description 通过navigator.platform和userAgent检测
 */
function detectPlatform() {
  const platform = navigator.platform.toLowerCase()
  const userAgent = navigator.userAgent.toLowerCase()

  if (platform.includes('mac') || userAgent.includes('mac')) {
    return 'mac'
  } else if (platform.includes('win') || userAgent.includes('win')) {
    return 'windows'
  } else if (platform.includes('linux') || userAgent.includes('linux')) {
    return 'linux'
  }
  return 'windows' // 默认为Windows
}

/**
 * 获取快捷键文本
 * 根据平台返回对应的快捷键说明
 *
 * @param {string} platform - 平台类型
 * @returns {string} 快捷键文本（多行）
 */
function getShortcutText(platform) {
  const shortcuts = {
    mac: [
      '🚀 ⌘+Enter  提交反馈',
      '💻 ⌥+C      插入代码',
      '📋 ⌘+V      粘贴图片',
      '📷 ⌘+U      上传图片',
      '🗑️ Delete   清除图片'
    ],
    windows: [
      '🚀 Ctrl+Enter 提交反馈',
      '💻 Alt+C      插入代码',
      '📋 Ctrl+V     粘贴图片',
      '📷 Ctrl+U     上传图片',
      '🗑️ Delete     清除图片'
    ],
    linux: [
      '🚀 Ctrl+Enter 提交反馈',
      '💻 Alt+C      插入代码',
      '📋 Ctrl+V     粘贴图片',
      '📷 Ctrl+U     上传图片',
      '🗑️ Delete     清除图片'
    ]
  }

  const lines = shortcuts[platform] || shortcuts.windows
  return lines.join('\n')
}

/**
 * 初始化快捷键提示
 * 根据平台显示对应的快捷键说明
 *
 * @description 桌面设备显示快捷键，移动设备隐藏
 */
function initializeShortcutTooltip() {
  // 桌面设备显示快捷键信息
  if (!isMobileDevice()) {
    const platform = detectPlatform()
    updateShortcutDisplay(platform)
    console.log(`检测到桌面平台: ${platform}，已设置对应快捷键`)
  } else {
    console.log('检测到移动设备，已隐藏快捷键部分')
  }
}

/**
 * 更新快捷键显示
 * 更新UI上的快捷键文本
 *
 * @param {string} platform - 平台类型
 * @description 根据平台使用Cmd/Ctrl，Option/Alt
 */
function updateShortcutDisplay(platform) {
  const isMac = platform === 'mac'
  const ctrlOrCmd = isMac ? 'Cmd' : 'Ctrl'
  const altOrOption = isMac ? 'Option' : 'Alt'

  // 更新各个快捷键显示
  const shortcuts = {
    'shortcut-submit': `${ctrlOrCmd}+Enter`,
    'shortcut-code': `${altOrOption}+C`,
    'shortcut-paste': `${ctrlOrCmd}+V`,
    'shortcut-upload': `${ctrlOrCmd}+U`,
    'shortcut-delete': 'Delete'
  }

  Object.entries(shortcuts).forEach(([id, shortcut]) => {
    const element = document.getElementById(id)
    if (element) {
      element.textContent = shortcut
    }
  })
}

/**
 * 浏览器兼容性检测
 * 检查浏览器是否支持所需特性
 *
 * @returns {boolean} 是否兼容
 * @description
 * 检测特性：FileAPI、拖拽、Canvas、WebWorker、RAF、ObjectURL、Clipboard
 */
function checkBrowserCompatibility() {
  const features = {
    fileAPI: !!(window.File && window.FileReader && window.FileList && window.Blob),
    dragDrop: 'ondragstart' in document.createElement('div'),
    canvas: !!document.createElement('canvas').getContext,
    webWorker: !!window.Worker,
    requestAnimationFrame: !!(window.requestAnimationFrame || window.webkitRequestAnimationFrame),
    objectURL: !!(window.URL && window.URL.createObjectURL),
    clipboard: !!(navigator.clipboard && navigator.clipboard.read)
  }

  console.log('浏览器兼容性检测:', features)

  // 关键功能检查
  if (!features.fileAPI) {
    showStatus('您的浏览器不支持文件API，部分功能可能无法使用', 'warning')
    return false
  }

  if (!features.canvas) {
    showStatus('您的浏览器不支持Canvas，图片压缩功能将被禁用', 'warning')
  }

  return true
}

/**
 * 特性降级处理
 * 为旧浏览器提供现代API的Polyfill
 *
 * @description
 * 降级项：
 * - requestAnimationFrame: 降级为多个厂商前缀或setTimeout
 * - Clipboard API: 检测并警告
 * - Object.assign: ES6特性polyfill
 */
function setupFeatureFallbacks() {
  // RAF降级
  if (!window.requestAnimationFrame) {
    window.requestAnimationFrame =
      window.webkitRequestAnimationFrame ||
      window.mozRequestAnimationFrame ||
      window.oRequestAnimationFrame ||
      window.msRequestAnimationFrame ||
      function (callback) {
        return setTimeout(callback, 16)
      }
  }

  // 复制API降级
  if (!navigator.clipboard) {
    console.warn('剪贴板API不可用，使用降级方案')
  }

  // Object.assign降级
  if (!Object.assign) {
    Object.assign = function (target, ...sources) {
      sources.forEach(source => {
        if (source) {
          Object.keys(source).forEach(key => {
            target[key] = source[key]
          })
        }
      })
      return target
    }
  }
}

/**
 * 初始化图片功能
 * 初始化所有图片相关功能（拖拽、粘贴、上传）
 *
 * @description
 * - 兼容性检查
 * - 初始化拖拽、粘贴、文件选择
 * - 绑定按钮事件
 * - 启动URL清理机制
 */
function initializeImageFeatures() {
  // 兼容性检查
  if (!checkBrowserCompatibility()) {
    console.error('浏览器兼容性检查失败')
    return
  }

  // 设置降级处理
  setupFeatureFallbacks()

  try {
    initializeDragAndDrop()
    initializePasteFunction()
    initializeFileSelection()

    // 清除所有图片按钮事件
    const clearBtn = document.getElementById('clear-all-images-btn')
    if (clearBtn) {
      clearBtn.addEventListener('click', clearAllImages)
    }

    console.log('图片功能初始化完成')
  } catch (error) {
    console.error('图片功能初始化失败:', error)
    showStatus('图片功能初始化失败，请刷新页面重试', 'error')
  }
}

// 事件监听器
document.addEventListener('DOMContentLoaded', () => {
  // 初始化多任务支持
  if (
    typeof window.multiTaskModule !== 'undefined' &&
    typeof window.multiTaskModule.initMultiTaskSupport === 'function'
  ) {
    window.multiTaskModule.initMultiTaskSupport()
    console.log('✅ 多任务支持已初始化')
  } else {
    console.warn('⚠️ 多任务模块未加载，可能是multi_task.js加载失败')
  }

  // 加载反馈提示语配置（用于自动提交时的默认消息）
  loadFeedbackPrompts()

  loadConfig()
    .then(() => {
      // 在配置加载完成后启动轮询
      console.log('✅ 配置加载完成，启动内容轮询检查...')
      console.log('当前配置:', {
        has_content: config.has_content,
        persistent: config.persistent,
        prompt_length: config.prompt ? config.prompt.length : 0
      })
      startContentPolling()
    })
    .catch(error => {
      console.error('❌ 配置加载失败:', error)
      // 即使配置加载失败，也尝试启动轮询（可能是网络问题）
      setTimeout(() => {
        console.log('🔄 配置加载失败，延迟启动轮询...')
        startContentPolling()
      }, 3000)
    })

  // 初始化图片功能
  initializeImageFeatures()

  // 启动 URL 对象定期清理
  startPeriodicCleanup()

  // 初始化快捷键提示
  initializeShortcutTooltip()

  // 初始化通知管理器
  notificationManager
    .init()
    .then(() => {
      console.log('通知管理器初始化完成')
      // 应用设置管理器的配置
      settingsManager.applySettings()
      // 确保状态信息正确更新
      setTimeout(() => {
        settingsManager.updateStatus()
      }, 100)
    })
    .catch(error => {
      console.warn('通知管理器初始化失败:', error)
    })

  // 按钮事件
  document.getElementById('insert-code-btn').addEventListener('click', insertCodeFromClipboard)
  document.getElementById('submit-btn').addEventListener('click', submitFeedback)
  document.getElementById('close-btn').addEventListener('click', closeInterface)

  // 键盘快捷键 - 支持跨平台
  document.addEventListener('keydown', event => {
    const isMac = detectPlatform() === 'mac'
    const ctrlOrCmd = isMac ? event.metaKey : event.ctrlKey
    const altOrOption = isMac ? event.altKey : event.altKey

    if (ctrlOrCmd && event.key === 'Enter') {
      event.preventDefault()
      submitFeedback()
    } else if (altOrOption && event.key === 'c') {
      event.preventDefault()
      insertCodeFromClipboard()
    } else if (ctrlOrCmd && event.key === 'v') {
      // Ctrl/Cmd+V 粘贴图片 - 浏览器默认处理，我们只在paste事件中处理
      console.log(`快捷键: ${isMac ? 'Cmd' : 'Ctrl'}+V 粘贴`)
    } else if (ctrlOrCmd && event.key === 'u') {
      event.preventDefault()
      document.getElementById('upload-image-btn').click()
      console.log(`快捷键: ${isMac ? 'Cmd' : 'Ctrl'}+U 上传图片`)
    } else if (event.key === 'Delete' && selectedImages.length > 0) {
      event.preventDefault()
      clearAllImages()
      console.log('快捷键: Delete 清除所有图片')
    } else if (ctrlOrCmd && event.shiftKey && event.key === 'N') {
      // Ctrl+Shift+N 测试通知
      event.preventDefault()
      testNotification()
      console.log(`快捷键: ${isMac ? 'Cmd' : 'Ctrl'}+Shift+N 测试通知`)
    }
  })

  /**
   * 用户首次交互时启用音频上下文
   * 解决浏览器自动播放策略限制
   *
   * @description
   * - 检测AudioContext状态
   * - 恢复suspended状态的音频上下文
   * - 确保通知声音能够正常播放
   */
  function enableAudioOnFirstInteraction() {
    if (
      notificationManager.audioContext &&
      notificationManager.audioContext.state === 'suspended'
    ) {
      notificationManager.audioContext
        .resume()
        .then(() => {
          console.log('音频上下文已启用')
        })
        .catch(error => {
          console.warn('启用音频上下文失败:', error)
        })
    }
  }

  // 添加首次交互监听器
  document.addEventListener('click', enableAudioOnFirstInteraction, { once: true })
  document.addEventListener('keydown', enableAudioOnFirstInteraction, { once: true })
  document.addEventListener('touchstart', enableAudioOnFirstInteraction, { once: true })

  /**
   * 测试通知功能
   * 发送测试通知以验证通知系统是否正常工作
   *
   * @returns {Promise<void>}
   * @description
   * - 触发方式：Ctrl/Cmd+Shift+N
   * - 发送测试通知
   * - 显示成功/失败状态
   * - 用于调试和权限检查
   */
  async function testNotification() {
    try {
      await notificationManager.sendNotification(
        '通知测试',
        '这是一个测试通知，用于验证通知功能是否正常工作',
        {
          tag: 'test-notification',
          requireInteraction: false
        }
      )
      showStatus('测试通知已发送', 'success')
    } catch (error) {
      console.error('测试通知失败:', error)
      showStatus('测试通知失败', 'error')
    }
  }
})
