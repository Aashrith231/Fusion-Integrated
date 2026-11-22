"""The client guards each office page with its nav item's own permission.

routes.tsx and registry.py name the same permission twice; a typo would lock
an operator out of their own page, or let the wrong role in, with every test
still green. Nine BADMS pages are office pages; the four a plain user may use
(backups, archival, restoration, storage) are deliberately not guarded.
"""
import re
from pathlib import Path

from modules.badms.registry import MODULE, NAV_ITEMS, PERMISSIONS

ROUTES = (Path(__file__).resolve().parents[3]
          / "client" / "src" / "modules" / "badms" / "routes.tsx")
OFFICE_PAGES = {
    "schedules", "archival-review", "classification", "encryption",
    "special-archival", "storage-approvals", "audit", "security", "reports",
}
OPEN_PAGES = {"backups", "archival", "restoration", "storage"}

GUARD_PATTERN = r'\{\s*path:\s*"([^"]+)",\s*element:\s*office\(\s*"([^"]+)"'
BARE_PATTERN = r'\{\s*path:\s*"([^"]+)",\s*element:\s*<(\w+) />'


def guarded_routes(text: str | None = None) -> dict[str, str]:
    return dict(re.findall(GUARD_PATTERN, text if text is not None
                           else ROUTES.read_text()))


def bare_routes(text: str | None = None) -> set[str]:
    return {m.group(1) for m in
            re.finditer(BARE_PATTERN,
                        text if text is not None else ROUTES.read_text())}


def nav_permission(path: str) -> str | None:
    base = MODULE.get("base_path", "/badms").rstrip("/")
    for item in NAV_ITEMS:
        if item.get("to") == f"{base}/{path}":
            return item.get("required_permission")
    return None


def test_every_office_page_is_guarded():
    assert set(guarded_routes()) >= OFFICE_PAGES


def test_the_plain_users_pages_are_not_guarded():
    assert bare_routes() >= OPEN_PAGES, bare_routes()


def test_each_guard_is_its_nav_items_own_permission():
    declared = {code for code, _ in PERMISSIONS}
    for path, permission in guarded_routes().items():
        assert permission in declared, f"{path}: {permission} is not declared"
        assert permission == nav_permission(path), (
            f"{path}: guard and nav item disagree")


def test_removing_a_guard_fails_this_suite():
    # The negative twin: strip one office() wrapper and the first assertion
    # no longer holds — the suite really is watching the guards.
    modified = re.sub(
        r'element:\s*office\("badms\.audit\.view",\s*<AuditPage />',
        "element: <AuditPage />",
        ROUTES.read_text())
    assert "audit" in bare_routes(modified)
    assert "audit" not in guarded_routes(modified)
