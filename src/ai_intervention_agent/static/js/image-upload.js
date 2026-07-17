/**
 * 图片上传与处理模块 - 从 app.js 拆分
 *
 * 职责：图片选择 / 拖拽 / 粘贴 / 压缩 / 预览 / 模态框 / 内存管理
 *
 * 依赖（全局）：showStatus(), t(), DOMSecurity, ValidationUtils, hourglassAnimation
 * 暴露（全局）：selectedImages, initializeImageFeatures(), startPeriodicCleanup(),
 *               stopPeriodicCleanup(), clearAllImages, removeImage, openImageModal,
 *               handleFileUpload, ...
 *
 * 加载顺序：templates/web_ui.html 中 image-upload.js 在 app.js 之前 defer 加载；
 *          app.js 顶层定义的 function t() 会挂到全局对象上，事件回调执行时可用。
 */

// ========== 图片处理功能 ==========

// 图片管理数组
let selectedImages = [];

function isImageItemActive(imageItem) {
  if (!imageItem) return false;
  return selectedImages.some(
    (img) => img === imageItem && img.id === imageItem.id,
  );
}

function dataTransferHasFiles(event) {
  const types =
    event && event.dataTransfer && event.dataTransfer.types
      ? event.dataTransfer.types
      : null;
  if (!types) return false;
  if (typeof types.includes === "function") return types.includes("Files");
  if (typeof types.contains === "function") return types.contains("Files");
  return Array.prototype.indexOf.call(types, "Files") !== -1;
}

function forEachClipboardEntry(collection, callback) {
  if (!collection) return;

  const iterator =
    typeof Symbol !== "undefined" ? collection[Symbol.iterator] : null;
  if (typeof iterator === "function") {
    for (const entry of collection) {
      callback(entry);
    }
    return;
  }

  const length = Number(collection.length);
  if (!Number.isFinite(length) || length <= 0) return;
  for (let i = 0; i < length; i += 1) {
    callback(collection[i]);
  }
}

// 性能优化工具函数

