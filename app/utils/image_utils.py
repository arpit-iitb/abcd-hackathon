import base64
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image


def load_image_base64(path: Optional[str], max_dim: int = 512, quality: int = 60) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = Path(__file__).resolve().parents[2] / file_path
    if not file_path.exists():
        raise FileNotFoundError(f"Missing image file: {file_path}")

    with Image.open(file_path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
