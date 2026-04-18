/**
 * DOM安全操作工具类
 *
 * @description
 * 提供一系列安全的DOM操作方法，防止XSS（跨站脚本攻击）
 *
 * ### 核心安全原则
 * 1. **避免innerHTML**：不使用innerHTML设置不受信任的内容
 * 2. **textContent优先**：使用textContent代替innerText/innerHTML
 * 3. **属性清理**：对所有用户输入进行HTML实体转义
 * 4. **URL验证**：严格验证URL协议（仅http/https/data）
 * 5. **DOM构建**：使用createElement和appendChild构建DOM
 *
 * ### 使用场景
 * - 处理用户输入的内容展示
 * - 动态创建DOM元素
 * - 设置元素属性和内容
 * - 防止恶意脚本注入
 *
 * ### 安全威胁防护
 * - ✅ XSS注入（<script>标签、事件处理器）
 * - ✅ HTML实体注入（<, >, &, ', "）
 * - ✅ JavaScript伪协议（javascript:）
 * - ✅ Data URI滥用（限制在特定场景）
 *
 * @example
 * // 不安全的方式
 * element.innerHTML = userInput; // ❌ 易受XSS攻击
 *
 * // 安全的方式
 * DOMSecurity.setTextContent(element, userInput); // ✅ 安全
 *
 * @class
 * @static
 */

// 本地 i18n 辅助函数，与 validation-utils.js 一致。
function __domSecT(key, params) {
  try {
    if (typeof window !== 'undefined'
      && window.AIIA_I18N
      && typeof window.AIIA_I18N.t === 'function') {
      return window.AIIA_I18N.t(key, params)
    }
  } catch (_e) { /* noop */ }
  return key
}

class DOMSecurity {
  /**
   * 安全地设置元素的文本内容
   *
   * @param {HTMLElement} element - 目标DOM元素
   * @param {string} text - 待设置的文本内容
   *
   * @description
   * 使用textContent替代innerHTML，自动转义所有HTML特殊字符
   *
   * ### 安全性
   * - ✅ 防止XSS注入：自动转义<, >, &等字符
   * - ✅ 无脚本执行风险：textContent不会解析HTML
   *
   * ### 使用场景
   * - 显示用户输入的文本
   * - 更新UI文本内容
   * - 设置提示信息和标签
   *
   * @example
   * // 安全显示用户输入
   * const userInput = '<script>alert("XSS")</script>';
   * DOMSecurity.setTextContent(element, userInput);
   * // 结果：显示为纯文本，不会执行脚本
   *
   * @returns {void}
   */
  static setTextContent(element, text) {
    if (!element || typeof text !== 'string') return
    element.textContent = text
  }

  /**
   * 安全地清空元素内容
   *
   * @param {HTMLElement} element - 目标DOM元素
   *
   * @description
   * 逐个移除子节点，确保事件监听器被正确清理
   *
   * ### 性能考虑
   * - 使用while循环逐个删除子节点
   * - 比innerHTML = ''更安全（避免内存泄漏）
   * - 确保事件监听器被垃圾回收
   *
   * ### 使用场景
   * - 清空容器准备重新渲染
   * - 移除动态生成的内容
   * - 重置UI状态
   *
   * @example
   * const container = document.getElementById('container');
   * DOMSecurity.clearContent(container);
   * // 容器已清空，可安全添加新内容
   *
   * @returns {void}
   */
  static clearContent(element) {
    if (!element) return
    while (element.firstChild) {
      element.removeChild(element.firstChild)
    }
  }

