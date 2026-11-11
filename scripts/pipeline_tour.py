"""The pipeline tour: plays the game unattended, from a new save through every debug Teleport destination as child and as
adult, with the items, their effects and the menus, so that its graphics pipelines are met and written to the pipeline state list
(gpu/vk/vk_draw.cpp: hookshot_pipeline_states.bin). The parts' lists become the tour's source of the list a release ships,
assets/pipeline_states/tour.bin.xz (nx2/pipeline_states.py tour): the first start prepares those pipelines before the title.

    python -I scripts/pipeline_tour.py tour --game <game folder> --out <dir> [--name play] [--parts ...] [--publish] [--env ...] [--ini ...]
    python -I scripts/pipeline_tour.py run  --game <game folder> --out <dir> [--name play] [--part <part>] [--first <stop>] [--stops N]
                                            [--skip-opening] [--env NAME=VALUE ...] [--ini key=value ...] [--window WxH] [--dry-run]
    python -I scripts/pipeline_tour.py merge --out <file> <list> ...
    python -I scripts/pipeline_tour.py report <out>/<name>

run: one game. The game folder is used as it is, so give it a copy (cp -a --reflink=always): its hookshot_pipelines.bin (the pipeline
notes), hookshot_pipeline_states.bin and hookshot_pipeline_states_shipped.bin are moved aside for the run (a precompiled pipeline is
not noted again, and only what this run meets counts) and put back after it. The run starts with no save at all (an empty data folder
of its own, <out>/<name>/data): the title, New Game, the opening, then control of Link, checked by the game accepting a teleport.
Then every item (the Debug tab's inventory), the pause menu's pages, and each destination: the teleport, its loading, the camera all
around, the sword, the shield and an item, until no new pipeline came for a while. Everything is driven through the live input file
(HOS_INPUT_LIVE) and its "!cheat <action>" lines, the Insert menu's Debug tab actions; nothing reaches the desktop, and no
controller is opened (HOS_NO_SDL). Waits are counted in the game's frames (RX_VK_FRAME_LOG) and the presses' times too
(HOS_INPUT_FRAME_CLOCK), so the game can run faster than real time: no window (HOS_HEADLESS), the smallest output (640x360: a
pipeline's key has formats and state, not sizes), frame pacing off, the rate cap at 240 with a 60th of a second of game time a
frame (HOS_FPS_MAX=240, HOS_FPS_STEP=0): fps / 60 times real time. Each step has a limit: a step that does not happen fails the run, it does not wander.
--env and --ini run it under other settings (RX_VK_FORCE_MESH_FALLBACK=1, dlss=0, hdr=1, HOS_HANDHELD=1); the options file is
restored. --window shows it on a Sway workspace instead.

tour: the parts in parallel, each in its own reflinked copy of the game folder on its share of --cpus, merged; --publish writes
the repository's tour list from them (nx2/pipeline_states.py tour, with the GPU, build, settings and route the runs logged).

Each run writes <out>/<name>/: states.bin (its list), report.txt and report.json (the pipelines and programs after each step, the new
ones each added, its frames and wall time), log.txt (the game's log) and steps.txt (what was sent, at which frame).

Standard library only. The actions' numbers come from host/hos_main.c, gpu/vk/oot_cheat_items.h and gpu/vk/vk_menu.cpp.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILES = ("hookshot_pipelines.bin", "hookshot_pipeline_states.bin", "hookshot_pipeline_states_shipped.bin")
LIST = "hookshot_pipeline_states.bin"

# no window, no sound, no controller, no pacing, game time a frame per frame with the rate cap at 240, the smallest output,
# the script's input alone, text at once, no frame generation
BASE_ENV = {
    "HOS_HEADLESS": "1",
    "HOS_NO_SDL": "1",
    "HOS_AUDIO": "0",
    "HOS_INPUT_EXCLUSIVE": "1",
    "HOS_INPUT_SCRIPT_BACKGROUND": "1",
    "HOS_INPUT_FRAME_CLOCK": "1",
    "HOS_OOT_CHEATS": "1",
    "HOS_OOT_PROTECT_HEARTS": "1",
    "HOS_NO_PACING": "1",
    "HOS_REALTIME_STEP": "0",
    "HOS_FPS_MAX": "240",
    "HOS_FPS_STEP": "0",
    "HOS_FPS_TARGET": "240",
    "HOS_FPS_LOG": "1",
    "HOS_OUTPUT_RES": "640x360",
    "HOS_TEXT_SPEED": "3",
    "HOOKSHOT_NO_UPDATE_CHECK": "1",
    "HOS_DISCORD": "0",
    "RX_VK_FRAMEGEN": "0",
    "RX_VK_SHOT_EVERY": "600",   # (with RX_VK_SHOTS, set per run: a small picture every 600 frames, to see where a run got stuck)
    "RX_VK_SHOT_W": "320",
    "RX_VK_SHOT_H": "180",
}
FPS = 60   # (the game's frames a second of game time: the presses' clock)
# the options for the run (its own copy of hookshot_options.ini, restored after it): the cheapest of each that does not take passes or
# formats away. The output 640x360 (as HOS_OUTPUT_RES), the upscaler the game's own (dlss=0), render scale 50%, no frame generation, sharpening or HDR, text at once. The
# speed is the environment's (BASE_ENV): the cap at 240 (HOS_FPS_MAX: the vsync events and the game's limiter) with every frame a
# 60th of a second of game time (HOS_FPS_STEP=0: host/nn_vi.c realtime_step), so the game runs fps / 60 times faster than real time
BASE_INI = {"output_res": "640x360", "dlss": "0", "upscaling": "0", "resolution": "4", "frame_generation": "0", "sharpness": "0", "hdr": "0",
            "frame_rate_cap": "0", "game_speed": "0", "text_speed": "3", "fps_counter": "0", "frame_pacing": "0",
            "discord_status": "0"}


# ---- the Debug tab's actions, as the source has them ----

def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def define(text, name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name, text)
    if not m:
        raise SystemExit("pipeline_tour: %s not found" % name)
    return int(m.group(1))


def bancs(main):
    """Each destination's maps, child and adult (None: none), as host/hos_main.c's oot_destinations has them"""
    table = main.split("oot_destinations[] = {", 1)[1].split("\n};", 1)[0]
    q = r'(NULL|"[^"]*")'
    out = []
    for m in re.finditer(r"\{%s,\s*%s,\s*%s,\s*%s," % (q, q, q, q), table):
        out.append(tuple(None if v == "NULL" else v.strip('"') for v in (m.group(1), m.group(4))))
    return out


def actions(root_read=read):
    """The action numbers and the lists they index: {teleport, age, item, teleports: [(name, adult_only)], items: {pouch name: index}}"""
    main, items_h, menu = root_read("host/hos_main.c"), root_read("gpu/vk/oot_cheat_items.h"), root_read("gpu/vk/vk_menu.cpp")
    names = re.search(r"teleport_names\[\]\s*=\s*\{(.*?)\};", menu, re.S)
    notes = re.search(r"teleport_notes\[\]\s*=\s*\{(.*?)\};", menu, re.S)
    if not names or not notes:
        raise SystemExit("pipeline_tour: the teleport list not found in gpu/vk/vk_menu.cpp")
    labels = re.findall(r'"((?:[^"\\]|\\.)*)"', names.group(1))
    note_list = [n.strip() for n in notes.group(1).split(",")]
    destinations = len(re.findall(r"\},\s*/\*", main.split("oot_destinations[]", 1)[1].split("};", 1)[0]))
    if destinations != len(labels) or len(note_list) != len(labels):
        raise SystemExit("pipeline_tour: %d teleport names, %d notes, %d destinations" % (len(labels), len(note_list), destinations))
    items = re.findall(r'OOT_ITEM\("[^"]*",\s*"([^"]+)",\s*(\d)\)', items_h)
    return {
        "teleport": define(main, "OOT_TELEPORT_ACTION"),
        "age": define(main, "OOT_AGE_ACTION"),
        "state": define(main, "OOT_STATE_ACTION"),
        "bancs": bancs(main),
        "item": define(items_h, "OOT_CHEAT_ITEM_ACTION"),
        "teleports": [(label, "adult only" in note) for label, note in zip(labels, note_list)],
        "dungeons": int(re.search(r'\{"Dungeons", (\d+)\}', menu).group(1)),
        "items": {name: (i, int(kind)) for i, (name, kind) in enumerate(items)},
    }


QUEST_ITEMS = ("Item_Medal_", "Item_Stone_", "Item_Melody_")
# Stops left out: a scene starts there that waits for something the tour does not do, and the map can then not be left
LEFT_OUT = {("adult", "Sacred Forest Meadow"): "Sheik's lesson starts on arrival and waits for the ocarina to be played",
            # (runs 2-4, ~/.cache/hookshot-work/tour/route-value.txt: what only these met, against everything else)
            ("child", "Lost Woods"): "20 pipelines no other stop met", ("adult", "Lost Woods"): "7",
            ("child", "Sacred Forest Meadow"): "4"}
# Rooms no Teleport destination reaches, by the game's own map and start position names ("!teleport <map> <start>": host/hos_main.c):
# the boss arenas and the sages' rooms, and the boss rush's rooms (DreamWorld). The "extras" part visits them, the child ones
# first; it is not one of the tour's default parts. (label, map, start position, age)
# Measured (a short run): Gohma_BattleStartPos loads the Deku Tree but the picture stays black, and no teleport is taken from there
# after ("result 0", as in the Haunted Wasteland); the run added 36 pipelines the tour list lacked. These are the events' own start
# positions, not the entrances' (NextStartPos): each wants its own arrival event, still to find. Until then each needs a game of
# its own (--part extras --first <label> --stops 1)
EXTRAS = [
    ("Gohma's room", "InsideTheDekuTree", "Gohma_BattleStartPos", "child"),
    ("Deku Tree, after Gohma", "InsideTheDekuTree", "StartPos_Get_StoneOfForest", "child"),
    ("King Dodongo's room", "DodongoCavern", "StartPos_Get_StoneOfFire", "child"),
    ("Barinade's room", "InsideJabuJabuBelly", "StartPos_StoneOfWater", "child"),
    ("Big Octo's room", "InsideJabuJabuBelly", "StartPos_Get_StoneOfWater_MiddleBoss", "child"),
    ("Boss rush", "DreamWorld", "StartPos_SubEvent_AllBossBattle", "child"),
    ("Phantom Ganon's room", "ForestTemple", "StartPos_SageOfForest", "adult"),
    ("Volvagia's room", "FireTemple", "StartPos_SageOfFire", "adult"),
    ("Morpha's room", "WaterTemple", "StartPos_SageOfWater", "adult"),
    ("Dark Link's room", "WaterTemple", "StartPos_SageOfWater_MiddleBoss", "adult"),
    ("Bongo Bongo's room", "ShadowTemple", "StartPos_SageOfShadow", "adult"),
    ("Shadow Temple's ship", "ShadowTemple", "StartPos_SageOfShadow_BattleOnShip", "adult"),
    ("Twinrova's room", "SpiritTemple", "StartPos_SageOfSpirit", "adult"),
    ("Ganondorf's room", "GanonCastle", "RestartPos_Ganondorf_BossBattle", "adult"),
    ("Ganon's arena", "GanonCastle", "FinalBattle_BossInStartPos", "adult"),
]
# Stops the game does not teleport out of (the request is refused: "result 0"), visited last in their part
LAST = {"Haunted Wasteland"}
# Where Link uses his items and their effects (one picked from the pause menu, a different one each time): a few stops per age,
# not every one. The rest only look around
# Overworld stops seen at night too (the Debug tab's clock: !cheat 100 + hour), then back to noon. Measured on a short run: Hyrule
# Field +4 pipelines at night, Kakariko +10, for ~10 s each: none by default (add names here for a run that wants them)
NIGHT_AT = set()
TIME_ACTION = 100
ACT_AT = {"Kokiri Forest", "Hyrule Field", "Lake Hylia", "Death Mountain Crater", "Zora's Domain", "Gerudo Valley",
          "Inside the Deku Tree", "Fire Temple", "Water Temple", "Shadow Temple"}


def items_unlock(a):
    """Every item Link can have (kind 0: unlocked once), the quantities filled (kind 1: +60)"""
    out = []
    for name, (i, kind) in a["items"].items():
        if name.startswith("Armor_Child_Mask_") and name != "Armor_Child_Mask_Truth":
            continue   # (one mask slot: the last one added is the one kept)
        if name.startswith(QUEST_ITEMS):
            continue   # (the story's flags: medallions, stones and songs start scenes that wait for the player)
        out.append(a["item"] + i * 256 + (200 if kind == 0 else 64 + 60))
    return out


# ---- the route ----
# Presses: <seconds>:<button>[+<button>][/<ms>] (docs/development.md, "Input for scripted runs"), here in game time.
# The buttons as the remake has them: B the sword (held: the spin attack), R the shield, ZL a target, A a roll, ZR the item on the
# item button; PLUS the pause menu, whose pages ZL and ZR turn (Collection, Equipment, Items, System) and B closes; on its Items
# page the stick moves the cursor and A puts the item on the item button.

def presses(items):
    return ",".join("%g:%s" % (t, b) for t, b in items)


LOOK = presses([(0, "RLEFT/1500"), (1.5, "RUP/400"), (1.9, "RRIGHT/700"), (2.6, "RDOWN/700"), (3.3, "RUP/300"),
                (0, "LUP/600"), (0.6, "LDOWN/600")])
LOOK_SPAN = 3.7
ACT = presses([(0, "B"), (0.35, "B"), (0.7, "B/900"), (1.7, "R/500"), (2.3, "ZL/300"), (3.2, "ZR/600"),
               (4, "ZR"), (4.6, "ZR/600")])   # (no A: next to someone it starts a conversation)
# Presses that end what holds a map change back (a conversation, a question, an item's prompt), one every second in turn
UNSTICK = ["0:A/100", "0:B/100", "0:LDOWN/150,0.3:A/100", "0:B/100", "0:LUP/150,0.3:A/100", "0:B/100,0.4:B/100"]
ACT_SPAN = 5.4


def pause_pick(k):
    """The pause menu's pages, then on the Items page the k-th item put on the item button (a cursor walk that differs from stop to
    stop), and closed. ZL three times first: from whatever page it opened on to the first, then ZR twice to Items"""
    seq, t = [(0, "PLUS")], 0.8
    for b in ("ZL", "ZL", "ZL", "ZR", "ZR"):
        seq.append((t, b))
        t += 0.45
    walk = ["LDOWN"] * (k % 5) + ["LRIGHT"] * ((k // 5) % 4)
    for b in walk:
        seq.append((t, b + "/120"))
        t += 0.25
    seq += [(t, "A"), (t + 0.4, "B"), (t + 0.9, "B")]
    return presses(seq), t + 1.3


PAUSE_TOUR = presses([(0, "PLUS"), (0.8, "ZR"), (1.5, "ZR"), (2.2, "ZR"), (2.9, "ZR"), (3.6, "ZL"), (4.3, "ZL"), (5, "ZL"),
                      (5.7, "ZL"), (6.4, "B"), (6.9, "B")])
PAUSE_SPAN = 7.4

# Water: at these stops Link arrives swimming; A held dives (the scales are given). As adult the pause menu's Equipment page then
# puts on the iron boots and the Zora tunic (its cursor starts on the Echo Gem in a new game: up is the iron boots, right then down
# the tunics' row), the stop is reached again, and Link walks the lake's bottom; the boots come off after
DIVE_AT = {"Lake Hylia"}
DIVE = presses([(0, "A/4000")])
DIVE_SPAN = 4.5
UNDERWATER_GEAR = presses([(0, "PLUS"), (0.8, "ZL"), (1.2, "ZL"), (1.6, "ZL"), (2.0, "ZR"), (2.6, "UP"), (3.0, "A"), (3.5, "RIGHT"),
                           (3.9, "DOWN"), (4.3, "RIGHT"), (4.7, "RIGHT"), (5.1, "A"), (5.6, "B"), (6.1, "B")])
GEAR_SPAN = 6.6
BOOTS_OFF = presses([(0, "PLUS"), (0.8, "ZL"), (1.2, "ZL"), (1.6, "ZL"), (2.0, "ZR"), (2.6, "LEFT"), (3.0, "LEFT"), (3.4, "LEFT"),
                     (3.8, "A"), (4.3, "B"), (4.8, "B")])   # (from the Zora tunic: left three times is the iron boots again)
BOOTS_SPAN = 5.3


PARTS = ("all", "child", "adult", "opening", "child-overworld", "child-dungeons", "adult-overworld", "adult-dungeons", "dungeons",
         "extras")


def plan_stops(a, part="all", stops=None, first=None):
    """The destinations a part visits, in order: [(age, index)]. opening: none (the new game's opening alone, watched whole);
    child-overworld, dungeons (both ages) and adult-overworld split the route in three"""
    adult_only = {i for i, (_, only) in enumerate(a["teleports"]) if only}
    first_dungeon = dungeons_from(a)
    child = [("child", i) for i in range(len(a["teleports"])) if i not in adult_only]
    adult = [("adult", i) for i in range(len(a["teleports"]))]
    over = lambda plan: [(age, i) for age, i in plan if i < first_dungeon]
    under = lambda plan: [(age, i) for age, i in plan if i >= first_dungeon]
    plan = {"all": child + adult, "child": child, "adult": adult, "opening": [], "child-overworld": over(child),
            "dungeons": under(child) + under(adult), "adult-overworld": over(adult), "child-dungeons": under(child),
            "adult-dungeons": under(adult), "extras": []}[part]
    plan = [(age, i) for age, i in plan if (age, a["teleports"][i][0]) not in LEFT_OUT]
    # (a stop the game will not teleport out of goes last: the next map change after it is the next run's)
    ages = [age for age, _ in plan]
    plan = sorted(plan, key=lambda x: (ages.index(x[0]), a["teleports"][x[1]][0] in LAST))   # (last within its age)
    if first:   # (a run that starts again at a stop: "<name>" or "<name> (<age>)", as the report names them)
        labels = ["%s (%s)" % (a["teleports"][i][0], age) for age, i in plan]
        at = [k for k, (lab, (age, i)) in enumerate(zip(labels, plan)) if first in (lab, a["teleports"][i][0])]
        if not at:
            raise SystemExit("pipeline_tour: no stop %r in this part" % first)
        plan = plan[at[0]:]
    return plan[:stops] if stops is not None else plan


def dungeons_from(a):
    """The first dungeon's index in the teleport list (vk_menu.cpp teleport_sections: "Dungeons")"""
    return a.get("dungeons", len(a["teleports"]))


def route(a, part="all", stops=None, first=None):
    """The steps of a run: ("newgame",), ("items",), ("press", text, span, label), ("age",), ("visit", age, index, k).
    The pause menu's pages once, in the opening part or a whole run"""
    steps = [("newgame",), ("items",)]
    if part in ("all", "child", "opening"):
        steps.append(("press", PAUSE_TOUR, PAUSE_SPAN, "pause menu pages"))
    age = "child"
    for k, (want, i) in enumerate(plan_stops(a, part, stops, first)):
        if want != age:
            steps += [("age",), ("items",)]   # (the adult's equipment is only given to the adult: a child's add is lost)
            age = want
        steps.append(("visit", want, i, k))
    if part == "extras":
        extras = [x for x in EXTRAS if x[3] == "child"] + [x for x in EXTRAS if x[3] == "adult"]
        if first:
            at = [k for k, x in enumerate(extras) if x[0] == first]
            if not at:
                raise SystemExit("pipeline_tour: no extra stop %r" % first)
            extras = extras[at[0]:]
        for x in extras[:stops] if stops is not None else extras:
            if x[3] != age:
                steps += [("age",), ("items",)]
                age = x[3]
            steps.append(("extra",) + x)
    return steps


# ---- the list ----

def state_tool():
    spec = importlib.util.spec_from_file_location("pipeline_states", os.path.join(ROOT, "nx2", "pipeline_states.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def list_counts(tool, path):
    """(pipelines, programs, records) of a list, as nx2/pipeline_states.py reads and counts them (whatever its format)"""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return 0, 0, set()
    try:
        recs = tool.read(path)
    except SystemExit:
        return 0, 0, set()
    m = re.search(r"of (\d+) programs", tool.describe(recs))
    return len(recs), int(m.group(1)) if m else 0, set(recs)


# ---- the game ----

class Failed(Exception):
    pass


class Game:
    """The game, its log and its frames: what was sent, at which frame"""
    def __init__(self, game, data, run_dir, env, dry=False):
        self.game, self.run_dir, self.dry = game, run_dir, dry
        self.live = os.path.join(run_dir, "live.txt")
        self.log_path = os.path.join(run_dir, "log.txt")
        self.frames_path = os.path.join(run_dir, "frames.csv")
        self.list_path = os.path.join(game, LIST)
        self.steps = open(os.path.join(run_dir, "steps.txt"), "w", encoding="utf-8")
        self.t0 = time.monotonic()
        self.pos = self.fpos = 0
        self.frame = 0          # (presents so far: the frame log's lines)
        self.draws = 0          # (the last "a frame: N draws")
        self.draw_lines = 0
        self.speed = []         # (the game clock's speeds the log gave: 1.0 is real time)
        self.fps = []           # (the frame rates the same lines gave)
        self.map = None         # (the map the last teleport check named)
        self.proc = None
        if dry:
            return
        open(self.live, "w").close()
        full = dict(os.environ)
        full.update(env)
        full["XDG_DATA_HOME"] = data
        full["HOS_INPUT_LIVE"] = self.live
        full["RX_VK_FRAME_LOG"] = self.frames_path
        exe = os.path.join(game, "bin", "hookshot")
        if not os.path.exists(exe):
            exe = os.path.join(game, "hookshot")
        self.logf = open(self.log_path, "wb")
        self.proc = subprocess.Popen([exe], cwd=game, env=full, stdout=self.logf, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)

    def now(self):
        return time.monotonic() - self.t0

    def note(self, what):
        self.steps.write("%8.1f s %7d  %s\n" % (self.now(), self.frame, what))
        self.steps.flush()

    def send(self, line):
        self.note(line)
        if not self.dry:
            with open(self.live, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def alive(self):
        return self.dry or self.proc.poll() is None

    def poll(self):
        """New log lines since the last poll; the frame count brought up to date"""
        if self.dry:
            return []
        try:
            with open(self.frames_path, "rb") as f:
                f.seek(self.fpos)
                chunk = f.read()
            cut = chunk.rfind(b"\n") + 1
            self.fpos += cut
            self.flines = getattr(self, "flines", 0) + chunk[:cut].count(b"\n")
            self.frame = max(self.frame, self.flines)
        except OSError:
            pass
        with open(self.log_path, "rb") as f:
            f.seek(self.pos)
            chunk = f.read()
        cut = chunk.rfind(b"\n") + 1
        self.pos += cut
        lines = chunk[:cut].decode("utf-8", "replace").splitlines()
        for line in lines:
            m = re.search(r"vk: \d+ presents, [\d.]+ fps; a frame: (\d+) draws", line)
            if m:
                self.draws, self.draw_lines = int(m.group(1)), self.draw_lines + 1
            m = re.search(r"vk: (\d+) presents, ", line)
            if m and int(m.group(1)) > self.frame:   # (no frame log without a window: the presents the log counts, 120 apart)
                self.frame = int(m.group(1))
            m = re.search(r"vi: game clock [\d.]+: [\d.]+ a second of wall time \(speed ([\d.]+)\) at ([\d.]+) fps", line)
            if m:
                self.speed.append(float(m.group(1)))
                self.fps.append(float(m.group(2)))
        return lines

    def tick(self):
        if not self.dry:
            time.sleep(0.05)
        lines = self.poll()
        if not self.alive():
            raise Failed("the game ended")
        return lines

    def frames(self, n, limit_s=300):
        """n frames of the game (the dry run: none)"""
        if self.dry:
            return
        end, until = time.monotonic() + limit_s, self.frame + n
        while self.frame < until:
            self.tick()
            if time.monotonic() > end:
                raise Failed("%d frames did not come in %d s" % (n, limit_s))

    def memory(self):
        """The game's resident memory in MB (Linux): {rss, anon, shmem} (guest memory is shared: shmem), {} elsewhere"""
        out = {}
        try:
            with open("/proc/%d/status" % self.proc.pid) as f:
                for line in f:
                    k, _, v = line.partition(":")
                    if k in ("VmRSS", "RssAnon", "RssShmem"):
                        out[{"VmRSS": "rss", "RssAnon": "anon", "RssShmem": "shmem"}[k]] = int(v.split()[0]) // 1024
        except (OSError, AttributeError, ValueError):
            pass
        return out

    def list_size(self):
        try:
            return os.path.getsize(self.list_path)
        except OSError:
            return 0

    def settle(self, quiet, most):
        """Frames until the list has had no new pipeline for `quiet` frames, `most` at most"""
        if self.dry:
            return
        start, size, since = self.frame, self.list_size(), self.frame
        while self.frame - start < most:
            self.tick()
            now = self.list_size()
            if now != size:
                size, since = now, self.frame
            elif self.frame - since >= quiet:
                return

    def stop(self):
        if self.dry or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(15)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait()


STATE_RE = re.compile(r'cheats: state: map "([^"]*)", reserved "([^"]*)", event playing (\d), loading (\d), (child|adult)')


def state_of(line):
    """The game's answer to "!cheat <state action>" (host/hos_main.c oot_log_state): {map, reserved, event, loading, age}"""
    m = STATE_RE.search(line)
    if not m:
        return None
    return {"map": m.group(1), "reserved": m.group(2), "event": m.group(3) == "1", "loading": m.group(4) == "1", "age": m.group(5)}


class Poll:
    """The game's state, asked every `every` frames through the live input; .new is a state that came since the last look"""
    def __init__(self, g, every=60):
        self.g, self.every, self.next_at, self.last, self.new = g, every, 0, None, None

    def step(self, lines):
        self.new = None
        for line in lines:
            st = state_of(line)
            if st:
                self.last = self.new = st
        if self.g.frame >= self.next_at:
            self.g.send("!cheat %d" % self.g.actions["state"])
            self.next_at = self.g.frame + self.every


def teleport(g, action, want, limit_frames=60 * 60 * 3, limit_s=300):
    """A map change (a teleport or the age switch): sent, sent again while the game is busy (an event playing, a request in
    progress, a map loading) or when it did not take it; done once the game's state says it is in the map wanted (want(state)),
    nothing loading and no event playing (the arrival's own scene over). Returns that state"""
    line = action if isinstance(action, str) else "!cheat %d" % action   # (or a "!teleport <map> <start>" line)
    if g.dry:
        g.note(line)
        return {"map": "?"}
    start, end = g.frame, time.monotonic() + limit_s
    poll = Poll(g)
    state, again_at = "send", 0
    busy_since, unstick_at, unstick, refused = None, 0, 0, 0
    while True:
        if state == "send" and g.frame >= again_at:
            g.send(line)
            state, again_at = "wait", g.frame + 600   # (no answer in 10 s of game time: the action was not read, again)
        elif state == "wait" and g.frame >= again_at:
            state = "send"
        lines = g.tick()
        for line in lines:
            said = line.split("cheats: ", 1)[1] if "cheats: " in line else ""
            if said.startswith("teleport") and ("ignored" in said or "waits until" in said or "unavailable" in said):
                state, again_at = "send", g.frame + 30   # (busy: again in half a second of game time)
                if "waits until" in said:   # (an event: one the tour started, a conversation or a prompt, may wait for a button)
                    busy_since = g.frame if busy_since is None else busy_since
                    if g.frame - busy_since > 240 and g.frame >= unstick_at:
                        g.send(UNSTICK[unstick % len(UNSTICK)])
                        unstick, unstick_at = unstick + 1, g.frame + 60
            elif "has no " in said or "age toggle undone" in said or "request not built" in said:
                raise Failed("the game refused: " + said)
            elif said.startswith("teleport ") and "request sent" in said and said.rstrip().endswith("result 0"):
                refused += 1   # (the event manager did not take it: in the Haunted Wasteland it never does)
                if refused >= 5:
                    raise Failed("the game did not take map change %s five times" % action)
                state, again_at = "send", g.frame + 120
            elif said.startswith("teleport ") and "request sent" in said:
                state, again_at = "sent", g.frame + 900
        if state == "sent":
            poll.step(lines)
            st = poll.new
            if st and want(st) and not st["loading"] and not st["event"]:
                return st
            if st and g.frame >= again_at and not st["reserved"] and not st["loading"] and not want(st):
                g.note("not taken (%s): again" % st)   # (sent between two events of a cutscene: the game let it go)
                state, again_at = "send", g.frame
        if g.frame - start > limit_frames or time.monotonic() > end:
            raise Failed("map change %s: not done after %d frames (%s, last state %s)" % (action, g.frame - start, state,
                                                                                            poll.last))


# The opening's scenes skipped (which of these does it was not narrowed down: together they took a run to control at frame ~12500
# instead of ~21100, at the cost of ~180 of the opening's own pipelines, which the part that watches it whole still finds)
SKIP = presses([(0, "PLUS/1200"), (1.4, "MINUS/300"), (1.9, "B/700"), (2.8, "X")])
SKIP_EVERY = 216


def new_game(g, limit_s=1200, skip=False):
    """From no save: A at the title until New Game starts, then through the opening (A now and then: its text), until the game's
    state says Link is in a map with no event playing and nothing loading, three times in a row a second apart: control.
    Returns the phases' (frame, s)"""
    phases = {}
    if g.dry:
        g.note("new game")
        return phases
    end = time.monotonic() + limit_s
    title = False
    next_a, next_skip, calm = 0, 0, 0
    poll = Poll(g)
    while calm < 3:
        lines = g.tick()
        if g.draws >= 15 and not title:
            title = True
            phases["title"] = (g.frame, round(g.now(), 1))
            g.note("title")
        if title:
            poll.step(lines)
            st = poll.new
            if st:
                if "player" not in phases:
                    phases["player"] = (g.frame, round(g.now(), 1))
                    g.note("Link is there: %s" % st)
                calm = calm + 1 if st["map"] and not st["event"] and not st["loading"] else 0
            if g.frame >= next_a:
                g.send("0:A/100")
                next_a = g.frame + 45
            if skip and "player" in phases and g.frame >= next_skip:
                g.send(SKIP)
                next_skip = g.frame + SKIP_EVERY
        if time.monotonic() > end:
            raise Failed("new game: %s after %d s (last state %s)" % ("no control" if title else "no title", limit_s, poll.last))
    phases["control"] = (g.frame, round(g.now(), 1))
    g.note("control: %s" % poll.last)
    return phases


# ---- a run to watch (Linux, Sway): a window on the test workspace ----

def sway(*args):
    return subprocess.run(["swaymsg"] + list(args), capture_output=True, text=True).stdout


def sway_nodes():
    try:
        stack = [json.loads(sway("-t", "get_tree") or "{}")]
    except ValueError:
        return
    while stack:
        node = stack.pop()
        yield node
        stack += node.get("nodes", []) + node.get("floating_nodes", [])


def sway_window(pid, limit=120):
    """The rect of the game's window (x, y, w, h), once Sway has it; None without"""
    end = time.monotonic() + limit
    while time.monotonic() < end:
        for node in sway_nodes():
            if node.get("pid") == pid:
                r = node["rect"]
                return r["x"], r["y"], r["width"], r["height"]
        time.sleep(0.25)
    return None


class Watch:
    """--window: the game's window moved to the test workspace (the focus given back), floating at 16:9 as wide as that output
    is. The move is checked (a window not yet mapped ignores it) and tried again. (No recording of the screen region: a window
    the desktop's user moves leaves the region on whatever is there)"""
    def __init__(self, g, workspace, slot=0):
        before = next((n.get("id") for n in sway_nodes() if n.get("focused")), None)
        if not sway_window(g.proc.pid):
            g.note("no window found to move")
            return
        try:
            out = next(w["rect"] for w in json.loads(sway("-t", "get_workspaces")) if str(w.get("num")) == str(workspace))
        except (ValueError, StopIteration):
            out = None
        rect = None
        for _ in range(40):
            if out:
                w = out["width"] - out["width"] % 16
                h = w * 9 // 16
                y = out["y"] + slot * h if out["height"] >= 2 * h else out["y"] + (out["height"] - h) // 2
                sway("[pid=%d] move container to workspace %s, floating enable, resize set %d %d, move absolute position %d %d" % (
                    g.proc.pid, workspace, w, h, out["x"], y))
            else:
                sway("[pid=%d] move container to workspace %s" % (g.proc.pid, workspace))
            time.sleep(0.5)
            rect = sway_window(g.proc.pid, 5)
            if rect and (not out or (out["x"] <= rect[0] < out["x"] + out["width"] and out["y"] <= rect[1] < out["y"] + out["height"])):
                break
        else:
            g.note("the window did not move to workspace %s" % workspace)
        if before is not None:
            sway("[con_id=%d] focus" % before)
        g.note("window at %s on workspace %s" % (rect, workspace))
    def stop(self):
        pass


# ---- a run ----

def set_ini(path, pairs):
    """The options file with these keys set: the original's text, to put back"""
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    lines = (old or "").splitlines()
    for key, value in pairs:
        for k, line in enumerate(lines):
            if line.split("=", 1)[0] == key:
                lines[k] = "%s=%s" % (key, value)
                break
        else:
            lines.append("%s=%s" % (key, value))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return old


def write_report(run_dir, rows, meta):
    total = rows[-1]["pipelines"] if rows else 0
    out = ["pipeline tour %s%s: %d pipelines, %d programs (the program cache holds %s), %.0f s, %s frames%s" % (
        meta["name"], "" if meta.get("completed", True) else " (NOT COMPLETED: %s)" % meta.get("error"), total,
        rows[-1]["programs"] if rows else 0, meta.get("program_cache") or "?", meta["seconds"], meta.get("frames", "?"),
        ", game speed %.1fx at %.0f fps (medians)" % (meta["speed"], meta.get("fps") or 0) if meta.get("speed") else "")]
    out.append("settings: %s" % " ".join("%s=%s" % kv for kv in sorted(meta["env"].items())))
    if meta.get("ini"):
        out.append("options: %s" % " ".join(meta["ini"]))
    out.append("%7s %7s %7s %7s %6s %6s %6s %6s  %s" % ("at s", "took s", "frames", "total", "new", "progs", "rss MB", "shm MB", "step"))
    for r in rows:
        mem = r.get("memory") or {}
        out.append("%7.0f %7.1f %7d %7d %6d %6d %6s %6s  %s" % (r["seconds"], r.get("took", 0), r.get("frames", 0), r["pipelines"],
                                                             r["new"], r["programs"], mem.get("rss", "-"), mem.get("shmem", "-"),
                                                             r["stop"]))
    text = "\n".join(out) + "\n"
    with open(os.path.join(run_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stops": rows}, f, indent=1)
    return text


def run(args):
    a = actions()
    steps = route(a, args.part, args.stops, args.first)
    run_dir = os.path.join(os.path.abspath(args.out), args.name)
    os.makedirs(run_dir, exist_ok=True)
    env = dict(BASE_ENV)
    if args.window:   # (a window: no headless run, the window's size)
        env.pop("HOS_HEADLESS", None)   # (the output stays 640x360, scaled into the window)
        env["HOS_WINDOW_SIZE"] = args.window
        env["HOS_WINDOW_NOACTIVATE"] = "1"
    for kv in args.env:
        k, _, v = kv.partition("=")
        if v == "-":
            env.pop(k, None)
        else:
            env[k] = v
    game = os.path.abspath(args.game)
    tool = state_tool()
    aside = os.path.join(game, ".pipeline_tour_aside")
    data = os.path.join(run_dir, "data")
    old_ini = None
    if not args.dry_run:
        if os.path.exists(aside):
            raise SystemExit("pipeline_tour: %s exists (an earlier run did not end): put its files back first" % aside)
        os.makedirs(aside)
        for name in STATE_FILES:
            if os.path.exists(os.path.join(game, name)):
                os.replace(os.path.join(game, name), os.path.join(aside, name))
        shutil.rmtree(data, ignore_errors=True)
        os.makedirs(data)   # (no save: the run makes its own)
        ini = dict(BASE_INI)
        ini.update(kv.split("=", 1) for kv in args.ini)
        old_ini = set_ini(os.path.join(game, "hookshot_options.ini"), sorted(ini.items()))
    rows, seen = [], set()
    if not any(kv.startswith("RX_VK_SHOTS=") for kv in args.env):   # (--env RX_VK_SHOTS=-: none)
        env["RX_VK_SHOTS"] = os.path.join(run_dir, "shots")
    if not args.dry_run and env.get("RX_VK_SHOTS"):
        os.makedirs(env["RX_VK_SHOTS"], exist_ok=True)
    if not args.dry_run and hasattr(os, "sched_setaffinity"):   # (the game inherits them)
        if args.cpus:
            os.sched_setaffinity(0, cpu_list(args.cpus))
        os.nice(max(0, args.nice - os.nice(0)))
    g = Game(game, data, run_dir, env, args.dry_run)
    g.actions = a
    watch = Watch(g, args.workspace, args.slot) if args.window and not args.dry_run else None
    error = None
    mark = [0.0, 0]
    misses = acts = 0
    dived = False

    def count(label):
        nonlocal seen
        n, progs, recs = list_counts(tool, g.list_path) if not args.dry_run else (0, 0, set())
        rows.append({"stop": label, "seconds": round(g.now(), 1), "took": round(g.now() - mark[0], 1), "frames": g.frame - mark[1],
                     "pipelines": n, "programs": progs, "new": len(recs - seen), "memory": g.memory() if not g.dry else {}})
        seen |= recs
        g.note("%s: %d pipelines (+%d), %d programs" % (label, n, rows[-1]["new"], progs))
        mark[0], mark[1] = g.now(), g.frame

    try:
        for step in steps:
            kind = step[0]
            if kind == "newgame":
                phases = new_game(g, skip=args.skip_opening)
                count("new game: title, opening, Link's house")
                rows[-1]["phases"] = phases
            elif kind == "items":
                for n in items_unlock(a):   # (one a live poll: the game keeps the last action a poll read, host/nn_hid.c)
                    g.send("!cheat %d" % n)
                    if not g.dry:
                        time.sleep(0.07)
                g.frames(30)
                count("every item")
            elif kind == "press":
                g.send(step[1])
                g.frames(int(step[2] * FPS))
                g.settle(30, 120)
                count(step[3])
            elif kind == "age":
                teleport(g, a["age"], lambda st: st["age"] == "adult")
                count("age switched: adult")
            elif kind == "extra":
                _, label, banc, start_pos, age = step
                try:
                    where = teleport(g, "!teleport %s %s" % (banc, start_pos), lambda st, banc=banc: st["map"].startswith(banc),
                                     limit_frames=60 * 60 * 2)
                except Failed as e:
                    misses += 1
                    g.note("missed: %s" % e)
                    count("%s (%s): MISSED" % (label, age))
                    if misses >= 3:
                        raise Failed("three stops in a row missed: %s" % e)
                    continue
                misses = 0
                g.note("arrived: %s" % where)
                g.send(LOOK)
                g.frames(int(LOOK_SPAN * FPS))
                g.settle(150, 600)
                count("%s (%s)" % (label, age))
            elif kind == "visit":
                _, age, i, k = step
                name = a["teleports"][i][0]
                banc = a["bancs"][i][0 if age == "child" else 1]
                try:
                    where = teleport(g, a["teleport"] + i, lambda st, banc=banc, age=age: st["map"] == banc and st["age"] == age,
                                     limit_frames=60 * 60 * 2)
                except Failed as e:   # (one stop missed, said in the report; three in a row end the run)
                    misses += 1
                    g.note("missed: %s" % e)
                    count("%s (%s): MISSED" % (name, age))
                    if misses >= 3:
                        raise Failed("three stops in a row missed: %s" % e)
                    continue
                misses = 0
                g.note("arrived: %s" % where)
                if name in DIVE_AT:
                    g.send(DIVE)
                    g.frames(int(DIVE_SPAN * FPS))
                g.send(LOOK)
                g.frames(int(LOOK_SPAN * FPS))
                if name in DIVE_AT and age == "adult" and not dived:
                    dived = True
                    count("%s (%s)" % (name, age))
                    g.send(UNDERWATER_GEAR)
                    g.frames(int(GEAR_SPAN * FPS))
                    try:   # (arrived again, in the water: with the boots Link sinks to the bottom)
                        teleport(g, a["teleport"] + i, lambda st: True, limit_frames=60 * 60)
                        g.frames(300)
                        g.send(LOOK)
                        g.frames(int(LOOK_SPAN * FPS))
                        g.settle(150, 600)
                        count("%s (%s) underwater" % (name, age))
                    except Failed as e:
                        g.note("underwater missed: %s" % e)
                    g.send(BOOTS_OFF)
                    g.frames(int(BOOTS_SPAN * FPS))
                    continue
                if name in ACT_AT:
                    pick, span = pause_pick(acts)
                    acts += 1
                    g.send(pick)
                    g.frames(int(span * FPS))
                    g.send(ACT)
                    g.frames(int(ACT_SPAN * FPS))
                g.settle(150, 600)   # (on once no new pipeline came for 2.5 s of game time, 10 s at most)
                count("%s (%s)" % (name, age))
                if name in NIGHT_AT and i < dungeons_from(a):
                    g.send("!cheat %d" % (TIME_ACTION + 22))
                    g.frames(60)
                    g.send(LOOK)
                    g.frames(int(LOOK_SPAN * FPS))
                    g.settle(150, 600)
                    count("%s (%s) at night" % (name, age))
                    g.send("!cheat %d" % (TIME_ACTION + 12))
                    g.frames(60)
    except Failed as e:
        error = str(e)
        g.note("FAILED: " + error)
    finally:
        if watch:
            watch.stop()
        g.stop()
        if not args.dry_run:
            if os.path.exists(g.list_path):
                shutil.copyfile(g.list_path, os.path.join(run_dir, "states.bin"))
            for name in STATE_FILES:
                if os.path.exists(os.path.join(game, name)):
                    os.replace(os.path.join(game, name), os.path.join(run_dir, name))
                if os.path.exists(os.path.join(aside, name)):
                    os.replace(os.path.join(aside, name), os.path.join(game, name))
            os.rmdir(aside)
            if old_ini is not None:
                with open(os.path.join(game, "hookshot_options.ini"), "w", encoding="utf-8") as f:
                    f.write(old_ini)
    speed = sorted(g.speed)[len(g.speed) // 2] if g.speed else None
    fps = sorted(g.fps)[len(g.fps) // 2] if g.fps else None
    meta = {"name": args.name, "part": args.part, "seconds": round(g.now(), 1), "frames": g.frame, "env": env, "ini": args.ini,
            "completed": error is None, "error": error, "speed": speed, "fps": fps,
            "program_cache": program_cache_count(g.log_path) if not args.dry_run else None}
    print(write_report(run_dir, rows, meta), end="")
    return 0 if error is None else 1


def cpu_list(text):
    """"0-3,12-15" -> {0, 1, 2, 3, 12, 13, 14, 15}"""
    out = set()
    for piece in text.split(","):
        lo, _, hi = piece.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out


def program_cache_count(log_path):
    """The programs the program cache holds, as the run's start logged them"""
    try:
        text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    m = re.findall(r"vk: precompile: (\d+) programs", text)
    return int(m[-1]) if m else None


def chunks(a, part, size):
    """A part's stops in runs of `size` (a fresh game each: one game's memory grows by about 1 GB an area and is not given back):
    [(first stop's label or None, stops)]. The opening part, or size 0: one run"""
    plan = plan_stops(a, part)
    if not plan or not size:
        return [(None, None)]
    return [("%s (%s)" % (a["teleports"][plan[k][1]][0], plan[k][0]), min(size, len(plan) - k)) for k in range(0, len(plan), size)]


def tour(args):
    """The parts at once, each in a reflinked copy of the game folder and in runs of --chunk stops one after another, then merged"""
    import threading
    a = actions()
    parts = args.parts.split(",")
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    t0 = time.monotonic()
    copies = {part: os.path.abspath(args.game).rstrip("/") + "-tour-" + part for part in parts}
    for copy in copies.values():   # (all copies first: the parts start together)
        if not os.path.exists(copy):
            subprocess.run(["cp", "-a", "--reflink=always", os.path.abspath(args.game), copy], check=True)
    print("tour %s: game folders copied in %.0f s" % (args.name, time.monotonic() - t0), flush=True)
    results, running, lock = [], [], threading.Lock()

    def part_runs(part):
        for k, (first, stops) in enumerate(chunks(a, part, args.chunk)):
            name = "%s-%s" % (args.name, part) + ("-%d" % k if first else "")
            cmd = [sys.executable, "-I", os.path.abspath(__file__), "run", "--game", copies[part], "--out", out, "--name", name,
                   "--part", part] + sum((["--env", e] for e in args.env), []) + sum((["--ini", i] for i in args.ini), [])
            if first:
                cmd += ["--first", first, "--stops", str(stops)]
            if part != "opening" and ("opening" in parts or (part != parts[0] and len(parts) > 1) or k):
                cmd.append("--skip-opening")   # (the opening is watched whole once: by its own part, else by the first)
            if args.cpus:   # (the tour's CPUs shared out between the parts)
                cmd += ["--cpus", ",".join(map(str, sorted(cpu_list(args.cpus))[parts.index(part)::len(parts)]))]
            if args.window:   # (each part in a window, one under the other)
                cmd += ["--window", args.window, "--slot", str(parts.index(part))]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            with lock:
                running.append(p)
            text = p.communicate()[0]
            with lock:
                running.remove(p)
                print(text, end="", flush=True)
                results.append((part, os.path.join(out, name), p.returncode))

    threads = [threading.Thread(target=part_runs, args=(part,), daemon=True) for part in parts]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:   # (stopped: each run ends its game and puts its files back first)
        with lock:
            for q in running:
                q.send_signal(signal.SIGINT)
        for t in threads:
            t.join()
        raise
    if not args.keep:
        for copy in copies.values():
            shutil.rmtree(copy, ignore_errors=True)
    rc = 0 if all(code == 0 for _, _, code in results) else 1
    order = sorted(results, key=lambda r: (parts.index(r[0]), r[1]))
    have = [os.path.join(d, "states.bin") for _, d, _ in order if os.path.exists(os.path.join(d, "states.bin"))]
    merged = os.path.join(out, "%s.bin" % args.name)
    if have:
        merge(argparse.Namespace(out=merged, lists=have))
    if args.publish and have and (not rc or args.publish_partial):
        rc = publish(have, [d for _, d, _ in order], parts)
    elif args.publish:
        print("tour %s: not published (a run failed or made no list: --publish-partial publishes anyway)" % args.name)
    print("tour %s: %.0f s in all, parts %s, %d runs%s" % (args.name, time.monotonic() - t0, ",".join(parts), len(results),
                                                         "" if not rc else " (a run failed)"))
    return rc


def publish(lists, run_dirs, parts, sources=None):
    """nx2/pipeline_states.py tour: the repository's tour list replaced by these, its note from what the runs logged"""
    gpu = build = ""
    settings, minutes = {}, 0.0
    for d in run_dirs:
        try:
            log = open(os.path.join(d, "log.txt"), encoding="utf-8", errors="replace").read()
            meta = json.load(open(os.path.join(d, "report.json"), encoding="utf-8"))["meta"]
        except (OSError, ValueError, KeyError):
            continue
        m = re.search(r"vk: (.+?), Vulkan [\d.]+, driver (\S+); mesh shaders", log)
        gpu = gpu or (m and "%s (driver %s)" % (m.group(1), m.group(2))) or ""
        m = re.search(r"hookshot (v\S+(?: \(source \w+\))?)", log)
        build = build or (m and m.group(1)) or ""
        settings = settings or {k: v for k, v in meta.get("env", {}).items() if k.startswith(("HOS_OUTPUT", "HOS_FPS", "RX_VK"))}
        minutes += meta.get("seconds", 0) / 60
    ini = " ".join("%s=%s" % kv for kv in sorted(BASE_INI.items()))
    cmd = [sys.executable, "-I", os.path.join(ROOT, "nx2", "pipeline_states.py"), "tour"] + lists + [
        "--gpu", gpu or "unknown", "--build", build or "unknown",
        "--settings", ini + " " + " ".join("%s=%s" % kv for kv in sorted(settings.items())),
        "--route", "scripts/pipeline_tour.py, parts %s, from a new save (%.0f minutes of runs)" % (", ".join(parts), minutes)]
    if sources:
        cmd += ["--dir", sources]
    return subprocess.run(cmd).returncode


def merge(args):
    """The lists merged by nx2/pipeline_states.py (its format, whatever it is), and how much each added"""
    tool = state_tool()
    seen = set()
    for path in args.lists:
        n, progs, recs = list_counts(tool, path)
        print("%s: %d pipelines, %d programs, %d not in the lists before it" % (path, n, progs, len(recs - seen)))
        seen |= recs
    ran = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "nx2", "pipeline_states.py"), "--out", args.out] + args.lists)
    return ran.returncode


def report(args):
    with open(os.path.join(args.run, "report.json"), encoding="utf-8") as f:
        r = json.load(f)
    print(write_report(args.run, r["stops"], r["meta"]), end="")
    return 0


def stopped(signum, frame):
    raise KeyboardInterrupt   # (SIGTERM as SIGINT: the run's finally ends the game and puts the game folder's files back)


def main(argv=None):
    signal.signal(signal.SIGTERM, stopped)
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--game", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--name", default="play")
    r.add_argument("--part", choices=PARTS, default="all")
    r.add_argument("--cpus", help="the CPUs the game may use (Linux), e.g. 0-3,12-15")
    r.add_argument("--nice", type=int, default=5, help="the game's niceness (default 5: the desktop stays responsive)")
    r.add_argument("--stops", type=int, help="only the first N stops")
    r.add_argument("--first", metavar="STOP", help="start the route at this stop (its name, or \"<name> (<age>)\"): after a failure")
    r.add_argument("--env", action="append", default=[], help="NAME=VALUE over the run's switches (NAME=- drops one)")
    r.add_argument("--ini", action="append", default=[], help="key=value in hookshot_options.ini for the run")
    r.add_argument("--window", metavar="WxH", help="a window (on a Sway workspace) instead of the headless run")
    r.add_argument("--workspace", default="10", help="the Sway workspace the window goes to (default 10)")
    r.add_argument("--slot", type=int, default=0, help="with --window: the window's place on the workspace, one under the other")
    r.add_argument("--skip-opening", action="store_true", help="skip the opening's scenes once Link is there")
    r.add_argument("--dry-run", action="store_true", help="the steps, without the game")
    t = sub.add_parser("tour")
    t.add_argument("--game", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--name", default="play")
    t.add_argument("--parts", default="opening,child-overworld,dungeons,adult-overworld")
    t.add_argument("--cpus", default="0-3,12-15", help="the CPUs the tour may use, shared out between its parts")
    t.add_argument("--env", action="append", default=[])
    t.add_argument("--ini", action="append", default=[])
    t.add_argument("--keep", action="store_true", help="keep the parts' game folder copies")
    t.add_argument("--chunk", type=int, default=8, help="stops a game, then a fresh one (one game grows ~1 GB an area); 0: no limit")
    t.add_argument("--publish-partial", action="store_true", help="--publish even when a run failed")
    t.add_argument("--window", metavar="WxH", help="each part in a window (on Sway workspace 10)")
    t.add_argument("--publish", action="store_true",
                   help="write the repository's tour list (assets/pipeline_states/tour.bin.xz and tour.md) from the parts' lists")
    m = sub.add_parser("merge")
    m.add_argument("--out", required=True)
    m.add_argument("lists", nargs="+")
    s = sub.add_parser("report")
    s.add_argument("run")
    a = p.parse_args(argv)
    return {"run": run, "tour": tour, "merge": merge, "report": report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
