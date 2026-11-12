// (hookshot) The programs' life: the game's create, set-shaders and free calls, each program's first draw or dispatch, and the
// census of what play had to make. See vk_programs.h.
//
// RX_VK_LOG_PROGRAM_LIFE=1 logs each of those ("vk: program life: ...") and, every 600 presents and when the window closes, one
// census line ("vk: program census ..."). The log answers when the game makes its programs against when it first draws them:
// whether the work a first draw does today (a program read from hookshot_programs.bin, a pipeline made from the caches) could be
// done at the create call instead.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <deque>
#include <mutex>
#include <unordered_map>
#include <unordered_set>

#include "vk_internal.h"
#include "vk_draw.h"
#include "vk_shader.h"
#include "vk_programs.h"

namespace mkwvk {

ProgramCensus census;
thread_local UseCounters use_counters;
bool programs_life_flag = false;
std::atomic<bool> programs_in_play{false};

namespace {
using Clock = std::chrono::steady_clock;
const Clock::time_point life_t0 = Clock::now();
double secs(Clock::time_point t) { return std::chrono::duration<double>(t - life_t0).count(); }
double ms_between(Clock::time_point a, Clock::time_point b) { return std::chrono::duration<double, std::milli>(b - a).count(); }

std::atomic<int64_t> last_present_ns{0};   // (since life_t0; 0: none yet)
std::atomic<int64_t> game_presents{0};
int64_t now_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - life_t0).count(); }

/// A guest program between its create call and some seconds after its free call (a draw recorded before the free is replayed
/// after it)
struct Life {
    Clock::time_point created, freed;
    int64_t frame = 0;          // (the game's presents before the create call)
    double since_present = 0;   // (ms, at the create call)
    double frame_ms = -1;       // (the frame the create call was in, known at the next present)
    uint64_t codes[4]{};
    bool ok = false, compute = false, mesh = false, used = false, is_freed = false;
};
std::mutex life_mu;
std::unordered_map<uint64_t, Life> lives;          // by program serial
std::vector<uint64_t> created_this_frame;          // (their frame_ms is set at the next present)
std::atomic<int> created_pending{0};
std::deque<std::pair<Clock::time_point, uint64_t>> freed_serials;   // (let go kFreedKeepS after the free call)
constexpr double kFreedKeepS = 30.0;

const char* kind_name(const Life& l) { return l.compute ? "compute" : l.mesh ? "mesh" : "graphics"; }
} // namespace

bool programs_life_on() {
    static const bool on = env_on("RX_VK_LOG_PROGRAM_LIFE");
    programs_life_flag = on;
    return on;
}

bool programs_in_load(double* since_ms) {
    const int64_t last = last_present_ns.load(std::memory_order_relaxed);
    const double ms = last ? (now_ns() - last) / 1e6 : 0.0;   // (before the first frame: not a load anyone can see)
    if (since_ms) *since_ms = ms;
    return ms >= kLoadGapMs;
}

void programs_presented() {
    const int64_t now = now_ns();
    const int64_t prev = last_present_ns.exchange(now, std::memory_order_relaxed);
    game_presents.fetch_add(1, std::memory_order_relaxed);
    if (!created_pending.load(std::memory_order_relaxed)) return;
    const double frame_ms = prev ? (now - prev) / 1e6 : 0.0;
    std::lock_guard lk(life_mu);
    for (const uint64_t serial : created_this_frame)
        if (const auto it = lives.find(serial); it != lives.end()) it->second.frame_ms = frame_ms;
    if (frame_ms >= kLoadGapMs) census.created_long_frame += (int64_t)created_this_frame.size();
    created_this_frame.clear();
    created_pending = 0;
}

void programs_play_begin() {
    programs_life_on();
    programs_in_play = true;
}

