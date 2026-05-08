/**
 * 图片上传与处理模块 - 从 app.js 拆分
 *
 * 职责：图片选择 / 拖拽 / 粘贴 / 压缩 / 预览 / 模态框 / 内存管理
 *
 * 依赖（全局）：showStatus(), t(), DOMSecurity, ValidationUtils, hourglassAnimation
 * 暴露（全局）：selectedImages, initializeImageFeatures(), startPeriodicCleanup(),
 *               clearAllImages, removeImage, openImageModal, handleFileUpload, ...
 *
 * 加载顺序：templates/web_ui.html 中 image-upload.js 在 app.js 之前 defer 加载；
 *          app.js 顶层定义的 function t() 会挂到全局对象上，事件回调执行时可用。
 */

// ========== 图片处理功能 ==========

// 图片管理数组
let selectedImages = []

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
    errors.push(t('validation.invalidFile'))
    return errors
  }
  if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errors.push(t('validation.unsupportedFormat', { type: file.type }))
  }
  if (file.size > MAX_IMAGE_SIZE) {
    const sizeMB = (file.size / 1024 / 1024).toFixed(2)
    const limitMB = (MAX_IMAGE_SIZE / 1024 / 1024).toFixed(0)
    errors.push(t('validation.fileSizeExceeded', { actual: sizeMB, limit: limitMB }))
  }
  if (file.name && file.name.length > 255) {
    errors.push(t('validation.fileNameTooLong'))
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
    setTimeout(
      () => {
        if (objectURLs.has(url)) {
          console.warn(`Auto-cleaning expired object URL: ${url}`)
          revokeObjectURL(url)
        }
      },
      30 * 60 * 1000
    ) // 30分钟

    return url
  } catch (error) {
    console.error('createObjectURL failed:', error)
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
      console.debug(`Revoked object URL: ${url}`)
    }
  } catch (error) {
    console.error('Revoke object URL failed:', error)
  }
}

// 清理所有Object URLs
function cleanupAllObjectURLs() {
  console.log(`Cleaning up ${objectURLs.size} object URLs`)
  const startTime = performance.now()

  objectURLs.forEach(url => {
    try {
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error(`Revoke URL failed: ${url}`, error)
    }
  })

  objectURLs.clear()
  urlCreationTime.clear()

  const endTime = performance.now()
  console.log(`Object URL cleanup done in ${(endTime - startTime).toFixed(2)}ms`)
}

// 定期清理过期的URL对象（每5分钟检查一次）
function startPeriodicCleanup() {
  setInterval(
    () => {
      const now = Date.now()
      const expiredUrls = []

      urlCreationTime.forEach((creationTime, url) => {
        // 清理超过20分钟的URL对象
        if (now - creationTime > 20 * 60 * 1000) {
          expiredUrls.push(url)
        }
      })

      if (expiredUrls.length > 0) {
        console.log(`Periodic cleanup: ${expiredUrls.length} expired object URLs`)
        expiredUrls.forEach(url => revokeObjectURL(url))
      }
    },
    5 * 60 * 1000
  ) // 每5分钟检查一次
}

/**
 * 通过 Image+ObjectURL 解码图片（fallback 路径）
 *
 * 返回结构与 createImageBitmap 路径一致，但内部用 HTMLImageElement，
 * 因此 cleanup() 必须 revoke 它持有的 ObjectURL，否则会泄漏内存。
 *
 * @param {File} file - 输入图片文件
 * @returns {Promise<{kind:'img', image:HTMLImageElement, width:number, height:number, cleanup:Function}>}
 */
function _loadImageViaObjectURL(file) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = createObjectURL(file)
    if (!url) {
      reject(new Error('createObjectURL failed'))
      return
    }
    img.onload = () => {
      resolve({
        kind: 'img',
        image: img,
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
        cleanup: () => revokeObjectURL(url)
      })
    }
    img.onerror = () => {
      revokeObjectURL(url)
      reject(new Error('image decode failed'))
    }
    img.src = url
  })
}

/**
 * R20.12-C：统一的图片解码入口，对齐 packages/vscode/webview-ui.js 的 decodeImageSource
 *
 * 优先 `createImageBitmap`：现代浏览器原生异步解码，**不阻塞主线程**且直出 GPU-friendly
 * bitmap，drawImage(bitmap) 比 drawImage(htmlImg) 快 ~30-50%。失败时回退到 ObjectURL+
 * HTMLImageElement 的旧路径，保持 100% 浏览器兼容性（Safari < 14 / 老版 Firefox 等）。
 *
 * 返回结构契约：
 *   - kind: 'bitmap' | 'img'  — 调试时区分实际走哪条路径用
 *   - image: ImageBitmap | HTMLImageElement  — 直接传给 ctx.drawImage 用
 *   - width / height: number  — 原始像素尺寸，用于计算 maxDimension 缩放比
 *   - cleanup: () => void  — 释放底层资源（bitmap.close() / revokeObjectURL）
 *
 * 调用方契约：
 *   - **必须**在 finally 块调用 `decoded.cleanup()`，否则 ImageBitmap GPU 缓存或 ObjectURL
 *     都会在浏览器内存里逗留，重复上传时会累积；
 *   - 解码失败抛错（不是返回 null），调用方可在 catch 里降级返回原 file。
 *
 * @param {File} file - 输入图片文件
 * @returns {Promise<{kind:string, image:ImageBitmap|HTMLImageElement, width:number, height:number, cleanup:Function}>}
 */
