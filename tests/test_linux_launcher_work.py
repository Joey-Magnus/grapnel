"""Game-free check of what the Linux launcher says while it builds or updates (builder/linux/launch_work.py): the rules of the
Windows launcher's LaunchWork.cs and of its menu's steps. Made-up lines of make_game.py go in; the number under the button,
the bar's words, the line under it and the steps' states come out. No window, disk or process.

python -I -B tests/test_linux_launcher_work.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "builder", "linux"))
import launch_work as lw  # noqa: E402

failed = []


def check(what, got, want):
    if got != want:
        failed.append("%s: got %r, want %r" % (what, got, want))


def states(work):
    return [(key, state, small) for key, _name, state, small in work.steps]


# ---- a build from game files ----
w = lw.Work("Building your game", back="files")
check("a build's steps", [name for _k, name, _s, _t in w.steps],
      ["Read the game files", "Translate to PC code", "Compile", "Put it together", "Prepare the shaders"])
check("before anything is said", (w.bar(), w.step_line(), w.fraction), ("Building... 0%", "Starting...", 0.0))
for line in ("build: up to 6 compilers at once", "@@stage read Reading your game files", "@@stage lift Translating", "@@progress 0.5"):
    w.line(line)
check("half way through the translation", round(w.fraction, 3), 0.125)
check("read is done, the translation is now", states(w)[:2], [("read", "done", ""), ("lift", "now", "")])
check("the line under the bar: the step under way", w.step_line(), "Translate to PC code...")
for line in ("@@stage compile Compiling", "@@plan 58 259", "@@file a.c 0 new", "@@file b.c 1 again", "@@file c.c 2 kept", "@@eta 1080",
             "@@progress 0.5"):
    w.line(line)
check("the compile's count is of the files that changed", w.step("compile")[2:], ["now", "2 of 58"])
check("half way through the compile", (round(w.fraction, 3), w.bar()), (0.55, "Building... 55%"))
check("the line under it", w.step_line(), "Compile 2 of 58 · 18 min left")
w.line("@@progress 0.2")
check("the number never goes back", round(w.fraction, 3), 0.55)
w.line("@@stage polish Something a later version says")
check("a stage with no words here moves nothing", (round(w.fraction, 3), w.says), (0.55, "Working"))
check("and the compile is done all the same", w.step("compile")[2], "done")
for line in ("@@stage finish Putting the game folder together", "@@stage shaders Preparing shaders", "@@progress 0.5", "@@times 2136 1585 0",
             "@@done /home/player/Games/Hookshot"):
    w.line(line)
check("where the game is", (w.done, w.times), ("/home/player/Games/Hookshot", (2136.0, 1585.0, 0.0)))
w.end(True)
check("done", (w.fraction, [s for _k, s, _t in states(w)]), (1.0, ["done"] * 5))
check("every line is kept for the details", len(w.log), 18)

# ---- the shaders' step left to the game's first start ----
w = lw.Work("Building your game", shaders=False, not_prepared="the shaders were not prepared")
check("no shaders step", [k for k, _s, _t in states(w)], ["read", "lift", "compile", "finish"])
w.line("the shaders were not prepared now: the game prepares them at its first start")
check("and it says so", w.shaders_later, True)

# ---- a compile with nothing to do ----
w = lw.Work("Updating to v2.1.0", update=True)
check("an update's steps", [name for _k, name, _s, _t in w.steps][::3], ["Read the kept files", "Swap in the game"])
w.line("@@stage compile Compiling")
w.line("@@plan 0 259")
check("everything already built", w.step("compile")[3], "Already built")
check("an update's bar", w.bar(), "Updating... 20%")
check("a switch's bar", lw.Work("Switching to v2.0.14", update=True).bar(), "Switching... 0%")

# ---- it stops ----
w = lw.Work("Building your game")
for line in ("@@stage read x", "@@stage lift x", "@@stage compile x", "clang: error: unable to execute command: Killed",
             "@@error The compiler stopped on code_006.c"):
    w.line(line)
w.end(False)
check("why it stopped", w.error, "The compiler stopped on code_006.c")
check("the step it stopped in", states(w)[2][:2], ("compile", "stopped"))
check("what the stopped state says", w.stopped_title(), "The build stopped")
check("an update's", lw.Work("Updating to v2.1.0", update=True).stopped_title(), "The update to v2.1.0 stopped")
check("a switch back's", lw.Work("Switching to v2.0.14", update=True).stopped_title(), "The switch to v2.0.14 stopped")

# ---- a version whose builder is downloaded first ----
w = lw.Work("Updating to v2.1.0", update=True, fetch=True)
check("its first step", (w.steps[0][:3], w.step_line()), (["download", "Get its builder", "now"], "Getting its builder..."))
w.note("Downloading part 3 of 6 (310 MB)...")
check("part 3 of 6: a third of the download's share", (round(w.fraction, 3), w.says), (0.04, "Getting its builder: downloading part 3 of 6 (310 MB)"))
w.fetched()
check("the builder is here", (round(w.fraction, 3), w.steps[0][2]), (0.12, "done"))
w.line("@@stage compile x")
w.line("@@progress 1")
check("the build's share comes after the download's", round(w.fraction, 3), round(0.12 + 0.88 * 0.9, 3))

# ---- under an update's bar: that it is a rebuild, then the step and the time left ----
w = lw.Work("Updating to v2.2.0", update=True)
w.started = 1000.0
w.line("@@stage lift x")
check("before the compile: what a build took here, less the time gone", w.under_bar(1800, now=1600.0),
      "Rebuilding your game as v2.2.0\nTranslate to PC code · 20 min left")
check("no build kept: no time guessed", w.under_bar(None, now=1600.0), "Rebuilding your game as v2.2.0\nTranslate to PC code...")
check("past the usual time: no time guessed", w.under_bar(1800, now=2750.0), "Rebuilding your game as v2.2.0\nTranslate to PC code...")
w.line("@@stage compile x")
check("the compile before its own time", w.under_bar(1800, now=1600.0), "Rebuilding your game as v2.2.0\nCompile · 20 min left")
w.line("@@eta 190")
check("the compile's own time wins", w.under_bar(1800, now=1600.0), "Rebuilding your game as v2.2.0\nCompile · 3 min left")
check("a switch back", lw.Work("Switching to v2.0.14", update=True).rebuild_line(), "Rebuilding your game as v2.0.14")
for seconds, want in ((None, "around half an hour or more"), (1810, "about 30 minutes"), (100, "about 5 minutes"), (3900, "about 1 h 5 min"),
                      (3600, "about 1 h")):
    check("about(%r)" % seconds, lw.about(seconds), want)

# ---- how long ----
for seconds, want in ((20, "less than a minute left"), (60, "1 min left"), (1080, "18 min left"), (3900, "1 h 5 min left")):
    check("short_left(%d)" % seconds, lw.short_left(seconds), want)
for seconds, want in ((20, "less than a minute"), (70, "a minute"), (2460, "41 minutes"), (3900, "1 h 5 min")):
    check("span(%d)" % seconds, lw.span(seconds), want)

if failed:
    print("\n".join(failed))
    sys.exit(1)
print("the Linux launcher's build and update words: ok")
