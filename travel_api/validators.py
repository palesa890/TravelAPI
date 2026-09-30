"""
Reusable validators for uploaded files.

Extension checks alone are easy to fake (rename virus.exe to photo.jpg), so every
upload is also checked by content: images must open with Pillow and PDFs must start
with the PDF magic bytes.
"""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp')
DOCUMENT_EXTENSIONS = ('pdf',) + IMAGE_EXTENSIONS
PDF_MAGIC = b'%PDF-'


@deconstructible
class MaxFileSizeValidator:
    """Reject files larger than `max_mb` megabytes (defaults to settings.MAX_UPLOAD_SIZE_MB)."""

    def __init__(self, max_mb=None):
        self.max_mb = max_mb

    def __call__(self, file):
        limit_mb = self.max_mb or settings.MAX_UPLOAD_SIZE_MB
        if file.size > limit_mb * 1024 * 1024:
            raise ValidationError(
                f'File too large ({file.size / (1024 * 1024):.1f} MB). Maximum size is {limit_mb} MB.',
                code='file_too_large',
            )

    def __eq__(self, other):
        return isinstance(other, MaxFileSizeValidator) and self.max_mb == other.max_mb


@deconstructible
class FileTypeValidator:
    """Check both the extension and the actual file content."""

    def __init__(self, allowed_extensions):
        self.allowed_extensions = tuple(ext.lower() for ext in allowed_extensions)

    def __call__(self, file):
        extension = os.path.splitext(file.name)[1].lstrip('.').lower()
        if extension not in self.allowed_extensions:
            raise ValidationError(
                f'Unsupported file type ".{extension}". Allowed: {", ".join(self.allowed_extensions)}.',
                code='invalid_extension',
            )
        if extension == 'pdf':
            self._check_pdf(file)
        else:
            self._check_image(file)

    @staticmethod
    def _check_pdf(file):
        file.seek(0)
        header = file.read(len(PDF_MAGIC))
        file.seek(0)
        if header != PDF_MAGIC:
            raise ValidationError('File is not a valid PDF.', code='invalid_pdf')

    @staticmethod
    def _check_image(file):
        try:
            file.seek(0)
            # verify() detects truncated or non-image data without decoding the whole file.
            with Image.open(file) as image:
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise ValidationError('File is not a valid image.', code='invalid_image')
        finally:
            file.seek(0)

    def __eq__(self, other):
        return isinstance(other, FileTypeValidator) and self.allowed_extensions == other.allowed_extensions


validate_image_file = FileTypeValidator(IMAGE_EXTENSIONS)
validate_document_file = FileTypeValidator(DOCUMENT_EXTENSIONS)
validate_file_size = MaxFileSizeValidator()
