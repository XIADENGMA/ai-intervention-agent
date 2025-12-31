# file_validator

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/file_validator.md`](../api.zh-CN/file_validator.md)

## Functions

### `validate_uploaded_file(file_data: bytes | None, filename: str, mime_type: str | None = None) -> FileValidationResult`

### `is_safe_image_file(file_data: bytes, filename: str) -> bool`

## Classes

### `class ImageTypeInfo`

### `class FileValidationResult`

### `class FileValidationError`

### `class FileValidator`

#### Methods

##### `__init__(self, max_file_size: int = 10 * 1024 * 1024)`

##### `validate_file(self, file_data: bytes | None, filename: str, declared_mime_type: str | None = None) -> FileValidationResult`
