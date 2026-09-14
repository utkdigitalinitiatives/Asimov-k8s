#!/usr/bin/env python3
"""Make Solr's Drupal logins match Git and Key Vault.

Why this exists: the Solr Operator writes security.json to ZooKeeper once, when
the cluster is first created, and never again. This cluster already has one, so
new users can only be added through Solr's Security API. This script is that
API call, written so it can run on a schedule and change nothing when nothing
differs.

Input: one directory per Drupal login under USERS_DIR, projected from a Secret
that External Secrets builds from Key Vault. Each holds three files:
`username`, `collection`, `password`.

For each login it makes sure that:
  1. the user exists and its password works (set-user only if it does not),
  2. the user has exactly one role, named after the user,
  3. a permission with the user's name lets that role (and admin) use every path
     on that one collection, and sits above every non-Drupal permission.

Order matters in (3). Solr uses the FIRST permission that matches a request,
whatever roles it lists. The operator's own `k8s-ping` (collection "*") and
`read` rules would match Drupal's requests first and deny them.

It never deletes a user or permission it did not write, and never touches
`admin`, `solr` or `k8s-oper`. Standard library only.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SOLR_URL = os.environ.get("SOLR_URL", "http://localhost:8983/solr").rstrip("/")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD_FILE = os.environ.get("ADMIN_PASSWORD_FILE", "/var/run/solr-admin/password")
USERS_DIR = os.environ.get("USERS_DIR", "/var/run/drupal-users")
# Solr applies security changes asynchronously; wait before reading them back.
SETTLE_SECONDS = float(os.environ.get("SETTLE_SECONDS", "3"))

PREFIX = "drupal-"
COLLECTION_RE = re.compile(r"^[A-Za-z0-9_-]+$")
USERNAME_RE = re.compile(r"^drupal-[a-z0-9-]+$")


def log(msg):
    print(msg, flush=True)


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def request(path, user, password, body=None):
    """Return (status, parsed JSON or None). Never raises on HTTP errors."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(SOLR_URL + path, data=data)
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


class Admin:
    def __init__(self, password):
        self.password = password

    def get(self, path):
        status, doc = request(path, ADMIN_USER, self.password)
        if status != 200 or doc is None:
            raise RuntimeError(f"GET {path} as {ADMIN_USER} returned HTTP {status}")
        return doc

    def post(self, path, body):
        status, doc = request(path, ADMIN_USER, self.password, body)
        if status != 200 or (doc or {}).get("errorMessages"):
            raise RuntimeError(f"POST {path} {list(body)} returned HTTP {status}: {doc}")
        time.sleep(SETTLE_SECONDS)

    def authorization(self):
        return self.get("/admin/authorization")["authorization"]

    def users(self):
        return set(self.get("/admin/authentication")["authentication"].get("credentials", {}))


def as_list(value):
    if value is None:
        return []
    return sorted(value) if isinstance(value, list) else [value]


def load_login(name):
    d = os.path.join(USERS_DIR, name)
    try:
        login = {k: read_file(os.path.join(d, k)) for k in ("username", "collection", "password")}
    except OSError as e:
        raise ValueError(f"incomplete login ({e})") from e
    if not USERNAME_RE.match(login["username"]):
        raise ValueError(f"username must match {USERNAME_RE.pattern}")
    if not COLLECTION_RE.match(login["collection"]):
        raise ValueError(f"collection must match {COLLECTION_RE.pattern}")
    if not login["password"]:
        raise ValueError("empty password")
    return login


def login_names():
    if not os.path.isdir(USERS_DIR):
        return []
    # Projected volumes also contain ..data and timestamped dirs; skip dot names.
    return sorted(n for n in os.listdir(USERS_DIR) if not n.startswith("."))


def ensure_password(admin, login):
    user, password = login["username"], login["password"]
    if user in admin.users():
        # /admin/info/system is open to anyone (operator rule k8s-probe-0), so a
        # valid login gets 200 and only a wrong password gets 401.
        status, _ = request("/admin/info/system", user, password)
        if status != 401:
            return False
    admin.post("/admin/authentication", {"set-user": {user: password}})
    return True


def ensure_role(admin, login):
    user = login["username"]
    if as_list(admin.authorization().get("user-role", {}).get(user)) == [user]:
        return False
    admin.post("/admin/authorization", {"set-user-role": {user: [user]}})
    return True


def permissions(admin):
    """(index, permission) pairs. Index is the 1-based position Solr's API uses.

    Solr only adds an "index" field after the first API edit; a security.json
    written by the operator has none, so count positions instead.
    """
    return list(enumerate(admin.authorization().get("permissions", []), start=1))


def ensure_permission(admin, login):
    user = login["username"]
    # "/*" is the form Solr 9 matches against every handler; a bare "*" matches
    # nothing, and leaving path out is rejected as "not a custom permission".
    want = {"name": user, "collection": login["collection"], "path": "/*", "role": [user, "admin"]}

    perms = permissions(admin)
    foreign = [i for i, p in perms if not str(p.get("name", "")).startswith(PREFIX)]
    first_foreign = min(foreign) if foreign else float("inf")
    mine = [(i, p) for i, p in perms if p.get("name") == user]

    if len(mine) == 1:
        i, p = mine[0]
        same = (
            p.get("collection") == want["collection"]
            and p.get("path") == want["path"]
            and as_list(p.get("role")) == sorted(want["role"])
            and "method" not in p
            and "params" not in p
        )
        if same and i < first_foreign:
            return False

    # Wrong, misplaced or duplicated: remove every copy (highest index first, so
    # the remaining indexes stay valid), then insert one at the top.
    for i, _ in sorted(mine, key=lambda pair: pair[0], reverse=True):
        admin.post("/admin/authorization", {"delete-permission": i})

    body = dict(want)
    if permissions(admin):
        body["before"] = 1
    admin.post("/admin/authorization", {"set-permission": body})
    return True


def main():
    admin = Admin(read_file(ADMIN_PASSWORD_FILE))
    names = login_names()
    if not names:
        log(f"No Drupal logins mounted under {USERS_DIR}; nothing to do.")
        return 0

    failed = 0
    for name in names:
        user = name
        try:
            login = load_login(name)
            user = login["username"]
            changes = [
                label
                for label, step in (
                    ("password", ensure_password),
                    ("role", ensure_role),
                    ("permission", ensure_permission),
                )
                if step(admin, login)
            ]
            log(f"{user} -> {login['collection']}: " + (f"updated {', '.join(changes)}" if changes else "no change"))
        except Exception as e:  # keep going so one bad login does not block the rest
            failed += 1
            log(f"{user}: FAILED: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
