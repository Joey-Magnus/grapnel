// (hookshot) The shader preparation's parts that run behind the game (vk_prepare_play.cpp; the rules in prepare_play.h): "Compile
// shaders" on Most (the default: the predicted pipelines and the compute programs' other variants behind the game) or Later (all of it
// behind the game). On All nothing here runs and the preparation is what it always was, before the game. And "When a shader isn't
// ready", the draws' choice in every mode.
#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>

#include "prepare_play.h"

namespace mkwvk {

/// The Compile shaders choice (read once, at the start: compile_shaders= in hookshot_options.ini, RX_VK_COMPILE_SHADERS over it)
prepare_play::Level prepare_level();
/// The start (vk_main.cpp started_up): Later, instead of the preparation before the game; Most, after it. True when the work behind the
/// game was started; false when there is nothing left (a folder prepared with All, or once it is all done) or the choice is All
bool prepare_play_begin();
/// The work behind the game is running now (false before it starts and once it is done: every rule here for it then stops)
bool prepare_play_running();
/// The window is being closed: the work behind the game stops, keeps what it made and where it got to (a few seconds at most)
void prepare_play_close();
/// (hookshot_prepare_play.txt) what this folder's preparation has left: -1 no record (prepared by All, or before these choices: all of
/// it), else the first part not done (prepare_play.h Part; kDone: none)
int prep_recorded();
/// (prepare_run, before the game) the programs are prepared: on Most or Later, with the compute programs not on the list at their base
/// variant, which leaves the other variants and the predicted pipelines to do
void prep_programs_prepared();
/// (vk_main.cpp, on All) what an earlier start on Most left was done before the game: the folder is all prepared
void prep_all_done();
/// Whether compute program key gets all its texture variants in the programs' part: on All every one (key 0 asks that); on Most and
/// Later those on the list of programs play dispatches (shipped, hookshot_computes_shipped.bin, and this folder's own)
bool prep_compute_every(uint64_t key);

// ---- for the preparation's own workers (vk_draw.cpp prepare_run, compute_rest_run, predict_run, state_list_prepare, warm_libraries) ----
/// A worker's start: behind the game, idle priority and the play caches left alone (pipelines go into the start's cache, as before
/// the game). Otherwise the priority it always had
void prep_thread_begin(int normal_priority);
/// How many workers to start: normal before the game; behind it, prepare_play.h workers_started (RX_VK_PREPARE_THREADS over it)
unsigned prep_threads(unsigned normal);
/// Between two items: behind the game, waits while the frame's own work is queued (jobs_pending), while memory is short, while the
/// workers allowed now (prepare_play.h workers) are taken, and while a checkpoint saves. Nothing before the game
void prep_gate();
/// Resuming: item i of a part (prepare_play.h Part) was done by an earlier start; and item i is done now
bool prep_item_skip(int phase, size_t i);
void prep_item_done(int phase, size_t i);
/// The part's item count, before its workers start (for the resume record)
void prep_phase_items(int phase, size_t n);
/// Where prepare_run writes hookshot_prepared.bin's record: on Later, behind the game, beside it (.play), moved over it once all is
/// done, so a start that ends halfway still prepares (the record says what is prepared: only all of it is)
const char* prep_record_suffix();
/// (thread-local) pipelines this thread makes go into the start's cache (pcache), not play's (create_cached)
bool prep_direct_cache();
/// The start's cache is being built into behind the game: its save waits (vkGetPipelineCacheData while pipelines are made into the
/// same cache crashed Intel's driver)
bool prep_building();

// ---- for the draws ----
/// When a shader isn't ready (the Insert menu's row, shader_miss=, RX_VK_SHADER_MISS over it): what a draw whose pipeline is not
/// ready does. skippable: its targets hold an earlier frame's picture and none of its stages writes memory
prepare_play::Act prep_miss_act(bool skippable);
/// Wait briefly's budget: what this frame has left (us), and what a wait spent of it
int64_t prep_miss_budget_left();
void prep_miss_spend(int64_t us);
/// A program or pipeline found not ready (the hold after a load waits for frames with none)
void prep_note_miss();
/// A pipeline this run makes for the first time (graphics_pipeline): for the area it was met in (learned per area)
void prep_pipeline_met(uint64_t key);
/// A present (vk_replay.cpp do_present): this frame's draws; true when it is hidden (an area's first frames held, prepare_play.h
/// Hold): not shown, the last picture stays. Only behind the game, never with frame generation, whose thread shows the frames
bool prep_present_hidden(int64_t draws, bool framegen);
/// The overlay: "Shaders: NN%" while the work behind the game runs (false otherwise)
bool prep_overlay_text(char* out, size_t n);
/// (logs) the draws left out and waited for (When a shader isn't ready), the frames held after loads
void prep_stats(int64_t* left_out, int64_t* waited, double* wait_ms, int64_t* hidden);

} // namespace mkwvk