void programs_created(const nvn_prog* p) {
    if (!p || !programs_life_on()) return;
    const auto t0 = Clock::now();
    double since = 0;
    const bool in_load = programs_in_load(&since);
    const CreatedProgram made = program_created_read(*p);
    Life l;
    l.created = t0, l.frame = game_presents.load(std::memory_order_relaxed), l.since_present = since;
    std::memcpy(l.codes, made.codes, sizeof l.codes);
    l.ok = made.ok, l.compute = made.compute, l.mesh = made.mesh;
    const auto t1 = Clock::now();
    census.created++, census.created_ok += made.ok, census.created_in_load += in_load;
    census.create_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
    logf("vk: program life: create serial %llx t %.3f frame %lld since_present_ms %.1f in_load %d kind %s stages %d codes "
         "%016llx %016llx %016llx %016llx read_us %.0f",
         (unsigned long long)p->serial, secs(t0), (long long)l.frame, since, (int)in_load, made.ok ? kind_name(l) : "none",
         made.stages, (unsigned long long)l.codes[0], (unsigned long long)l.codes[1], (unsigned long long)l.codes[2],
         (unsigned long long)l.codes[3], ms_between(t0, t1) * 1000.0);
    std::lock_guard lk(life_mu);
    lives[p->serial] = l;
    created_this_frame.push_back(p->serial);
    created_pending = 1;
}

void programs_freed(const nvn_prog* p) {
    if (!p || !p->serial || !programs_life_on()) return;
    const auto now = Clock::now();
    program_created_forget(p->serial);
    std::lock_guard lk(life_mu);
    while (!freed_serials.empty() && std::chrono::duration<double>(now - freed_serials.front().first).count() > kFreedKeepS) {
        lives.erase(freed_serials.front().second);
        freed_serials.pop_front();
    }
    const auto it = lives.find(p->serial);
    if (it == lives.end() || it->second.is_freed) return;   // (one made before the back end started, or freed twice)
    Life& l = it->second;
    l.is_freed = true, l.freed = now;
    freed_serials.push_back({now, p->serial});
    census.freed++, census.freed_undrawn += !l.used;
    logf("vk: program life: free serial %llx t %.3f frame %lld age_ms %.1f used %d", (unsigned long long)p->serial, secs(now),
         (long long)game_presents.load(std::memory_order_relaxed), ms_between(l.created, now), (int)l.used);
}

void ProgramUse::begin(const nvn_prog& prog, bool is_compute) {
    static thread_local uint64_t last_serial[2];
    static thread_local std::unordered_set<uint64_t> seen;
    if (prog.serial == last_serial[is_compute]) return;
    last_serial[is_compute] = prog.serial;
    if (!seen.insert(prog.serial).second) return;
    on = true, compute = is_compute, serial = prog.serial;
    before = use_counters;
    translated0 = shader_translated();
    t0 = Clock::now();
}