// 防抖函数
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// 节流函数
function throttle(func, limit) {
  let inThrottle;
  return function (...args) {
    if (!inThrottle) {
      func.apply(this, args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

// RAF优化的更新函数
function rafUpdate(callback) {
  if (window.requestAnimationFrame) {
    requestAnimationFrame(callback);
  } else {
    setTimeout(callback, 16); // 降级为60fps
  }
}

// 支持的图片格式（R122：与后端 file_validator.IMAGE_MAGIC_NUMBERS 严格对齐——
// SVG 是 XML 文本，可携带 <script>/onload 实现 XSS，后端无 magic-byte 校验，
// 默认拒绝；前端若放行只会让用户先选 SVG 再被后端 reject，UX 断裂兼安全
// 隐患，因此前后端三端统一不收 SVG。jpg 与 jpeg 同义但少数浏览器/上传组件
// 报 image/jpg，故在前端 MIME 白名单里同时收两个，后端 magic-byte 检测层
// 仍按 image/jpeg 一种实际格式存在）。
const SUPPORTED_IMAGE_TYPES = [
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/gif",
  "image/webp",
  "image/bmp",
];
const MAX_IMAGE_SIZE = 10 * 1024 * 1024; // 10MB
const MAX_IMAGE_COUNT = 10;
const MAX_IMAGE_DIMENSION = 1920; // 最大宽度或高度
const COMPRESS_QUALITY = 0.8; // 压缩质量 (0.1-1.0)

/**
 * 验证图片文件（使用 ValidationUtils 工具类）
 * @param {File} file - 要验证的文件对象
 * @returns {string[]} 错误信息数组
 */
function validateImageFile(file) {
  // 使用 ValidationUtils 进行验证（如果可用）
  if (typeof ValidationUtils !== "undefined") {
    const result = ValidationUtils.validateImageFile(file);
    return result.errors;
  }

  // 回退到基础验证
  const errors = [];
  if (!file || !file.type) {
    errors.push(t("validation.invalidFile"));
    return errors;
  }
  if (!SUPPORTED_IMAGE_TYPES.includes(file.type)) {
    errors.push(t("validation.unsupportedFormat", { type: file.type }));
  }
  if (file.size > MAX_IMAGE_SIZE) {
    const sizeMB = (file.size / 1024 / 1024).toFixed(2);
    const limitMB = (MAX_IMAGE_SIZE / 1024 / 1024).toFixed(0);
    errors.push(
      t("validation.fileSizeExceeded", { actual: sizeMB, limit: limitMB }),
    );
  }
  if (file.name && file.name.length > 255) {
    errors.push(t("validation.fileNameTooLong"));
  }
  return errors;
}

/**
 * 安全的文件名清理（使用 ValidationUtils 工具类）
 * @param {string} fileName - 原始文件名
 * @returns {string} 清理后的安全文件名
 */
function sanitizeFileName(fileName) {
  // 使用 ValidationUtils 进行清理（如果可用）
  if (typeof ValidationUtils !== "undefined") {
    return ValidationUtils.sanitizeFilename(fileName, 100);
  }

  // 回退到基础清理
  return fileName
    .replace(/[<>:"/\\|?*]/g, "")
    .replace(/\s+/g, "_")
    .trim()
    .substring(0, 100);
}

// 注意：已移除 fileToBase64 函数，现在直接使用文件对象上传

// 改进的内存管理跟踪：防止内存泄漏
const OBJECT_URL_MAX_AGE_MS = 20 * 60 * 1000;
const OBJECT_URL_CLEANUP_INTERVAL_MS = 5 * 60 * 1000;

let objectURLs = new Set();
let urlToFileMap = new WeakMap(); // 使用WeakMap跟踪URL与文件的关联
let urlCreationTime = new Map(); // 跟踪URL创建时间，用于自动清理
let objectURLCleanupIntervalId = null;
let objectURLLifecycleListenersInstalled = false;

function shouldRunObjectURLCleanupInterval() {
  if (typeof setInterval !== "function") return false;
  if (objectURLs.size === 0) return false;
  if (typeof document !== "undefined" && document.hidden === true) {
    return false;
  }
  return true;
}

function stopPeriodicCleanup() {
  if (objectURLCleanupIntervalId === null) return false;
  if (typeof clearInterval === "function") {
    clearInterval(objectURLCleanupIntervalId);
  }
  objectURLCleanupIntervalId = null;
  return true;
}

function stopPeriodicCleanupIfIdle() {
  if (objectURLs.size === 0) {
    stopPeriodicCleanup();
  }
}

// 创建安全的Object URL
function createObjectURL(file) {
  try {
    const url = URL.createObjectURL(file);
    objectURLs.add(url);
    urlToFileMap.set(file, url);
    urlCreationTime.set(url, Date.now());
    startPeriodicCleanup();

    return url;
  } catch (error) {
    console.error("createObjectURL failed:", error);
    return null;
  }
}

// 清理Object URL
function revokeObjectURL(url) {
  if (!url) return;

  try {
    if (objectURLs.has(url)) {
      URL.revokeObjectURL(url);
      objectURLs.delete(url);
      urlCreationTime.delete(url);
      stopPeriodicCleanupIfIdle();
      console.debug(`Revoked object URL: ${url}`);
    }
  } catch (error) {
    console.error("Revoke object URL failed:", error);
  }
}

// 清理所有Object URLs
function cleanupAllObjectURLs() {
  console.debug(`Cleaning up ${objectURLs.size} object URLs`);
  const startTime = performance.now();

  for (const url of objectURLs) {
    try {
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error(`Revoke URL failed: ${url}`, error);
    }
  }

  objectURLs.clear();
  urlCreationTime.clear();
  stopPeriodicCleanup();

  const endTime = performance.now();
  console.debug(
    `Object URL cleanup done in ${(endTime - startTime).toFixed(2)}ms`,
  );
}

function cleanupExpiredObjectURLs(now = Date.now()) {
  const expiredUrls = [];

  for (const [url, creationTime] of urlCreationTime) {
    if (now - creationTime > OBJECT_URL_MAX_AGE_MS) {
      expiredUrls.push(url);
    }
  }

  if (expiredUrls.length > 0) {
    console.debug(`Periodic cleanup: ${expiredUrls.length} expired object URLs`);
    const expiredUrlCount = expiredUrls.length;
    for (let index = 0; index < expiredUrlCount; index += 1) {
      revokeObjectURL(expiredUrls[index]);
    }
  }

  stopPeriodicCleanupIfIdle();
  return expiredUrls.length;
}

// 定期清理过期的URL对象（仅在有 URL 且页面可见时运行）
function startPeriodicCleanup() {
  if (objectURLCleanupIntervalId !== null) return objectURLCleanupIntervalId;
  if (!shouldRunObjectURLCleanupInterval()) return null;

  objectURLCleanupIntervalId = setInterval(() => {
    cleanupExpiredObjectURLs();
  }, OBJECT_URL_CLEANUP_INTERVAL_MS);
  return objectURLCleanupIntervalId;
}

function syncObjectURLCleanupWithVisibility() {
  if (typeof document !== "undefined" && document.hidden === true) {
    stopPeriodicCleanup();
    return;
  }
  cleanupExpiredObjectURLs();
  startPeriodicCleanup();
}

function setupObjectURLCleanupLifecycle() {
  if (objectURLLifecycleListenersInstalled) return false;
  objectURLLifecycleListenersInstalled = true;

  if (
    typeof document !== "undefined" &&
    typeof document.addEventListener === "function"
  ) {
    document.addEventListener(
      "visibilitychange",
      syncObjectURLCleanupWithVisibility,
    );
  }

  if (
    typeof window !== "undefined" &&
    typeof window.addEventListener === "function"
  ) {
    window.addEventListener("pageshow", syncObjectURLCleanupWithVisibility);
  }

  return true;
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
    const img = new Image();
    const url = createObjectURL(file);
    if (!url) {
      reject(new Error("createObjectURL failed"));
      return;
    }
    img.onload = () => {
      resolve({
        kind: "img",
        image: img,
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
        cleanup: () => revokeObjectURL(url),
      });
    };
    img.onerror = () => {
      revokeObjectURL(url);
      reject(new Error("image decode failed"));
    };
    img.src = url;
  });
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
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = await createImageBitmap(file);
      return {
        kind: "bitmap",
        image: bmp,
        width: bmp.width,
        height: bmp.height,
        cleanup: () => {
          try {
            bmp.close();
          } catch (_) {
            // close() 在 Safari < 15 不存在，忽略；GC 会回收
          }
        },
      };
    } catch (_) {
      // createImageBitmap 失败（HEIC 等小众格式 / GPU OOM）：回退 ObjectURL 路径
    }
  }
  return _loadImageViaObjectURL(file);
}

// 优化的图片压缩函数
//
// R20.12-C：内部从「new Image() + ObjectURL 同步解码」切到 createImageBitmap
// 异步解码（fallback 兼容老浏览器），单张大图压缩 wall time 实测降 ~40-60%。
// 外部仍返回 Promise<File>，调用方零感知。
async function compressImage(file) {
  // SVG 图片和 GIF 不进行压缩
  if (file.type === "image/svg+xml" || file.type === "image/gif") {
    return file;
  }

  // 强制压缩：避免大图直接原样返回到 MCP 调用方（base64 会非常大）
  const MAX_RETURN_BYTES = 2 * 1024 * 1024; // 2MB
  const forceCompress = file.size > MAX_RETURN_BYTES;

  // 大文件使用更激进的压缩
  const isLargeFile = file.size > 5 * 1024 * 1024; // 5MB

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", {
    alpha: file.type === "image/png",
    willReadFrequently: false,
  });
  if (!ctx) {
    return file;
  }

  let decoded;
  try {
    decoded = await decodeImageSource(file);
  } catch (_) {
    // 解码失败（损坏图片 / 格式不支持）：原样返回让上层处理
    return file;
  }

  return new Promise((resolve) => {
    // R20.12-C：所有 resolve 都必须先 cleanup() 释放底层资源（ImageBitmap 或 ObjectURL），
    // 否则重复上传时浏览器会累积内存。包一层 safeResolve 让重构后契约保持一致。
    let cleaned = false;
    const safeResolve = (val) => {
      if (!cleaned) {
        cleaned = true;
        try {
          decoded.cleanup();
        } catch (_) {
          // cleanup 失败属于浏览器底层异常，不影响业务返回值
        }
      }
      resolve(val);
    };

    let width = decoded.width || 0;
    let height = decoded.height || 0;
    if (!width || !height) {
      // 解码无尺寸（损坏图或浏览器异常）：原样返回让上层 fallback
      safeResolve(file);
      return;
    }

    const originalArea = width * height;

    // 大图片使用更激进的压缩
    let maxDimension = MAX_IMAGE_DIMENSION;
    if (forceCompress || isLargeFile || originalArea > 4000000) {
      // 4MP
      maxDimension = Math.min(MAX_IMAGE_DIMENSION, 1200);
    }

    if (width > maxDimension || height > maxDimension) {
      const ratio = Math.min(maxDimension / width, maxDimension / height);
      width = Math.floor(width * ratio);
      height = Math.floor(height * ratio);
    }

    let currentWidth = width;
    let currentHeight = height;

    canvas.width = currentWidth;
    canvas.height = currentHeight;

    // 优化的绘制设置
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";

    // 根据文件大小调整初始压缩质量
    let quality = COMPRESS_QUALITY;
    if (isLargeFile) {
      quality = Math.max(0.6, COMPRESS_QUALITY - 0.2);
    }
    if (forceCompress) {
      quality = Math.min(quality, 0.75);
    }

    // 选择输出格式：
    // - PNG：小图尽量保持 PNG；大图强制转 WebP/JPEG（PNG 通常无法“有损压缩”）
    // - 其他：优先 WebP（若浏览器不支持则回退 JPEG）
    const mimeCandidates = [];
    if (file.type === "image/png") {
      if (forceCompress || isLargeFile || originalArea > 4000000) {
        mimeCandidates.push("image/webp", "image/jpeg");
      } else {
        mimeCandidates.push("image/png");
      }
    } else if (file.type === "image/webp") {
      mimeCandidates.push("image/webp", "image/jpeg");
    } else {
      if (forceCompress) {
        mimeCandidates.push("image/webp", "image/jpeg");
      } else {
        mimeCandidates.push("image/jpeg");
      }
    }

    const getExtensionForMime = (mimeType) => {
      if (mimeType === "image/png") return ".png";
      if (mimeType === "image/webp") return ".webp";
      if (mimeType === "image/jpeg") return ".jpg";
      return null;
    };

    const replaceExtension = (filename, newExt) => {
      if (!filename || !newExt) return filename;
      const safeName = sanitizeFileName(filename);
      const withoutExt = safeName.replace(/\.[^/.]+$/, "");
      return `${withoutExt}${newExt}`;
    };

    const logCompression = (blob, finalName) => {
      try {
        const ratio = ((1 - blob.size / file.size) * 100).toFixed(1);
        console.debug(
          `Image compression: ${file.name} ${(file.size / 1024).toFixed(2)}KB → ${(
            blob.size / 1024
          ).toFixed(2)}KB (ratio: ${ratio}%) out: ${finalName}`,
        );
      } catch (_) {
        // 忽略：日志仅用于观测压缩效果
      }
    };

    let attempt = 0;
    const MAX_ATTEMPTS = 8;

    const tryToBlob = (mimeIndex) => {
      const outType = mimeCandidates[mimeIndex];
      if (!outType) {
        safeResolve(file);
        return;
      }

      canvas.toBlob(
        (blob) => {
          if (!blob) return tryToBlob(mimeIndex + 1);

          // 确保“声明的 MIME”与“真实文件内容”一致（避免后端 MIME 不一致拒绝）
          if (!blob.type) return tryToBlob(mimeIndex + 1);

          const finalMimeType = blob.type || outType;
          const ext = getExtensionForMime(finalMimeType);
          const finalName = ext ? replaceExtension(file.name, ext) : file.name;

          const compressedFile = new File([blob], finalName, {
            type: finalMimeType,
            lastModified: file.lastModified,
          });

          // 非强制：仅在变小时采用
          if (!forceCompress) {
            if (blob.size < file.size) {
              logCompression(blob, finalName);
              safeResolve(compressedFile);
            } else {
              safeResolve(file);
            }
            return;
          }

          // 强制：先满足上限；否则继续降质/缩放
          if (blob.size <= MAX_RETURN_BYTES) {
            logCompression(blob, finalName);
            safeResolve(compressedFile);
            return;
          }

          attempt++;
          if (attempt >= MAX_ATTEMPTS) {
            console.warn(
              `Image compression: max attempts reached but still above ${(
                MAX_RETURN_BYTES /
                1024 /
                1024
              ).toFixed(1)}MB; returning current compressed version`,
            );
            logCompression(blob, finalName);
            safeResolve(compressedFile);
            return;
          }

          // 优先降低质量（对 webp/jpeg 有效）；质量到底后再缩小尺寸
          if (quality > 0.55) {
            quality = Math.max(0.55, quality - 0.1);
            return tryToBlob(0);
          }

          const nextWidth = Math.max(320, Math.floor(currentWidth * 0.85));
          const nextHeight = Math.max(320, Math.floor(currentHeight * 0.85));
          if (nextWidth === currentWidth && nextHeight === currentHeight) {
            logCompression(blob, finalName);
            safeResolve(compressedFile);
            return;
          }

          currentWidth = nextWidth;
          currentHeight = nextHeight;
          canvas.width = currentWidth;
          canvas.height = currentHeight;
          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = "high";

          rafUpdate(() => {
            ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight);
            tryToBlob(0);
          });
        },
        outType,
        quality,
      );
    };

    // 首次绘制（已 await decoded ready）：不再依赖 img.onload。
    rafUpdate(() => {
      ctx.drawImage(decoded.image, 0, 0, currentWidth, currentHeight);
      tryToBlob(0);
    });
  });
}

