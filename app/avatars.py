"""Profilbilder: hochgeladenes Bild prüfen, quadratisch zuschneiden, verkleinern und speichern.

Das Bild wird immer neu kodiert. Dadurch landen nur echte, kleine Bilder in der DB, und
Metadaten (z. B. GPS-Position aus Handyfotos) werden entfernt.
"""

import time
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from . import models

SIZE = 512
MAX_UPLOAD = 5 * 1024 * 1024  # Bytes; Vercel nimmt ohnehin höchstens ~4.5 MB pro Anfrage an
MAX_PIXELS = 40_000_000  # Schutz gegen "Dekompressionsbomben"


class AvatarError(ValueError):
    pass


def process_image(data: bytes) -> bytes:
    if not data:
        raise AvatarError("Please choose an image.")
    if len(data) > MAX_UPLOAD:
        raise AvatarError("The image is too large (max. 5 MB).")
    try:
        with Image.open(BytesIO(data)) as img:
            if img.width * img.height > MAX_PIXELS:
                raise AvatarError("The image has too many pixels.")
            img = ImageOps.exif_transpose(img)  # Handyfotos richtig herum drehen
            img = ImageOps.fit(img.convert("RGBA"), (SIZE, SIZE), Image.Resampling.LANCZOS)
    except AvatarError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise AvatarError("This file is not a supported image (JPEG, PNG, WebP or GIF).") from None
    # Transparenz auf weißen Hintergrund legen
    flat = Image.new("RGB", img.size, (255, 255, 255))
    flat.paste(img, mask=img.getchannel("A"))
    out = BytesIO()
    flat.save(out, "WEBP", quality=82, method=4)
    return out.getvalue()


def save_avatar(db: Session, user: models.User, data: bytes) -> None:
    """Prüft und speichert das Bild. Wirft AvatarError mit einer Meldung für den User."""
    image = process_image(data)
    avatar = db.get(models.Avatar, user.id) or models.Avatar(user_id=user.id)
    avatar.image = image
    avatar.updated_at = models._now()
    db.add(avatar)
    # Zeitstempel statt Zähler: nach Löschen + neuem Upload bekommt das Bild trotzdem eine neue URL
    user.avatar_version = max(int(time.time()), (user.avatar_version or 0) + 1)
    db.commit()


def delete_avatar(db: Session, user: models.User) -> None:
    avatar = db.get(models.Avatar, user.id)
    if avatar is not None:
        db.delete(avatar)
    user.avatar_version = None
    db.commit()
