/**
 * DOM安全操作工具 - 防止XSS攻击
 * 提供安全的DOM操作方法，替换不安全的innerHTML使用
 */

class DOMSecurity {
  /**
   * 安全地设置元素的文本内容
   * @param {HTMLElement} element - 目标元素
   * @param {string} text - 文本内容
   */
  static setTextContent(element, text) {
    if (!element || typeof text !== 'string') return
    element.textContent = text
  }

  /**
   * 安全地清空元素内容
   * @param {HTMLElement} element - 目标元素
   */
  static clearContent(element) {
    if (!element) return
    while (element.firstChild) {
      element.removeChild(element.firstChild)
    }
  }

  /**
   * 安全地创建带有文本的元素
   * @param {string} tagName - 标签名
   * @param {string} text - 文本内容
   * @param {Object} attributes - 属性对象
   * @returns {HTMLElement} 创建的元素
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
   * 安全地创建复选框选项
   * @param {string} id - 复选框ID
   * @param {string} value - 复选框值
   * @param {string} label - 标签文本
   * @returns {HTMLElement} 包含复选框和标签的容器
   */
  static createCheckboxOption(id, value, label) {
    const container = document.createElement('div')
    container.className = 'option-item'
    
    const checkbox = document.createElement('input')
    checkbox.type = 'checkbox'
    checkbox.id = id
    checkbox.value = this.sanitizeAttribute(value)
    
    const labelElement = document.createElement('label')
    labelElement.setAttribute('for', id)
    labelElement.textContent = label
    
    container.appendChild(checkbox)
    container.appendChild(labelElement)
    
    return container
  }

  /**
   * 安全地创建通知元素
   * @param {string} title - 通知标题
   * @param {string} message - 通知消息
   * @param {string} type - 通知类型
   * @returns {HTMLElement} 通知元素
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
    closeButton.setAttribute('aria-label', '关闭通知')
    
    content.appendChild(titleElement)
    content.appendChild(messageElement)
    content.appendChild(closeButton)
    notification.appendChild(content)
    
    return notification
  }

  /**
   * 安全地创建图片预览元素
   * @param {Object} imageItem - 图片项目对象
   * @param {boolean} isLoading - 是否显示加载状态
   * @returns {HTMLElement} 预览元素
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
      text.textContent = '处理中...'
      
      loadingDiv.appendChild(spinner)
      loadingDiv.appendChild(text)
      previewElement.appendChild(loadingDiv)
    } else {
      const img = document.createElement('img')
      img.src = imageItem.previewUrl
      img.alt = this.sanitizeAttribute(imageItem.name)
      img.className = 'image-preview-thumbnail'
      
      const removeButton = document.createElement('button')
      removeButton.className = 'image-remove-btn'
      removeButton.textContent = '×'
      removeButton.setAttribute('aria-label', '删除图片')
      removeButton.onclick = () => removeImage(imageItem.id)
      
      const info = document.createElement('div')
      info.className = 'image-info'
      info.textContent = `${imageItem.name} (${(imageItem.size / 1024).toFixed(1)}KB)`
      
      previewElement.appendChild(img)
      previewElement.appendChild(removeButton)
      previewElement.appendChild(info)
    }
    
    return previewElement
  }

  /**
   * 安全地创建复制按钮
   * @param {string} targetText - 要复制的文本
   * @returns {HTMLElement} 复制按钮
   */
  static createCopyButton(targetText) {
    const button = document.createElement('button')
    button.className = 'copy-button'
    button.textContent = '📋 复制'
    button.setAttribute('aria-label', '复制代码')
    
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(targetText)
        this.updateButtonState(button, '✅ 已复制', 'copied')
      } catch (err) {
        this.updateButtonState(button, '❌ 复制失败', 'error')
      }
    })
    
    return button
  }

  /**
   * 更新按钮状态
   * @param {HTMLElement} button - 按钮元素
   * @param {string} text - 新文本
   * @param {string} className - CSS类名
   * @param {number} duration - 恢复时间（毫秒）
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
   * 清理属性值，防止XSS
   * @param {string} value - 属性值
   * @returns {string} 清理后的值
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
   * 清理文本内容，防止XSS
   * @param {string} text - 文本内容
   * @returns {string} 清理后的文本
   */
  static sanitizeText(text) {
    if (typeof text !== 'string') return ''
    
    const div = document.createElement('div')
    div.textContent = text
    return div.textContent || div.innerText || ''
  }

  /**
   * 安全地更新元素内容（替换innerHTML）
   * @param {HTMLElement} element - 目标元素
   * @param {HTMLElement|DocumentFragment} content - 新内容
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
   * @returns {DocumentFragment} 文档片段
   */
  static createFragment() {
    return document.createDocumentFragment()
  }

  /**
   * 验证URL是否安全
   * @param {string} url - URL字符串
   * @returns {boolean} 是否安全
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
   * @param {HTMLElement} element - 目标元素
   * @param {string} url - URL
   */
  static setSafeSource(element, url) {
    if (!element || !this.isValidURL(url)) return
    element.src = url
  }
}

// 导出到全局作用域
window.DOMSecurity = DOMSecurity
