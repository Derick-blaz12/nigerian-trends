import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ValidationError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 25_000_000  # refuse decompression bombs before decoding
MIN_SIDE = 200
MAX_SIDE = 1200


def _invalid(message):
    return ValidationError("The image is invalid.", details={"image": message})


def process_image(data):
    """Validate an uploaded image and return clean JPEG bytes (resized, no metadata)."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise _invalid("Use a JPEG, PNG or WebP image.")
        if img.width * img.height > MAX_PIXELS:
            raise _invalid("The image dimensions are too large.")
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise _invalid("The file is not a valid image.") from None

    img = ImageOps.exif_transpose(img)  # respect phone-camera rotation
    if min(img.size) < MIN_SIDE:
        raise _invalid(f"The image must be at least {MIN_SIDE}x{MIN_SIDE} pixels.")

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")

    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)  # re-encoding drops EXIF/GPS
    return out.getvalue()