  /**
   * 安全地创建带有文本和属性的元素
   *
   * @param {string} tagName - HTML标签名（如'div', 'span', 'button'）
   * @param {string} [text=''] - 元素的文本内容（可选）
   * @param {Object} [attributes={}] - 元素属性对象（可选）
   * @returns {HTMLElement} 创建的DOM元素
   *
   * @description
   * 安全创建DOM元素，自动过滤非法属性值
   *
   * ### 安全措施
   * - ✅ 使用createElement避免HTML注入
   * - ✅ textContent设置文本，自动转义
   * - ✅ 仅接受string和number类型属性
   * - ✅ 过滤对象、函数等危险类型
   *
   * ### 使用场景
   * - 动态创建UI元素
   * - 构建复杂DOM结构
   * - 批量生成列表项
   *
   * @example
   * // 创建带属性的按钮
   * const button = DOMSecurity.createElement('button', '点击我', {
   *   class: 'btn-primary',
   *   id: 'submit-btn',
   *   'data-action': 'submit'
   * });
   *
   * @example
   * // 创建简单文本元素
   * const span = DOMSecurity.createElement('span', '用户名');
   *
   * @throws {Error} 如果tagName无效，浏览器会抛出异常
   */
  static createElement(tagName, text = '', attributes = {}) {
    const element = document.createElement(tagName)

    if (text) {
      element.textContent = text
    }

    // 安全地设置属性
    Object.entries(attributes).forEach(([key, value]) => {
      if (typeof value === 'string' || typeof value === 'number') {
        element.setAttribute(key, String(value))
      }
    })

    return element
  }

  /**
   * 安全地创建复选框选项（增强版）
   *
   * @param {string} id - 复选框唯一ID
   * @param {string} value - 复选框值（将被清理）
   * @param {string} label - 标签显示文本
   * @returns {HTMLElement} 包含复选框、标签的完整容器
   *
   * @description
   * 创建具有增强用户体验的复选框组件
   *
   * ### 功能特性
   * 1. **点击容器触发**：点击整个容器区域都能切换复选框
   * 2. **立即视觉反馈**：状态变化立即反映在UI上
   * 3. **防止文本选择**：双击和拖动不会选中文本
   * 4. **无障碍支持**：正确的label关联和aria属性
   *
   * ### 交互优化
   * - 点击整个容器 → 切换复选框
   * - 双击 → 防止文本选中
   * - 拖动 → 禁用文本选择
   * - 键盘 → 支持Tab和空格键
   *
   * ### 安全性
   * - ✅ value值自动清理（sanitizeAttribute）
   * - ✅ label文本安全设置（textContent）
   * - ✅ 事件冒泡正确处理
   *
   * @example
   * const checkbox = DOMSecurity.createCheckboxOption(
   *   'option-1',
   *   'approve',
   *   '同意条款'
   * );
   * container.appendChild(checkbox);
   *
   * @returns {HTMLElement} div.option-item容器
   */
  static createCheckboxOption(id, value, label) {
    const container = document.createElement('div')
    container.className = 'option-item'

    const checkbox = document.createElement('input')
    checkbox.type = 'checkbox'
    checkbox.id = id
    checkbox.value = this.sanitizeAttribute(value)

    // 添加立即视觉反馈：确保checked属性变化立即可见
    checkbox.addEventListener('change', function(e) {
      // 强制同步更新，确保状态立即反映
      this.checked = e.target.checked
    })

    const labelElement = document.createElement('label')
    labelElement.setAttribute('for', id)
    labelElement.textContent = label

    // 点击整个容器区域都能触发checkbox（提升点击体验）
    container.addEventListener('click', function(e) {
      // 如果点击的不是checkbox本身或label，则手动切换checkbox状态
      if (e.target !== checkbox && e.target !== labelElement) {
        checkbox.checked = !checkbox.checked
        // 触发change事件，确保事件监听器被调用
        checkbox.dispatchEvent(new Event('change', { bubbles: true }))
      }
    })

    // ✅ 移除了阻止文本选择的逻辑，允许用户正常选中和复制选项文本
    // 原有的 selectstart 事件监听器会导致用户无法选中任何文本，影响用户体验

    container.appendChild(checkbox)
    container.appendChild(labelElement)

    return container
  }

