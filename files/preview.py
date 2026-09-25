"""
preview.py

Preview generation and conversion.
"""

from pathlib import Path
from PIL import Image
import pillow_avif


class PreviewProcessor:

    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def find_existing_preview(self, source: Path):
        folder = source.parent
        name = source.stem
        fmt = self.config.PREVIEW_FORMAT.lower()
        possible = [f".{fmt}", ".png", ".jpg", ".jpeg", ".webp"]
        for ext in possible:
            file = folder / f"{name}{ext}"
            if file.exists():
                self.logger.info(f"Existing preview found: {file.name}")
                return file
        return None

    def convert_to_avif(self, source: Path, output: Path) -> tuple[Path, Path, int, int]:
        """
        Produces two files from a single decode:
          - the full preview (configured format)
          - a small thumbnail tier next to it

        Returns (full_preview_path, thumb_path, original_width, original_height).
        """
        fmt = self.config.PREVIEW_FORMAT.upper()
        thumb_fmt = self.config.THUMB_FORMAT.upper()
        self.logger.info(f"Converting {source.name} to {fmt}")
        image = Image.open(source)
        original_width, original_height = image.size

        # Thumbnail first
        thumb_output = output.with_suffix(f".thumb.{self.config.THUMB_FORMAT.lower()}")
        thumb_image = image.copy()
        thumb_image.thumbnail((self.config.THUMB_WIDTH, self.config.THUMB_HEIGHT))
        thumb_image.save(thumb_output, thumb_fmt, quality=self.config.THUMB_QUALITY, speed=self.config.AVIF_SPEED)
        if not thumb_output.exists():
            raise RuntimeError(f"Thumbnail {thumb_fmt} was not created.")

        image.thumbnail((self.config.PREVIEW_WIDTH, self.config.PREVIEW_HEIGHT))
        image.save(output, fmt, quality=self.config.AVIF_QUALITY, speed=self.config.AVIF_SPEED)
        if not output.exists():
            raise RuntimeError(f"{fmt} was not created.")

        return output, thumb_output, original_width, original_height

    def create_contact_sheet(self, image_paths: list[Path], output: Path, cols: int = 4) -> Path:
        """
        Create a grid/contact sheet from a list of image paths.
        Returns the output path of the contact sheet image.
        """
        self.logger.info(f"Creating contact sheet with {len(image_paths)} images ({cols} cols)")
        loaded = []
        for p in image_paths:
            try:
                img = Image.open(p)
                img = img.convert("RGB")
                loaded.append(img)
            except Exception as e:
                self.logger.warning(f"Could not load {p.name} for contact sheet: {e}")

        if not loaded:
            raise RuntimeError("No images could be loaded for contact sheet.")

        thumb_size = (self.config.THUMB_WIDTH // 2, self.config.THUMB_HEIGHT // 2)
        thumbs = []
        for img in loaded:
            img.thumbnail(thumb_size, Image.LANCZOS)
            thumbs.append(img)

        rows = (len(thumbs) + cols - 1) // cols
        sheet_w = cols * thumb_size[0]
        sheet_h = rows * thumb_size[1]
        sheet = Image.new("RGB", (sheet_w, sheet_h), (30, 30, 30))

        for i, img in enumerate(thumbs):
            row = i // cols
            col = i % cols
            x = col * thumb_size[0]
            y = row * thumb_size[1]
            sheet.paste(img, (x, y))

        sheet.save(output, "PNG")
        self.logger.info(f"Contact sheet saved: {output.name} ({sheet_w}x{sheet_h})")
        return output

    def delete_file_safe(self, file: Path):
        try:
            if file.exists():
                file.unlink()
        except Exception as error:
            self.logger.warning(f"Could not delete {file}: {error}")

    @property
    def _image_extensions(self):
        return {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp",
                ".avif", ".heic", ".svg", ".ico"}
