function __domSecT(key, params) {
  try {
    if (
      typeof window !== 'undefined' &&
      window.AIIA_I18N &&
      typeof window.AIIA_I18N.t === 'function'
    ) {
      return window.AIIA_I18N.t(key, params)
    }
  } catch (_e) {

  }
  return key
}

function __domSecFormatNumber(value, options) {
  try {
    if (
      typeof window !== 'undefined' &&
      window.AIIA_I18N &&
      typeof window.AIIA_I18N.formatNumber === 'function'
    ) {
      return window.AIIA_I18N.formatNumber(value, options)
    }
  } catch (_e) {

  }
  var digits =
    options && typeof options.maximumFractionDigits === 'number' ? options.maximumFractionDigits : 2
  return Number(value).toFixed(digits)
}

class DOMSecurity {

  static clearContent(element) {
    if (!element) return
    while (element.firstChild) {
      element.removeChild(element.firstChild)
    }
  }

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
      img.alt = typeof imageItem.name === 'string' ? imageItem.name : ''
      img.className = 'image-preview-thumbnail'

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
      info.textContent = __domSecT('status.sizeLabelKB', {
        name: imageItem.name,
        size: __domSecFormatNumber(imageItem.size / 1024, { maximumFractionDigits: 1 })
      })

      previewElement.appendChild(img)
      previewElement.appendChild(removeButton)
      previewElement.appendChild(info)
    }

    return previewElement
  }

  static async writeTextToClipboard(text) {
    const value = String(text)
    const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : null
    if (clipboard && typeof clipboard.writeText === 'function') {
      try {
        await clipboard.writeText(value)
        return true
      } catch (_e) {
        // Refused (permission, document not focused): the selection copy may still work.
      }
    }
    return DOMSecurity.copyThroughSelection(value)
  }

  static copyThroughSelection(value) {
    const previouslyFocused = document.activeElement
    const selection = typeof document.getSelection === 'function' ? document.getSelection() : null
    const savedRanges = []
    let helper = null
    try {
      if (selection) {
        for (let index = 0; index < selection.rangeCount; index += 1) {
          savedRanges.push(selection.getRangeAt(index))
        }
      }
      helper = document.createElement('textarea')
      helper.value = value
      helper.setAttribute('readonly', '')
      helper.setAttribute('aria-hidden', 'true')
      helper.style.position = 'fixed'
      helper.style.top = '-1000px'
      helper.style.left = '-1000px'
      helper.style.opacity = '0'
      document.body.appendChild(helper)
      helper.select()
      return document.execCommand('copy') === true
    } catch (_e) {
      return false
    } finally {
      if (helper && helper.parentNode) {
        helper.parentNode.removeChild(helper)
      }
      try {
        if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
          previouslyFocused.focus({ preventScroll: true })
        }
        if (selection && savedRanges.length > 0) {
          selection.removeAllRanges()
          for (const range of savedRanges) {
            selection.addRange(range)
          }
        }
      } catch (_e2) {
        // Restoring focus and selection is best effort; the copy itself already has its result.
      }
    }
  }

  static createCopyButton(targetText) {
    const button = document.createElement('button')
    button.className = 'copy-button'

    const copyIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M10.5 3C11.3284 3 12 3.67157 12 4.5V5.5H13C13.8284 5.5 14.5 6.17157 14.5 7V13C14.5 13.8284 13.8284 14.5 13 14.5H7C6.17157 14.5 5.5 13.8284 5.5 13V11.5H4.5C3.67157 11.5 3 10.8284 3 10V4C3 3.17157 3.67157 2.5 4.5 2.5H10.5V3ZM5.5 10.5V13C5.5 13.5523 5.94772 14 6.5 14H13C13.5523 14 14 13.5523 14 13V7C14 6.44772 13.5523 6 13 6H12V10C12 10.8284 11.3284 11.5 10.5 11.5H5.5ZM3.5 4C3.5 3.44772 3.94772 3 4.5 3H10.5C11.0523 3 11.5 3.44772 11.5 4V10C11.5 10.5523 11.0523 11 10.5 11H4.5C3.94772 11 3.5 10.5523 3.5 10V4Z"/></svg>`

    const checkIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.7803 4.21967C14.0732 4.51256 14.0732 4.98744 13.7803 5.28033L6.78033 12.2803C6.48744 12.5732 6.01256 12.5732 5.71967 12.2803L2.21967 8.78033C1.92678 8.48744 1.92678 8.01256 2.21967 7.71967C2.51256 7.42678 2.98744 7.42678 3.28033 7.71967L6.25 10.6893L12.7197 4.21967C13.0126 3.92678 13.4874 3.92678 13.7803 4.21967Z"/></svg>`

    const errorIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" style="width: 14px; height: 14px; margin-right: 4px; vertical-align: middle;"><path fill-rule="evenodd" clip-rule="evenodd" d="M4.21967 4.21967C4.51256 3.92678 4.98744 3.92678 5.28033 4.21967L8 6.93934L10.7197 4.21967C11.0126 3.92678 11.4874 3.92678 11.7803 4.21967C12.0732 4.51256 12.0732 4.98744 11.7803 5.28033L9.06066 8L11.7803 10.7197C12.0732 11.0126 12.0732 11.4874 11.7803 11.7803C11.4874 12.0732 11.0126 12.0732 10.7197 11.7803L8 9.06066L5.28033 11.7803C4.98744 12.0732 4.51256 12.0732 4.21967 11.7803C3.92678 11.4874 3.92678 11.0126 4.21967 10.7197L6.93934 8L4.21967 5.28033C3.92678 4.98744 3.92678 4.51256 4.21967 4.21967Z"/></svg>`

    const escapeText = value =>
      String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')

    const idleHtml = () => {
      const label = __domSecT('page.copyCode')
      const text = label === 'page.copyCode' ? '' : escapeText(label)
      return `${copyIconSvg}<span data-i18n="page.copyCode">${text}</span>`
    }

    button.innerHTML = idleHtml()
    button.setAttribute('aria-label', __domSecT('page.copyCode'))
    button.setAttribute('data-i18n-aria-label', 'page.copyCode')

    let restoreTimer = null

    const showFeedback = (html, stateClass) => {
      clearTimeout(restoreTimer)
      button.innerHTML = html
      button.classList.remove('copied', 'error')
      button.classList.add(stateClass)
      restoreTimer = setTimeout(() => {
        restoreTimer = null
        button.innerHTML = idleHtml()
        button.classList.remove('copied', 'error')
      }, 2000)
    }

    button.addEventListener('click', async () => {
      if (!(await DOMSecurity.writeTextToClipboard(targetText))) {
        showFeedback(`${errorIconSvg}${escapeText(__domSecT('page.copyFailed'))}`, 'error')
        return
      }
      showFeedback(`${checkIconSvg}${escapeText(__domSecT('page.copied'))}`, 'copied')
    })

    return button
  }

  static replaceContent(element, content) {
    if (!element) return

    this.clearContent(element)

    if (content instanceof DocumentFragment || content instanceof HTMLElement) {
      element.appendChild(content)
    }
  }
}

window.DOMSecurity = DOMSecurity
