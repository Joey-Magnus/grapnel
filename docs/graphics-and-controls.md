# Graphics and controls

Press **F1** or, by default, **Insert** to open the menu. On a controller, use Home or Select + Start; a DualShock 4
or DualSense touchpad click also opens it. Options are saved in `hookshot_options.ini` in the game folder.

Rows marked **After restart** take effect when the game starts again. Save your progress before choosing
**Restart now**. Some rows only appear when the build, GPU and driver support them.

## Follow the picture through the settings

| Setting | What it controls |
|---|---|
| Render resolution | How many pixels the game draws for the 3D scene. Auto allows dynamic resolution. |
| Upscaler | How the 3D scene reaches the output size: the game's own, DLSS/DLAA, or an available FSR mode. |
| Output resolution | The size of the whole game frame, including the HUD. |
| Window scaling filter | Scaling from that whole frame to the window, when the two sizes differ. |
| Sharpness | The sharpening applied to the resulting picture. |

The [reference manual](../readme.md#in-game-menu) lists supported sizes, modes, hardware requirements and build-time
SDK requirements. An unavailable upscaler does not necessarily mean your installation is broken.

## Frame rate and frame generation

**Game frame rate cap** limits the frames the game renders. **Frame generation** inserts additional displayed
frames. A 60 FPS game cap with 2× frame generation can display 120 FPS without raising the game's simulation cap.

Keep the game cap at **60** for normal play while the
[above-60 timing issue](https://github.com/NotRexed/Hookshot/issues/1742) remains unresolved. Higher caps have affected
Gohma, cutscenes and other frame-counted systems. Frame generation can introduce ghosting and extra latency; switch
it off when measuring the game's performance or diagnosing artifacts.

If the HUD shimmers, see the [frame-generation answer](common-issues.md#the-hud-ghosts-or-shimmers-with-frame-generation).

## A useful starting point

Choose a quality preset suited to your GPU's memory, keep the game cap at 60, and change one setting at a time.
Compare the same route twice after preparation finishes. First-visit stutter and a slowdown that persists until
restart are different symptoms; the [common-issues page](common-issues.md) explains what to report.

On a computer with multiple GPUs, check **GPU device** and the `vk: device` entries in the log. For HDR, follow the
current reference manual's display and platform requirements rather than copying another player's numeric INI values.

## Controls

Use the Controls tab for layout and bindings, and the [controls reference](../readme.md#controls) for the current
shortcuts. Include both Hookshot's layout and the game's own control settings when reporting a mismatch. Known
Xbox/PC layout reports are linked from [Common issues](common-issues.md#controller-buttons-do-not-match-the-selected-layout).
