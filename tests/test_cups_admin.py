"""CUPS-Admin-Gruppe aus cups-files.conf und der Hinweistext dazu.

Alles gemockt: Datei im Temp-Ordner, grp.getgrnam ersetzt.

Ausführen: python3 -m unittest discover -s tests -v
"""
import gettext
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from print_ease import cups_admin  # noqa: E402


def groups_exist(*names):
    """Ersatz für grp.getgrnam: nur die genannten Gruppen gibt es."""
    def getgrnam(name):
        if name in names:
            return mock.Mock(gr_name=name)
        raise KeyError(name)
    return mock.patch.object(cups_admin.grp, "getgrnam", side_effect=getgrnam)


class AdminGroup(unittest.TestCase):
    """Außerhalb des Flatpaks (/.flatpak-info gibt es nicht)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.conf = Path(tmp.name) / "cups-files.conf"
        patcher = mock.patch.object(cups_admin, "FLATPAK_INFO", Path(tmp.name) / "keine-flatpak-info")
        patcher.start()
        self.addCleanup(patcher.stop)

    def group(self, conf_text, *existing):
        if conf_text is not None:
            self.conf.write_text(conf_text, encoding="utf-8")
        with groups_exist(*existing):
            return cups_admin.cups_admin_group(self.conf)

    def test_debian_ubuntu(self):
        self.assertEqual(self.group("SystemGroup lpadmin\n", "lpadmin", "lp"), "lpadmin")

    def test_arch_fedora_default_skips_root(self):
        self.assertEqual(self.group("SystemGroup sys root wheel\n", "root", "sys", "wheel"), "sys")

    def test_root_only_is_never_suggested(self):
        self.assertEqual(self.group("SystemGroup root\n", "root", "wheel"), "wheel")

    def test_first_existing_group_wins(self):
        self.assertEqual(self.group("SystemGroup admin sys wheel\n", "wheel", "sys"), "sys")

    def test_several_lines_commas_quotes_case_and_comments(self):
        text = (
            "# SystemGroup lp\n"
            "  systemgroup root   # Kommentar\n"
            "SystemGroup 'print admins',\"lpadmin\"\n"
        )
        self.assertEqual(cups_admin._system_groups(text), ["root", "print admins", "lpadmin"])
        self.assertEqual(self.group(text, "root", "lpadmin"), "lpadmin")

    def test_other_directives_are_ignored(self):
        text = "SystemGroupAuthKey system.print.admin\nUser lp\nGroup lp\n"
        self.assertEqual(cups_admin._system_groups(text), [])
        self.assertEqual(self.group(text, "lp", "wheel"), "wheel")

    def test_no_systemgroup_line_falls_back(self):
        self.assertEqual(self.group("LogLevel warn\n", "lpadmin", "wheel"), "lpadmin")

    def test_listed_groups_missing_falls_back(self):
        self.assertEqual(self.group("SystemGroup sys wheel\n", "lpadmin"), "lpadmin")
        self.assertEqual(self.group("SystemGroup lpadmin\n"), "wheel")

    def test_unreadable_file(self):
        self.conf.write_text("SystemGroup sys\n", encoding="utf-8")
        with mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")):
            with groups_exist("sys", "lpadmin", "wheel"):
                self.assertEqual(cups_admin.cups_admin_group(self.conf), "lpadmin")
            with groups_exist("sys", "wheel"):
                self.assertEqual(cups_admin.cups_admin_group(self.conf), "wheel")

    def test_missing_file(self):
        self.assertEqual(self.group(None, "lpadmin"), "lpadmin")
        self.assertEqual(self.group(None), "wheel")

    def test_lp_is_never_the_answer_without_systemgroup(self):
        self.assertNotEqual(self.group(None, "lp"), "lp")


OS_RELEASE = {
    "ubuntu": 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n',
    "mint": 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n',
    "debian": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n',
    "pop": "ID=pop\nID_LIKE='ubuntu debian'\n",
    "fedora": 'NAME="Fedora Linux"\nID=fedora\nVERSION_ID=43\n',
    "arch": 'NAME="Arch Linux"\nID=arch\n',
    "cachyos": 'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n',
    "opensuse": 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n',
    "kein-debian-als-teilwort": "ID=debianish\nID_LIKE=notdebian\n",
}


class FlatpakHostOsRelease(unittest.TestCase):
    """In der Sandbox: cups-files.conf fehlt, Gruppen des Hosts sind unbekannt."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        info = self.tmp / ".flatpak-info"
        info.write_text("[Application]\nname=at.printease.PrintEase\n")
        self.os_release = self.tmp / "os-release"
        for name, value in (("FLATPAK_INFO", info), ("HOST_OS_RELEASE", self.os_release)):
            patcher = mock.patch.object(cups_admin, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.missing_conf = self.tmp / "cups-files.conf"   # wie in der Sandbox: fehlt

    def group(self, distro=None, *existing):
        if distro is not None:
            self.os_release.write_text(OS_RELEASE[distro], encoding="utf-8")
        with groups_exist(*existing):
            return cups_admin.cups_admin_group(self.missing_conf)

    def test_debian_family_gets_lpadmin(self):
        for distro in ("ubuntu", "mint", "debian", "pop"):
            with self.subTest(distro=distro):
                # wie in der echten Sandbox: lpadmin ist dort unbekannt
                self.assertEqual(self.group(distro), "lpadmin")

    def test_other_distributions_get_wheel(self):
        for distro in ("fedora", "arch", "cachyos", "opensuse", "kein-debian-als-teilwort"):
            with self.subTest(distro=distro):
                self.assertEqual(self.group(distro, "lpadmin"), "wheel")

    def test_missing_os_release_gets_wheel(self):
        self.assertEqual(self.group(None, "lpadmin"), "wheel")

    def test_readable_conf_still_wins_in_flatpak(self):
        self.missing_conf.write_text("SystemGroup sys\n", encoding="utf-8")
        self.assertEqual(self.group("ubuntu", "sys"), "sys")

    def test_outside_flatpak_os_release_is_ignored(self):
        self.os_release.write_text(OS_RELEASE["ubuntu"], encoding="utf-8")
        with mock.patch.object(cups_admin, "FLATPAK_INFO", self.tmp / "fehlt"), groups_exist("wheel"):
            self.assertEqual(cups_admin.cups_admin_group(self.missing_conf), "wheel")

    def test_ubuntu_hint_in_flatpak(self):
        self.os_release.write_text(OS_RELEASE["ubuntu"], encoding="utf-8")
        with groups_exist(), mock.patch.object(cups_admin, "_", lambda s: s), \
             mock.patch.object(cups_admin, "CUPS_FILES_CONF", self.missing_conf):
            text = cups_admin.admin_rights_hint()
        self.assertIn("Gruppe 'lpadmin'", text)
        self.assertIn("sudo gpasswd -a $USER lpadmin", text)


class Hint(unittest.TestCase):
    def test_group_is_inserted_into_text_and_command(self):
        with mock.patch.object(cups_admin, "_", lambda s: s):
            text = cups_admin.admin_rights_hint("lpadmin")
        self.assertIn("Gruppe 'lpadmin'", text)
        self.assertIn("    sudo gpasswd -a $USER lpadmin\n", text)
        self.assertIn("abmelden und wieder anmelden", text)
        self.assertIsNone(re.search(r"(?<![A-Za-z])lp(?![A-Za-z])", text))

    def test_without_argument_the_detected_group_is_used(self):
        with mock.patch.object(cups_admin, "cups_admin_group", return_value="wheel"), \
             mock.patch.object(cups_admin, "_", lambda s: s):
            self.assertIn("$USER wheel", cups_admin.admin_rights_hint())


LOCALE = Path(cups_admin.__file__).resolve().parent / "locale"
MSGID_START = "Möglicherweise fehlen die nötigen CUPS-Admin-Rechte."


def po_translation(po: Path, msgid_start: str) -> tuple[str, str] | None:
    """(msgid, msgstr) des Eintrags, dessen msgid so beginnt (kleiner .po-Parser)."""
    def unq(s):
        return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)
    text = po.read_text(encoding="utf-8")
    for block in text.split("\n\n"):
        lines = [l for l in block.splitlines() if not l.startswith("#")]
        if not lines or not lines[0].startswith("msgid "):
            continue
        msgid, msgstr, cur = [], [], None
        for l in lines:
            if l.startswith("msgid "):
                cur = msgid
            elif l.startswith("msgstr "):
                cur = msgstr
            m = re.search(r'"(.*)"\s*$', l)
            if cur is not None and m:
                cur.append(unq(m.group(1)))
        mid = "".join(msgid)
        if mid.startswith(msgid_start):
            return mid, "".join(msgstr)
    return None