// 添加图片到列表
async function addImageToList(file) {
  // 验证图片数量
  if (selectedImages.length >= MAX_IMAGE_COUNT) {
    showStatus(t("status.maxImages", { count: MAX_IMAGE_COUNT }), "error");
    return false;
  }

  // 验证文件
  const errors = validateImageFile(file);
  if (errors.length > 0) {
    showStatus(errors.join("; "), "error");
    return false;
  }

  // 检查是否已经添加过相同文件
  const isDuplicate = selectedImages.some(
    (img) =>
      img.name === file.name &&
      img.size === file.size &&
      img.lastModified === file.lastModified,
  );
  if (isDuplicate) {
    showStatus(t("status.imageDuplicate"), "error");
    return false;
  }

  // 预先生成 ID，确保 catch 分支也能安全引用
  const imageId = Date.now() + Math.random();
  let imageItem = null;

  try {
    // 创建加载占位符
    const timestamp = Date.now();
    imageItem = {
      id: imageId,
      file: file,
      name: file.name,
      size: file.size,
      base64: null,
      timestamp: timestamp,
      lastModified: file.lastModified,
    };

    selectedImages.push(imageItem);
    renderImagePreview(imageItem, true); // true表示显示加载状态
    updateImageCounter();

    // 压缩图片（如果需要）
    const processedFile = await compressImage(file);
    if (!isImageItemActive(imageItem)) {
      return false;
    }

    // 更新文件信息
    imageItem.file = processedFile;
    imageItem.size = processedFile.size;

    // 创建安全的预览 URL
    const previewUrl = createObjectURL(processedFile);
    if (previewUrl) {
      imageItem.previewUrl = previewUrl;
    } else {
      throw new Error("createObjectURL failed for preview");
    }

    // 更新预览
    renderImagePreview(imageItem, false);

    console.debug(
      "Image added:",
      file.name,
      `(${(imageItem.size / 1024).toFixed(2)}KB)`,
    );
    return true;
  } catch (error) {
    if (!isImageItemActive(imageItem)) {
      return false;
    }

    console.error("Image processing failed:", error);
    showStatus(t("status.imageError", { reason: error.message }), "error");

    // 释放可能已创建的预览 URL
    let failureRemoval = null;
    try {
      failureRemoval = prepareImageRemoval(imageId, true);
      const failed = failureRemoval ? failureRemoval.imageToRemove : null;
      if (
        failed &&
        failed.previewUrl &&
        failed.previewUrl.startsWith("blob:")
      ) {
        revokeObjectURL(failed.previewUrl);
      }
    } catch (_) {
      // 忽略：失败时继续走清理与回退流程
    }

    // 从列表中移除失败的图片
    if (failureRemoval) selectedImages = failureRemoval.nextImages;
    const previewElement = document.getElementById(`preview-${imageId}`);
    if (previewElement) {
      previewElement.remove();
    }
    updateImageCounter();
    updateImagePreviewVisibility();
    return false;
  }
}