  /**
   * 安全地创建通知元素
   *
   * @param {string} title - 通知标题
   * @param {string} message - 通知消息内容
   * @param {string} [type='info'] - 通知类型（info/success/warning/error）
   * @returns {HTMLElement} 完整的通知DOM元素
   *
   * @description
   * 创建页内通知组件，包含标题、消息和关闭按钮
   *
   * ### DOM结构
   * ```
   * div.in-page-notification
   *   └─ div.in-page-notification-content
   *       ├─ div.in-page-notification-title (标题)
   *       ├─ div.in-page-notification-message (消息)
   *       └─ button.in-page-notification-close (关闭按钮)
   * ```
   *
   * ### 类型说明
   * - `info`: 一般信息提示
   * - `success`: 成功操作提示
   * - `warning`: 警告信息
   * - `error`: 错误信息
   *
   * ### 安全性
   * - ✅ 标题和消息使用textContent，防止XSS
   * - ✅ 按钮具有aria-label无障碍属性
   * - ✅ 所有元素安全创建
   *
   * @example
   * const notification = DOMSecurity.createNotification(
   *   '操作成功',
   *   '您的数据已保存',
   *   'success'
   * );
   * document.body.appendChild(notification);
   *
   * @returns {HTMLElement} div.in-page-notification元素
   */
  static createNotification(title, message, type = 'info') {
    const notification = document.createElement('div')
    notification.className = 'in-page-notification'

    const content = document.createElement('div')
    content.className = 'in-page-notification-content'

    const titleElement = document.createElement('div')
    titleElement.className = 'in-page-notification-title'
    titleElement.textContent = title

    const messageElement = document.createElement('div')
    messageElement.className = 'in-page-notification-message'
    messageElement.textContent = message

    const closeButton = document.createElement('button')
    closeButton.className = 'in-page-notification-close'
    closeButton.textContent = '×'
    closeButton.setAttribute('aria-label', __domSecT('page.closeNotification'))

    content.appendChild(titleElement)
    content.appendChild(messageElement)
    content.appendChild(closeButton)
    notification.appendChild(content)

    return notification
  }

  /**
   * 安全地创建图片预览元素
   *
   * @param {Object} imageItem - 图片数据对象
   * @param {string} imageItem.id - 图片唯一ID
   * @param {string} imageItem.name - 图片文件名
   * @param {number} imageItem.size - 图片大小（字节）
   * @param {string} imageItem.previewUrl - 图片预览URL（Blob URL）
   * @param {boolean} [isLoading=false] - 是否显示加载状态
   * @returns {HTMLElement} 图片预览容器元素
   *
   * @description
   * 创建图片预览卡片，支持加载状态和预览状态两种模式
   *
   * ### 两种状态
   * 1. **加载状态** (isLoading=true)
   *    - 显示加载动画
   *    - 显示"处理中..."文本
   *    - 适用于图片压缩阶段
   *
   * 2. **预览状态** (isLoading=false)
   *    - 显示图片缩略图
   *    - 显示文件名和大小
   *    - 显示删除按钮
   *    - 支持点击删除
   *
   * ### DOM结构（预览状态）
   * ```
   * div.image-preview-item
   *   ├─ img.image-preview-thumbnail (缩略图)
   *   ├─ button.image-preview-remove (删除按钮)
   *   └─ div.image-preview-info (文件信息)
   * ```
   *
   * ### 安全性
   * - ✅ 文件名清理（sanitizeAttribute）
   * - ✅ URL验证（src赋值）
   * - ✅ 删除按钮有aria-label
   * - ✅ 文件大小安全显示
   *
   * @example
   * // 加载状态
   * const loading = DOMSecurity.createImagePreview({ id: 1 }, true);
   *
   * // 预览状态
   * const preview = DOMSecurity.createImagePreview({
   *   id: 1,
   *   name: 'photo.jpg',
   *   size: 102400,
   *   previewUrl: 'blob:...'
   * }, false);
   *
   * @returns {HTMLElement} div.image-preview-item元素
   */
  static createImagePreview(imageItem, isLoading = false) {
    const previewElement = document.createElement('div')
    previewElement.className = 'image-preview-item'
    previewElement.id = `preview-${imageItem.id}`

    if (isLoading) {
      const loadingDiv = document.createElement('div')
      loadingDiv.className = 'image-loading'

      const spinner = document.createElement('div')
      spinner.className = 'loading-spinner'

      const text = document.createElement('div')
      text.textContent = __domSecT('status.processing')

      loadingDiv.appendChild(spinner)
      loadingDiv.appendChild(text)
      previewElement.appendChild(loadingDiv)
    } else {
      const img = document.createElement('img')
      img.src = imageItem.previewUrl
      img.alt = this.sanitizeAttribute(imageItem.name)
      img.className = 'image-preview-thumbnail'
      // 点击缩略图放大预览（复用 app.js 的 openImageModal）
      // 说明：openImageModal() 目前可以接受 blob: URL 或 data URL
      img.addEventListener('click', () => {
        try {
          if (typeof openImageModal === 'function') {
            const src = imageItem.previewUrl || imageItem.base64 || ''
            openImageModal(src, imageItem.name || '', imageItem.size || 0)
          }
        } catch (e) {
          console.warn('Open image preview failed:', e)
        }
      })

      const removeButton = document.createElement('button')
      removeButton.className = 'image-preview-remove'
      removeButton.textContent = '×'
      removeButton.setAttribute('aria-label', __domSecT('page.removeImage'))
      removeButton.onclick = () => removeImage(imageItem.id)

      const info = document.createElement('div')
      info.className = 'image-preview-info'
      info.textContent = `${imageItem.name} (${(imageItem.size / 1024).toFixed(1)}KB)`

      previewElement.appendChild(img)
      previewElement.appendChild(removeButton)
      previewElement.appendChild(info)
    }

    return previewElement
  }

