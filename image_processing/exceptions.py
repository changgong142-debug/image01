"""Custom exceptions for the image processing service."""

from __future__ import annotations


class ImageProcessingError(Exception):
    """Base exception for all image processing related errors."""


class UnsupportedImageTypeError(ImageProcessingError):
    """Raised when an unsupported image file extension is encountered."""


class BackgroundRemovalError(ImageProcessingError):
    """Raised when background removal with rembg fails."""