async function decodeImageSource(file) {
  // 优先用 createImageBitmap：避免主线程同步解码（HTMLImageElement.src= 会同步阻塞）
  if (typeof createImageBitmap === 'function') {
    try {
      const bmp = await createImageBitmap(file)
      return {
        kind: 'bitmap',
        image: bmp,
        width: bmp.width,
        height: bmp.height,
        cleanup: () => {
          try {
            bmp.close()
          } catch (_) {
            // close() 在 Safari < 15 不存在，忽略；GC 会回收
          }
        }
      }
    } catch (_) {
      // createImageBitmap 失败（HEIC 等小众格式 / GPU OOM）：回退 ObjectURL 路径
    }
  }
  return _loadImageViaObjectURL(file)
}

// 优化的图片压缩函数
//
// R20.12-C：内部从「new Image() + ObjectURL 同步解码」切到 createImageBitmap
// 异步解码（fallback 兼容老浏览器），单张大图压缩 wall time 实测降 ~40-60%。
// 外部仍返回 Promise<File>，调用方零感知。
async function compressImage(file) {
  // SVG 图片和 GIF 不进行压缩
  if (file.type === 'image/svg+xml' || file.type === 'image/gif') {
    return file
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
    return file
  }

  let decoded
  try {
    decoded = await decodeImageSource(file)
  } catch (_) {
    // 解码失败（损坏图片 / 格式不支持）：原样返回让上层处理
    return file
  }

  return new Promise(resolve => {
    // R20.12-C：所有 resolve 都必须先 cleanup() 释放底层资源（ImageBitmap 或 ObjectURL），
    // 否则重复上传时浏览器会累积内存。包一层 safeResolve 让重构后契约保持一致。
    let cleaned = false
    const safeResolve = val => {
      if (!cleaned) {
        cleaned = true
        try {
          decoded.cleanup()
        } catch (_) {
          // cleanup 失败属于浏览器底层异常，不影响业务返回值
        }
      }
      resolve(val)
    }

    let width = decoded.width || 0
    let height = decoded.height || 0
    if (!width || !height) {
      // 解码无尺寸（损坏图或浏览器异常）：原样返回让上层 fallback
      safeResolve(file)
      return
    }

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
          `Image compression: ${file.name} ${(file.size / 1024).toFixed(2)}KB → ${(
            blob.size / 1024
          ).toFixed(2)}KB (ratio: ${ratio}%) out: ${finalName}`
        )
      } catch (_) {
        // 忽略：日志仅用于观测压缩效果
      }
    }

    let attempt = 0
    const MAX_ATTEMPTS = 8

    const tryToBlob = mimeIndex => {
      const outType = mimeCandidates[mimeIndex]
      if (!outType) {
        safeResolve(file)
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
              safeResolve(compressedFile)
            } else {
              safeResolve(file)
            }
            return
          }

          // 强制：先满足上限；否则继续降质/缩放
          if (blob.size <= MAX_RETURN_BYTES) {
            logCompression(blob, finalName)
            safeResolve(compressedFile)
            return
          }

          attempt++
          if (attempt >= MAX_ATTEMPTS) {
            console.warn(
              `Image compression: max attempts reached but still above ${(
                MAX_RETURN_BYTES /
                1024 /
                1024
              ).toFixed(1)}MB; returning current compressed version`
            )
            logCompression(blob, finalName)
            safeResolve(compressedFile)
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
            safeResolve(compressedFile)
            return
          }

          currentWidth = nextWidth
          currentHeight = nextHeight
          canvas.width = currentWidth
          canvas.height = currentHeight
          ctx.imageSmoothingEnabled = true
          ctx.imageSmoothingQuality = 'high'

          rafUpdate(() => {
            ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)
            tryToBlob(0)
          })
        },
        outType,
        quality
      )
    }

    // 首次绘制（已 await decoded ready）：不再依赖 img.onload。
    rafUpdate(() => {
      ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight)
      tryToBlob(0)
    })
  })
}

