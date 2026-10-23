import email
import imaplib
import random
import re
import time

import requests

BASE = ""
USERNAME = ""
PASSWORD = ""

RUN_TIMES = 10
TEMP_USER_EVERY = 5  # every Nth cycle: throwaway user (register, rename, forbidden checks, self-delete)
ERROR_RATE = 0.3  # chance per cycle of each "bad request" action (400/401/403 paths)
DELAY = 0  # seconds to sleep between actions

# ---- password reset (end of every cycle) ----
# RESET_EMAIL: USERNAME's email on the site. The reset sets the password back to the same PASSWORD.
# Fill in IMAP_* so the script can read the reset link from that inbox (Gmail: imap.gmail.com + an app password).
# With IMAP_USER empty it only requests the reset and opens the confirm page with an invalid link.
RESET_EMAIL = "bot-reset@example.com"
IMAP_HOST = "imap.gmail.com"
IMAP_USER = ""
IMAP_PASSWORD = ""
RESET_MAIL_TIMEOUT = 120  # seconds to wait for the reset email

session = requests.Session()
messages_pool = ["hello", "testing 123", "hcl", "cwc", "log entry", "status ok"]


# ---------- helpers ----------

def get_csrf_token(url, sess=None):
    sess = sess or session
    r = sess.get(url)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not match:
        raise Exception(f"No CSRF token found on {url} (status={r.status_code}, landed on {r.url})")
    return match.group(1)


def post_form(url, data, sess=None):
    # GETs the page first (the *_ACCESSED log), then POSTs the form with its CSRF token
    sess = sess or session
    token = get_csrf_token(url, sess)
    return sess.post(url, data={"csrfmiddlewaretoken": token, **data}, headers={"Referer": url})


def show(label, r):
    print(f"  {label}: {r.status_code} -> {r.url}")
    return r


# ---------- auth ----------

def login(sess=None, username=USERNAME, password=PASSWORD):
    r = post_form(f"{BASE}/login/", {"username": username, "password": password}, sess)
    if "/login/" in r.url:
        raise Exception(f"Login failed for {username}")
    return show(f"login ({username})", r)


def login_bad():
    # LOGIN INVALID_REQUEST (401) — nonexistent user so the real account is never touched
    return show("login_bad", post_form(f"{BASE}/login/", {"username": "no_such_user_bot", "password": "wrong"}))


def login_page():
    return show("login_page", session.get(f"{BASE}/login/"))  # LOGIN_ACCESSED, or LOGIN_FINISHED if logged in


def logout():
    return show("logout", session.get(f"{BASE}/logout/"))  # LOGOUT_SUCCESS, or LOGOUT_FINISHED if logged out


def ensure_logged_in():
    r = session.get(f"{BASE}/create-room/")
    if "/login/" in r.url:
        login()


def register(sess, username, password):
    r = post_form(
        f"{BASE}/register/",
        {"username": username, "email": f"{username}@example.com", "password1": password, "password2": password},
        sess,
    )
    return show(f"register ({username})", r)


def register_bad(sess):
    # REGISTER INVALID_REQUEST (400) — mismatched passwords
    r = post_form(
        f"{BASE}/register/",
        {"username": "bad_reg_bot", "email": "bad_reg_bot@example.com", "password1": "TempPass123!", "password2": "Mismatch123!"},
        sess,
    )
    return show("register_bad", r)


# ---------- rooms ----------

def create_room(name, topic="", description=""):
    r = show("create_room", post_form(
        f"{BASE}/create-room/", {"name": name, "topic": topic, "description": description}
    ))
    match = re.search(r"/room/(\d+)/", r.url)
    return int(match.group(1)) if match else None


def create_room_bad():
    # CREATEROOM INVALID_REQUEST (400) — empty name
    return show("create_room_bad", post_form(f"{BASE}/create-room/", {"name": "", "topic": "Testing", "description": ""}))


def view_room(room_id, sess=None):
    return show("view_room", (sess or session).get(f"{BASE}/room/{room_id}/"))


