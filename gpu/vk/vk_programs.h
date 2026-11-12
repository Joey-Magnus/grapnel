// (hookshot) The programs' life (vk_programs.cpp): what the game does with its programs (makes them, gives them their shaders,
// frees them), what each needed when it was first drawn or dispatched, and one set of counters for all of it (the census).
// Not part of the translator stamp: a change here keeps every player's translated programs.
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>

#include "vk_internal.h"

namespace mkwvk {

struct Program;

// ---- the game's side (its own threads) ----
/// The game gave a program its shaders (MkwVkRenderer::nvn_program_created): its stages are in the game's memory now
void programs_created(const nvn_prog* p);
/// The game frees a program, or gives it other shaders (MkwVkRenderer::nvn_program_released, before the replay hears of it)
void programs_freed(const nvn_prog* p);
/// The game presents a frame (vk_replay.cpp present, the presenting thread)
void programs_presented();
/// Whether the game seems to be in a load: no frame presented for kLoadGapMs or more. *since_ms: how long since the last one
constexpr double kLoadGapMs = 100.0;
bool programs_in_load(double* since_ms = nullptr);

// ---- the census: one set of counters, whoever does the work ----
struct ProgramCensus {
    std::atomic<int64_t> created{0}, created_ok{0}, freed{0}, freed_undrawn{0};
    std::atomic<int64_t> created_in_load{0};       // (no present for kLoadGapMs before the call)
    std::atomic<int64_t> created_long_frame{0};    // (in a frame that took kLoadGapMs or more, as the next present told)
    std::atomic<int64_t> create_ns{0};             // (the game's thread's time in the create call)
    // first uses (a program's first draw or dispatch): what the program needed
    std::atomic<int64_t> used{0}, used_ready{0}, used_loaded{0}, used_translated{0}, used_failed{0};
    std::atomic<int64_t> used_unknown{0};          // (no create call was seen for it: made before the back end started)
    std::atomic<int64_t> used_codes_differ{0};     // (the stages the draw read are not those read at the create call)
    // ... and its pipeline
    std::atomic<int64_t> pipe_ready{0}, pipe_cache{0}, pipe_compiled{0}, pipe_made{0}, pipe_left_out{0}, pipe_none{0};
    // how long after its create call the first use came
    std::atomic<int64_t> after_16{0}, after_100{0}, after_1000{0}, after_more{0};
    // ... for the first uses that needed something (a load, a translation, a pipeline made)
    std::atomic<int64_t> needy{0}, needy_after_100{0}, needy_in_load{0};
    // everything play makes, first use or not
    std::atomic<int64_t> play_loads{0}, play_load_ns{0};   // (program records read from hookshot_programs.bin in play)
    std::atomic<int64_t> play_pipes_new{0};                // (graphics pipelines play asked for that were not ready)
    std::atomic<int64_t> play_from_driver{0}, play_from_start{0}, play_compiled{0};   // (create_cached, graphics and compute)
};
extern ProgramCensus census;
/// One line of the census (every 600 presents with RX_VK_LOG_PROGRAM_LIFE=1, and when the window closes)
void programs_census_log(const char* when);
bool programs_life_on();   // (RX_VK_LOG_PROGRAM_LIFE=1)

// ---- a program's first draw or dispatch (the thread replaying), for the log and the census ----
enum class NeedProgram : uint8_t { Ready, Loaded, Translated, Failed };
enum class NeedPipeline : uint8_t { None, Ready, Cache, Compiled, Made, LeftOut };   // (Made: by another thread, how not known)
/// What vk_progcache.cpp and vk_draw.cpp count on the thread that does the work, read around a first use
struct UseCounters {
    int64_t loads = 0, load_ns = 0;   // (program records read from disk by this thread)
    int64_t pipes_new = 0;            // (pipelines this thread asked for that no one had)
    uint8_t made_how = 0;             // (the last pipeline this thread made: 1 the driver's cache, 2 the start's, 3 compiled)
};
extern thread_local UseCounters use_counters;
/// Around a draw or dispatch: reports the first use of the bound program's serial (once a serial, whichever thread). Costs one
/// compare a draw when the log is off
extern bool programs_life_flag;   // (programs_life_on, read once the back end starts)
struct ProgramUse {
    bool on = false, compute = false;
    uint64_t serial = 0;
    const Program* p = nullptr;
    std::chrono::steady_clock::time_point t0;
    UseCounters before;
    int64_t translated0 = 0;
    bool program_ready = false, pipe_new = false, pipe_was_ready = false, left_out = false, has_pipe = false;
    uint8_t pipe_how = 0;
    ProgramUse(const nvn_prog& prog, bool has_prog, bool is_compute) {
        if (programs_life_flag && has_prog) begin(prog, is_compute);
    }
    ~ProgramUse() {
        if (on) end();
    }
    void program(const Program* cp, bool ready) { p = cp, program_ready = ready; }   // (after program_for: as it came back)
    void pipeline(bool was_ready, bool is_new) { has_pipe = true, pipe_was_ready = was_ready, pipe_new = is_new; }
    void pipeline_made(uint8_t how) { pipe_how = how; }   // (how a pipeline that was not ready was made: UseCounters::made_how)
    void skipped() { left_out = true; }                   // (left out: its program or pipeline was not ready)
    void begin(const nvn_prog& prog, bool is_compute);
    void end();
};
/// (vk_main.cpp, once the start-up's work is done) what is made from now on is made in play
void programs_play_begin();
extern std::atomic<bool> programs_in_play;

} // namespace mkwvk
