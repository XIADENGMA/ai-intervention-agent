# file_validator

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/file_validator.md`](../api/file_validator.md)

文件验证模块 - 魔数验证、恶意内容扫描、文件名安全检查，防止上传攻击。

## 函数

### `validate_uploaded_file(file_data: bytes | None, filename: str, mime_type: str | None = None) -> FileValidationResult`

便捷函数：使用默认单例验证文件

### `is_safe_image_file(file_data: bytes, filename: str) -> bool`

便捷函数：返回文件是否通过验证

## 类

### `class ImageTypeInfo`

图片类型信息（用于魔数识别）

### `class FileValidationResult`

文件验证结果结构（用于类型检查与 IDE 提示）

### `class FileValidator`

文件验证器 - 魔数验证、恶意内容扫描、文件名安全检查。

#### 方法

##### `__init__(self, max_file_size: int = 10 * 1024 * 1024)`

初始化并预编译恶意内容正则

##### `validate_file(self, file_data: bytes | None, filename: str, declared_mime_type: str | None = None) -> FileValidationResult`

验证文件安全性，返回 {valid, file_type, mime_type, extension, size, warnings, errors}