def view_update_room_page(room_id):
    # UPDATEROOM_ACCESSED (200) — owner opens the edit-room form without submitting yet
    return show("view_update_room_page", session.get(f"{BASE}/update-room/{room_id}/"))


def update_room(room_id, name, topic, description):
    return show("update_room", post_form(
        f"{BASE}/update-room/{room_id}/",
        {"_method": "PUT", "name": name, "topic": topic, "description": description},
    ))


def update_room_bad(room_id):
    # UPDATEROOM INVALID_REQUEST (400) — empty name
    return show("update_room_bad", post_form(
        f"{BASE}/update-room/{room_id}/", {"_method": "PUT", "name": "", "topic": "Testing", "description": ""}
    ))


# ---------- messages ----------

def send_message(room_id, text):
    return show("send_message", post_form(f"{BASE}/room/{room_id}/", {"body": text}))


def send_empty_message(room_id):
    # ROOM INVALID_REQUEST (400)
    return show("send_empty_message", post_form(f"{BASE}/room/{room_id}/", {"body": ""}))


def get_latest_message_id(room_id):
    r = session.get(f"{BASE}/room/{room_id}/")
    ids = re.findall(r"/delete-message/(\d+)/", r.text)
    return int(ids[0]) if ids else None


def view_delete_message_page(message_id):
    # DELETEMESSAGE_ACCESSED (200) — owner opens the delete-message confirm page without confirming yet
    return show("view_delete_message_page", session.get(f"{BASE}/delete-message/{message_id}/"))


def delete_message(message_id):
    return show("delete_message", post_form(f"{BASE}/delete-message/{message_id}/", {"_method": "DELETE"}))


# ---------- profile ----------

def view_profile(username, sess=None):
    return show("view_profile", (sess or session).get(f"{BASE}/profile/{username}/"))


def update_username(sess, current_username, new_username):
    r = post_form(
        f"{BASE}/profile/{current_username}/update/",
        {"_method": "PUT", "username": new_username, "email": f"{current_username}@example.com"},
        sess,
    )
    return show(f"update_username ({current_username} -> {new_username})", r)


def update_username_bad(sess, current_username):
    # PROFILEUPDATE INVALID_REQUEST (400) — empty username fails form validation
    r = post_form(
        f"{BASE}/profile/{current_username}/update/",
        {"_method": "PUT", "username": "", "email": f"{current_username}@example.com"},
        sess,
    )
    return show(f"update_username_bad ({current_username})", r)


def profile_delete(sess, username):
    return show(f"profile_delete ({username})", post_form(
        f"{BASE}/profile/{username}/delete/", {"_method": "DELETE"}, sess
    ))


# ---------- read-only pages ----------

def visit_home(q=None):
    return show("home" + (f" ?q={q}" if q else ""), session.get(f"{BASE}/", params={"q": q} if q else None))


def visit_topics(q=None):
    return show("topics" + (f" ?q={q}" if q else ""), session.get(f"{BASE}/topics/", params={"q": q} if q else None))


def visit_activities():
    return show("activities", session.get(f"{BASE}/activities/"))


def hit_health_endpoints():
    for path in ["health/", "start/", "ready/", "live/"]:
        show(path, session.get(f"{BASE}/{path}"))


def password_reset(email_addr=RESET_EMAIL, sess=None):
    # PASSWORDRESET_ACCESSED -> redirects to /password_reset_done/
    return show("password_reset", post_form(f"{BASE}/password_reset/", {"email": email_addr}, sess or requests.Session()))


def password_reset_confirm_bad():
    # confirm page with a bogus uid/token — Django renders the "invalid link" page
    return show("password_reset_confirm_bad", requests.get(f"{BASE}/password_reset_confirm/MQ/invalid-token/"))


RESET_LINK_RE = re.compile(r"/password_reset_confirm/([A-Za-z0-9_\-]+)/([A-Za-z0-9\-]+)/")