// 优化的图片预览渲染
function renderImagePreview(imageItem, isLoading = false) {
  rafUpdate(() => {
    if (!isImageItemActive(imageItem)) {
      return;
    }

    const previewContainer = document.getElementById("image-previews");
    if (!previewContainer) {
      console.error(
        "Image preview container #image-previews not found; cannot render",
      );
      return;
    }
    let previewElement = document.getElementById(`preview-${imageItem.id}`);

    if (!previewElement) {
      previewElement = document.createElement("div");
      previewElement.id = `preview-${imageItem.id}`;
      previewElement.className = "image-preview-item";
      previewContainer.appendChild(previewElement);
    }

    // 将 createImagePreview() 生成的 DOM 安全地“解包”到现有容器中
    // 注意：.hidden 使用了 !important，且我们复用已有的 previewElement（保持 id/class 不变）
    const replacePreviewChildren = (container, built) => {
      const fragment = document.createDocumentFragment();
      while (built.firstChild) {
        fragment.appendChild(built.firstChild);
      }
      DOMSecurity.replaceContent(container, fragment);
    };

    // 使用安全的图片预览创建方法
    const newPreviewElement = DOMSecurity.createImagePreview(
      imageItem,
      isLoading,
    );
    replacePreviewChildren(previewElement, newPreviewElement);

    if (!isLoading && imageItem.previewUrl) {
      // 延迟加载图片以优化性能
      const img = new Image();
      img.onload = () => {
        rafUpdate(() => {
          if (!isImageItemActive(imageItem)) {
            return;
          }
          const currentPreviewElement = document.getElementById(
            `preview-${imageItem.id}`,
          );
          if (!currentPreviewElement) {
            return;
          }
          const updatedPreviewElement = DOMSecurity.createImagePreview(
            imageItem,
            false,
          );
          replacePreviewChildren(currentPreviewElement, updatedPreviewElement);
        });
      };
      img.src = imageItem.previewUrl;
    }
  });
}

