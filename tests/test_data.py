import unittest

from core.government_types import GOVERNMENT_TYPES, _parse
from innovations.innovation import ALL_INNOVATIONS, AGES, reached_age_index
from utils.data_files import DataError


def reachable(gov_keys):
    interfaces = set()
    for key in gov_keys:
        g = GOVERNMENT_TYPES[key]
        interfaces |= set(g.member_interfaces) | {i for o in g.offices.values() for i in o.interfaces}
    found, changed = set(AGES[0].starting_innovations), True
    while changed:
        changed = False
        for i in ALL_INNOVATIONS.values():
            if i.name not in found and i.interface in interfaces and i.is_discoverable(found):
                found.add(i.name)
                changed = True
    return found


class GameData(unittest.TestCase):
    def test_tribal_innovations_reachable_under_tribal_government(self):
        found = reachable(["tribal"])
        self.assertEqual(sorted(n for n, i in ALL_INNOVATIONS.items() if i.age == "tribal" and n not in found), [])
        self.assertGreaterEqual(reached_age_index(found), 1)

    def test_every_path_through_the_ages_reaches_every_innovation(self):
        stone = [k for k, g in GOVERNMENT_TYPES.items() if g.age == "stone"]
        metal = [k for k, g in GOVERNMENT_TYPES.items() if g.age == "metal"]
        for s in stone:
            for m in metal:
                with self.subTest(path=f"tribal->{s}->{m}"):
                    self.assertEqual(sorted(set(ALL_INNOVATIONS) - reachable(["tribal", s, m])), [])

    def test_bad_government_data_is_rejected(self):
        def base():
            return {"key": "x", "name": "X", "age": "tribal",
                    "offices": {"Chief": {"seats": 1, "selected_by": {"method": "tribe_vote"}}}}
        cases = [
            (lambda d: d["offices"]["Chief"].update(interfaces=["magic"]), "unknown interface"),
            (lambda d: d["offices"]["Chief"].update(selected_by={"method": "council_vote", "council": "Senate"}), "'council' must name an office"),
            (lambda d: d["offices"]["Chief"].update(requires=["Warp Drive"]), "unknown innovation"),
            (lambda d: d.update(carry_over={"Elder": "Senator"}), "unknown office 'Senator'"),
            (lambda d: d.update(reformed_by={"method": "divine_sign"}), "'method' must be one of"),
        ]
        for change, message in cases:
            with self.subTest(message=message):
                data = base()
                change(data)
                with self.assertRaises(DataError) as ctx:
                    _parse(data, "test.json")
                self.assertIn(message, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class IconWidthTest(unittest.TestCase):
    def test_every_icon_in_the_data_has_a_reliable_width(self):
        """Icons with a variation selector (🛡️) or text-style emoji (🗡) are drawn wider by some terminals
        than the layout expects, which pushes box borders out of line. One wide emoji, or one plain symbol."""
        import glob
        import json
        import unicodedata
        from rich.cells import cell_len
        from utils.data_files import DATA_DIR
        bad = []

        def walk(o, where):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "icon" and isinstance(v, str):
                        ok = len(v) == 1 and (unicodedata.east_asian_width(v) == "W" or cell_len(v) == 2
                                              or ord(v) < 0x1F000)
                        if not ok:
                            bad.append(f"{where}: {v!r}")
                    else:
                        walk(v, f"{where}/{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, f"{where}[{i}]")
        for path in glob.glob(str(DATA_DIR / "**" / "*.json"), recursive=True):
            walk(json.load(open(path, encoding="utf-8")), path.split("data/")[-1])
        self.assertEqual(bad, [])
