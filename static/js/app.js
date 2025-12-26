/**
 * AI Intervention Agent - 主应用脚本
 *
 * 功能模块：
 *   - Lottie 动画配置和初始化
 *   - Markdown 渲染和代码高亮
 *   - 页面状态管理（无内容页面/内容页面切换）
 *   - 内容轮询逻辑
 *   - 表单处理和提交
 *   - 通知管理器
 *   - 设置管理器
 *   - 图片上传处理
 *   - 应用初始化
 *
 * 依赖：
 *   - mathjax-loader.js: MathJax 懒加载
 *   - multi_task.js: 多任务管理
 *   - theme.js: 主题管理
 *   - dom-security.js: DOM 安全工具
 *   - validation-utils.js: 验证工具
 *   - marked.js: Markdown 解析
 *   - prism.js: 代码高亮
 *   - lottie.min.js: 动画库
 */

// ==================================================================
// 访问地址兼容性处理（0.0.0.0 -> 127.0.0.1）
// ==================================================================
//
// 背景：
// - 0.0.0.0 是服务端“监听所有网卡”的绑定地址，适合服务端 bind，但不适合作为浏览器访问地址。
// - 部分浏览器/环境下，访问 http://0.0.0.0:PORT 可能出现异常（如权限异常、请求失败、Failed to fetch）。
//
// 处理策略：
// - 若检测到当前页面 hostname 为 0.0.0.0，则自动切换为 127.0.0.1（保持端口/路径/查询参数不变）
// - 使用 location.replace 避免污染历史记录
;(function redirectZeroHostToLoopback() {
  try {
    const url = new URL(window.location.href)
    if (url.hostname === '0.0.0.0') {
      url.hostname = '127.0.0.1'
      console.warn(`检测到访问地址为 0.0.0.0，已自动切换为 ${url.origin}（避免浏览器兼容性问题）`)
      window.location.replace(url.toString())
    }
  } catch (e) {
    // 忽略：不影响主流程
  }
})()

// 主题管理器已在 theme.js 中定义和初始化
// 此处不再重复定义，避免 CSP nonce 和重复声明问题

let config = null

// ==================================================================
// Lottie 嫩芽动画配置
// ==================================================================
//
// 功能说明：
//   在"无有效内容"页面显示循环播放的嫩芽生长动画，
//   向用户传达"等待中/正在生长"的视觉隐喻。
//
// 动画来源：
//   /static/lottie/sprout.json
//
// 主题适配：
//   - 浅色模式：原色（深色线条）
//   - 深色模式：通过 CSS filter: invert(1) 反转为白色线条
//   - 叶子颜色因 invert 也会变化（可接受的视觉效果）
//
// 降级处理：
//   若 Lottie 库加载失败，显示 🌱 emoji 作为备用
// ==================================================================

// Lottie 动画实例引用（用于后续控制如暂停/销毁）
let hourglassAnimation = null

/**
 * 初始化嫩芽生长 Lottie 动画
 *
 * 生命周期：
 *   1. 检查容器元素是否存在
 *   2. 检查 Lottie 库是否已加载
 *   3. 销毁已有动画（防止内存泄漏）
 *   4. 创建新动画实例
 *   5. 监听加载完成事件，应用主题颜色
 *   6. 监听错误事件，显示降级 emoji
 */
function initHourglassAnimation() {
  const container = document.getElementById('hourglass-lottie')
  if (!container) {
    console.warn('动画容器未找到')
    return
  }

  // 检查 Lottie 库是否已通过 <script defer> 加载
  if (typeof lottie === 'undefined') {
    console.warn('Lottie 库未加载，显示备用图标')
    container.textContent = '🌱'
    return
  }

  try {
    // 销毁旧动画实例（防止内存泄漏和重复动画）
    if (hourglassAnimation) {
      hourglassAnimation.destroy()
    }

    // 创建嫩芽生长动画
    hourglassAnimation = lottie.loadAnimation({
      container: container,
      renderer: 'svg', // 使用 SVG 渲染器（高质量缩放）
      loop: true, // 循环播放
      autoplay: true, // 自动开始播放
      path: '/static/lottie/sprout.json', // 动画 JSON 文件路径
      rendererSettings: {
        preserveAspectRatio: 'xMidYMid meet' // 保持宽高比，居中显示
      }
    })

    // 动画加载完成后，根据当前主题更新线条颜色
    hourglassAnimation.addEventListener('DOMLoaded', () => {
      updateLottieAnimationColor()
    })

    // 动画加载错误处理（网络问题或 JSON 解析失败）
    hourglassAnimation.addEventListener('error', () => {
      console.warn('Lottie 动画加载失败，显示备用图标')
      container.textContent = '🌱'
    })

    console.log('✅ 嫩芽动画初始化成功')
  } catch (error) {
    console.error('Lottie 动画初始化失败:', error)
    container.textContent = '🌱' // 降级为 emoji
  }
}

/**
 * 根据当前主题更新 Lottie 动画的线条颜色
 *
 * 实现方式：
 *   使用 CSS filter: invert(1) 反转颜色，而非修改 SVG 内部属性。
 *   这种方式更简单可靠，且能在主题切换时即时生效。
 *
 * 效果：
 *   - invert(0) / none：保持原色
 *   - invert(1)：将所有颜色反转（黑→白，白→黑）
 */
function updateLottieAnimationColor() {
  const container = document.getElementById('hourglass-lottie')
  if (!container) return

  // 获取当前主题状态
  const isLightTheme = document.documentElement.getAttribute('data-theme') === 'light'

  // 应用 CSS filter 实现颜色切换
  if (isLightTheme) {
    // 浅色模式：保持原色（深色线条在浅色背景上清晰可见）
    container.style.filter = 'none'
  } else {
    // 深色模式：反转颜色（深色线条变为白色，在深色背景上清晰可见）
    container.style.filter = 'invert(1)'
  }

  console.log('✅ Lottie 动画颜色已更新:', isLightTheme ? '浅色模式（原色）' : '深色模式（反转）')
}

// 监听主题变化事件（由 ThemeManager 在 theme.js 中派发）
// 用于在用户切换主题时即时更新 Lottie 动画颜色
window.addEventListener('theme-changed', event => {
  console.log('主题变更事件:', event.detail)
  // 延迟 50ms 执行，确保 DOM data-theme 属性已更新
  setTimeout(updateLottieAnimationColor, 50)
})