// 文本安全化函数，防止XSS
function sanitizeText(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// 删除图片
function prepareImageRemoval(imageId, strictId = false) {
  let nextImages = null;
  let imageToRemove = null;
  for (let i = 0; i < selectedImages.length; i += 1) {
    const image = selectedImages[i];
    const matches = strictId ? image.id === imageId : image.id == imageId;
    if (matches) {
      if (imageToRemove === null) imageToRemove = image;
      if (nextImages === null) nextImages = selectedImages.slice(0, i);
    } else if (nextImages !== null) {
      nextImages.push(image);
    }
  }
  if (nextImages === null) return null;
  return { imageToRemove, nextImages };
}

function removeImage(imageId) {
  // 找到要删除的图片并安全释放 URL
  const removal = prepareImageRemoval(imageId);
  const imageToRemove = removal ? removal.imageToRemove : null;
  if (
    imageToRemove &&
    imageToRemove.previewUrl &&
    imageToRemove.previewUrl.startsWith("blob:")
  ) {
    revokeObjectURL(imageToRemove.previewUrl);
  }

  if (removal) selectedImages = removal.nextImages;
  const previewElement = document.getElementById(`preview-${imageId}`);
  if (previewElement) {
    previewElement.remove();
  }
  updateImageCounter();
  updateImagePreviewVisibility();
}

// 清除所有图片
function clearAllImages() {
  // 清理内存中的 Object URLs
  const selectedImageCount = selectedImages.length;
  for (let index = 0; index < selectedImageCount; index += 1) {
    if (!(index in selectedImages)) continue;
    const img = selectedImages[index];
    if (img.previewUrl && img.previewUrl.startsWith("blob:")) {
      revokeObjectURL(img.previewUrl);
    }
  }

  selectedImages = [];
  const previewContainer = document.getElementById("image-previews");
  // 安全清空容器内容
  DOMSecurity.clearContent(previewContainer);
  updateImageCounter();
  updateImagePreviewVisibility();

  // 强制垃圾回收提示（仅在开发环境）
  if (window.gc && typeof window.gc === "function") {
    setTimeout(() => window.gc(), 1000);
  }

  console.debug("All images cleared; memory released");
}

// 页面离开时的清理
function cleanupOnPageExit(event) {
  if (event && event.persisted === true) {
    stopPeriodicCleanup();
    return;
  }

  // 清理 Lottie 动画实例（避免在页面卸载过程中仍占用定时器/RAF）
  try {
    if (hourglassAnimation) {
      hourglassAnimation.destroy();
      hourglassAnimation = null;
    }
  } catch (e) {
    // 忽略：卸载过程中销毁动画失败不应影响后续清理
  }
  try {
    const container = document.getElementById("hourglass-lottie");
    if (container) container.textContent = "";
  } catch (e) {
    // 忽略：卸载过程中 DOM 可能已不可用
  }

  cleanupAllObjectURLs();
  clearAllImages();
}

setupObjectURLCleanupLifecycle();

// 监听页面离开事件；pagehide 与 bfcache 兼容，持久化时只暂停定时器。
window.addEventListener("pagehide", cleanupOnPageExit);

// 更新图片计数
function updateImageCounter() {
  const countElement = document.getElementById("image-count");
  if (countElement) {
    countElement.textContent = selectedImages.length;
  }
}

// 更新图片预览区域可见性
function updateImagePreviewVisibility() {
  const container = document.getElementById("image-preview-container");
  if (!container) return;

  // 注意：.hidden 使用了 display:none !important，不能用 style.display 覆盖
  if (selectedImages.length > 0) {
    container.classList.remove("hidden");
    container.classList.add("visible");
  } else {
    container.classList.add("hidden");
    container.classList.remove("visible");
  }
}

// 优化的批量文件处理
async function handleFileUpload(files) {
  const fileCount = files.length;
  const maxConcurrent = 3; // 限制并发处理数量
  let processed = 0;
  let successful = 0;

  // 显示批量处理进度
  if (fileCount > 1) {
    showStatus(
      t("status.processingBatch", { count: fileCount }),
      "info",
    );
  }

  // 分批处理文件，避免内存溢出
  for (let i = 0; i < fileCount; i += maxConcurrent) {
    const batchEnd = Math.min(i + maxConcurrent, fileCount);
    const batchPromises = [];

    for (let j = i; j < batchEnd; j += 1) {
      const file = files[j];
      batchPromises.push(
        (async () => {
          try {
            const success = await addImageToList(file);
            if (success) successful++;
            processed++;

            // 更新进度
            if (fileCount > 1) {
              showStatus(
                t("status.processProgress", {
                  done: processed,
                  total: fileCount,
                }),
                "info",
              );
            }

            return success;
          } catch (error) {
            console.error("File processing failed:", file.name, error);
            processed++;
            return false;
          }
        })(),
      );
    }

    // 等待当前批次完成
    await Promise.all(batchPromises);

    // 批次间添加小延迟，避免阻塞UI
    if (batchEnd < fileCount) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }

  updateImagePreviewVisibility();

  // 显示最终结果
  if (fileCount > 1) {
    showStatus(
      t("status.batchComplete", { successful, total: fileCount }),
      successful > 0 ? "success" : "error",
    );
  } else if (fileCount === 1) {
    const file = files[0];
    const filename = file && file.name ? file.name : "";
    showStatus(
      successful > 0
        ? t("status.fileProcessSuccess", { filename })
        : t("status.fileProcessFailed", { filename, reason: "" }),
      successful > 0 ? "success" : "error",
    );
  }
}

// 优化的拖放功能实现
function initializeDragAndDrop() {
  if (typeof window.__aiInterventionAgentDragDropCleanup === "function") {
    try {
      window.__aiInterventionAgentDragDropCleanup();
    } catch (_) {
      // 忽略：旧 handler 清理失败不应阻止重新绑定当前 DOM
    }
  }

  const textarea = document.getElementById("feedback-text");
  const dragOverlay = document.getElementById("drag-overlay");

  if (!textarea || !dragOverlay) {
    const missing = [];
    if (!textarea) missing.push("#feedback-text");
    if (!dragOverlay) missing.push("#drag-overlay");
    console.debug(
      `Image drag-and-drop skipped: ${missing.join(", ")} unavailable`,
    );
    return false;
  }

  let dragCounter = 0;
  let dragTimer = null;
  const listenerEntries = [];

  const addDocumentListener = (type, handler, options) => {
    document.addEventListener(type, handler, options);
    listenerEntries.push({ type, handler, options });
  };

  // 阻止默认的拖放行为
  const preventDefaultListenerOptions = { passive: false };
  addDocumentListener("dragenter", preventDefaults, preventDefaultListenerOptions);
  addDocumentListener("dragover", preventDefaults, preventDefaultListenerOptions);
  addDocumentListener("dragleave", preventDefaults, preventDefaultListenerOptions);
  addDocumentListener("drop", preventDefaults, preventDefaultListenerOptions);

  function preventDefaults(e) {
    if (!dataTransferHasFiles(e)) return;
    e.preventDefault();
    e.stopPropagation();
  }

  // 节流的拖拽处理函数
  const throttledFileDragEnter = throttle((e) => {
    dragCounter++;
    rafUpdate(() => {
      dragOverlay.style.display = "flex";
      textarea.classList.add("textarea-drag-over");
    });
  }, 100);

  const throttledFileDragLeave = throttle((e) => {
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      clearTimeout(dragTimer);
      dragTimer = setTimeout(() => {
        rafUpdate(() => {
          dragOverlay.style.display = "none";
          textarea.classList.remove("textarea-drag-over");
        });
      }, 100);
    }
  }, 50);

  const throttledFileDragOver = throttle((e) => {
    e.dataTransfer.dropEffect = "copy";
  }, 50);

  const dragEnterHandler = (e) => {
    if (!dataTransferHasFiles(e)) return;
    throttledFileDragEnter(e);
  };

  const dragLeaveHandler = (e) => {
    if (!dataTransferHasFiles(e)) return;
    throttledFileDragLeave(e);
  };

  const dragOverHandler = (e) => {
    if (!dataTransferHasFiles(e)) return;
    throttledFileDragOver(e);
  };

  const dropHandler = function (e) {
    dragCounter = 0;
    clearTimeout(dragTimer);

    rafUpdate(() => {
      dragOverlay.style.display = "none";
      textarea.classList.remove("textarea-drag-over");
    });

    const files = e && e.dataTransfer ? e.dataTransfer.files : null;
    if (!files || files.length === 0) return;

    // 验证文件数量限制
    const totalFiles = selectedImages.length + files.length;
    if (totalFiles > MAX_IMAGE_COUNT) {
      showStatus(t("status.maxImages", { count: MAX_IMAGE_COUNT }), "error");
      return;
    }

    handleFileUpload(files);
  };

  // 拖拽事件监听
  addDocumentListener("dragenter", dragEnterHandler);
  addDocumentListener("dragleave", dragLeaveHandler);
  addDocumentListener("dragover", dragOverHandler);
  addDocumentListener("drop", dropHandler);

  function cleanupDragAndDrop() {
    const listenerEntryCount = listenerEntries.length;
    for (let index = 0; index < listenerEntryCount; index += 1) {
      if (!(index in listenerEntries)) continue;
      const entry = listenerEntries[index];
      document.removeEventListener(entry.type, entry.handler, entry.options);
    }
    clearTimeout(dragTimer);
    dragCounter = 0;
    dragOverlay.style.display = "none";
    textarea.classList.remove("textarea-drag-over");
    if (window.__aiInterventionAgentDragDropCleanup === cleanupDragAndDrop) {
      window.__aiInterventionAgentDragDropCleanup = null;
    }
  }

  window.__aiInterventionAgentDragDropCleanup = cleanupDragAndDrop;

  return true;
}