void ProgramUse::end() {
    const auto t1 = Clock::now();
    NeedProgram np = NeedProgram::Ready;
    if (!p || p->failed) np = NeedProgram::Failed;
    else if (!program_ready || shader_translated() != translated0) np = NeedProgram::Translated;
    else if (use_counters.loads != before.loads) np = NeedProgram::Loaded;
    NeedPipeline pp = NeedPipeline::None;
    if (left_out) pp = NeedPipeline::LeftOut;
    else if (has_pipe && pipe_was_ready && !pipe_new) pp = NeedPipeline::Ready;
    else if (has_pipe)
        pp = pipe_how == 1 || pipe_how == 2 ? NeedPipeline::Cache : pipe_how == 3 ? NeedPipeline::Compiled : NeedPipeline::Made;
    static const char* const prog_names[] = {"ready", "loaded", "translated", "failed"};
    static const char* const pipe_names[] = {"none", "ready", "cache", "compiled", "made", "left_out"};
    const bool needy = np == NeedProgram::Loaded || np == NeedProgram::Translated || pp == NeedPipeline::Cache ||
                       pp == NeedPipeline::Compiled || pp == NeedPipeline::Made || pp == NeedPipeline::LeftOut;
    Life l;
    bool known = false;
    {
        std::lock_guard lk(life_mu);
        const auto it = lives.find(serial);
        if (it != lives.end()) {
            if (it->second.used) return;   // (another thread's first use of it came first)
            it->second.used = true;
            l = it->second, known = true;
        }
    }
    census.used++;
    (np == NeedProgram::Ready ? census.used_ready : np == NeedProgram::Loaded ? census.used_loaded
     : np == NeedProgram::Translated ? census.used_translated : census.used_failed)++;
    (pp == NeedPipeline::None ? census.pipe_none : pp == NeedPipeline::Ready ? census.pipe_ready
     : pp == NeedPipeline::Cache ? census.pipe_cache : pp == NeedPipeline::Compiled ? census.pipe_compiled
     : pp == NeedPipeline::Made ? census.pipe_made : census.pipe_left_out)++;
    const uint64_t* codes = p ? p->codes : nullptr;
    if (!known) {
        census.used_unknown++;
        logf("vk: program life: first %s serial %llx t %.3f created unknown program %s pipeline %s ms %.2f key %016llx variant "
             "%016llx", compute ? "dispatch" : "draw", (unsigned long long)serial, secs(t0), prog_names[(int)np],
             pipe_names[(int)pp], ms_between(t0, t1), (unsigned long long)(p ? p->key : 0), (unsigned long long)(p ? p->variant : 0));
        return;
    }
    const double after = ms_between(l.created, t0);
    (after < 16.7 ? census.after_16 : after < 100.0 ? census.after_100 : after < 1000.0 ? census.after_1000 : census.after_more)++;
    // (the stages a draw reads are those of the create call: the keys of the program it drew with)
    const bool same = !codes || !codes[0] || !l.ok ||
                      (codes[0] == l.codes[0] && (l.compute || (codes[1] == l.codes[1] && codes[2] == l.codes[2])));
    census.used_codes_differ += !same;
    const bool long_frame = l.frame_ms >= kLoadGapMs;
    if (needy) census.needy++, census.needy_after_100 += after >= 100.0, census.needy_in_load += l.since_present >= kLoadGapMs || long_frame;
    logf("vk: program life: first %s serial %llx t %.3f after_create_ms %.1f create_since_present_ms %.1f create_frame_ms %.1f "
         "codes_same %d program %s pipeline %s ms %.2f key %016llx variant %016llx freed %d",
         compute ? "dispatch" : "draw", (unsigned long long)serial, secs(t0), after, l.since_present, l.frame_ms, (int)same,
         prog_names[(int)np], pipe_names[(int)pp], ms_between(t0, t1), (unsigned long long)(p ? p->key : 0),
         (unsigned long long)(p ? p->variant : 0), (int)l.is_freed);
}

void programs_census_log(const char* when) {
    if (!programs_life_on()) return;
    const ProgramCensus& c = census;
    int64_t skips = 0, waits = 0;
    double wait_ms = 0;
    draw_stats3(&skips, &waits, &wait_ms);
    const auto n = [](const std::atomic<int64_t>& a) { return (long long)a.load(); };
    logf("vk: program census (%s): created %lld (%lld with stages; %lld with no present for 100 ms before, %lld in a frame of 100 ms or "
         "more; %.1f ms of the game's threads), freed %lld (%lld never used); first uses %lld: program ready %lld, loaded %lld, "
         "translated %lld, failed %lld; pipeline ready %lld, from a cache %lld, compiled %lld, made %lld, left out %lld, none %lld; "
         "%lld with no create call seen, %lld whose stages are not the create call's; after the create call: under 16.7 ms %lld, "
         "under 100 ms %lld, under 1 s %lld, longer %lld; needing work %lld (%lld of them 100 ms or more after the create call, %lld "
         "created in a load or a long frame); in play: %lld program records loaded (%.1f ms), %lld new graphics pipelines, pipelines "
         "from the driver's cache %lld, from the start's cache %lld, compiled %lld; %lld draws and dispatches left out, %lld waits "
         "(%.1f ms)",
         when, n(c.created), n(c.created_ok), n(c.created_in_load), n(c.created_long_frame), c.create_ns.load() / 1e6, n(c.freed),
         n(c.freed_undrawn), n(c.used), n(c.used_ready), n(c.used_loaded), n(c.used_translated), n(c.used_failed), n(c.pipe_ready),
         n(c.pipe_cache), n(c.pipe_compiled), n(c.pipe_made), n(c.pipe_left_out), n(c.pipe_none), n(c.used_unknown),
         n(c.used_codes_differ), n(c.after_16), n(c.after_100), n(c.after_1000), n(c.after_more), n(c.needy), n(c.needy_after_100),
         n(c.needy_in_load), n(c.play_loads), c.play_load_ns.load() / 1e6, n(c.play_pipes_new), n(c.play_from_driver),
         n(c.play_from_start), n(c.play_compiled), (long long)skips, (long long)waits, wait_ms);
}

} // namespace mkwvk
