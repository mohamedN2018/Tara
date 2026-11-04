#!/usr/bin/env python3
"""End-to-end API check through the gateway, as two real users.

Needs the running stack (`make up`). Standard library only.

    python scripts/smoke_test.py
    TARA_API=https://tara.example.com/api/v1 TARA_MAILPIT= python scripts/smoke_test.py

Writes nothing but synthetic users and their content. Exits 1 on any failure.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.getenv("TARA_API", "http://127.0.0.1:8080/api/v1")
MAILPIT = os.getenv("TARA_MAILPIT", "http://127.0.0.1:8026/api/v1")
PASSWORD = "Str0ng-Pass-987!"  # noqa: S105 - synthetic test user
# Identity's LEGAL_TERMS_VERSION / LEGAL_PRIVACY_VERSION (override when they change).
LEGAL_VERSION = os.getenv("TARA_LEGAL_VERSION", "2026-11-04-draft")
EVENT_TIMEOUT_SECONDS = 20
PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)
failures: list[str] = []


def call(method, url, token=None, body=None, raw=None, headers=None):
    all_headers = {"Content-Type": "application/json"}
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    all_headers.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    target = url if url.startswith("http") else API + url
    request = urllib.request.Request(target, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, exc.read()
    try:
        return status, json.loads(payload)
    except ValueError:
        return status, payload


def data(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def check(name, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        print(f"     {str(detail)[:300]}")
        failures.append(name)


def eventually(fetch, predicate):
    """Poll until an asynchronous event has taken effect."""
    deadline = time.time() + EVENT_TIMEOUT_SECONDS
    result = fetch()
    while not predicate(result) and time.time() < deadline:
        time.sleep(0.5)
        result = fetch()
    return result


def make_user(name, tag):
    email = f"{name}{tag}@example.com"
    # The full sign-up body (plan 08, track 1D): names, confirmed password,
    # date of birth and consent to the current legal versions.
    signup = {
        "email": email,
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "first_name": name.capitalize(),
        "last_name": "Smoke",
        "date_of_birth": "1990-06-15",
        "accept_terms": True,
        "terms_version": LEGAL_VERSION,
        "privacy_version": LEGAL_VERSION,
    }
    mismatched = {**signup, "password_confirm": "x" + PASSWORD}
    status, body = call("POST", "/auth/register/", body=mismatched)
    check(f"{name}: a mismatched confirmation is refused", status == 400, body)
    status, body = call("POST", "/auth/register/", body=signup)
    check(f"{name} registers", status == 201, body)

    def mailbox():
        return call("GET", f"{MAILPIT}/search?query=to:{email}")[1]

    found = eventually(mailbox, lambda m: isinstance(m, dict) and m.get("messages"))
    message = call("GET", f"{MAILPIT}/message/{found['messages'][0]['ID']}")[1]
    token = re.search(r"token=([\w\-.:%]+)", message["Text"]).group(1)

    status, body = call("POST", "/auth/login/", body={"email": email, "password": PASSWORD})
    check(f"{name} cannot log in before verifying", status == 403, body)
    status, body = call("POST", "/auth/verify-email/", body={"token": token})
    check(f"{name} verifies email", status == 200, body)
    status, body = call("POST", "/auth/login/", body={"email": email, "password": PASSWORD})
    check(f"{name} logs in", status == 200, body)
    access = data(body)["access_token"]
    return access, data(call("GET", "/me/", access)[1])["id"]


def social(alice, alice_id, bob, bob_id):
    profile = eventually(lambda: call("GET", "/profile/me/", alice), lambda r: r[0] == 200)
    check("profile created from account.registered", profile[0] == 200, profile)
    handle = data(profile[1])["handle"]
    status, public = call("GET", f"/users/{handle}/", bob)
    check("public profile returns account_id", data(public).get("account_id") == alice_id, public)
    status, by_id = call("GET", f"/users/id/{alice_id}/", bob)
    check("profile loads by account id", status == 200, by_id)
    status, cards = eventually(
        lambda: call("POST", "/users/lookup/", bob, {"ids": [alice_id, bob_id]}),
        lambda r: len(data(r[1])) == 2,
    )
    check("bulk profile lookup", status == 200 and len(data(cards)) == 2, cards)

    status, body = call("POST", f"/follows/{alice_id}/", bob)
    check("follow", status == 204, body)
    status, body = call("POST", "/friends/requests/", bob, {"to_user_id": alice_id})
    check("friend request", status == 201, body)
    status, body = call("POST", f"/friends/requests/{data(body)['id']}/accept/", alice)
    check("accept friend request", status == 200, body)


def posts(alice, alice_id, bob):
    text = "نص طويل " * 60
    status, body = call("POST", "/posts/", alice, {"body": text, "audience": "public"})
    check("create post", status == 201, body)
    post_id = data(body)["id"]

    feed = eventually(lambda: call("GET", "/feed/", bob)[1], lambda f: data(f))
    check("post reaches follower feed", any(i["post_id"] == post_id for i in data(feed)), feed)

    status, body = call("GET", f"/posts/?author_id={alice_id}", bob)
    check("profile timeline is paginated", status == 200 and "page" in body, body)
    check("timeline lists the post", any(p["id"] == post_id for p in data(body)), body)

    status, body = call("POST", f"/posts/{post_id}/reactions/", bob, {"type": "like"})
    check("react", status < 300, body)
    status, body = call("POST", f"/posts/{post_id}/comments/", bob, {"body": "تعليق"})
    check("comment", status == 201, body)

    status, body = call("GET", f"/posts/{post_id}/", bob)
    check("post shows the viewer's reaction", data(body).get("my_reaction") == "like", body)

    # follow + reaction + comment stay unread; the friend request was accepted, so
    # its notification is settled (resolution "accepted", read) by notifications v2.
    unread = eventually(
        lambda: call("GET", "/notifications/unread-count/", alice)[1],
        lambda r: data(r).get("unread", 0) >= 3,
    )
    check("notifications arrive", data(unread).get("unread", 0) >= 3, unread)
    status, items = call("GET", "/notifications/", alice)
    request = next((n for n in data(items) if n.get("kind") == "friend.request"), {})
    check(
        "accepted friend request is settled",
        request.get("resolution") == "accepted" and bool(request.get("read_at")),
        request,
    )


def media(alice):
    png = base64.b64decode(PNG_1X1)
    payload = {"kind": "image", "mime": "image/png", "size": len(png), "visibility": "public"}
    status, body = call("POST", "/media/uploads/sign/", alice, payload)
    check("sign upload through the gateway", status == 201, body)
    signed = data(body)
    upload_url = signed["upload_url"]
    headers = {"Content-Type": "image/png"}
    if "minio:9000" in upload_url:  # dev signs for the internal host
        upload_url = upload_url.replace("minio:9000", "127.0.0.1:9000")
        headers["Host"] = "minio:9000"
    status, body = call("PUT", upload_url, raw=png, headers=headers)
    check("upload to object storage", status == 200, body)
    media_id = signed["media_id"]
    status, body = call("POST", f"/media/uploads/{media_id}/complete/", alice, {})
    check("complete upload", status == 200, body)
    asset = eventually(
        lambda: call("GET", f"/media/{media_id}/", alice)[1],
        lambda a: data(a).get("status") == "ready",
    )
    check("media becomes ready", data(asset).get("status") == "ready", asset)


def chat(alice, bob, bob_id):
    status, body = call("POST", "/conversations/", alice, {"type": "dm", "other_id": bob_id})
    check("create DM", status == 201, body)
    conversation = data(body)["id"]
    for text in ("m0", "m1", "m2"):
        status, body = call(
            "POST", f"/conversations/{conversation}/messages/", alice, {"body": text}
        )
        check(f"send {text}", status == 201, body)
    status, body = call("GET", f"/conversations/{conversation}/messages/", bob)
    check("recipient reads messages", status == 200 and len(data(body)) == 3, body)


def marketplace(alice, bob):
    status, body = call("GET", "/marketplace/categories/", alice)
    check("categories seeded", status == 200 and data(body), body)
    listing = {
        "title": f"كرسي-{uuid.uuid4().hex[:6]}",
        "description": "كرسي خشب",
        "price": "100.00",
        "currency": "EGP",
        "category_id": data(body)[0]["id"],
    }
    status, body = call("POST", "/marketplace/listings/", alice, listing)
    check("create listing", status == 201, body)
    listing_id = data(body)["id"]
    status, body = call("POST", f"/marketplace/listings/{listing_id}/publish/", alice)
    check("publish listing", status == 200, body)


def authorization(bob):
    status, body = call("GET", "/moderation/cases/", bob)
    check("moderation is closed to normal users", status == 403, body)
    status, body = call("GET", "/admin/service-health/", bob)
    check("admin is closed to normal users", status == 403, body)
    status, body = call("GET", "/feed/")
    check("anonymous requests are rejected", status == 401, body)


def main() -> int:
    tag = uuid.uuid4().hex[:6]
    alice, alice_id = make_user("alice", tag)
    bob, bob_id = make_user("bob", tag)
    social(alice, alice_id, bob, bob_id)
    posts(alice, alice_id, bob)
    media(alice)
    chat(alice, bob, bob_id)
    marketplace(alice, bob)
    authorization(bob)
    print(f"\n{len(failures)} failed" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