// 粘贴功能实现
function initializePasteFunction() {
  const textarea = document.getElementById("feedback-text");

  // data:image/*;base64,xxxx → File
  const dataUriToFile = (dataUri) => {
    try {
      const match = /^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$/.exec(dataUri);
      if (!match) return null;

      const mime = match[1];
      const base64 = match[2].replace(/\s+/g, "");

      // 安全限制：避免极端大 data uri 卡死页面（阈值约 15MB base64）
      if (base64.length > 15 * 1024 * 1024) {
        console.warn("Clipboard data URI too large; skipped");
        return null;
      }

      const binaryString = atob(base64);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      let ext = "png";
      if (mime === "image/jpeg") ext = "jpg";
      else if (mime === "image/webp") ext = "webp";
      else if (mime === "image/png") ext = "png";
      const filename = `pasted-image-${Date.now()}.${ext}`;
      return new File([bytes], filename, {
        type: mime,
        lastModified: Date.now(),
      });
    } catch (err) {
      console.warn("Failed to parse clipboard data URI image:", err);
      return null;
    }
  };

  // 防重复注册：
  // 某些场景下（例如脚本被重复执行、或初始化函数被重复调用），会导致 paste 监听器被注册多次，
  // 从而出现“粘贴一次添加两张重复图片”的问题。这里通过“先移除旧 handler，再注册新 handler”保证幂等。
  try {
    if (window.__aiInterventionAgentPasteHandler) {
      document.removeEventListener(
        "paste",
        window.__aiInterventionAgentPasteHandler,
      );
    }
  } catch (_) {
    // 忽略：移除旧 handler 失败不应阻塞注册新 handler
  }

  const pasteHandler = async function (e) {
    const clipboardData = e.clipboardData;
    if (!clipboardData) return;

    // 仅在“反馈文本框”聚焦时处理图片粘贴（避免影响其他输入场景）
    if (!textarea || document.activeElement !== textarea) return;

    const filesToAdd = [];
    let matches = [];

    // 方案 A：优先从 clipboardData.items 获取图片文件（大多数桌面浏览器）
    forEachClipboardEntry(clipboardData.items, (item) => {
      if (!item) return;
      if (item.kind !== "file") return;
      if (!item.type || !item.type.startsWith("image/")) return;

      const file = item.getAsFile();
      if (file) filesToAdd.push(file);
    });

    // 方案 B：部分浏览器只在 clipboardData.files 暴露文件
    // 注意：很多浏览器同时在 items 和 files 中暴露同一张图片。
    // 若我们两边都收集，会导致“一次粘贴出现两张重复图片”。
    // 因此仅当方案 A 没拿到图片时，才回退到 files。
    if (filesToAdd.length === 0) {
      forEachClipboardEntry(clipboardData.files, (file) => {
        if (file && file.type && file.type.startsWith("image/")) {
          filesToAdd.push(file);
        }
      });
    }

    // 方案 C：兜底解析 text/html 或 text/plain 中的 data:image;base64（某些移动端/特殊场景）
    if (filesToAdd.length === 0) {
      const html = clipboardData.getData("text/html") || "";
      const text =
        clipboardData.getData("text/plain") ||
        clipboardData.getData("text") ||
        "";
      const combined = `${html}\n${text}`;

      const dataUriRegex =
        /data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+/g;
      matches = combined.match(dataUriRegex) || [];

      for (const dataUri of matches.slice(0, MAX_IMAGE_COUNT)) {
        const file = dataUriToFile(dataUri);
        if (file) filesToAdd.push(file);
      }
    }

    if (filesToAdd.length === 0) return;

    // 如果剪贴板同时有文本内容，尽量不阻止默认粘贴（让文本正常进入 textarea）
    const rawPastedText =
      clipboardData.getData("text/plain") ||
      clipboardData.getData("text") ||
      "";
    const pastedText = rawPastedText.trim();
    const dataUriText = pastedText.replace(/\s+/g, "");
    const dataUriOnly =
      matches.length > 0 &&
      /^data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+$/i.test(dataUriText);

    if (!pastedText || dataUriOnly) {
      e.preventDefault();
    }

    let added = 0;
    for (const file of filesToAdd) {
      const ok = await addImageToList(file);
      if (ok) added++;
    }

    updateImagePreviewVisibility();
    if (added > 0) {
      showStatus(t("status.clipboardAdded", { count: added }), "success");
    }
  };

  window.__aiInterventionAgentPasteHandler = pasteHandler;
  document.addEventListener("paste", pasteHandler);
}