// 添加图片到列表
async function addImageToList(file) {
  // 验证图片数量
  if (selectedImages.length >= MAX_IMAGE_COUNT) {
    showStatus(t('status.maxImages', { count: MAX_IMAGE_COUNT }), 'error')
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
    showStatus(t('status.imageDuplicate'), 'error')
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
      throw new Error('createObjectURL failed for preview')
    }

    // 更新预览
    renderImagePreview(imageItem, false)

    console.log('Image added:', file.name, `(${(imageItem.size / 1024).toFixed(2)}KB)`)
    return true
  } catch (error) {
    console.error('Image processing failed:', error)
    showStatus(t('status.imageError', { reason: error.message }), 'error')

    // 释放可能已创建的预览 URL
    try {
      const failed = selectedImages.find(img => img.id === imageId)
      if (failed && failed.previewUrl && failed.previewUrl.startsWith('blob:')) {
        revokeObjectURL(failed.previewUrl)
      }
    } catch (_) {
      // 忽略：失败时继续走清理与回退流程
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

// 优化的图片预览渲染
function renderImagePreview(imageItem, isLoading = false) {
  rafUpdate(() => {
    const previewContainer = document.getElementById('image-previews')
    if (!previewContainer) {
      console.error('Image preview container #image-previews not found; cannot render')
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

  console.log('All images cleared; memory released')
}

// 页面卸载时的清理
function cleanupOnUnload() {
  // 清理 Lottie 动画实例（避免在页面卸载过程中仍占用定时器/RAF）
  try {
    if (hourglassAnimation) {
      hourglassAnimation.destroy()
      hourglassAnimation = null
    }
  } catch (e) {
    // 忽略：卸载过程中销毁动画失败不应影响后续清理
  }
  try {
    const container = document.getElementById('hourglass-lottie')
    if (container) container.textContent = ''
  } catch (e) {
    // 忽略：卸载过程中 DOM 可能已不可用
  }

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
    showStatus(t('status.processingBatch', { count: fileArray.length }), 'info')
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
          showStatus(
            t('status.processProgress', { done: processed, total: fileArray.length }),
            'info'
          )
        }

        return success
      } catch (error) {
        console.error('File processing failed:', file.name, error)
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
      t('status.batchComplete', { successful, total: fileArray.length }),
      successful > 0 ? 'success' : 'error'
    )
  } else if (fileArray.length === 1) {
    const file = fileArray[0]
    const filename = file && file.name ? file.name : ''
    showStatus(
      successful > 0
        ? t('status.fileProcessSuccess', { filename })
        : t('status.fileProcessFailed', { filename, reason: '' }),
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
        showStatus(t('status.maxImages', { count: MAX_IMAGE_COUNT }), 'error')
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
        console.warn('Clipboard data URI too large; skipped')
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
      console.warn('Failed to parse clipboard data URI image:', err)
      return null
    }
  }

  // 防重复注册：
  // 某些场景下（例如脚本被重复执行、或初始化函数被重复调用），会导致 paste 监听器被注册多次，
  // 从而出现“粘贴一次添加两张重复图片”的问题。这里通过“先移除旧 handler，再注册新 handler”保证幂等。
  try {
    if (window.__aiInterventionAgentPasteHandler) {
      document.removeEventListener('paste', window.__aiInterventionAgentPasteHandler)
    }
  } catch (_) {
    // 忽略：移除旧 handler 失败不应阻塞注册新 handler
  }

  const pasteHandler = async function (e) {
    const clipboardData = e.clipboardData
    if (!clipboardData) return

    // 仅在“反馈文本框”聚焦时处理图片粘贴（避免影响其他输入场景）
    if (!textarea || document.activeElement !== textarea) return

    const filesToAdd = []
    let matches = []

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
      matches = combined.match(dataUriRegex) || []

      for (const dataUri of matches.slice(0, MAX_IMAGE_COUNT)) {
        const file = dataUriToFile(dataUri)
        if (file) filesToAdd.push(file)
      }
    }

    if (filesToAdd.length === 0) return

    // 如果剪贴板同时有文本内容，尽量不阻止默认粘贴（让文本正常进入 textarea）
    const rawPastedText = clipboardData.getData('text/plain') || clipboardData.getData('text') || ''
    const pastedText = rawPastedText.trim()
    const dataUriText = pastedText.replace(/\s+/g, '')
    const dataUriOnly =
      matches.length > 0 &&
      /^data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+$/i.test(dataUriText)

    if (!pastedText || dataUriOnly) {
      e.preventDefault()
    }

    let added = 0
    for (const file of filesToAdd) {
      const ok = await addImageToList(file)
      if (ok) added++
    }

    updateImagePreviewVisibility()
    if (added > 0) {
      showStatus(t('status.clipboardAdded', { count: added }), 'success')
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
  const _formatNum =
    (window.AIIA_I18N && window.AIIA_I18N.formatNumber) ||
    function (n) {
      return Number(n).toFixed(2)
    }
  modalInfo.textContent = t('status.sizeLabelKB', {
    name: name,
    size: _formatNum(size / 1024, { maximumFractionDigits: 2 })
  })

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

  console.log('Browser compatibility check:', features)

  // 关键功能检查
  if (!features.fileAPI) {
    showStatus(t('status.noFileAPI'), 'warning')
    return false
  }

  if (!features.canvas) {
    showStatus(t('status.noCanvas'), 'warning')
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
    console.warn('Clipboard API unavailable; falling back to manual paste')
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
    console.error('Browser compatibility check failed')
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

    console.log('Image features initialized')
  } catch (error) {
    console.error('Image features init failed:', error)
    showStatus(t('status.imageInitFailed'), 'error')
  }
}