def inbox_reset_links():
    # every reset link in the latest matching emails, newest first
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(IMAP_USER, IMAP_PASSWORD)
        imap.select("INBOX")
        _, data = imap.search(None, '(BODY "password_reset_confirm")')
        links = []
        for num in reversed(data[0].split()[-10:]):
            _, msg_data = imap.fetch(num, "(RFC822)")
            for part in email.message_from_bytes(msg_data[0][1]).walk():
                if part.get_content_maintype() == "text":
                    body = (part.get_payload(decode=True) or b"").decode(errors="ignore")
                    links += [m.group(0) for m in RESET_LINK_RE.finditer(body)]
        return links
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def wait_for_new_reset_link(old_links):
    deadline = time.time() + RESET_MAIL_TIMEOUT
    while time.time() < deadline:
        for link in inbox_reset_links():
            if link not in old_links:
                return link
        time.sleep(5)
    raise Exception(f"No reset email arrived within {RESET_MAIL_TIMEOUT}s")


def full_password_reset():
    temp = requests.Session()
    if not IMAP_USER:
        password_reset(RESET_EMAIL, temp)
        password_reset_confirm_bad()
        print("  (IMAP not configured — password not changed)")
        return

    # remember links already in the inbox so an old email is never reused
    old_links = set(inbox_reset_links())
    password_reset(RESET_EMAIL, temp)
    link = wait_for_new_reset_link(old_links)

    # GET the emailed link -> Django redirects to .../set-password/ with the token kept in the session
    r = show("password_reset_confirm", temp.get(f"{BASE}{link}"))
    if "set-password" not in r.url:
        raise Exception(f"Reset link rejected: {r.url}")

    # PASSWORDRESETCONFIRM INVALID_REQUEST (400) — mismatched new password on an otherwise-valid link.
    # The token stays valid until the password is actually changed, so the real submission below still works.
    show("password_reset_set_bad (mismatched)", post_form(r.url, {"new_password1": "Mismatch1!", "new_password2": "Mismatch2!"}, temp))
    r = post_form(r.url, {"new_password1": PASSWORD, "new_password2": PASSWORD}, temp)
    show("password_reset_set (same password)", r)
    if "/password_reset_complete/" not in r.url:
        raise Exception("Setting the password failed")

    # password hash changed, so the main session is logged out — log back in to prove the password still works
    login()


def password_reset_bad():
    # PASSWORDRESET INVALID_REQUEST (400) — malformed email
    return show("password_reset_bad", post_form(f"{BASE}/password_reset/", {"email": "not-an-email"}, requests.Session()))


def register_page():
    return show("register_page", session.get(f"{BASE}/register/"))  # REGISTER_ACCESSED


def own_profile_pages():
    # PROFILEUPDATE_ACCESSED / PROFILEDELETE_ACCESSED — GET only, nothing is submitted for the real account
    show("profile_update_page", session.get(f"{BASE}/profile/{USERNAME}/update/"))
    show("profile_delete_page", session.get(f"{BASE}/profile/{USERNAME}/delete/"))


def password_reset_pages():
    show("password_reset_done_page", session.get(f"{BASE}/password_reset_done/"))
    show("password_reset_complete_page", session.get(f"{BASE}/password_reset_complete/"))


# ---------- composite actions ----------

def auth_cycle(room_id):
    logout()
    logout()  # LOGOUT_FINISHED
    view_room(room_id)  # login_required -> redirect to /login/
    login_page()  # LOGIN_ACCESSED
    if random.random() < ERROR_RATE:
        login_bad()
    login()
    login_page()  # LOGIN_FINISHED