// 文件选择功能
function initializeFileSelection() {
  const fileInput = document.getElementById("file-upload-input");
  const uploadBtn = document.getElementById("upload-image-btn");

  if (!fileInput || !uploadBtn) {
    console.debug(
      "Image file selection skipped: upload controls unavailable",
    );
    return false;
  }

  if (!uploadBtn.dataset.aiiaImageUploadWired) {
    uploadBtn.dataset.aiiaImageUploadWired = "1";
    uploadBtn.addEventListener("click", () => {
      if (typeof fileInput.click === "function") {
        fileInput.click();
      }
    });
  }

  if (!fileInput.dataset.aiiaImageUploadWired) {
    fileInput.dataset.aiiaImageUploadWired = "1";
    fileInput.addEventListener("change", (e) => {
      const target = e && e.target ? e.target : fileInput;
      if (target.files && target.files.length > 0) {
        handleFileUpload(target.files);
        // 清空input，允许重复选择相同文件
        target.value = "";
      }
    });
  }

  return true;
}

// 图片模态框功能（cycle-8 Track B R263：完整 a11y dialog 行为）
//
// 历史问题（cycle-8 audit 发现）：
//   1. 每次 openImageModal 都 addEventListener("click", ...) 给 modal，
//      累积 N 个 anonymous handler 永不解绑（leak + 多次触发）。
//   2. 缺 focus 管理：用户键盘打开 modal 后焦点丢失，关闭后无法回到
//      触发元素，违反 WAI-ARIA Dialog Pattern。
//   3. 缺 Tab trap：用户 Tab 出 modal 后能进入背景（虽然 aria-modal
//      告诉 AT 忽略背景，但视觉/键盘焦点还能游走）。
//
// 修复参考 keyboard_shortcut_help.js (cycle-1 Track A R255) 的模式。

let _imageModalPreviouslyFocusedElement = null;
let _imageModalKeydownHandlersAttached = false;

function _imageModalBackgroundClickHandler(e) {
  const modal = document.getElementById("image-modal");
  if (e.target === modal) {
    closeImageModal();
  }
}

function _imageModalTabTrapHandler(event) {
  // image-modal 内只有 1 个可聚焦元素（close button），简化方案：把所有
  // Tab/Shift+Tab 都重定向回 close button，焦点不会逸出。
  if (event.key !== "Tab") return;
  const closeBtn = document.querySelector(".image-modal-close");
  if (!closeBtn) return;
  event.preventDefault();
  try {
    closeBtn.focus();
  } catch (_e) {
    // ignore: focus could throw if element is removed mid-event
  }
}

function _initImageModalOnce() {
  // 只在 DOMContentLoaded 时绑一次背景点击事件，避免 R263 历史 leak。
  const modal = document.getElementById("image-modal");
  if (!modal || modal.dataset.aiiaInited === "1") return;
  modal.addEventListener("click", _imageModalBackgroundClickHandler);
  modal.dataset.aiiaInited = "1";
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _initImageModalOnce);
} else {
  _initImageModalOnce();
}

function _attachImageModalKeydownHandlers() {
  if (_imageModalKeydownHandlersAttached) return;
  document.addEventListener("keydown", handleModalKeydown);
  document.addEventListener("keydown", _imageModalTabTrapHandler);
  _imageModalKeydownHandlersAttached = true;
}

function _detachImageModalKeydownHandlers() {
  if (!_imageModalKeydownHandlersAttached) return;
  document.removeEventListener("keydown", handleModalKeydown);
  document.removeEventListener("keydown", _imageModalTabTrapHandler);
  _imageModalKeydownHandlersAttached = false;
}

function _getImageModalPartsForOpen() {
  const modal = document.getElementById("image-modal");
  const modalImage = document.getElementById("modal-image");
  const modalInfo = document.getElementById("modal-info");

  if (!modal || !modalImage || !modalInfo) {
    const missing = [];
    if (!modal) missing.push("#image-modal");
    if (!modalImage) missing.push("#modal-image");
    if (!modalInfo) missing.push("#modal-info");
    console.debug(`Image modal open skipped: ${missing.join(", ")} unavailable`);
    return null;
  }

  return { modal, modalImage, modalInfo };
}

