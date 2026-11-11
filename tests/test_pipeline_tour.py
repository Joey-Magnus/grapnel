"""The pipeline tour (scripts/pipeline_tour.py): the Debug tab's action numbers it reads from the source, the live input it sends,
its route, and its counts and merge of the pipeline state lists.

The tour drives the game through the live input file's "!cheat <action>" lines (host/nn_hid.c), whose numbers are the Insert
menu's (host/hos_main.c, gpu/vk/oot_cheat_items.h, gpu/vk/vk_menu.cpp): a renumbered action or a reordered teleport list must
not send the tour somewhere else. Synthetic data only, no game.
python -I -B tests/test_pipeline_tour.py
"""
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fail(why):
    raise SystemExit("pipeline tour: " + why)


def main():
    tour = load("pipeline_tour", ROOT / "scripts" / "pipeline_tour.py")
    a = tour.actions()
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")

    # the actions as the game side reads them: teleport 1000 + index, the age toggle, the inventory's items
    if "action >= OOT_TELEPORT_ACTION" not in main_c or "oot_teleport(c, actor, (unsigned)(action - OOT_TELEPORT_ACTION))" not in main_c:
        fail("host/hos_main.c no longer takes a teleport as OOT_TELEPORT_ACTION + index")
    if "action == OOT_AGE_ACTION" not in main_c:
        fail("host/hos_main.c no longer toggles the age on OOT_AGE_ACTION")
    if "action == OOT_STATE_ACTION" not in main_c or a["state"] in (a["age"], a["teleport"]) or a["state"] >= a["teleport"]:
        fail("host/hos_main.c has no state action of its own (OOT_STATE_ACTION)")
    line = '[hos x] cheats: state: map "KokiriForest_Child", reserved "", event playing 1, loading 0, child'
    if tour.state_of(line) != {"map": "KokiriForest_Child", "reserved": "", "event": True, "loading": False, "age": "child"}:
        fail("the state line is not read: %s" % tour.state_of(line))
    if 'hos_log("cheats: state: map \\"%s\\", reserved \\"%s\\", event playing %d, loading %d, %s",' not in main_c:
        fail("host/hos_main.c's state line is not the one the tour reads (scripts/pipeline_tour.py STATE_RE)")
    if len(a["bancs"]) != len(a["teleports"]) or any((child is None) != only for (child, _), (_, only) in zip(a["bancs"], a["teleports"])):
        fail("the destinations' maps and the teleport list differ")
    if "cheat_action.store(1000 + teleport_choice)" not in menu or a["teleport"] != 1000:
        fail("the menu's teleport action and OOT_TELEPORT_ACTION (%d) differ" % a["teleport"])
    if "cheat_action.store(999)" not in menu or a["age"] != 999:
        fail("the menu's age action and OOT_AGE_ACTION (%d) differ" % a["age"])
    if not re.search(r'if \(!strncmp\(line, "!cheat ", 7\)\) __atomic_store_n\(&hos_oot_live_action, atoi\(line \+ 7\)', hid):
        fail("host/nn_hid.c's live input no longer reads \"!cheat <action>\"")

    # the teleports: one for each destination, in its order; the adult-only ones those without a child map
    table = main_c.split("oot_destinations[] = {", 1)[1].split("\n};", 1)[0]
    entries = re.findall(r"\{(NULL|\"[^\"]*\"),.*?\},\s*/\* ([^*]+) \*/", table, re.S)
    if [label for _, label in entries] != [name for name, _ in a["teleports"]]:
        fail("the teleport names and host/hos_main.c's destinations differ:\n%s\n%s" % (
            [label for _, label in entries], [name for name, _ in a["teleports"]]))
    for (child, label), (_, adult_only) in zip(entries, a["teleports"]):
        if (child == "NULL") != adult_only:
            fail("%s: adult only in the menu %s, no child map in the table %s" % (label, adult_only, child == "NULL"))

    # the inventory: the item list's order is the action's index; kinds 0 (unlock) and 1 (a quantity)
    names = list(a["items"])
    for must in ("Item_Bomb", "Item_Hookshot", "Item_Arrow_Fire", "Item_DinFire", "Weapon_Range_Bow", "Item_Ocarina_Time"):
        if must not in a["items"]:
            fail("%s is not in the inventory list" % must)
    if a["items"][names[0]][0] != 0 or a["items"]["Item_Bomb"][1] != 1 or a["items"]["Item_Hookshot"][1] != 0:
        fail("the inventory's indices or kinds are read wrong: %s" % list(a["items"].items())[:16])
    unlock = tour.items_unlock(a)
    for n in unlock:
        item, op = divmod(n - a["item"], 256)
        if not 0 <= item < len(names) or not (op == 200 or 0 < op - 64 <= 63):
            fail("an inventory action out of range: %d" % n)

    # the route: a new game first, every destination as child (but the adult-only ones) and as adult, the age switched once
    steps = tour.route(a)
    if steps[0] != ("newgame",) or ("items",) not in steps:
        fail("the route does not start with a new game and the items")
    visits = [(s[1], s[2]) for s in steps if s[0] == "visit"]
    for i, (name, adult_only) in enumerate(a["teleports"]):
        if ("adult", name) in tour.LEFT_OUT:
            if ("adult", i) in visits:
                fail("%s (adult) is visited though it is left out" % name)
            continue
        if ("adult", i) not in visits or (("child", i) in visits) == adult_only:
            fail("%s is not in the route as it should be" % name)
    ages = [k for k, s in enumerate(steps) if s == ("age",)]
    if len(ages) != 1 or any(s[0] == "visit" and s[1] == "adult" for s in steps[:ages[0]]):
        fail("the age is not switched once, before the adult stops")
    for part in ("child", "adult"):
        plan = tour.plan_stops(a, part)
        if not plan or any(age != part for age, _ in plan):
            fail("the %s part visits other ages" % part)
    for age, name in tour.LEFT_OUT:
        if name not in [n for n, _ in a["teleports"]]:
            fail("a left-out stop names no destination: %s" % name)
    if any(n.startswith(tour.QUEST_ITEMS) for n in [names[(x - a["item"]) // 256] for x in unlock]):
        fail("the quest items (the story's flags) are given")
    if len(tour.plan_stops(a, "all")) != len(tour.plan_stops(a, "child")) + len(tour.plan_stops(a, "adult")):
        fail("the child and adult parts are not the whole route")
    main_time = re.search(r"action >= (\d+) && action < (\d+)\) \{\s*oot_set_time\(c, action - (\d+)\)", main_c)
    if not main_time or int(main_time.group(1)) != tour.TIME_ACTION or int(main_time.group(2)) < tour.TIME_ACTION + 23:
        fail("host/hos_main.c's clock action is not TIME_ACTION + hour")
    for part in ("child-dungeons", "adult-dungeons"):
        if not tour.plan_stops(a, part) or any(i < a["dungeons"] for _, i in tour.plan_stops(a, part)):
            fail("%s visits the overworld" % part)
    resumed = tour.plan_stops(a, "child", first="Market")
    if a["teleports"][resumed[0][1]][0] != "Market" or len(resumed) >= len(tour.plan_stops(a, "child")):
        fail("--first Market does not start the route there")
    for part in tour.PARTS:   # (the runs of 8 stops cover the part's route, each starting where the one before ended)
        runs = tour.chunks(a, part, 8)
        covered = sum((tour.plan_stops(a, part, stops, first) for first, stops in runs), [])
        if covered != tour.plan_stops(a, part):
            fail("the %s part's runs of 8 stops are not its route" % part)
    extras = [x for x in tour.route(a, "extras") if x[0] == "extra"]
    if len(extras) != len(tour.EXTRAS):
        fail("the extras part does not visit every extra stop")
    if [x[4] for x in extras] != ["child"] * sum(x[3] == "child" for x in tour.EXTRAS) + ["adult"] * sum(x[3] == "adult" for x in tour.EXTRAS):
        fail("the extras part does not do the child stops first")
    if '!strncmp(line, "!teleport ", 10)' not in hid or "OOT_TELEPORT_CUSTOM" not in main_c:
        fail("the live input's \"!teleport <map> <start>\" is gone (host/nn_hid.c, host/hos_main.c)")
    if tour.chunks(a, "opening", 8) != [(None, None)]:
        fail("the opening part is not one run")
    if len([s for s in tour.route(a, stops=3) if s[0] == "visit"]) != 3:
        fail("--stops 3 is not three stops")

    # the presses: buttons host/nn_hid.c knows, in its <seconds>:<button>[+<button>][/<ms>] form, each within its step's span
    known = set(re.findall(r'\{"([A-Z]+)", (?:B_|-1)', hid))
    texts = [(tour.LOOK, tour.LOOK_SPAN), (tour.ACT, tour.ACT_SPAN), (tour.PAUSE_TOUR, tour.PAUSE_SPAN), (tour.SKIP, tour.SKIP_EVERY / tour.FPS), (tour.DIVE, tour.DIVE_SPAN), (tour.UNDERWATER_GEAR, tour.GEAR_SPAN), (tour.BOOTS_OFF, tour.BOOTS_SPAN)]
    texts += [tour.pause_pick(k) for k in range(25)]
    for text, span in texts:
        for press in text.split(","):
            m = re.fullmatch(r"([\d.]+):([A-Z+]+)(?:/(\d+))?", press)
            if not m or not set(m.group(2).split("+")) <= known:
                fail("a press nn_hid.c does not read: %s" % press)
            if float(m.group(1)) + int(m.group(3) or 200) / 1000 > span + 1e-6:
                fail("a press past its step's span (%g s): %s" % (span, press))
    if len({tour.pause_pick(k)[0] for k in range(20)}) != 20:
        fail("the item picks do not differ from stop to stop")
    if "HOS_INPUT_FRAME_CLOCK" not in tour.BASE_ENV or "HOS_INPUT_FRAME_CLOCK" not in hid:
        fail("the presses are not timed in game frames")

    # the counts and the merge, through nx2/pipeline_states.py (whatever its format)
    states = tour.state_tool()

    def rec(vs, fs, topo):
        r = bytearray(states.SIZE)
        struct.pack_into("<QQ", r, 0, vs, fs)
        struct.pack_into("<I", r, 44, topo)
        return bytes(r)

    with tempfile.TemporaryDirectory() as d:
        head = states.MAGIC + struct.pack("<I", states.SIZE)
        one, two, out = (os.path.join(d, n) for n in ("one.bin", "two.bin", "out.bin"))
        open(one, "wb").write(head + rec(1, 2, 3) + rec(1, 2, 4))
        open(two, "wb").write(head + rec(1, 2, 4) + rec(5, 0, 3))
        n, programs, recs = tour.list_counts(states, one)
        if (n, programs, len(recs)) != (2, 1, 2):
            fail("list_counts: %d pipelines, %d programs, expected 2 and 1" % (n, programs))
        if tour.list_counts(states, os.path.join(d, "none.bin"))[:2] != (0, 0):
            fail("a missing list is not empty")
        ran = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "pipeline_tour.py"), "merge", "--out", out, one, two],
                             capture_output=True, text=True)
        if ran.returncode or "1 not in the lists before it" not in ran.stdout:
            fail("merge: %s%s" % (ran.stdout, ran.stderr))
        if states.read(out) != [rec(1, 2, 3), rec(1, 2, 4), rec(5, 0, 3)]:
            fail("merge did not write the three different pipelines in order")
        # the options file: the keys set, the rest kept, the original given back
        ini = os.path.join(d, "hookshot_options.ini")
        open(ini, "w").write("dlss=1\nhdr=0\n")
        old = tour.set_ini(ini, [("hdr", "1"), ("handheld_profile", "1")])
        if old != "dlss=1\nhdr=0\n" or open(ini).read() != "dlss=1\nhdr=1\nhandheld_profile=1\n":
            fail("set_ini: %r" % open(ini).read())
        # the report: the steps in order with their new pipelines, a run that did not end said so
        text = tour.write_report(d, [{"stop": "a", "seconds": 1, "pipelines": 2, "programs": 1, "new": 2},
                                     {"stop": "b", "seconds": 2, "pipelines": 3, "programs": 2, "new": 1}],
                                 {"name": "t", "seconds": 2, "env": {"X": "1"}, "ini": [], "completed": False, "error": "x"})
        if "3 pipelines" not in text or "NOT COMPLETED: x" not in text or not os.path.exists(os.path.join(d, "report.json")):
            fail("the report: %s" % text)
    # --publish: the tour's source written by nx2/pipeline_states.py tour, its note from what the runs logged
    with tempfile.TemporaryDirectory() as d:
        head = states.MAGIC + struct.pack("<I", states.SIZE)
        part = os.path.join(d, "run-child")
        os.makedirs(part)
        open(os.path.join(part, "states.bin"), "wb").write(head + rec(1, 2, 3) + rec(5, 0, 3))
        open(os.path.join(part, "log.txt"), "w").write(
            "[hos host] hookshot v9.9.9-1-gabc (source 1234abcd)\n"
            "[hos MainThread] vk: Some GPU 9000, Vulkan 1.4, driver 0x1234; mesh shaders yes, host memory import yes\n")
        json.dump({"meta": {"seconds": 120, "env": {"HOS_OUTPUT_RES": "640x360"}}, "stops": []},
                  open(os.path.join(part, "report.json"), "w"))
        sources = os.path.join(d, "sources")
        os.makedirs(sources)
        if tour.publish([os.path.join(part, "states.bin")], [part], ["child"], sources):
            fail("publish failed")
        note = open(os.path.join(sources, "tour.md"), encoding="utf-8").read()
        if states.read(os.path.join(sources, "tour.bin.xz")) != [rec(1, 2, 3), rec(5, 0, 3)]:
            fail("publish did not write the parts' pipelines")
        for want in ("Some GPU 9000", "v9.9.9-1-gabc", "640x360", "parts child"):
            if want not in note:
                fail("the tour's note lacks %r:\n%s" % (want, note))
    print("pipeline tour: actions, route, presses, counts and merge ok")


if __name__ == "__main__":
    main()
