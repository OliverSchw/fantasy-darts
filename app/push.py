"""Web-Push ("Du bist dran!") ohne Zusatzdienst: VAPID (RFC 8292) + verschlüsselte Nachricht (RFC 8291, aes128gcm).

Die VAPID-Schlüssel legt die App beim ersten Gebrauch selbst an und speichert sie in app_settings -
es muss nichts eingerichtet werden. Jedes Gerät, das Benachrichtigungen erlaubt, hinterlegt ein
Abo (PushSubscription). Nicht mehr gültige Abos (404/410 vom Push-Dienst) werden gelöscht.

Fehler beim Senden brechen nie die eigentliche Aktion ab (Ergebnis speichern usw.) - sie werden nur geloggt.
"""

import base64
import json
import logging
import os
import struct
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from . import models

log = logging.getLogger(__name__)

VAPID_KEY = "vapid_keys"
BOARD_CALLS = "board_calls"  # Session.info: Matches, die gerade eine Scheibe bekommen haben
VAPID_SUBJECT = "mailto:push@moenninghausen-games.app"
TIMEOUT = 5  # Sekunden pro Push-Dienst-Anfrage
# Tests setzen das auf eine Liste und sammeln die Nachrichten, statt sie zu senden.
outbox: list | None = None


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------------------------------------------------------------- VAPID-Schlüssel


def vapid_keys(db: Session) -> tuple[ec.EllipticCurvePrivateKey, str]:
    """(privater Schlüssel, öffentlicher Schlüssel als base64url) - beim ersten Aufruf neu erzeugt."""
    row = db.get(models.AppSetting, VAPID_KEY)
    if row is None or not isinstance(row.value, dict) or "private" not in row.value:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        if row is None:
            db.add(models.AppSetting(key=VAPID_KEY, value={"private": pem}))
        else:
            row.value = {"private": pem}
        db.commit()
        row = db.get(models.AppSetting, VAPID_KEY)  # bei gleichzeitigem Anlegen gewinnt der gespeicherte
    key = serialization.load_pem_private_key(row.value["private"].encode(), password=None)
    return key, b64u(_raw_public(key))


def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, now: float | None = None) -> str:
    """Authorization-Header: signiertes JWT (ES256) für den Push-Dienst des Endpunkts."""
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
              "sub": VAPID_SUBJECT}
    signing_input = (b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
                     + b64u(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing_input + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={b64u(_raw_public(key))}"


# ---------------------------------------------------------------- Verschlüsselung (RFC 8291)


def _hmac(key: bytes, data: bytes) -> bytes:
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Nachricht für ein Abo verschlüsseln (Content-Encoding: aes128gcm, ein einziger Datensatz)."""
    ua_public = b64u_decode(p256dh)
    auth_secret = b64u_decode(auth)
    salt = salt or os.urandom(16)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(server_key)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = letzter Datensatz, kein Padding
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + body


# ---------------------------------------------------------------- Senden


def _post(endpoint: str, body: bytes, auth_header: str) -> int:
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "Authorization": auth_header, "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": "3600", "Urgency": "high"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code


def send_to_users(db: Session, user_ids, title: str, body: str, url: str, tag: str | None = None) -> int:
    """Benachrichtigung an alle Geräte dieser Nutzer. Gibt die Zahl der zugestellten Nachrichten zurück."""
    user_ids = {u for u in user_ids if u}
    if not user_ids:
        return 0
    subs = db.scalars(select(models.PushSubscription).where(models.PushSubscription.user_id.in_(user_ids))).all()
    if not subs:
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag}).encode()
    if outbox is not None:
        outbox.extend({"user_id": s.user_id, "title": title, "body": body, "url": url} for s in subs)
        return len(subs)
    key, _ = vapid_keys(db)

    def one(sub):
        try:
            return sub, _post(sub.endpoint, encrypt(payload, sub.p256dh, sub.auth), vapid_header(key, sub.endpoint))
        except Exception:  # Netzwerk, kaputter Schlüssel ...
            log.exception("push failed")
            return sub, 0

    with ThreadPoolExecutor(max_workers=min(8, len(subs))) as pool:
        results = list(pool.map(one, subs))
    for sub, status in results:
        if status in (404, 410):  # Abo abgelaufen / abgemeldet
            db.delete(sub)
    db.commit()
    return sum(1 for _, status in results if 200 <= status < 300)


def save_subscription(db: Session, user: models.User, data: dict) -> models.PushSubscription:
    """Abo aus dem Browser (PushSubscription.toJSON()) speichern; ein Endpunkt gehört immer dem letzten Nutzer."""
    try:
        endpoint = str(data["endpoint"])
        p256dh, auth = str(data["keys"]["p256dh"]), str(data["keys"]["auth"])
        if (urlsplit(endpoint).scheme != "https" or len(endpoint) > 1000
                or len(b64u_decode(p256dh)) != 65 or len(b64u_decode(auth)) != 16):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("Invalid push subscription.") from None
    sub = db.scalar(select(models.PushSubscription).where(models.PushSubscription.endpoint == endpoint))
    if sub is None:
        sub = models.PushSubscription(endpoint=endpoint)
        db.add(sub)
    sub.user_id, sub.p256dh, sub.auth = user.id, p256dh, auth
    db.commit()
    return sub


def delete_subscription(db: Session, user: models.User, endpoint: str) -> None:
    sub = db.scalar(select(models.PushSubscription).where(models.PushSubscription.endpoint == endpoint,
                                                          models.PushSubscription.user_id == user.id))
    if sub is not None:
        db.delete(sub)
        db.commit()


# ---------------------------------------------------------------- "Du bist dran": Match bekommt eine Scheibe


def notify_board_calls(bind, match_ids: list[int]) -> int:
    """Alle Spieler (mit Konto) der Matches benachrichtigen - in einer eigenen Session."""
    sent = 0
    with Session(bind=bind, expire_on_commit=False) as db:
        for mid in dict.fromkeys(match_ids):
            m = db.get(models.TournamentMatch, mid)
            if m is None or m.board is None or m.is_played or m.entry1 is None or m.entry2 is None:
                continue  # inzwischen gespielt, gelöscht oder wieder frei
            t = db.get(models.Tournament, m.tournament_id)
            place = "Table" if t.sport == "beerpong" else "Board"
            section = "beerpong" if t.sport == "beerpong" else "darts"
            users = {c.user_id for e in (m.entry1, m.entry2) for c in e.competitors}
            from .tournaments import match_title  # hier, um einen Import-Kreis zu vermeiden
            sent += send_to_users(
                db, users, f"🎯 You're up – {place} {m.board}",
                f"{m.entry1.display_name} vs {m.entry2.display_name} · {t.name} ({match_title(t, m)})",
                f"/{section}/tournaments/{t.id}/matches/{m.id}", tag=f"match-{m.id}")
    return sent


def _after_commit(session: Session) -> None:
    calls = session.info.pop(BOARD_CALLS, None)
    if not calls:
        return
    ids = [inspect(m).identity[0] for m in calls if inspect(m).identity]
    try:
        notify_board_calls(session.get_bind(), ids)
    except Exception:  # Benachrichtigungen dürfen nie das Speichern stören
        log.exception("board notifications failed")


def _after_rollback(session: Session) -> None:
    session.info.pop(BOARD_CALLS, None)


event.listen(Session, "after_commit", _after_commit)
event.listen(Session, "after_rollback", _after_rollback)
