import re

import requests

BASE = "https://logger.duvindu.org"
USERNAME = "duvindu"
PASSWORD = "#Gedara@123"

DRY_RUN = False  # set True to only list the rooms that would be deleted

session = requests.Session()


def get_csrf_token(url):
    r = session.get(url)
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not match:
        raise Exception(f"No CSRF token found on {url} (status={r.status_code}, landed on {r.url})")
    return match.group(1)


def login():
    url = f"{BASE}/login/"
    token = get_csrf_token(url)
    r = session.post(
        url,
        data={"csrfmiddlewaretoken": token, "username": USERNAME, "password": PASSWORD},
        headers={"Referer": url},
    )
    if "/login/" in r.url:
        raise Exception("Login failed — check username/password.")
    print("Logged in as", USERNAME)


def get_my_room_ids(username):
    # profile view renders user.room_set.all() as <div class="roomListRoom"> cards;
    # the activity feed on the same page links to other rooms, so match on card author
    r = session.get(f"{BASE}/profile/{username}/")
    ids = set()
    for card in r.text.split('<div class="roomListRoom">')[1:]:
        author = re.search(r'href="/profile/([^/"]+)/"', card)
        room = re.search(r'href="/room/(\d+)/"', card)
        if author and room and author.group(1) == username:
            ids.add(int(room.group(1)))
    return sorted(ids)


def delete_room(room_id):
    url = f"{BASE}/delete-room/{room_id}/"
    token = get_csrf_token(url)
    r = session.post(
        url,
        data={"csrfmiddlewaretoken": token, "_method": "DELETE"},
        headers={"Referer": url},
    )
    print(f"delete_room ({room_id}): {r.status_code} -> {r.url}")
    # deleteRoom redirects to home on success, returns 403 if not the host
    return r.status_code == 200 and r.url.rstrip("/") == BASE


def delete_all_my_rooms(username):
    room_ids = get_my_room_ids(username)
    print(f"Found {len(room_ids)} room(s) hosted by {username}:", room_ids)
    if DRY_RUN:
        print("DRY_RUN is on — nothing deleted.")
        return []

    deleted, failed = [], []
    for rid in room_ids:
        try:
            (deleted if delete_room(rid) else failed).append(rid)
        except Exception as e:
            print(f"delete_room({rid}) error:", e)
            failed.append(rid)
    print(f"\nDeleted {len(deleted)} room(s):", deleted)
    if failed:
        print(f"Failed {len(failed)} room(s):", failed)
    return deleted


if __name__ == "__main__":
    login()
    delete_all_my_rooms(USERNAME)
