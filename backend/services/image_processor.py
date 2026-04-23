from __future__ import annotations
import asyncio
import hashlib
import io
import logging
import os
from pathlib import Path
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
from PIL.Image import Image as PILImage
from ..config import settings

log = logging.getLogger(__name__)

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _to_srgb(img: PILImage) -> PILImage:
    icc = img.info.get("icc_profile")
    if icc:
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            return ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
        except Exception as e:
            log.warning("ICC convert failed: %s", e)
    return img.convert("RGB") if img.mode != "RGB" else img


def _blur_fill(img: PILImage, target: tuple[int, int]) -> PILImage:
    tw, th = target
    # background = blurred cover
    bg = img.copy()
    bw, bh = bg.size
    scale = max(tw / bw, th / bh)
    bg = bg.resize((int(bw * scale), int(bh * scale)), Image.LANCZOS)
    bx = (bg.width - tw) // 2
    by = (bg.height - th) // 2
    bg = bg.crop((bx, by, bx + tw, by + th))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))
    bg = ImageEnhance.Color(bg).enhance(0.7)

    # foreground = fit by height
    fg = img.copy()
    fw, fh = fg.size
    fscale = th / fh
    new_w = int(fw * fscale)
    if new_w > tw:
        fscale = tw / fw
        new_w = tw
        new_h = int(fh * fscale)
    else:
        new_h = th
    fg = fg.resize((new_w, new_h), Image.LANCZOS)
    fx = (tw - new_w) // 2
    fy = (th - new_h) // 2
    bg.paste(fg, (fx, fy))
    return bg


def _center_crop_resize(img: PILImage, target: tuple[int, int]) -> PILImage:
    tw, th = target
    iw, ih = img.size
    target_ratio = tw / th
    cur_ratio = iw / ih
    if cur_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        x = (iw - new_w) // 2
        img = img.crop((x, 0, x + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        y = (ih - new_h) // 2
        img = img.crop((0, y, iw, y + new_h))
    return img.resize((tw, th), Image.LANCZOS)


def process_image_sync(src_path: str, file_hash: str) -> tuple[str, int, int]:
    """Run pipeline. Return (processed_path, width, height). Cached by hash."""
    out_path = os.path.join(settings.IMAGE_CACHE_DIR, f"{file_hash}.jpg")
    if os.path.exists(out_path):
        with Image.open(out_path) as im:
            return out_path, im.width, im.height

    target = settings.resolution_tuple
    with Image.open(src_path) as im:
        im = ImageOps.exif_transpose(im)
        im = _to_srgb(im)
        iw, ih = im.size
        ratio = iw / ih
        if ratio < 1.3:
            mode = settings.PORTRAIT_HANDLING.lower()
            if mode == "skip":
                # still produce centred letterbox black bg
                processed = Image.new("RGB", target, (0, 0, 0))
                fscale = target[1] / ih
                new_w = int(iw * fscale)
                fg = im.resize((new_w, target[1]), Image.LANCZOS)
                processed.paste(fg, ((target[0] - new_w) // 2, 0))
            elif mode == "crop":
                processed = _center_crop_resize(im, target)
            else:
                processed = _blur_fill(im, target)
        else:
            processed = _center_crop_resize(im, target)

        # subtle sharpen
        processed = processed.filter(ImageFilter.UnsharpMask(radius=1.0, percent=30, threshold=3))

        # strip EXIF, save sRGB jpeg
        clean = Image.new("RGB", processed.size)
        clean.paste(processed)
        clean.save(out_path, "JPEG", quality=95, optimize=True)
        return out_path, clean.width, clean.height


def make_thumbnail_sync(src_path: str, file_hash: str, width: int = 400) -> str:
    out_path = os.path.join(settings.THUMBNAIL_DIR, f"{file_hash}_{width}.jpg")
    if os.path.exists(out_path):
        return out_path
    with Image.open(src_path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        ratio = width / im.width
        new_h = max(1, int(im.height * ratio))
        im = im.resize((width, new_h), Image.LANCZOS)
        im.save(out_path, "JPEG", quality=85, optimize=True)
    return out_path


async def process_image(src_path: str, file_hash: str) -> tuple[str, int, int]:
    return await asyncio.to_thread(process_image_sync, src_path, file_hash)


async def make_thumbnail(src_path: str, file_hash: str, width: int = 400) -> str:
    return await asyncio.to_thread(make_thumbnail_sync, src_path, file_hash, width)


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXT
