"""Public API for the image processing package."""

from .exceptions import BackgroundRemovalError, ImageProcessingError, UnsupportedImageTypeError
from .service import ImageProcessingService, ImageMetadata, JobResult
from . import utils

__all__ = [
    "BackgroundRemovalError",
    "ImageMetadata",
    "ImageProcessingService",
    "ImageProcessingError",
    "JobResult",
    "UnsupportedImageTypeError",
    "utils",
]
