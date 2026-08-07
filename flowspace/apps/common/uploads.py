"""Shared upload validation helpers.

Django's ImageField only runs its Pillow-based validation when a full
ModelForm/clean() cycle happens. Several views in this project assign an
uploaded file straight to a FileField/ImageField and call .save(), which
skips that validation entirely — allowing any file (regardless of real
content or extension) to be stored and later served back from /media/.
These helpers close that gap and are meant to be called explicitly before
the file is attached to a model instance.
"""
from django.core.exceptions import ValidationError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# Extensions that browsers can execute or render as active content if a user
# is tricked into opening the uploaded file directly (stored XSS / drive-by).
DANGEROUS_EXTENSIONS = {
    ".html", ".htm", ".svg", ".xhtml", ".js", ".mjs", ".php", ".phtml",
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".msi", ".jar", ".py", ".dll",
}


def _ext(filename: str) -> str:
    import os
    return os.path.splitext(filename or "")[1].lower()


def validate_image_upload(file_obj, max_size: int = 5 * 1024 * 1024) -> None:
    """Raise ValidationError unless `file_obj` is a small, genuine raster image."""
    if file_obj.size > max_size:
        raise ValidationError(f"Arquivo muito grande. Máximo {max_size // (1024 * 1024)}MB.")

    if _ext(file_obj.name) not in IMAGE_EXTENSIONS:
        raise ValidationError("Formato de imagem não permitido. Use JPG, PNG, GIF ou WEBP.")

    from PIL import Image, UnidentifiedImageError
    try:
        file_obj.seek(0)
        with Image.open(file_obj) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("O arquivo enviado não é uma imagem válida.")
    finally:
        file_obj.seek(0)


def validate_generic_upload(file_obj, max_size: int = 10 * 1024 * 1024) -> None:
    """Raise ValidationError for oversized files or extensions that are executable/renderable by a browser."""
    if file_obj.size > max_size:
        raise ValidationError(f"Arquivo muito grande. Máximo {max_size // (1024 * 1024)}MB.")

    if _ext(file_obj.name) in DANGEROUS_EXTENSIONS:
        raise ValidationError("Este tipo de arquivo não é permitido por segurança.")