def temp_user_cycle(n, room_id):
    # separate session — never touches the real login
    temp = requests.Session()
    username = f"tempuser_{n}_{random.randint(1000, 9999)}"
    password = "TempPass123!"

    if random.random() < ERROR_RATE:
        register_bad(temp)
    register(temp, username, password)
    view_profile(username, temp)

    # FORBIDDEN_ACCESS checks against duvindu's own content — all GETs, the view returns 403 before changing anything
    msg_id = get_latest_message_id(room_id)
    show("forbidden update_room", temp.get(f"{BASE}/update-room/{room_id}/"))
    show("forbidden delete_room", temp.get(f"{BASE}/delete-room/{room_id}/"))
    if msg_id:
        show("forbidden delete_message", temp.get(f"{BASE}/delete-message/{msg_id}/"))
    show("forbidden profile_update", temp.get(f"{BASE}/profile/{USERNAME}/update/"))
    show("forbidden profile_delete", temp.get(f"{BASE}/profile/{USERNAME}/delete/"))

    if random.random() < ERROR_RATE:
        update_username_bad(temp, username)

    new_username = f"{username}_r"
    r = update_username(temp, username, new_username)
    if f"/profile/{new_username}/" in r.url:
        username = new_username
    profile_delete(temp, username)


def step(name, fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        print(f"  !! {name} failed: {e}")
    finally:
        if DELAY:
            time.sleep(DELAY)


def run_cycle(n, created_rooms):
    ensure_logged_in()

    if random.random() < ERROR_RATE:
        step("create_room_bad", create_room_bad)
    room_id = step("create_room", create_room, f"Bot Room {n}", "Testing", "Made by script")
    if room_id is None:
        print("  Skipping this cycle — no room id.")
        return
    created_rooms.add(room_id)

    # always send one message so delete_message / its confirm page has something to work with
    step("send_message", send_message, room_id, random.choice(messages_pool))

    tasks = {
        "view_room": lambda: view_room(room_id),
        "view_update_room_page": lambda: view_update_room_page(room_id),
        "send_message": lambda: send_message(room_id, random.choice(messages_pool)),
        "update_room": lambda: update_room(room_id, f"Bot Room {n} (edited)", "Updated topic", "Edited by script"),
        "view_delete_message_page": lambda: (
            view_delete_message_page(msg_id) if (msg_id := get_latest_message_id(room_id)) else print("  No message to view.")
        ),
        "delete_message": lambda: (
            delete_message(msg_id) if (msg_id := get_latest_message_id(room_id)) else print("  No message to delete.")
        ),
        "home": visit_home,
        "home_search": lambda: visit_home("Bot"),
        "topics": visit_topics,
        "topics_search": lambda: visit_topics("Test"),
        "activities": visit_activities,
        "profile": lambda: view_profile(USERNAME),
        "health": hit_health_endpoints,
        "auth": lambda: auth_cycle(room_id),
        "register_page": register_page,
        "own_profile_pages": own_profile_pages,
        "password_reset_pages": password_reset_pages,
    }
    if random.random() < ERROR_RATE:
        tasks["update_room_bad"] = lambda: update_room_bad(room_id)
    if random.random() < ERROR_RATE:
        tasks["password_reset_bad"] = password_reset_bad
    if random.random() < ERROR_RATE:
        tasks["send_empty_message"] = lambda: send_empty_message(room_id)

    order = list(tasks)
    random.shuffle(order)
    for name in order:
        step(name, tasks[name])

    if n % TEMP_USER_EVERY == 0:
        step("temp_user_cycle", temp_user_cycle, n, room_id)

    # rooms are kept — only open the delete confirm page (DELETEROOM_ACCESSED); -rooms_bot.py does the deleting
    ensure_logged_in()
    step("delete_room_page", lambda: show("delete_room_page", session.get(f"{BASE}/delete-room/{room_id}/")))

    # last: reset the password to the same one it already is
    step("full_password_reset", full_password_reset)


if __name__ == "__main__":
    login()

    created_rooms = set()
    for i in range(RUN_TIMES):
        print(f"\n--- Cycle {i + 1}/{RUN_TIMES} ---")
        try:
            run_cycle(i + 1, created_rooms)
        except Exception as e:
            print(f"  !! cycle {i + 1} failed: {e}")

    print(f"\nAll cycles complete. Created {len(created_rooms)} room(s):", sorted(created_rooms))
