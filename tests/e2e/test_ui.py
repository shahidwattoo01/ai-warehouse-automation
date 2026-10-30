"""End-to-end tests of the operator UI in a real (headless) browser.

    python tasks.py backend & python tasks.py frontend     # start the app first
    python -m pytest tests/e2e -q

They open the running app like an operator would, logged in as the development users of
`python scripts/create_dev_users.py` (passwords in the git-ignored dev_users.local.json). When the
app is not running or those users do not exist (for example in CI, which tests the parts
separately), they are skipped. URLs: E2E_UI_URL (default http://localhost:3000) and E2E_API_URL
(default http://localhost:8000). The simulation's running / paused state is restored afterwards.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from functools import cache
from pathlib import Path

import pytest

UI = os.environ.get("E2E_UI_URL", "http://localhost:3000")
API = os.environ.get("E2E_API_URL", "http://localhost:8000")
DEV_USERS = Path(__file__).resolve().parents[2] / "dev_users.local.json"


def _call(
    url: str, method: str = "GET", body: dict | None = None, token: str | None = None
) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as res:  # noqa: S310 (local test URLs)
        return json.loads(res.read())


def password(username: str) -> str:
    return json.loads(DEV_USERS.read_text(encoding="utf-8"))[username]["password"]


@cache
def token(username: str = "dev-admin") -> str:
    return _call(
        f"{API}/api/v1/auth/login", "POST", {"username": username, "password": password(username)}
    )["access_token"]


def get(url: str) -> dict:
    """GET an API URL as the development admin."""
    return _call(url, token=token())


def app_running() -> bool:
    try:
        _call(f"{API}/health")
        urllib.request.urlopen(UI, timeout=30)  # noqa: S310
        return DEV_USERS.exists()
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not app_running(), reason="the app or the development users are missing (see module docstring)"
)
sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def login(page, username: str) -> None:
    page.goto(f"{UI}/login", wait_until="domcontentloaded")
    sign_in = page.get_by_role("button", name="Sign in")
    for _ in range(60):  # typing before React has hydrated the form is lost: type until it sticks
        page.get_by_label("Username").fill(username)
        page.get_by_label("Password").fill(password(username))
        if sign_in.is_enabled():
            break
        page.wait_for_timeout(500)
    sign_in.click()
    page.wait_for_url(lambda url: "/login" not in url)


@pytest.fixture
def page(browser):
    """A fresh, logged-in (admin) tab per test, so one page's load (e.g. the 3D dashboard) cannot
    slow the next."""
    context = browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.set_default_timeout(120_000)  # the 3D scene renders in software (no GPU)
    login(page, "dev-admin")
    yield page
    context.close()


@pytest.fixture
def restore_running():
    before = get(f"{API}/api/v1/simulation/state")["running"]
    yield
    action = "start" if before else "pause"
    _call(f"{API}/api/v1/simulation/{action}", "POST", token=token())


def button_reads(page, label: str) -> None:
    """Wait until the header's Start/Pause button shows `label`."""
    page.wait_for_function(
        "label => [...document.querySelectorAll('header button')]"
        ".some(b => b.innerText.trim() === label)",
        arg=label,
    )


def tick(page) -> int:
    return int(re.search(r"tick (\d+)", page.inner_text("body")).group(1))


def test_dashboard_loads_with_navigation(page):
    page.goto(f"{UI}/dashboard", wait_until="domcontentloaded")
    page.locator('nav a[href="/dashboard"]').wait_for()  # the session is restored first
    for path in (
        "/dashboard",
        "/simulation",
        "/fleet",
        "/orders",
        "/vision",
        "/analytics",
        "/copilot",
    ):
        assert page.locator(f'nav a[href="{path}"]').count() == 1  # labels hide on narrow screens
    page.wait_for_function("document.body.innerText.includes('tick')")


def test_start_and_pause_toggle_like_a_real_button(page, restore_running):
    # The header (Start/Pause button, live clock) is the same on every page; the Analytics page
    # has no 3D scene, which a headless browser without a GPU renders far too slowly.
    page.goto(f"{UI}/analytics", wait_until="domcontentloaded")
    button = page.locator("header button", has_text=re.compile(r"^\s*(Start|Pause)\s*$"))
    # Clicks are sent as events (no mouse geometry is tested here).
    if button.inner_text().strip() == "Pause":  # bring it to a known state
        button.dispatch_event("click")
        button_reads(page, "Start")

    button.dispatch_event("click")  # Start
    button_reads(page, "Pause")
    first = tick(page)
    page.wait_for_timeout(2500)
    assert tick(page) > first, "the clock should run after Start"

    button.dispatch_event("click")  # Pause
    button_reads(page, "Start")
    stopped = tick(page)
    page.wait_for_timeout(2000)
    assert tick(page) == stopped, "the clock should stop after Pause"