// 高性能markdown渲染函数
// isMarkdown: 是否为 Markdown 源文本（需要 marked.js 解析）
function renderMarkdownContent(element, content, isMarkdown = false) {
  // 使用requestAnimationFrame优化渲染时机
  requestAnimationFrame(() => {
    if (content) {
      let htmlContent = content

      // 如果是 Markdown 文本，先用 marked.js 解析
      if (isMarkdown && typeof marked !== 'undefined') {
        try {
          htmlContent = marked.parse(content)
        } catch (e) {
          console.warn('marked.js 解析失败:', e)
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

      // 处理代码块，添加复制按钮
      processCodeBlocks(element)

      // 处理删除线语法
      processStrikethrough(element)

      /**
       * 按需加载并渲染 MathJax 数学公式
       *
       * 加载策略：
       *   1. 首先检测内容中是否包含数学公式（$...$, $$...$$, \(...\), \[...\]）
       *   2. 如果有数学公式，触发 MathJax 懒加载（约 1.17MB）
       *   3. MathJax 加载完成后，通过 startup.ready 回调自动渲染待处理元素
       *
       * 回退机制：
       *   如果 loadMathJaxIfNeeded 未定义（理论上不会发生），
       *   回退到直接检查 MathJax 对象并调用 typesetPromise
       */
      const textContent = element.textContent || ''
      if (window.loadMathJaxIfNeeded) {
        window.loadMathJaxIfNeeded(element, textContent)
      } else if (window.MathJax && window.MathJax.typesetPromise) {
        // 回退：如果 MathJax 已加载但 loadMathJaxIfNeeded 不可用，直接渲染
        window.MathJax.typesetPromise([element]).catch(err => {
          console.warn('MathJax 渲染失败:', err)
        })
      }
    } else {
      element.textContent = '加载中...'
    }
  })
}

// 处理代码块，添加复制按钮和语言标识
function processCodeBlocks(container) {
  const codeBlocks = container.querySelectorAll('pre')

  codeBlocks.forEach(pre => {
    // 检查是否已经被处理过
    if (pre.parentElement && pre.parentElement.classList.contains('code-block-container')) {
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

// 复制代码到剪贴板
async function copyCodeToClipboard(preElement, button) {
  // Claude 官方风格图标
  const checkIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.7803 4.21967C14.0732 4.51256 14.0732 4.98744 13.7803 5.28033L6.78033 12.2803C6.48744 12.5732 6.01256 12.5732 5.71967 12.2803L2.21967 8.78033C1.92678 8.48744 1.92678 8.01256 2.21967 7.71967C2.51256 7.42678 2.98744 7.42678 3.28033 7.71967L6.25 10.6893L12.7197 4.21967C13.0126 3.92678 13.4874 3.92678 13.7803 4.21967Z"/></svg>'
  const errorIconSvg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M4.21967 4.21967C4.51256 3.92678 4.98744 3.92678 5.28033 4.21967L8 6.93934L10.7197 4.21967C11.0126 3.92678 11.4874 3.92678 11.7803 4.21967C12.0732 4.51256 12.0732 4.98744 11.7803 5.28033L9.06066 8L11.7803 10.7197C12.0732 11.0126 12.0732 11.4874 11.7803 11.7803C11.4874 12.0732 11.0126 12.0732 10.7197 11.7803L8 9.06066L5.28033 11.7803C4.98744 12.0732 4.51256 12.0732 4.21967 11.7803C3.92678 11.4874 3.92678 11.0126 4.21967 10.7197L6.93934 8L4.21967 5.28033C3.92678 4.98744 3.92678 4.51256 4.21967 4.21967Z"/></svg>'

  try {
    const codeElement = preElement.querySelector('code')
    const textToCopy = codeElement ? codeElement.textContent : preElement.textContent

    await navigator.clipboard.writeText(textToCopy)

    // 更新按钮状态
    const originalHTML = button.innerHTML
    button.innerHTML = checkIconSvg + '已复制'
    button.classList.add('copied')

    // 2秒后恢复原状
    setTimeout(() => {
      button.innerHTML = originalHTML
      button.classList.remove('copied')
    }, 2000)
  } catch (err) {
    console.error('复制失败:', err)

    // 显示错误状态
    const originalHTML = button.innerHTML
    button.innerHTML = errorIconSvg + '复制失败'
    button.classList.add('error')

    setTimeout(() => {
      button.innerHTML = originalHTML
      button.classList.remove('error')
    }, 2000)
  }
}

// 处理删除线语法 ~~text~~
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

// 加载配置
async function loadConfig() {
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

    // 页面首次加载不发送通知，只在内容变化时通知

    // 更新描述 - 使用高性能渲染函数
    const descriptionElement = document.getElementById('description')
    renderMarkdownContent(descriptionElement, config.prompt_html || config.prompt)

    // 加载预定义选项
    if (config.predefined_options && config.predefined_options.length > 0) {
      const optionsContainer = document.getElementById('options-container')
      const separator = document.getElementById('separator')

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

      optionsContainer.style.display = 'block'
      separator.style.display = 'block'
    }
  } catch (error) {
    console.error('加载配置失败:', error)
    showStatus('加载配置失败', 'error')
    throw error // 重新抛出错误，让调用者知道加载失败
  }
}

// 显示无内容页面
function showNoContentPage() {
  document.getElementById('content-container').style.display = 'none'
  document.getElementById('no-content-container').style.display = 'flex'

  // 添加无内容模式的CSS类，启用特殊布局
  document.body.classList.add('no-content-mode')

  // 隐藏任务标签栏（无内容时不需要显示）
  const taskTabsContainer = document.getElementById('task-tabs-container')
  if (taskTabsContainer) {
    taskTabsContainer.classList.add('hidden')
  }

  // 显示关闭按钮，让用户可以关闭服务
  if (config) {
    document.getElementById('no-content-buttons').style.display = 'block'
  }
}

// 显示内容页面
function showContentPage() {
  document.getElementById('content-container').style.display = 'block'
  document.getElementById('no-content-container').style.display = 'none'

  // 移除无内容模式的CSS类，恢复正常布局
  document.body.classList.remove('no-content-mode')

  // 任务标签栏的显示由 multi_task.js 的 renderTaskTabs() 控制
  // 这里不需要手动显示，等待 renderTaskTabs() 根据任务数量决定

  enableSubmitButton()
}

// 禁用提交按钮
function disableSubmitButton() {
  const submitBtn = document.getElementById('submit-btn')
  const insertBtn = document.getElementById('insert-code-btn')
  const feedbackText = document.getElementById('feedback-text')

  if (submitBtn) {
    submitBtn.disabled = true
    submitBtn.style.backgroundColor = '#3a3a3c'
    submitBtn.style.color = '#8e8e93'
    submitBtn.style.cursor = 'not-allowed'
  }
  if (insertBtn) {
    insertBtn.disabled = true
    insertBtn.style.backgroundColor = '#3a3a3c'
    insertBtn.style.color = '#8e8e93'
    insertBtn.style.cursor = 'not-allowed'
  }
  if (feedbackText) {
    feedbackText.disabled = true
    feedbackText.style.backgroundColor = '#2c2c2e'
    feedbackText.style.color = '#8e8e93'
    feedbackText.style.cursor = 'not-allowed'
  }
}

// 启用提交按钮
function enableSubmitButton() {
  const submitBtn = document.getElementById('submit-btn')
  const insertBtn = document.getElementById('insert-code-btn')
  const feedbackText = document.getElementById('feedback-text')

  if (submitBtn) {
    submitBtn.disabled = false
    submitBtn.style.backgroundColor = '#0a84ff'
    submitBtn.style.color = '#ffffff'
    submitBtn.style.cursor = 'pointer'
  }
  if (insertBtn) {
    insertBtn.disabled = false
    insertBtn.style.backgroundColor = '#48484a'
    insertBtn.style.color = '#ffffff'
    insertBtn.style.cursor = 'pointer'
  }
  if (feedbackText) {
    feedbackText.disabled = false
    feedbackText.style.backgroundColor = 'rgba(255, 255, 255, 0.03)'
    feedbackText.style.color = '#f5f5f7'
    feedbackText.style.cursor = 'text'
  }
}

// 显示状态消息
function showStatus(message, type) {
  // 检查当前是否在无内容页面（使用 style.display 检查）
  const noContentContainer = document.getElementById('no-content-container')
  const isNoContentPage = noContentContainer && noContentContainer.style.display === 'flex'

  // 🚫 在有内容时，只显示错误消息，跳过成功/信息提示
  if (!isNoContentPage && type !== 'error') {
    console.log(`[showStatus] 跳过非错误提示: ${message} (${type})`)
    return
  }

  const statusElement = isNoContentPage
    ? document.getElementById('no-content-status-message')
    : document.getElementById('status-message')

  if (!statusElement) return

  statusElement.textContent = message
  statusElement.className = `status-message status-${type}`
  statusElement.style.display = 'block'

  if (type === 'success') {
    setTimeout(() => {
      statusElement.style.display = 'none'
    }, 3000)
  }
}

// 插入代码功能 - 与GUI版本逻辑完全一致
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

// 提交反馈
async function submitFeedback() {
  const feedbackText = document.getElementById('feedback-text').value.trim()
  const selectedOptions = []

  // 【修复】直接从 DOM 获取选中的预定义选项
  // 不再依赖 config.predefined_options，因为在多任务模式下切换任务时 config 可能未同步更新
  const optionsContainer = document.getElementById('options-container')
  if (optionsContainer) {
    const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]:checked')
    checkboxes.forEach(checkbox => {
      // 使用 checkbox 的 value 属性获取选项文本
      if (checkbox.value) {
        selectedOptions.push(checkbox.value)
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
    submitBtn.innerHTML = '提交中...'

    // 使用 FormData 上传文件，避免 base64 编码
    const formData = new FormData()
    formData.append('feedback_text', feedbackText)
    formData.append('selected_options', JSON.stringify(selectedOptions))

    // 添加图片文件（直接使用原始文件，不需要base64）
    selectedImages.forEach((img, index) => {
      if (img.file) {
        formData.append(`image_${index}`, img.file)
      }
    })

    // 获取当前活动任务ID（由 multi_task.js 管理）
    const currentTaskId = window.activeTaskId

    // 优先使用多任务提交端点（如果有活动任务）
    const submitUrl = currentTaskId ? `/api/tasks/${currentTaskId}/submit` : '/api/submit'
    console.log(`使用提交端点: ${submitUrl}`)

    const response = await fetch(submitUrl, {
      method: 'POST',
      body: formData // 不设置 Content-Type，让浏览器自动设置 multipart/form-data
    })

    const result = await response.json()

    if (response.ok) {
      showStatus(result.message, 'success')

      // 反馈提交成功，不需要通知（用户要求）

      // 清空表单
      document.getElementById('feedback-text').value = ''
      // 取消选中所有复选框
      document.querySelectorAll('input[type="checkbox"]').forEach(cb => (cb.checked = false))
      // 清除所有图片
      clearAllImages()

      // 清理该任务的缓存（如果是多任务模式）
      if (currentTaskId) {
        if (typeof taskTextareaContents !== 'undefined') {
          delete taskTextareaContents[currentTaskId]
        }
        if (typeof taskOptionsStates !== 'undefined') {
          delete taskOptionsStates[currentTaskId]
        }
        if (typeof taskImages !== 'undefined') {
          delete taskImages[currentTaskId]
        }
      }

      // 立即刷新任务列表（由 multi_task.js 处理页面状态切换）
      if (typeof refreshTasksList === 'function') {
        console.log('调用 refreshTasksList 刷新任务列表...')
        await refreshTasksList()
      } else {
        // 兼容旧模式：如果没有多任务支持，显示无内容页面
        if (config) {
          config.has_content = false
          console.log('反馈提交后，本地状态已更新为无内容')
        }
        showNoContentPage()
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
    // Claude 风格发送图标（右箭头，简洁风格）
    submitBtn.innerHTML = `
      <svg class="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M3.29289 3.29289C3.68342 2.90237 4.31658 2.90237 4.70711 3.29289L10.7071 9.29289C11.0976 9.68342 11.0976 10.3166 10.7071 10.7071L4.70711 16.7071C4.31658 17.0976 3.68342 17.0976 3.29289 16.7071C2.90237 16.3166 2.90237 15.6834 3.29289 15.2929L8.58579 10L3.29289 4.70711C2.90237 4.31658 2.90237 3.68342 3.29289 3.29289ZM9.29289 3.29289C9.68342 2.90237 10.3166 2.90237 10.7071 3.29289L16.7071 9.29289C17.0976 9.68342 17.0976 10.3166 16.7071 10.7071L10.7071 16.7071C10.3166 17.0976 9.68342 17.0976 9.29289 16.7071C8.90237 16.3166 8.90237 15.6834 9.29289 15.2929L14.5858 10L9.29289 4.70711C8.90237 4.31658 8.90237 3.68342 9.29289 3.29289Z"/>
      </svg>
      发送请求
    `
  }
}

// 关闭界面 - 简化版本，统一刷新逻辑
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

// 安全刷新页面函数
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

// ==================================================================
// 内容轮询 - 已停用
// ==================================================================
//
// 说明：
//   内容轮询功能已完全由 multi_task.js 的任务轮询接管。
//   此处仅保留空实现，防止被其他代码调用时报错。
//
// 历史原因：
//   原设计中 app.js 负责轮询 /api/config 检测内容变化，
//   但与 multi_task.js 的 /api/tasks 轮询存在冲突，
//   导致 textarea 内容被意外清空。
//
// 解决方案：
//   1. 停用 app.js 轮询，由 multi_task.js 统一管理
//   2. multi_task.js 实现了实时保存机制
// ==================================================================

/**
 * 停止内容轮询（空实现）
 *
 * 保留此函数是因为 closeInterface() 会调用它。
 * 实际轮询由 multi_task.js 的 stopTasksPolling() 管理。
 */
function stopContentPolling() {
  // 轮询已停用，此函数不执行任何操作
  console.log('[app.js] stopContentPolling 被调用，但轮询已停用')
}

// updatePageContent() 已删除
// 页面内容更新现在完全由 multi_task.js 的以下函数处理：
//   - loadTaskDetails(): 加载任务详情
//   - updateDescriptionDisplay(): 更新描述区域
//   - updateOptionsDisplay(): 更新选项区域

// ========== 图片处理功能 ==========

// 图片管理数组
let selectedImages = []

// 通知管理系统
class NotificationManager {
  constructor() {
    this.isSupported = 'Notification' in window
    this.permission = this.isSupported ? Notification.permission : 'denied'
    this.audioContext = null
    this.audioBuffers = new Map()
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

    try {
      const response = await fetch(url)
      const arrayBuffer = await response.arrayBuffer()
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer)
      this.audioBuffers.set(name, audioBuffer)
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

      const notification = new Notification(title, notificationOptions)

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

      // 移动设备震动
      if (this.config.mobileVibrate && 'vibrate' in navigator) {
        navigator.vibrate([200, 100, 200])
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

    const audioBuffer = this.audioBuffers.get(soundName)
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
    if (this.config.mobileVibrate && 'vibrate' in navigator) {
      try {
        navigator.vibrate([200, 100, 200]) // 振动模式：200ms振动，100ms停止，200ms振动
        console.log('使用振动提醒')
        return true
      } catch (error) {
        console.warn('振动提醒失败:', error)
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

    // 添加样式
    notification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: rgba(30, 30, 40, 0.95);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 12px;
      padding: 1rem;
      max-width: 300px;
      z-index: 10000;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
      backdrop-filter: blur(10px);
      color: #f5f5f7;
      font-family: inherit;
    `

    // 添加内容样式
    const titleEl = notification.querySelector('.in-page-notification-title')
    const messageEl = notification.querySelector('.in-page-notification-message')
    const closeEl = notification.querySelector('.in-page-notification-close')

    titleEl.style.cssText = 'font-weight: 600; margin-bottom: 0.5rem; font-size: 1rem;'
    messageEl.style.cssText =
      'font-size: 0.9rem; line-height: 1.4; color: rgba(245, 245, 247, 0.8);'
    closeEl.style.cssText = `
      position: absolute;
      top: 0.5rem;
      right: 0.5rem;
      background: none;
      border: none;
      color: rgba(245, 245, 247, 0.6);
      cursor: pointer;
      font-size: 1.2rem;
      padding: 0.25rem;
      border-radius: 4px;
      transition: all 0.2s ease;
    `

    // 添加到页面
    document.body.appendChild(notification)

    // 关闭按钮事件
    closeEl.addEventListener('click', () => {
      notification.style.transform = 'translateX(100%)'
      notification.style.opacity = '0'
      setTimeout(() => {
        if (notification.parentNode) {
          notification.parentNode.removeChild(notification)
        }
      }, 300)
    })

    closeEl.addEventListener('mouseenter', () => {
      closeEl.style.background = 'rgba(255, 255, 255, 0.1)'
      closeEl.style.color = '#f5f5f7'
    })

    closeEl.addEventListener('mouseleave', () => {
      closeEl.style.background = 'none'
      closeEl.style.color = 'rgba(245, 245, 247, 0.6)'
    })

    // 入场动画
    notification.style.transform = 'translateX(100%)'
    notification.style.transition = 'all 0.3s ease-out'
    setTimeout(() => {
      notification.style.transform = 'translateX(0)'
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

    // 性能优化：存储到本地存储
    try {
      const storageKey = 'ai-intervention-fallback-events'
      const events = JSON.parse(localStorage.getItem(storageKey) || '[]')

      // 性能优化：清理过期事件
      const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
      const validEvents = events.filter(e => e.timestamp > sevenDaysAgo)

      validEvents.push(event)

      // 性能优化：只保留最近50个事件
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

  // 性能优化：监控 localStorage 使用情况
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

  // 性能优化：清理 localStorage
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
    this.initialized = false
    // 注意：不在构造函数中调用 init()，由 DOMContentLoaded 触发
  }

  async init() {
    if (this.initialized) return
    this.settings = await this.loadSettings()
    this.initEventListeners()
    this.initialized = true
    console.log('SettingsManager 初始化完成')
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

  /**
   * 获取状态图标 SVG（Claude 风格线条图标）
   *
   * 功能说明：
   *   生成用于设置面板状态显示的 SVG 图标，替代原有的 emoji。
   *   采用 Claude 官方设计风格：线条图标、适当的 stroke-width。
   *
   * 设计规范：
   *   - 尺寸：16x16px
   *   - stroke-width: 2（与其他图标一致）
   *   - stroke-linecap/linejoin: round（圆润的线条端点）
   *   - 垂直居中：vertical-align: middle
   *   - 与文字间距：margin-right: 4px
   *
   * 颜色方案：
   *   - success: #4CAF50（绿色）- 表示正常/已启用
   *   - error: #F44336（红色）- 表示错误/已禁用
   *   - warning: #FF9800（橙色）- 表示警告/未配置
   *   - paused: #9E9E9E（灰色）- 表示暂停状态
   *
   * @param {string} type - 图标类型：'success' | 'error' | 'warning' | 'paused'
   * @returns {string} SVG HTML 字符串，可直接插入到 innerHTML
   */
  getStatusIcon(type) {
    const icons = {
      // 成功图标（勾号）- 浏览器支持/通知已授权/音频运行中
      success: `<svg class="status-icon status-icon-success" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #4CAF50;"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
      // 错误图标（叉号）- 不支持/已拒绝/已关闭
      error: `<svg class="status-icon status-icon-error" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #F44336;"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`,
      // 警告图标（感叹号三角形）- 未请求权限/未知状态
      warning: `<svg class="status-icon status-icon-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #FF9800;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
      // 暂停图标（双竖线）- 音频已暂停
      paused: `<svg class="status-icon status-icon-paused" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px; color: #9E9E9E;"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>`
    }
    // 默认返回警告图标，处理未知类型
    return icons[type] || icons.warning
  }

  updateStatus() {
    // 更新状态信息（使用 SVG 图标替代 emoji）
    const browserSupportHtml = notificationManager.isSupported
      ? this.getStatusIcon('success') + '支持'
      : this.getStatusIcon('error') + '不支持'

    let permissionHtml
    if (notificationManager.permission === 'granted') {
      permissionHtml = this.getStatusIcon('success') + '已授权'
    } else if (notificationManager.permission === 'denied') {
      permissionHtml = this.getStatusIcon('error') + '已拒绝'
    } else {
      permissionHtml = this.getStatusIcon('warning') + '未请求'
    }

    // 音频状态中文化
    let audioStateHtml = this.getStatusIcon('error') + '不可用'
    if (notificationManager.audioContext) {
      const state = notificationManager.audioContext.state
      switch (state) {
        case 'running':
          audioStateHtml = this.getStatusIcon('success') + '运行中'
          break
        case 'suspended':
          audioStateHtml = this.getStatusIcon('paused') + '已暂停'
          break
        case 'closed':
          audioStateHtml = this.getStatusIcon('error') + '已关闭'
          break
        default:
          audioStateHtml = this.getStatusIcon('warning') + state
      }
    }

    document.getElementById('browser-support-status').innerHTML = browserSupportHtml
    document.getElementById('notification-permission-status').innerHTML = permissionHtml
    document.getElementById('audio-status').innerHTML = audioStateHtml
  }

  initEventListeners() {
    // 设置按钮点击事件 - 使用直接绑定确保可靠
    const settingsBtn = document.getElementById('settings-btn')
    const settingsCloseBtn = document.getElementById('settings-close-btn')
    const testNotificationBtn = document.getElementById('test-notification-btn')
    const testBarkNotificationBtn = document.getElementById('test-bark-notification-btn')
    const resetSettingsBtn = document.getElementById('reset-settings-btn')

    if (settingsBtn) {
      settingsBtn.addEventListener('click', e => {
        e.stopPropagation()
        this.showSettings()
      })
    }
    if (settingsCloseBtn) {
      settingsCloseBtn.addEventListener('click', () => this.hideSettings())
    }
    if (testNotificationBtn) {
      testNotificationBtn.addEventListener('click', () => this.testNotification())
    }
    if (testBarkNotificationBtn) {
      testBarkNotificationBtn.addEventListener('click', () => this.testBarkNotification())
    }
    if (resetSettingsBtn) {
      resetSettingsBtn.addEventListener('click', () => this.resetSettings())
    }

    // 主题切换按钮点击事件 - 已由 theme.js 处理，此处删除避免重复绑定

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

  async showSettings() {
    // 防御性：确保已初始化（极端情况下用户可能在 init() 未完成时快速点击）
    if (!this.initialized) {
      try {
        await this.init()
      } catch (e) {
        console.warn('SettingsManager 初始化失败（打开设置面板时）:', e)
      }
    }

    const panel = document.getElementById('settings-panel')
    if (panel) {
      // 临时移除 container 的 overflow: hidden，以便设置面板可以覆盖整个屏幕
      const container = document.querySelector('.container')
      if (container) {
        container.style.overflow = 'visible'
      }

      panel.classList.remove('hidden') // 移除 hidden 类（它使用了 !important）
      panel.style.display = 'flex'

      // 浅色主题适配
      this.applySettingsTheme()
    }

    // ✅ 方案A：每次打开设置面板，都从后端刷新一次配置
    // 目的：
    // - 让“外部编辑 config.jsonc”能在不刷新页面的情况下反映到 UI
    // - 避免打开面板时把旧的本地缓存配置反向写回后端（覆盖外部修改）
    try {
      this.settings = await this.loadSettings()
    } catch (e) {
      console.warn('打开设置面板时刷新配置失败，继续使用当前设置:', e)
    }

    this.updateUI()
    this.updateStatus()
  }

  applySettingsTheme() {
    const theme = document.documentElement.getAttribute('data-theme')

    // 动态注入浅色主题样式（解决 CSS 优先级问题）
    if (!document.getElementById('settings-light-theme-styles')) {
      const style = document.createElement('style')
      style.id = 'settings-light-theme-styles'
      style.textContent = `
        [data-theme="light"] .settings-panel {
          background: rgba(0, 0, 0, 0.7) !important;
        }
        [data-theme="light"] .settings-content {
          background: #faf9f5 !important;
          border: 1px solid rgba(0, 0, 0, 0.12) !important;
          box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2), 0 10px 20px rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .settings-body {
          background: #faf9f5 !important;
        }
        [data-theme="light"] .setting-group {
          background: #ffffff !important;
          border: 1px solid rgba(0, 0, 0, 0.1) !important;
        }
        [data-theme="light"] .setting-subgroup {
          background: #f8f8f5 !important;
        }
        [data-theme="light"] .settings-header {
          border-bottom: 1px solid rgba(0, 0, 0, 0.1) !important;
          background: #f2f1ec !important;
        }
        [data-theme="light"] .status-row {
          background: rgba(0, 0, 0, 0.02) !important;
          border-color: rgba(0, 0, 0, 0.08) !important;
          color: #141413 !important;
        }
        [data-theme="light"] .status-row span:first-child {
          color: rgba(20, 20, 19, 0.85) !important;
        }
        [data-theme="light"] .status-row span:last-child {
          color: #141413 !important;
        }
        [data-theme="light"] .setting-description {
          color: rgba(20, 20, 19, 0.65) !important;
        }
        [data-theme="light"] .setting-item:hover .setting-description {
          color: rgba(20, 20, 19, 0.75) !important;
        }
        [data-theme="light"] .setting-label:hover .setting-title {
          color: rgba(20, 20, 19, 0.9) !important;
        }
        [data-theme="light"] .setting-input::placeholder {
          color: rgba(20, 20, 19, 0.5) !important;
        }
        [data-theme="light"] .setting-label,
        [data-theme="light"] .setting-subgroup-title,
        [data-theme="light"] .settings-main-title,
        [data-theme="light"] #settings-title {
          color: #141413 !important;
        }
        [data-theme="light"] .setting-input {
          background: #ffffff !important;
          border-color: rgba(0, 0, 0, 0.15) !important;
          color: #141413 !important;
        }
        [data-theme="light"] .setting-select {
          background: #ffffff !important;
          border-color: rgba(0, 0, 0, 0.15) !important;
          color: #141413 !important;
        }
      `
      document.head.appendChild(style)
    }
  }

  hideSettings() {
    const panel = document.getElementById('settings-panel')
    if (panel) {
      // 恢复 container 的 overflow
      const container = document.querySelector('.container')
      if (container) {
        container.style.overflow = ''
      }

      panel.classList.add('hidden') // 添加 hidden 类
      panel.style.display = 'none'
    }
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

// 防抖函数
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

// 节流函数
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

// RAF优化的更新函数
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
const MAX_IMAGE_SIZE = 10 * 1024 * 1024 // 10MB
const MAX_IMAGE_COUNT = 10
const MAX_IMAGE_DIMENSION = 1920 // 最大宽度或高度
const COMPRESS_QUALITY = 0.8 // 压缩质量 (0.1-1.0)

/**
 * 验证图片文件（使用 ValidationUtils 工具类）
 * @param {File} file - 要验证的文件对象
 * @returns {string[]} 错误信息数组
 */
function validateImageFile(file) {
  // 使用 ValidationUtils 进行验证（如果可用）
  if (typeof ValidationUtils !== 'undefined') {
    const result = ValidationUtils.validateImageFile(file)
    return result.errors
  }

  // 回退到基础验证
  const errors = []
  if (!file || !file.type) {
    errors.push('无效的文件对象')
    return errors
  }
  if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errors.push(`不支持的文件格式: ${file.type}`)
  }
  if (file.size > MAX_IMAGE_SIZE) {
    errors.push(`文件大小超过限制: ${(file.size / 1024 / 1024).toFixed(2)}MB > 10MB`)
  }
  if (file.name && file.name.length > 255) {
    errors.push('文件名过长')
  }
  return errors
}

/**
 * 安全的文件名清理（使用 ValidationUtils 工具类）
 * @param {string} fileName - 原始文件名
 * @returns {string} 清理后的安全文件名
 */
function sanitizeFileName(fileName) {
  // 使用 ValidationUtils 进行清理（如果可用）
  if (typeof ValidationUtils !== 'undefined') {
    return ValidationUtils.sanitizeFilename(fileName, 100)
  }

  // 回退到基础清理
  return fileName
    .replace(/[<>:"/\\|?*]/g, '')
    .replace(/\s+/g, '_')
    .trim()
    .substring(0, 100)
}

// 注意：已移除 fileToBase64 函数，现在直接使用文件对象上传

// 改进的内存管理跟踪：防止内存泄漏
let objectURLs = new Set()
let urlToFileMap = new WeakMap() // 使用WeakMap跟踪URL与文件的关联
let urlCreationTime = new Map() // 跟踪URL创建时间，用于自动清理

// 创建安全的Object URL
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

// 清理Object URL
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

  const endTime = performance.now()
  console.log(`URL对象清理完成，耗时: ${(endTime - startTime).toFixed(2)}ms`)
}

// 定期清理过期的URL对象（每5分钟检查一次）
function startPeriodicCleanup() {
  setInterval(() => {
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

// 优化的图片压缩函数
function compressImage(file) {
  return new Promise(resolve => {
    // SVG 图片和 GIF 不进行压缩
    if (file.type === 'image/svg+xml' || file.type === 'image/gif') {
      resolve(file)
      return
    }

    // 强制压缩：避免大图直接原样返回到 MCP 调用方（base64 会非常大）
    const MAX_RETURN_BYTES = 2 * 1024 * 1024 // 2MB
    const forceCompress = file.size > MAX_RETURN_BYTES

    // 大文件使用更激进的压缩
    const isLargeFile = file.size > 5 * 1024 * 1024 // 5MB

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d', {
      alpha: file.type === 'image/png',
      willReadFrequently: false
    })
    if (!ctx) {
      resolve(file)
      return
    }
    const img = new Image()

    const objectURL = createObjectURL(file)

    img.onload = () => {
      // 计算压缩后的尺寸
      let { width, height } = img
      const originalArea = width * height

      // 大图片使用更激进的压缩
      let maxDimension = MAX_IMAGE_DIMENSION
      if (forceCompress || isLargeFile || originalArea > 4000000) {
        // 4MP
        maxDimension = Math.min(MAX_IMAGE_DIMENSION, 1200)
      }

      if (width > maxDimension || height > maxDimension) {
        const ratio = Math.min(maxDimension / width, maxDimension / height)
        width = Math.floor(width * ratio)
        height = Math.floor(height * ratio)
      }

      let currentWidth = width
      let currentHeight = height

      canvas.width = currentWidth
      canvas.height = currentHeight

      // 优化的绘制设置
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'high'

      // 根据文件大小调整初始压缩质量
      let quality = COMPRESS_QUALITY
      if (isLargeFile) {
        quality = Math.max(0.6, COMPRESS_QUALITY - 0.2)
      }
      if (forceCompress) {
        quality = Math.min(quality, 0.75)
      }

      // 选择输出格式：
      // - PNG：小图尽量保持 PNG；大图强制转 WebP/JPEG（PNG 通常无法“有损压缩”）
      // - 其他：优先 WebP（若浏览器不支持则回退 JPEG）
      const mimeCandidates = []
      if (file.type === 'image/png') {
        if (forceCompress || isLargeFile || originalArea > 4000000) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/png')
        }
      } else if (file.type === 'image/webp') {
        mimeCandidates.push('image/webp', 'image/jpeg')
      } else {
        if (forceCompress) {
          mimeCandidates.push('image/webp', 'image/jpeg')
        } else {
          mimeCandidates.push('image/jpeg')
        }
      }

      const getExtensionForMime = mimeType => {
        if (mimeType === 'image/png') return '.png'
        if (mimeType === 'image/webp') return '.webp'
        if (mimeType === 'image/jpeg') return '.jpg'
        return null
      }

      const replaceExtension = (filename, newExt) => {
        if (!filename || !newExt) return filename
        const safeName = sanitizeFileName(filename)
        const withoutExt = safeName.replace(/\.[^/.]+$/, '')
        return `${withoutExt}${newExt}`
      }

      const logCompression = (blob, finalName) => {
        try {
          const ratio = ((1 - blob.size / file.size) * 100).toFixed(1)
          console.log(
            `图片压缩: ${file.name} ${(file.size / 1024).toFixed(2)}KB → ${(
              blob.size / 1024
            ).toFixed(2)}KB (压缩率: ${ratio}%) 输出: ${finalName}`
          )
        } catch (_) {
          // ignore
        }
      }

      let attempt = 0
      const MAX_ATTEMPTS = 8

      const tryToBlob = mimeIndex => {
        const outType = mimeCandidates[mimeIndex]
        if (!outType) {
          resolve(file)
          return
        }

        canvas.toBlob(
          blob => {
            if (!blob) return tryToBlob(mimeIndex + 1)

            // 确保“声明的 MIME”与“真实文件内容”一致（避免后端 MIME 不一致拒绝）
            if (!blob.type) return tryToBlob(mimeIndex + 1)

            const finalMimeType = blob.type || outType
            const ext = getExtensionForMime(finalMimeType)
            const finalName = ext ? replaceExtension(file.name, ext) : file.name

            const compressedFile = new File([blob], finalName, {
              type: finalMimeType,
              lastModified: file.lastModified
            })

            // 非强制：仅在变小时采用
            if (!forceCompress) {
              if (blob.size < file.size) {
                logCompression(blob, finalName)
                resolve(compressedFile)
              } else {
                resolve(file)
              }
              return
            }

            // 强制：先满足上限；否则继续降质/缩放
            if (blob.size <= MAX_RETURN_BYTES) {
              logCompression(blob, finalName)
              resolve(compressedFile)
              return
            }

            attempt++
            if (attempt >= MAX_ATTEMPTS) {
              console.warn(
                `图片压缩：已达到最大尝试次数，但仍超过 ${(MAX_RETURN_BYTES / 1024 / 1024).toFixed(
                  1
                )}MB，将返回当前压缩版本`
              )
              logCompression(blob, finalName)
              resolve(compressedFile)
              return
            }

            // 优先降低质量（对 webp/jpeg 有效）；质量到底后再缩小尺寸
            if (quality > 0.55) {
              quality = Math.max(0.55, quality - 0.1)
              return tryToBlob(0)
            }

            const nextWidth = Math.max(320, Math.floor(currentWidth * 0.85))
            const nextHeight = Math.max(320, Math.floor(currentHeight * 0.85))
            if (nextWidth === currentWidth && nextHeight === currentHeight) {
              logCompression(blob, finalName)
              resolve(compressedFile)
              return
            }

            currentWidth = nextWidth
            currentHeight = nextHeight
            canvas.width = currentWidth
            canvas.height = currentHeight
            ctx.imageSmoothingEnabled = true
            ctx.imageSmoothingQuality = 'high'

            rafUpdate(() => {
              ctx.drawImage(img, 0, 0, currentWidth, currentHeight)
              tryToBlob(0)
            })
          },
          outType,
          quality
        )
      }

      // 首次绘制后即可释放 ObjectURL（后续仅使用已加载的 img + canvas）
      rafUpdate(() => {
        ctx.drawImage(img, 0, 0, currentWidth, currentHeight)
        revokeObjectURL(objectURL)
        tryToBlob(0)
      })
    }

    img.onerror = () => {
      revokeObjectURL(objectURL)
      resolve(file)
    }

    img.src = objectURL
  })
}

// 添加图片到列表
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

  // 预先生成 ID，确保 catch 分支也能安全引用
  const imageId = Date.now() + Math.random()

  try {
    // 创建加载占位符
    const timestamp = Date.now()
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

    // 释放可能已创建的预览 URL
    try {
      const failed = selectedImages.find(img => img.id === imageId)
      if (failed && failed.previewUrl && failed.previewUrl.startsWith('blob:')) {
        revokeObjectURL(failed.previewUrl)
      }
    } catch (_) {
      // ignore
    }

    // 从列表中移除失败的图片
    selectedImages = selectedImages.filter(img => img.id !== imageId)
    const previewElement = document.getElementById(`preview-${imageId}`)
    if (previewElement) {
      previewElement.remove()
    }
    updateImageCounter()
    updateImagePreviewVisibility()
    return false
  }
}

// 批量DOM更新队列
let domUpdateQueue = []
let domUpdateScheduled = false

// 批量处理DOM更新
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

// 优化的图片预览渲染
function renderImagePreview(imageItem, isLoading = false) {
  rafUpdate(() => {
    const previewContainer = document.getElementById('image-previews')
    if (!previewContainer) {
      console.error('图片预览容器 #image-previews 未找到，无法渲染预览')
      return
    }
    let previewElement = document.getElementById(`preview-${imageItem.id}`)

    if (!previewElement) {
      previewElement = document.createElement('div')
      previewElement.id = `preview-${imageItem.id}`
      previewElement.className = 'image-preview-item'
      previewContainer.appendChild(previewElement)
    }

    // 将 createImagePreview() 生成的 DOM 安全地“解包”到现有容器中
    // 注意：.hidden 使用了 !important，且我们复用已有的 previewElement（保持 id/class 不变）
    const replacePreviewChildren = (container, built) => {
      const fragment = document.createDocumentFragment()
      while (built.firstChild) {
        fragment.appendChild(built.firstChild)
      }
      DOMSecurity.replaceContent(container, fragment)
    }

    // 使用安全的图片预览创建方法
    const newPreviewElement = DOMSecurity.createImagePreview(imageItem, isLoading)
    replacePreviewChildren(previewElement, newPreviewElement)

    if (!isLoading && imageItem.previewUrl) {
      // 延迟加载图片以优化性能
      const img = new Image()
      img.onload = () => {
        rafUpdate(() => {
          const updatedPreviewElement = DOMSecurity.createImagePreview(imageItem, false)
          replacePreviewChildren(previewElement, updatedPreviewElement)
        })
      }
      img.src = imageItem.previewUrl
    }
  })
}

// 文本安全化函数，防止XSS
function sanitizeText(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

// 删除图片
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

// 清除所有图片
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

// 页面卸载时的清理
function cleanupOnUnload() {
  cleanupAllObjectURLs()
  clearAllImages()
}

// 监听页面卸载事件
window.addEventListener('beforeunload', cleanupOnUnload)
window.addEventListener('pagehide', cleanupOnUnload)

// 更新图片计数
function updateImageCounter() {
  const countElement = document.getElementById('image-count')
  if (countElement) {
    countElement.textContent = selectedImages.length
  }
}

// 更新图片预览区域可见性
function updateImagePreviewVisibility() {
  const container = document.getElementById('image-preview-container')
  if (!container) return

  // 注意：.hidden 使用了 display:none !important，不能用 style.display 覆盖
  if (selectedImages.length > 0) {
    container.classList.remove('hidden')
    container.classList.add('visible')
  } else {
    container.classList.add('hidden')
    container.classList.remove('visible')
  }
}

// 优化的批量文件处理
async function handleFileUpload(files) {
  const fileArray = Array.from(files)
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
function initializeDragAndDrop() {
  const textarea = document.getElementById('feedback-text')
  const dragOverlay = document.getElementById('drag-overlay')
  let dragCounter = 0
  let dragTimer = null

  // 阻止默认的拖放行为
  ;['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    document.addEventListener(eventName, preventDefaults, { passive: false })
  })

  function preventDefaults(e) {
    e.preventDefault()
    e.stopPropagation()
  }

  // 节流的拖拽处理函数
  const throttledDragEnter = throttle(e => {
    dragCounter++
    if (e.dataTransfer.types.includes('Files')) {
      rafUpdate(() => {
        dragOverlay.style.display = 'flex'
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
          dragOverlay.style.display = 'none'
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
      dragOverlay.style.display = 'none'
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

// 粘贴功能实现
function initializePasteFunction() {
  const textarea = document.getElementById('feedback-text')

  // data:image/*;base64,xxxx → File
  const dataUriToFile = dataUri => {
    try {
      const match = /^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/.exec(dataUri)
      if (!match) return null

      const mime = match[1]
      const base64 = match[2].replace(/\s+/g, '')

      // 安全限制：避免极端大 data uri 卡死页面（阈值约 15MB base64）
      if (base64.length > 15 * 1024 * 1024) {
        console.warn('剪贴板图片过大（data uri），已跳过')
        return null
      }

      const binaryString = atob(base64)
      const bytes = new Uint8Array(binaryString.length)
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i)
      }

      let ext = 'png'
      if (mime === 'image/jpeg') ext = 'jpg'
      else if (mime === 'image/webp') ext = 'webp'
      else if (mime === 'image/png') ext = 'png'
      const filename = `pasted-image-${Date.now()}.${ext}`
      return new File([bytes], filename, { type: mime, lastModified: Date.now() })
    } catch (err) {
      console.warn('解析剪贴板 data uri 图片失败:', err)
      return null
    }
  }

  // ⚠️ 防重复注册：
  // 某些场景下（例如脚本被重复执行、或初始化函数被重复调用），会导致 paste 监听器被注册多次，
  // 从而出现“粘贴一次添加两张重复图片”的问题。这里通过“先移除旧 handler，再注册新 handler”保证幂等。
  try {
    if (window.__aiInterventionAgentPasteHandler) {
      document.removeEventListener('paste', window.__aiInterventionAgentPasteHandler)
    }
  } catch (_) {
    // ignore
  }

  const pasteHandler = async function (e) {
    const clipboardData = e.clipboardData
    if (!clipboardData) return

    // 仅在“反馈文本框”聚焦时处理图片粘贴（避免影响其他输入场景）
    if (!textarea || document.activeElement !== textarea) return

    const filesToAdd = []

    // 方案 A：优先从 clipboardData.items 获取图片文件（大多数桌面浏览器）
    const items = Array.from(clipboardData.items || [])
    for (const item of items) {
      if (!item) continue
      if (item.kind !== 'file') continue
      if (!item.type || !item.type.startsWith('image/')) continue

      const file = item.getAsFile()
      if (file) filesToAdd.push(file)
    }

    // 方案 B：部分浏览器只在 clipboardData.files 暴露文件
    // 注意：很多浏览器同时在 items 和 files 中暴露同一张图片。
    // 若我们两边都收集，会导致“一次粘贴出现两张重复图片”。
    // 因此仅当方案 A 没拿到图片时，才回退到 files。
    if (filesToAdd.length === 0) {
      const files = Array.from(clipboardData.files || [])
      for (const file of files) {
        if (file && file.type && file.type.startsWith('image/')) {
          filesToAdd.push(file)
        }
      }
    }

    // 方案 C：兜底解析 text/html 或 text/plain 中的 data:image;base64（某些移动端/特殊场景）
    if (filesToAdd.length === 0) {
      const html = clipboardData.getData('text/html') || ''
      const text = clipboardData.getData('text/plain') || clipboardData.getData('text') || ''
      const combined = `${html}\n${text}`

      const dataUriRegex = /data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+/g
      const matches = combined.match(dataUriRegex) || []

      for (const dataUri of matches.slice(0, MAX_IMAGE_COUNT)) {
        const file = dataUriToFile(dataUri)
        if (file) filesToAdd.push(file)
      }
    }

    if (filesToAdd.length === 0) return

    // 如果剪贴板同时有文本内容，尽量不阻止默认粘贴（让文本正常进入 textarea）
    const pastedText = (clipboardData.getData('text/plain') || clipboardData.getData('text') || '').trim()
    if (!pastedText) {
      e.preventDefault()
    }

    let added = 0
    for (const file of filesToAdd) {
      const ok = await addImageToList(file)
      if (ok) added++
    }

    updateImagePreviewVisibility()
    if (added > 0) {
      showStatus(`从剪贴板添加了 ${added} 张图片`, 'success')
    }
  }

  window.__aiInterventionAgentPasteHandler = pasteHandler
  document.addEventListener('paste', pasteHandler)
}

// 文件选择功能
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

// 图片模态框功能
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

function closeImageModal() {
  const modal = document.getElementById('image-modal')
  modal.classList.remove('show')

  // 移除键盘事件监听
  document.removeEventListener('keydown', handleModalKeydown)
}

function handleModalKeydown(event) {
  if (event.key === 'Escape') {
    closeImageModal()
  }
}

// 移动设备检测
function isMobileDevice() {
  return (
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints &&
      navigator.maxTouchPoints > 2 &&
      /MacIntel/.test(navigator.platform))
  )
}

// 平台检测和快捷键设置
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

function getShortcutText(platform) {
  const shortcuts = {
    mac: [
      '⌘+Enter  提交反馈',
      '⌥+C      插入代码',
      '⌘+V      粘贴图片',
      '⌘+U      上传图片',
      'Delete   清除图片'
    ],
    windows: [
      'Ctrl+Enter 提交反馈',
      'Alt+C      插入代码',
      'Ctrl+V     粘贴图片',
      'Ctrl+U     上传图片',
      'Delete     清除图片'
    ],
    linux: [
      'Ctrl+Enter 提交反馈',
      'Alt+C      插入代码',
      'Ctrl+V     粘贴图片',
      'Ctrl+U     上传图片',
      'Delete     清除图片'
    ]
  }

  const lines = shortcuts[platform] || shortcuts.windows
  return lines.join('\n')
}

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

// 浏览器兼容性检测
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

// 特性降级处理
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

// 初始化图片功能
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

// 事件监听器 - 兼容 DOM 已加载完成的情况
function initializeApp() {
  // 初始化 Lottie 沙漏动画
  initHourglassAnimation()

  loadConfig()
    .then(() => {
      // 配置加载完成
      console.log('✅ 配置加载完成')
      console.log('当前配置:', {
        has_content: config.has_content,
        persistent: config.persistent,
        prompt_length: config.prompt ? config.prompt.length : 0
      })

      // 【优化】停用 app.js 内容轮询，使用 multi_task.js 的任务轮询统一管理
      // 原因：两个轮询系统会导致 textarea 内容被意外清空
      // startContentPolling() // 已停用

      // 初始化多任务支持（内含任务轮询）
      if (typeof initMultiTaskSupport === 'function') {
        initMultiTaskSupport()
      }
    })
    .catch(error => {
      console.error('❌ 配置加载失败:', error)
      // 即使配置加载失败，也尝试初始化多任务支持
      setTimeout(() => {
        console.log('🔄 配置加载失败，延迟初始化多任务支持...')
        // startContentPolling() // 已停用

        // 初始化多任务支持（内含任务轮询）
        if (typeof initMultiTaskSupport === 'function') {
          initMultiTaskSupport()
        }
      }, 3000)
    })

  // 初始化图片功能
  initializeImageFeatures()

  // 启动 URL 对象定期清理
  startPeriodicCleanup()

  // 初始化快捷键提示
  initializeShortcutTooltip()

  // 初始化设置管理器（必须在 DOM 加载完成后）
  settingsManager.init().catch(error => {
    console.warn('设置管理器初始化失败:', error)
  })

  // 初始化通知管理器
  notificationManager
    .init()
    .then(() => {
      console.log('通知管理器初始化完成')
      // 应用设置管理器的配置
      settingsManager.applySettings()
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

  // 用户首次交互时启用音频上下文
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

  // 测试通知功能
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
}

// 兼容 DOM 已加载和未加载两种情况
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp)
} else {
  // DOM 已加载完成，立即执行
  initializeApp()
}