@unittest.skipUnless((LOCALE / "LINGUAS").exists() or any(LOCALE.glob("*/LC_MESSAGES/*.po")),
                     "Übersetzungsdateien nicht vorhanden")
class HintTranslations(unittest.TestCase):
    def test_placeholder_and_command_kept_in_every_language(self):
        pos = sorted(LOCALE.glob("*/LC_MESSAGES/print_ease.po"))
        self.assertEqual(len(pos), 33)
        for po in pos:
            lang = po.parent.parent.name
            with self.subTest(lang=lang):
                entry = po_translation(po, MSGID_START)
                self.assertIsNotNone(entry)
                msgid, msgstr = entry
                self.assertIn("%(group)s", msgid)
                self.assertTrue(msgstr, "nicht übersetzt")
                self.assertEqual(msgstr.count("%(group)s"), 2)
                self.assertIn("\n    sudo gpasswd -a $USER %(group)s\n", msgstr)
                self.assertIsNone(re.search(r"(?<![A-Za-z])lp(?![A-Za-z])", msgstr))
                filled = msgstr % {"group": "lpadmin"}
                self.assertIn("sudo gpasswd -a $USER lpadmin", filled)

    def test_compiled_catalogues_if_present(self):
        mos = sorted(LOCALE.glob("*/LC_MESSAGES/print_ease.mo"))
        if not mos:
            self.skipTest(".mo nicht kompiliert")
        msgid = po_translation(LOCALE / "de" / "LC_MESSAGES" / "print_ease.po", MSGID_START)[0]
        for mo in mos:
            with self.subTest(lang=mo.parent.parent.name), mo.open("rb") as f:
                text = gettext.GNUTranslations(f).gettext(msgid) % {"group": "wheel"}
                self.assertIn("sudo gpasswd -a $USER wheel", text)


if __name__ == "__main__":
    unittest.main()
