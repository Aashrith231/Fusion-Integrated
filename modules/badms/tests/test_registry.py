"""The module registry: navigation, permissions and grants stay consistent.

The permission manifest and the nav/route check read this module's registry;
these tests keep its internal structure honest (Step 2.1, registry.py).
"""

from modules.badms import registry

NAV_KEYS = {"code", "label", "icon", "to", "required_permission"}
ROLE_GRANTS = {"student", "faculty", "staff", "hod", "sysadmin",
               "it_security", "super_admin"}


def test_module_identity():
    assert registry.MODULE["code"] == "badms"
    assert registry.MODULE["base_path"] == "/badms"


def test_every_nav_item_is_well_formed():
    assert len(registry.NAV_ITEMS) == 13
    for item in registry.NAV_ITEMS:
        assert set(item) >= NAV_KEYS, item
        base = registry.MODULE["base_path"]
        assert item["to"].startswith(base + "/")
        assert item["code"].startswith("badms.")
        assert item["code"] == "badms." + \
            item["to"].rsplit("/", 1)[-1].replace("-", "_")
        names = {code for code, _l in registry.PERMISSIONS}
        assert item["required_permission"] in names


def test_every_permission_appears_in_some_grant():
    granted = set()
    for perms in registry.ROLE_GRANTS.values():
        granted |= set(perms)
    named = {code for code, _label in registry.PERMISSIONS}
    assert named - granted == set(), (
        "a permission nobody holds can never be exercised")
    # SYSTEM_PERMISSIONS are the module's own scheduled-work grants; none of
    # them may reach a person through a designation.
    assert not (granted & set(registry.SYSTEM_PERMISSIONS))


def test_the_super_admin_holds_everything_the_sysadmin_does():
    assert set(registry.ROLE_GRANTS["sysadmin"]) <= \
        set(registry.ROLE_GRANTS["super_admin"])


def test_the_plain_user_never_holds_an_administrative_permission():
    for role in ("student", "faculty", "staff"):
        held = set(registry.ROLE_GRANTS[role])
        assert not (held & set(registry.SYSTEM_PERMISSIONS)), (role, held)


def test_system_permissions_never_reach_a_hod():
    held = set(registry.ROLE_GRANTS["hod"])
    assert not (held & set(registry.SYSTEM_PERMISSIONS))