function openImageModal(base64, name, size) {
  const parts = _getImageModalPartsForOpen();
  if (!parts) return false;

  const { modal, modalImage, modalInfo } = parts;
  const wasAlreadyOpen = modal.classList.contains("show");

  modalImage.src = base64;
  modalImage.alt = name;
  const _formatNum =
    (window.AIIA_I18N && window.AIIA_I18N.formatNumber) ||
    function (n) {
      return Number(n).toFixed(2);
    };
  modalInfo.textContent = t("status.sizeLabelKB", {
    name: name,
    size: _formatNum(size / 1024, { maximumFractionDigits: 2 }),
  });

  // R263 a11y: 记录触发元素以便 close 时回归焦点（cycle-1 R255 pattern）。
  // 若 modal 已打开，只更新图片内容，不把 opener 污染成 modal 内 close button。
  if (!wasAlreadyOpen) {
    _imageModalPreviouslyFocusedElement = document.activeElement;
  }

  // R237 follow-up：HTML 默认带 ``hidden`` attribute（screen reader 跳过且
  // user-agent stylesheet 默认 ``display: none``），打开 modal 时必须先
  // 移除该属性，否则即使加了 ``.show`` class 屏幕阅读器仍会忽略整个 dialog。
  modal.removeAttribute("hidden");
  modal.classList.add("show");

  _attachImageModalKeydownHandlers();

  // R263 a11y: 把焦点移到 close button（modal 内唯一可聚焦元素）
  const closeBtn = modal.querySelector(".image-modal-close");
  if (!wasAlreadyOpen && closeBtn) {
    try {
      closeBtn.focus();
    } catch (_e) {
      // ignore
    }
  }

  return true;
}

function closeImageModal() {
  const modal = document.getElementById("image-modal");
  if (modal) {
    modal.classList.remove("show");
    // R237 follow-up：恢复 ``hidden`` attribute，让 screen reader 重新跳过
    // 整个 modal 并避免 page-load 残留焦点陷阱。
    modal.setAttribute("hidden", "");
  } else {
    console.debug("Image modal close skipped: #image-modal unavailable");
  }

  _detachImageModalKeydownHandlers();

  // R263 a11y: 焦点回归到触发元素（cycle-1 R255 pattern）
  if (
    _imageModalPreviouslyFocusedElement &&
    document.contains(_imageModalPreviouslyFocusedElement)
  ) {
    try {
      _imageModalPreviouslyFocusedElement.focus();
    } catch (_e) {
      // ignore: focus restore is best-effort
    }
  }
  _imageModalPreviouslyFocusedElement = null;

  return !!modal;
}

function handleModalKeydown(event) {
  if (event.key === "Escape") {
    closeImageModal();
  }
}

// 浏览器兼容性检测
function checkBrowserCompatibility() {
  const features = {
    fileAPI: !!(
      window.File &&
      window.FileReader &&
      window.FileList &&
      window.Blob
    ),
    dragDrop: "ondragstart" in document.createElement("div"),
    canvas: !!document.createElement("canvas").getContext,
    webWorker: !!window.Worker,
    requestAnimationFrame: !!(
      window.requestAnimationFrame || window.webkitRequestAnimationFrame
    ),
    objectURL: !!(window.URL && window.URL.createObjectURL),
    clipboard: !!(navigator.clipboard && navigator.clipboard.read),
  };

  console.debug("Browser compatibility check:", features);

  // 关键功能检查
  if (!features.fileAPI) {
    showStatus(t("status.noFileAPI"), "warning");
    return false;
  }

  if (!features.canvas) {
    showStatus(t("status.noCanvas"), "warning");
  }

  return true;
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
        return setTimeout(callback, 16);
      };
  }

  // 复制API降级
  if (!navigator.clipboard) {
    console.warn("Clipboard API unavailable; falling back to manual paste");
  }

  // Object.assign降级
  if (!Object.assign) {
    Object.assign = function (target, ...sources) {
      for (let sourceIndex = 0; sourceIndex < sources.length; sourceIndex += 1) {
        const source = sources[sourceIndex];
        if (source) {
          for (const key in source) {
            if (Object.prototype.hasOwnProperty.call(source, key)) {
              target[key] = source[key];
            }
          }
        }
      }
      return target;
    };
  }
}

// 初始化图片功能
function initializeImageFeatures() {
  // 兼容性检查
  if (!checkBrowserCompatibility()) {
    console.error("Browser compatibility check failed");
    return;
  }

  // 设置降级处理
  setupFeatureFallbacks();

  try {
    initializeDragAndDrop();
    initializePasteFunction();
    initializeFileSelection();

    // 清除所有图片按钮事件
    const clearBtn = document.getElementById("clear-all-images-btn");
    if (clearBtn && !clearBtn.dataset.aiiaImageUploadWired) {
      clearBtn.dataset.aiiaImageUploadWired = "1";
      clearBtn.addEventListener("click", clearAllImages);
    }

    console.debug("Image features initialized");
  } catch (error) {
    console.error("Image features init failed:", error);
    showStatus(t("status.imageInitFailed"), "error");
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    OBJECT_URL_MAX_AGE_MS,
    OBJECT_URL_CLEANUP_INTERVAL_MS,
    createObjectURL,
    revokeObjectURL,
    cleanupAllObjectURLs,
    cleanupExpiredObjectURLs,
    startPeriodicCleanup,
    stopPeriodicCleanup,
    setupObjectURLCleanupLifecycle,
    _getObjectURLLifecycleState: () => ({
      size: objectURLs.size,
      cleanupIntervalId: objectURLCleanupIntervalId,
      lifecycleListenersInstalled: objectURLLifecycleListenersInstalled,
      trackedUrls: Array.from(objectURLs),
      creationTimes: Array.from(urlCreationTime.entries()),
    }),
  };
}