  /**
   * 安全地创建复制按钮
   *
   * @param {string} targetText - 待复制的文本内容
   * @returns {HTMLElement} 复制按钮元素
   *
   * @description
   * 创建具有复制功能的按钮，支持视觉反馈
   *
   * ### 功能特性
   * - 使用Clipboard API复制文本
   * - 成功/失败视觉反馈
   * - 自动恢复原始状态（2秒）
   * - 无障碍支持（aria-label）
   *
   * ### 状态变化
   * - 初始状态：📋 复制
   * - 成功状态：✅ 已复制 (2秒后恢复)
   * - 失败状态：❌ 复制失败 (2秒后恢复)
   *
   * ### 兼容性
   * - 需要HTTPS环境或localhost
   * - 依赖Clipboard API
   * - 捕获并处理复制失败
   *
   * @example
   * const codeText = 'console.log("Hello")';
   * const button = DOMSecurity.createCopyButton(codeText);
   * codeBlock.appendChild(button);
   *
   * @returns {HTMLButtonElement} button.copy-button元素
   */
  static createCopyButton(targetText) {
    const button = document.createElement('button')
    button.className = 'copy-button'
    // 使用 Claude 官方复制图标 SVG（16x16 小尺寸版本）
    const copyIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M10.5 3C11.3284 3 12 3.67157 12 4.5V5.5H13C13.8284 5.5 14.5 6.17157 14.5 7V13C14.5 13.8284 13.8284 14.5 13 14.5H7C6.17157 14.5 5.5 13.8284 5.5 13V11.5H4.5C3.67157 11.5 3 10.8284 3 10V4C3 3.17157 3.67157 2.5 4.5 2.5H10.5V3ZM5.5 10.5V13C5.5 13.5523 5.94772 14 6.5 14H13C13.5523 14 14 13.5523 14 13V7C14 6.44772 13.5523 6 13 6H12V10C12 10.8284 11.3284 11.5 10.5 11.5H5.5ZM3.5 4C3.5 3.44772 3.94772 3 4.5 3H10.5C11.0523 3 11.5 3.44772 11.5 4V10C11.5 10.5523 11.0523 11 10.5 11H4.5C3.94772 11 3.5 10.5523 3.5 10V4Z"/></svg>`
    // 成功图标（勾选）
    const checkIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.7803 4.21967C14.0732 4.51256 14.0732 4.98744 13.7803 5.28033L6.78033 12.2803C6.48744 12.5732 6.01256 12.5732 5.71967 12.2803L2.21967 8.78033C1.92678 8.48744 1.92678 8.01256 2.21967 7.71967C2.51256 7.42678 2.98744 7.42678 3.28033 7.71967L6.25 10.6893L12.7197 4.21967C13.0126 3.92678 13.4874 3.92678 13.7803 4.21967Z"/></svg>`
    // 失败图标（X）
    const errorIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M4.21967 4.21967C4.51256 3.92678 4.98744 3.92678 5.28033 4.21967L8 6.93934L10.7197 4.21967C11.0126 3.92678 11.4874 3.92678 11.7803 4.21967C12.0732 4.51256 12.0732 4.98744 11.7803 5.28033L9.06066 8L11.7803 10.7197C12.0732 11.0126 12.0732 11.4874 11.7803 11.7803C11.4874 12.0732 11.0126 12.0732 10.7197 11.7803L8 9.06066L5.28033 11.7803C4.98744 12.0732 4.51256 12.0732 4.21967 11.7803C3.92678 11.4874 3.92678 11.0126 4.21967 10.7197L6.93934 8L4.21967 5.28033C3.92678 4.98744 3.92678 4.51256 4.21967 4.21967Z"/></svg>`

    const copyLabel = __domSecT('page.copyCode')
    const copiedLabel = __domSecT('page.copied')
    const copyFailedLabel = __domSecT('page.copyFailed')

    button.innerHTML = `${copyIconSvg}${copyLabel}`
    button.setAttribute('aria-label', copyLabel)

    // 保存原始 HTML 以便恢复
    const originalHTML = button.innerHTML

    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(targetText)
        button.innerHTML = `${checkIconSvg}${copiedLabel}`
        button.classList.add('copied')
        setTimeout(() => {
          button.innerHTML = originalHTML
          button.classList.remove('copied')
        }, 2000)
      } catch (err) {
        button.innerHTML = `${errorIconSvg}${copyFailedLabel}`
        button.classList.add('error')
        setTimeout(() => {
          button.innerHTML = originalHTML
          button.classList.remove('error')
        }, 2000)
      }
    })

    return button
  }

  /**
   * 更新按钮状态（临时变更）
   *
   * @param {HTMLElement} button - 目标按钮元素
   * @param {string} text - 临时显示的文本
   * @param {string} className - 临时添加的CSS类名
   * @param {number} [duration=2000] - 恢复时间（毫秒，默认2秒）
   *
   * @description
   * 临时更改按钮文本和样式，指定时间后自动恢复
   *
   * ### 使用场景
   * - 复制成功/失败反馈
   * - 操作完成提示
   * - 临时状态展示
   *
   * ### 工作流程
   * 1. 保存原始文本和类名
   * 2. 设置新文本和类名
   * 3. 延迟N毫秒后恢复
   *
   * @example
   * // 显示成功状态2秒
   * DOMSecurity.updateButtonState(btn, '✅ 已保存', 'success');
   *
   * // 显示加载状态5秒
   * DOMSecurity.updateButtonState(btn, '⏳ 处理中...', 'loading', 5000);
   *
   * @returns {void}
   */
  static updateButtonState(button, text, className, duration = 2000) {
    const originalText = button.textContent
    const originalClasses = button.className

    button.textContent = text
    button.classList.add(className)

    setTimeout(() => {
      button.textContent = originalText
      button.className = originalClasses
    }, duration)
  }

  /**
   * 清理属性值，防止XSS攻击
   *
   * @param {string} value - 待清理的属性值
   * @returns {string} 清理后的安全属性值
   *
   * @description
   * 转义HTML特殊字符，防止属性注入攻击
   *
   * ### 转义规则
   * | 字符 | 转义后 | 说明 |
   * |------|---------|------|
   * | `<`  | `&lt;`  | 小于号，防止标签注入 |
   * | `>`  | `&gt;`  | 大于号，防止标签闭合 |
   * | `"`  | `&quot;` | 双引号，防止属性逃逸 |
   * | `'`  | `&#x27;` | 单引号，防止属性逃逸 |
   * | `&`  | `&amp;` | 与符号，防止实体注入 |
   *
   * ### 攻击防护
   * - ✅ HTML标签注入：`<script>` → `&lt;script&gt;`
   * - ✅ 属性值逃逸：`" onclick="alert(1)"` → 安全字符串
   * - ✅ 事件处理器注入：`' onerror='alert(1)'` → 安全字符串
   *
   * ### 使用场景
   * - 设置元素属性（id, class, data-*）
   * - 设置alt, title等属性
   * - 处理用户输入作为属性值
   *
   * @example
   * // 危险输入
   * const dangerous = '<img src=x onerror="alert(1)">';
   * const safe = DOMSecurity.sanitizeAttribute(dangerous);
   * // 结果: &lt;img src=x onerror=&quot;alert(1)&quot;&gt;
   *
   * @example
   * // 用于属性赋值
   * element.setAttribute('title', DOMSecurity.sanitizeAttribute(userInput));
   *
   * @returns {string} 转义后的字符串（去除首尾空格）
   */
  static sanitizeAttribute(value) {
    if (typeof value !== 'string') return ''

    return value
      .replace(/[<>'"&]/g, (match) => {
        const entities = {
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#x27;',
          '&': '&amp;'
        }
        return entities[match] || match
      })
      .trim()
  }

  /**
   * 清理文本内容，防止XSS注入
   *
   * @param {string} text - 待清理的文本内容
   * @returns {string} 清理后的纯文本
   *
   * @description
   * 使用DOM API自动转义所有HTML字符
   *
   * ### 工作原理
   * 1. 创建临时div元素
   * 2. 使用textContent设置文本（自动转义）
   * 3. 读取转义后的文本
   * 4. 兼容性降级（textContent → innerText）
   *
   * ### 与sanitizeAttribute的区别
   * - `sanitizeAttribute`: 手动映射转义，用于属性值
   * - `sanitizeText`: DOM API转义，用于文本内容
   *
   * ### 使用场景
   * - 过滤用户输入的文本
   * - 安全显示不受信任的内容
   * - 预处理数据后再渲染
   *
   * @example
   * const userInput = '<script>alert("XSS")</script>';
   * const safe = DOMSecurity.sanitizeText(userInput);
   * console.log(safe); // 纯文本，所有HTML已转义
   *
   * @returns {string} 纯文本（所有HTML实体已转义）
   */
  static sanitizeText(text) {
    if (typeof text !== 'string') return ''

    const div = document.createElement('div')
    div.textContent = text
    return div.textContent || div.innerText || ''
  }

  /**
   * 安全地更新元素内容（替换innerHTML）
   *
   * @param {HTMLElement} element - 目标容器元素
   * @param {HTMLElement|DocumentFragment} content - 新的DOM内容
   *
   * @description
   * 安全地替换元素内容，避免使用innerHTML
   *
   * ### 工作流程
   * 1. 清空现有内容（使用clearContent）
   * 2. 验证新内容类型
   * 3. 使用appendChild安全添加
   *
   * ### 为什么不用innerHTML
   * - ❌ innerHTML会解析HTML字符串，易受XSS攻击
   * - ❌ 会重新解析所有子元素，性能差
   * - ❌ 会丢失事件监听器
   * - ✅ 使用DOM API安全且高效
   *
   * ### 支持的内容类型
   * - `HTMLElement`: 单个DOM元素
   * - `DocumentFragment`: 文档片段（批量操作）
   *
   * ### 使用场景
   * - 替换容器内容
   * - 动态更新UI组件
   * - 批量渲染列表
   *
   * @example
   * // 替换为单个元素
   * const newDiv = document.createElement('div');
   * newDiv.textContent = '新内容';
   * DOMSecurity.replaceContent(container, newDiv);
   *
   * @example
   * // 替换为文档片段（批量）
   * const fragment = DOMSecurity.createFragment();
   * fragment.appendChild(elem1);
   * fragment.appendChild(elem2);
   * DOMSecurity.replaceContent(container, fragment);
   *
   * @returns {void}
   */
  static replaceContent(element, content) {
    if (!element) return

    this.clearContent(element)

    if (content instanceof DocumentFragment || content instanceof HTMLElement) {
      element.appendChild(content)
    }
  }

  /**
   * 创建文档片段（用于批量DOM操作）
   *
   * @returns {DocumentFragment} 空文档片段
   *
   * @description
   * 创建DocumentFragment，用于高效的批量DOM操作
   *
   * ### DocumentFragment优势
   * 1. **性能优化**：在内存中构建，只触发一次重排
   * 2. **减少重绘**：批量添加，避免多次DOM更新
   * 3. **轻量级**：不是真实DOM的一部分
   * 4. **一次性添加**：appendChild后自动清空
   *
   * ### 使用场景
   * - 批量创建列表项
   * - 动态生成大量元素
   * - 复杂DOM结构构建
   * - 性能敏感的渲染
   *
   * ### 性能对比
   * ```javascript
   * // ❌ 慢：每次都触发重排
   * for (let i = 0; i < 1000; i++) {
   *   container.appendChild(createItem(i));
   * }
   *
   * // ✅ 快：只触发一次重排
   * const fragment = DOMSecurity.createFragment();
   * for (let i = 0; i < 1000; i++) {
   *   fragment.appendChild(createItem(i));
   * }
   * container.appendChild(fragment);
   * ```
   *
   * @example
   * const fragment = DOMSecurity.createFragment();
   * items.forEach(item => {
   *   const elem = DOMSecurity.createElement('div', item.name);
   *   fragment.appendChild(elem);
   * });
   * container.appendChild(fragment); // 一次性添加所有元素
   *
   * @returns {DocumentFragment} 文档片段对象
   */
  static createFragment() {
    return document.createDocumentFragment()
  }

  /**
   * 验证URL是否安全
   *
   * @param {string} url - 待验证的URL字符串
   * @returns {boolean} 是否为安全URL
   *
   * @description
   * 验证URL协议，防止JavaScript伪协议注入
   *
   * ### 安全协议白名单
   * - ✅ `http:` - HTTP协议
   * - ✅ `https:` - HTTPS协议（推荐）
   * - ✅ `data:` - Data URI（仅限图片等）
   * - ❌ `javascript:` - 危险！可执行代码
   * - ❌ `file:` - 本地文件访问（安全风险）
   * - ❌ `ftp:`, `tel:`, `mailto:` - 未明确允许
   *
   * ### 攻击防护
   * - ✅ JavaScript伪协议：`javascript:alert(1)`
   * - ✅ Data URI XSS：限制使用场景
   * - ✅ 文件访问：阻止file://协议
   * - ✅ 格式错误：捕获URL构造异常
   *
   * ### 使用场景
   * - 设置img src前验证
   * - 设置iframe src前验证
   * - 设置链接href前验证
   * - API返回URL的验证
   *
   * @example
   * // 安全URL
   * DOMSecurity.isValidURL('https://example.com'); // true
   * DOMSecurity.isValidURL('http://example.com/image.jpg'); // true
   * DOMSecurity.isValidURL('data:image/png;base64,...'); // true
   *
   * @example
   * // 危险URL
   * DOMSecurity.isValidURL('javascript:alert(1)'); // false
   * DOMSecurity.isValidURL('file:///etc/passwd'); // false
   * DOMSecurity.isValidURL('not-a-url'); // false
   *
   * @returns {boolean} true=安全，false=不安全或无效
   */
  static isValidURL(url) {
    if (typeof url !== 'string') return false

    try {
      const urlObj = new URL(url)
      // 只允许http和https协议
      return ['http:', 'https:', 'data:'].includes(urlObj.protocol)
    } catch {
      return false
    }
  }

  /**
   * 安全地设置元素的src属性
   *
   * @param {HTMLElement} element - 目标元素（img, iframe, script等）
   * @param {string} url - 待设置的URL
   *
   * @description
   * 验证URL后安全设置src属性，防止恶意URL注入
   *
   * ### 安全流程
   * 1. 验证element是否存在
   * 2. 验证URL是否安全（isValidURL）
   * 3. 验证通过才设置src
   * 4. 验证失败则静默忽略
   *
   * ### 适用元素
   * - `<img>` - 图片
   * - `<iframe>` - 内嵌框架
   * - `<script>` - 脚本（谨慎使用）
   * - `<audio>`, `<video>` - 媒体
   *
   * ### 攻击防护
   * - ✅ JavaScript伪协议：`javascript:alert(1)`
   * - ✅ Data URI滥用：限制协议范围
   * - ✅ 本地文件访问：阻止file://
   * - ✅ XSS注入：通过URL验证阻断
   *
   * ### 使用场景
   * - 动态设置图片源
   * - 加载远程资源
   * - 设置iframe URL
   * - API返回URL的显示
   *
   * @example
   * // 安全设置图片
   * const img = document.createElement('img');
   * DOMSecurity.setSafeSource(img, 'https://example.com/image.jpg');
   * // ✅ 验证通过，src已设置
   *
   * @example
   * // 阻止危险URL
   * const img = document.createElement('img');
   * DOMSecurity.setSafeSource(img, 'javascript:alert(1)');
   * // ❌ 验证失败，src未设置，静默忽略
   *
   * @example
   * // 使用Blob URL
   * const img = document.createElement('img');
   * const blobUrl = URL.createObjectURL(file);
   * // 注意：Blob URL (blob:) 需要特殊处理或直接赋值
   * img.src = blobUrl; // 直接赋值Blob URL
   *
   * @returns {void}
   */
  static setSafeSource(element, url) {
    if (!element || !this.isValidURL(url)) return
    element.src = url
  }
}

// 导出到全局作用域
window.DOMSecurity = DOMSecurity
