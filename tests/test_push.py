"""Push-Benachrichtigungen: Verschlüsselung (RFC 8291), VAPID, Abos und "Du bist dran" bei Scheiben-Zuteilung."""

import json

import pytest
from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import competitors, models, push
from app import tournaments as tour
from app.darts import service
from app.main import app


def _hmac(key, data):
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def _device():
    """Schlüssel eines "Browsers": (privater Schlüssel, Abo-JSON)."""
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, auth, {"endpoint": f"https://push.example.com/send/{push.b64u(pub[:8])}",
                       "keys": {"p256dh": push.b64u(pub), "auth": push.b64u(auth)}}


def _decrypt(body: bytes, ua_key, auth: bytes) -> bytes:
    """Empfängerseite nach RFC 8291 / RFC 8188 - so entschlüsselt der Browser die Nachricht."""
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public = body[21:21 + idlen]
    assert rs == 4096 and idlen == 65
    ua_public = ua_key.public_key().public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = _hmac(_hmac(auth, shared), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_roundtrip():
    key, auth, sub = _device()
    body = push.encrypt(b'{"title": "Hi"}', sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert _decrypt(body, key, auth) == b'{"title": "Hi"}'
    # jedes Mal neues Salz und neuer Server-Schlüssel
    assert push.encrypt(b"x", sub["keys"]["p256dh"], sub["keys"]["auth"])[:16] != body[:16]


def test_rfc8291_test_vector():
    """Beispiel aus RFC 8291, Anhang A - gleiche Eingaben müssen byte-genau dieselbe Nachricht ergeben."""
    as_key = ec.derive_private_key(int.from_bytes(
        push.b64u_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = push.encrypt(b"When I grow up, I want to be a watermelon",
                        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                        "BTBZMqHH6r4Tts7J_aSIgg", salt=push.b64u_decode("DGv6ra1nlYgDCS1FRnbzlw"), server_key=as_key)
    assert push.b64u(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBr"
        "u3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_vapid_keys_and_jwt(db):
    key, public = push.vapid_keys(db)
    assert push.vapid_keys(db)[1] == public  # gespeichert, nicht jedes Mal neu
    assert len(push.b64u_decode(public)) == 65
    header = push.vapid_header(key, "https://fcm.googleapis.com/fcm/send/abc", now=1000)
    assert header.startswith("vapid t=") and header.endswith(f", k={public}")
    jwt = header[len("vapid t="):].split(",")[0]
    h, c, sig = jwt.split(".")
    assert json.loads(push.b64u_decode(h)) == {"typ": "JWT", "alg": "ES256"}
    claims = json.loads(push.b64u_decode(c))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["exp"] == 1000 + 12 * 3600
    assert claims["sub"].startswith("mailto:")
    raw = push.b64u_decode(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.b64u_decode(public))
    pub.verify(der, f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))  # wirft, wenn falsch


@pytest.fixture
def client(db, make_user):
    make_user("olli")
    with TestClient(app) as c:
        c.post("/login", data={"username": "olli", "password": "secret123"})
        yield c


@pytest.fixture
def outbox():
    push.outbox = []
    yield push.outbox
    push.outbox = None


def test_subscribe_unsubscribe(client, db, make_user):
    r = client.get("/push/key")
    assert r.status_code == 200 and r.json()["devices"] == 0
    _, _, sub = _device()
    assert client.post("/push/subscribe", json=sub).json() == {"ok": True}
    assert client.post("/push/subscribe", json=sub).status_code == 200  # doppelt = kein zweites Abo
    rows = db.scalars(select(models.PushSubscription)).all()
    assert len(rows) == 1 and rows[0].user_id == db.scalar(select(models.User.id).where(models.User.username == "olli"))
    assert client.get("/push/key").json()["devices"] == 1
    # kaputte Abos
    for bad in ({}, {"endpoint": "http://x", "keys": sub["keys"]}, {"endpoint": sub["endpoint"], "keys": {"p256dh": "abc", "auth": "x"}}):
        assert client.post("/push/subscribe", json=bad).status_code == 400
    # anderer Nutzer auf demselben Gerät übernimmt das Abo
    make_user("dana")
    with TestClient(app) as c2:
        c2.post("/login", data={"username": "dana", "password": "secret123"})
        c2.post("/push/subscribe", json=sub)
        db.expire_all()
        assert db.scalar(select(models.PushSubscription)).user_id == db.scalar(
            select(models.User.id).where(models.User.username == "dana"))
        assert client.post("/push/unsubscribe", json={"endpoint": sub["endpoint"]}).status_code == 200
        db.expire_all()
        assert db.scalar(select(models.PushSubscription)) is not None  # olli darf danas Abo nicht löschen
        c2.post("/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    db.expire_all()
    assert db.scalar(select(models.PushSubscription)) is None
    # ohne Login
    with TestClient(app) as anon:
        assert anon.post("/push/subscribe", json=sub, follow_redirects=False).status_code in (303, 401)


def test_send_and_expired_subscriptions(db, make_user, monkeypatch):
    u = make_user("olli")
    key, auth, sub = _device()
    push.save_subscription(db, u, sub)
    _, _, gone = _device()
    gone["endpoint"] += "gone"
    push.save_subscription(db, u, gone)
    calls = []

    def fake_post(endpoint, body, auth_header):
        calls.append(endpoint)
        if endpoint.endswith("gone"):
            return 410
        payload = json.loads(_decrypt(body, key, auth))
        assert payload == {"title": "T", "body": "B", "url": "/x", "tag": None}
        assert auth_header.startswith("vapid t=")
        return 201

    monkeypatch.setattr(push, "_post", fake_post)
    assert push.send_to_users(db, [u.id], "T", "B", "/x") == 1
    assert len(calls) == 2
    assert [s.endpoint for s in db.scalars(select(models.PushSubscription))] == [sub["endpoint"]]
    assert push.send_to_users(db, [], "T", "B", "/x") == 0
    assert push.send_to_users(db, [None], "T", "B", "/x") == 0


def test_test_notification(client, db, outbox):
    assert client.post("/push/test").json() == {"sent": 0}
    _, _, sub = _device()
    client.post("/push/subscribe", json=sub)
    assert client.post("/push/test").json() == {"sent": 1}
    assert outbox[0]["title"].startswith("🎯")


def _players(db, make_user, names):
    users = [make_user(n) for n in names]
    for u in users:
        push.save_subscription(db, u, _device()[2])
    return users, [competitors.competitor_for_user(db, u).id for u in users]


def test_board_call_notifies_players(db, make_user, outbox):
    users, cids = _players(db, make_user, ["anna", "ben", "carl", "dora"])
    t = tour.create_tournament(db, "darts", "Board Cup", [[c] for c in cids],
                               {"start": 301, "legs": 1, "final_legs": 1, "boards": 1}, None)
    first = next(m for m in t.matches if m.board == 1)
    names = {first.entry1.display_name, first.entry2.display_name}
    assert len(outbox) == 2 and {o["user_id"] for o in outbox} == {
        u.id for u in users if u.username in names}
    assert outbox[0]["title"] == "🎯 You're up – Board 1"
    assert outbox[0]["url"] == f"/darts/tournaments/{t.id}/matches/{first.id}"
    assert "Board Cup" in outbox[0]["body"] and " vs " in outbox[0]["body"]
    # Ergebnis -> nächstes Match kommt auf die Scheibe -> die anderen beiden bekommen Bescheid
    outbox.clear()
    service.record_tournament_result(db, t, first, 1, 0)
    second = next(m for m in t.matches if m.board == 1 and not m.is_played)
    assert {o["user_id"] for o in outbox} == {c.user_id for e in (second.entry1, second.entry2) for c in e.competitors}
    assert all(o["url"].endswith(f"/matches/{second.id}") for o in outbox)
    # Organisator ändert nur die Zahl der Scheiben (kein neues Match frei) -> keine Nachricht
    outbox.clear()
    tour.set_boards(db, t, 1)
    assert outbox == []


def test_board_call_rollback_and_guests(db, make_user, outbox):
    users, cids = _players(db, make_user, ["anna", "ben"])
    guests = [competitors.create_guest(db, n).id for n in ("Gast1", "Gast2")]
    t = tour.create_tournament(db, "beerpong", "Pong", [[cids[0], guests[0]], [cids[1], guests[1]]], {"boards": 0}, None)
    outbox.clear()
    # Zuteilung, die zurückgerollt wird, schickt nichts
    t.settings = {**t.settings, "boards": 1}
    tour.assign_boards(t)
    db.rollback()
    db.commit()
    assert outbox == []
    tour.set_boards(db, t, 1)
    assert {o["user_id"] for o in outbox} == {users[0].id, users[1].id}  # Gäste haben kein Konto
    assert outbox[0]["title"] == "🎯 You're up – Table 1" and outbox[0]["url"].startswith("/beerpong/")


def test_push_errors_never_break_results(db, make_user, monkeypatch):
    users, cids = _players(db, make_user, ["anna", "ben", "carl"])

    def boom(*a, **k):
        raise RuntimeError("push service down")

    monkeypatch.setattr(push, "_post", boom)  # einzelne Fehler werden abgefangen
    t = tour.create_tournament(db, "darts", "Cup", [[c] for c in cids], {"start": 301, "legs": 1, "final_legs": 1,
                                                                        "boards": 2}, None)
    assert sum(1 for m in t.matches if m.board) == 1
    monkeypatch.setattr(push, "send_to_users", boom)  # selbst ein Totalausfall stört das Speichern nicht
    m = next(m for m in t.matches if m.board)
    service.record_tournament_result(db, t, m, 1, 0)
    db.expire_all()
    assert db.get(models.TournamentMatch, m.id).is_played


def test_account_page_and_banner(client, db, make_user):
    r = client.get("/account")
    assert "Turn on notifications" in r.text and "/static/push.js" in r.text
    olli = db.scalar(select(models.User).where(models.User.username == "olli"))
    me = competitors.competitor_for_user(db, olli).id
    other = competitors.create_guest(db, "Gast").id
    t = tour.create_tournament(db, "darts", "Cup", [[me], [other]], {"start": 301, "legs": 1, "final_legs": 1,
                                                                     "boards": 1}, None)
    assert "pushToggle(true)" in client.get(f"/darts/tournaments/{t.id}").text
    t2 = tour.create_tournament(db, "darts", "Not mine", [[other], [competitors.create_guest(db, "G2").id]],
                                {"start": 301, "legs": 1, "final_legs": 1, "boards": 1}, None)
    assert "pushToggle(true)" not in client.get(f"/darts/tournaments/{t2.id}").text
    sw = client.get("/sw.js").text
    assert 'addEventListener("push"' in sw and "notificationclick" in sw