def test_vision_page_lists_every_camera_on_the_wall(page):
    robots = len(get(f"{API}/api/v1/simulation/state")["robots"])
    page.goto(f"{UI}/vision", wait_until="domcontentloaded")
    wall = page.get_by_role("tab", name=re.compile("Camera wall"))
    wall.wait_for()
    page.wait_for_function("!document.body.innerText.includes('Camera wall (0)')")
    cameras = int(re.search(r"Camera wall \((\d+)\)", wall.inner_text()).group(1))
    # overviews + fixed CCTV + one per robot (+ hazard and closed-aisle cameras)
    assert cameras >= 2 + 16 + robots

    wall.dispatch_event("click")
    page.get_by_role("button", name=re.compile(r"^Detect all \d+ cameras$")).wait_for()
    tiles = page.locator("main button", has_text=re.compile("^Open$"))
    assert tiles.count() == cameras


def ask(page, text: str) -> None:
    page.get_by_label("Command").fill(text)
    page.get_by_label("Command").press("Enter")


def test_copilot_answers_questions_and_waits_for_approval(page):
    """Read-only questions are answered at once; an action waits for Approve / Cancel, and
    cancelling changes nothing. Nothing is approved here, so the warehouse stays as it was."""
    before = {r["robot_id"]: r["status"] for r in get(f"{API}/api/v1/simulation/state")["robots"]}
    page.goto(f"{UI}/copilot", wait_until="domcontentloaded")
    page.wait_for_function("/Model: (?!connecting)/.test(document.body.innerText)")

    ask(page, "where is robot 7?")
    page.get_by_text(re.compile(r"^R7 is ")).wait_for()
    assert page.get_by_text("robot_status", exact=True).count() == 1  # what the model understood

    ask(page, "pause robot 3")
    card = page.get_by_text(re.compile(r"(Approval needed|Not sure, check first):"))
    card.wait_for()
    page.get_by_role("button", name="Cancel").click()
    page.get_by_text("Cancelled, nothing was changed.").wait_for()
    assert card.count() == 0

    history = get(f"{API}/api/v1/copilot/history")
    assert history[0]["text"] == "pause robot 3" and history[0]["outcome"] == "rejected"
    after = get(f"{API}/api/v1/simulation/state")["robots"]
    assert next(r for r in after if r["robot_id"] == "R3")["status"] == before["R3"]


def test_knowledge_answers_with_sources_or_says_not_covered(page):
    page.goto(f"{UI}/knowledge", wait_until="domcontentloaded")
    page.wait_for_function("/(memory|pgvector) search/.test(document.body.innerText)")
    question = page.get_by_label("Question")

    question.fill("What do we do when a robot overheats?")
    question.press("Enter")
    page.get_by_text("Sources", exact=True).wait_for()
    page.get_by_role("button", name="SOP-04").first.click()  # the citation opens the section
    page.get_by_text("Overheating robot").first.wait_for()

    question.fill("What is the Wi-Fi password for the robot network?")
    question.press("Enter")
    page.get_by_text("Closest passages", exact=True).wait_for()
    assert page.get_by_text("Not covered.").count() == 1


def test_inventory_scan_opens_the_item(page):
    """Scanning an item barcode anywhere opens it in the Items tab, with its own barcode."""
    try:
        first = get(f"{API}/api/v1/wms/items?limit=1")["items"][0]
    except OSError:
        pytest.skip("the backend runs the simple inventory model")
    page.goto(f"{UI}/inventory", wait_until="domcontentloaded")
    page.get_by_text("Inventory record accuracy").wait_for()
    box = page.get_by_label("Barcode").first
    box.fill(first["gtin"])
    box.press("Enter")
    page.get_by_text(f"GTIN {first['gtin']}", exact=True).wait_for()
    assert page.locator(f'img[alt="ean13 {first["gtin"]}"]').count() == 1


def test_anonymous_visitors_are_sent_to_the_login(browser):
    page = browser.new_page()
    page.goto(f"{UI}/inventory", wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"/login\?next=%2Finventory"))
    page.close()


def test_each_role_sees_its_own_start_page_and_menu(browser):
    for username, home, hidden in (
        ("dev-viewer", "/analytics", "/copilot"),
        ("dev-clerk", "/inventory", "/admin/users"),
        ("dev-operator", "/dashboard", "/admin/users"),
    ):
        context = browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        page.set_default_timeout(120_000)
        login(page, username)
        page.wait_for_url(re.compile(home))
        page.locator(f'nav a[href="{home}"]').wait_for()
        assert page.locator(f'nav a[href="{hidden}"]').count() == 0, username
        context.close()


def test_a_viewer_cannot_open_the_copilot(browser):
    context = browser.new_context()
    page = context.new_page()
    login(page, "dev-viewer")
    page.goto(f"{UI}/copilot", wait_until="domcontentloaded")
    page.get_by_text("Not available for your role").wait_for()
    context.close()
