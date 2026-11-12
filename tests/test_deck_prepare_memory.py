"""Execute the offline precompile and object release with counted Vulkan handles."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def body(source, marker):
    start = source.index(marker)
    at = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


HEAD = r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <cstring>
#include <cstdlib>
#include <string>
#if defined(__GLIBC__)
#include <malloc.h>
#endif
using VkPipeline = uint64_t;
using VkPrimitiveTopology = int;
constexpr int VK_SUCCESS=0, VK_NULL_HANDLE=0, VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO=1;
constexpr int VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO=2, VK_SHADER_STAGE_COMPUTE_BIT=4;
struct VkComputePipelineCreateInfo {
    int sType=0;
    struct { int sType=0, stage=0; uint64_t module=0; const char* pName=nullptr; } stage;
    uint64_t layout=0;
};
struct Stage { uint64_t module=0; };
struct Program {
    uint64_t key=0, variant=0, layout=0, set_layout=0, compute_pipeline=0;
    bool compute=false, fallback=false;
    int workgroup[3]{32,1,1};
    std::vector<Stage> stages;
    std::vector<VkPipeline> fallback_compute;
};
struct { int device=1; } dev;
std::atomic<int> alive{0}, peak{0}, graphics{0}, computes{0};
bool fake_deck=true;
bool env_on(const char*) { return fake_deck; }
uint64_t handle() {
    int n=++alive, p=peak;
    while(n>p && !peak.compare_exchange_weak(p,n)) {}
    return 1;
}
void vkDestroyPipeline(int, uint64_t h, void*) { assert(h); --alive; }
void vkDestroyShaderModule(int, uint64_t h, void*) { assert(h); --alive; }
void vkDestroyPipelineLayout(int, uint64_t h, void*) { assert(h); --alive; }
void vkDestroyDescriptorSetLayout(int, uint64_t h, void*) { assert(h); --alive; }
std::mutex shader_mu, disk_mu;
std::unordered_map<uint64_t,std::vector<std::unique_ptr<Program>>> programs;
struct Record { int kind; };
std::unordered_map<uint64_t,std::vector<Record>> disk_records, disk_taken;
void disk_init() {}
void program_cache_load(uint64_t key, std::vector<std::unique_ptr<Program>>& out, bool) {
    for (int v=0; v<2; v++) {
        auto p=std::make_unique<Program>(); p->key=key; p->variant=v;
        p->compute=key==1001; p->fallback=key==1002;
        p->stages.push_back({handle()}); out.push_back(std::move(p));
    }
}
'''

DRAW_HEAD = r'''
thread_local bool driver_cache_only=false;
struct PipeNote { uint64_t prog=0, variant=0; int s=0, topo=0; };
void ensure_layout(Program& p) { p.layout=handle(); p.set_layout=handle(); }
void pin_subgroup(auto&, int) {}
int cached_compute(const VkComputePipelineCreateInfo* ci, VkPipeline* made) {
    assert(ci->layout && ci->stage.module); *made=handle(); computes++; return VK_SUCCESS;
}
void fallback_compute_pipelines(Program& p) { p.fallback_compute.push_back(handle()); }
int note_targets(const PipeNote&) { return 0; }
VkPrimitiveTopology pipeline_topology(const Program&, int) { return 77; }
VkPipeline build_graphics(Program& p, int, int, VkPrimitiveTopology topo) {
    assert(driver_cache_only && p.layout && p.set_layout && topo==77); graphics++; return handle();
}
std::unordered_set<uint64_t> computes_read() { return {1001}; }
void ub_thread_off() {}
bool prepare_stopped() { return false; }
unsigned usable_cpus() { return 128; }
unsigned batch_count=1, batch_index=0;
void select_batch(unsigned index,unsigned count) {
#ifdef _WIN32
    _putenv_s("HOOKSHOT_DECK_BATCH_COUNT",std::to_string(count).c_str());
    _putenv_s("HOOKSHOT_DECK_BATCH_INDEX",std::to_string(index).c_str());
#else
    setenv("HOOKSHOT_DECK_BATCH_COUNT",std::to_string(count).c_str(),1);
    setenv("HOOKSHOT_DECK_BATCH_INDEX",std::to_string(index).c_str(),1);
#endif
}
void Sleep(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void prepare_progress_log(const char*,size_t,size_t,auto,auto&) {}
void logf(const char*,...) {}
size_t reported=0, total_reported=0;
void progress(size_t done,size_t total) { reported=done; total_reported=total; }
'''

MAIN = r'''
int main() {
    // Loaded programs are freed, but their borrowed disk records become readable again.
    program_cache_load(9, programs[9], true);
    for(auto& p:programs[9]) {
        ensure_layout(*p); p->compute_pipeline=handle(); p->fallback_compute.push_back(handle());
    }
    disk_taken[9].push_back({0});
    program_cache_release_loaded();
    assert(alive==0 && programs.empty() && disk_taken.empty() && disk_records[9].size()==1);
    disk_records.clear();
    std::vector<std::unique_ptr<PipeNote>> notes;
    for(uint64_t key=1;key<=300;key++) {
        disk_records[key].push_back({0});
        for(uint64_t v=0;v<2;v++) notes.push_back(std::make_unique<PipeNote>(PipeNote{key,v}));
    }
    disk_records[1001].push_back({1}); // compute, selected by its dispatch record
    disk_records[1002].push_back({4}); // fallback, selected even without graphics notes
    disk_records[1003].push_back({0}); // unused graphics must stay on disk
    disk_taken[1001].push_back({1});   // a repeated key must be borrowed once
    peak=0;
    size_t all_done=0, all_total=0;
    for (batch_count=8,batch_index=0; batch_index<batch_count; batch_index++) {
        select_batch(batch_index,batch_count); precompile_stream(notes,progress);
        all_done+=reported; all_total+=total_reported;
    }
    assert(alive==0 && peak<=32);      // four workers, independent of the 302 groups
    assert(graphics==600 && computes==2);
    assert(reported==total_reported && reported>0 && reported<902);
    assert(all_done==902 && all_total==902);
    for(uint64_t key=0;key<10000;key++) {
        unsigned selected=0;
        for(unsigned index=0;index<8;index++) { select_batch(index,8); selected+=prepare_key_selected(key); }
        assert(selected==1);
    }
    fake_deck=false; assert(prepare_key_selected(1234));
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cxx', default='clang++')
    args = parser.parse_args()
    cache = (ROOT / 'gpu/vk/vk_progcache.cpp').read_text(encoding='utf-8')
    draw = (ROOT / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8')
    parts = [body(cache, marker) for marker in (
        'static void program_cache_release(', 'void program_cache_borrow(',
        'void program_cache_release_loaded(', 'std::vector<uint64_t> program_cache_precompile_keys(',
        'bool prepare_key_selected(')]
    fixture = HEAD + '\n'.join(parts) + DRAW_HEAD + body(draw, 'static void precompile_stream(') + MAIN
    with tempfile.TemporaryDirectory(prefix='hookshot-deck-memory-') as tmp:
        source, exe = Path(tmp) / 'check.cpp', Path(tmp) / 'check'
        source.write_text(fixture, encoding='utf-8')
        subprocess.run([args.cxx, '-std=c++20', '-O1', '-pthread', str(source), '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=15)
        path_fixture = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <string>
using DWORD=unsigned long;
constexpr DWORD MAX_PATH=4096, INVALID_FILE_ATTRIBUTES=~0ul, FILE_ATTRIBUTE_DIRECTORY=16;
std::string game="/tmp/a moved \xc3\xa9 game/hookshot", found;
bool directory=false;
namespace mkwvk { DWORD game_module_path(char* p, DWORD) { strcpy(p,game.c_str()); return game.size(); } }
DWORD GetFileAttributesA(const char* path) { found=path; return directory?FILE_ATTRIBUTE_DIRECTORY:INVALID_FILE_ATTRIBUTES; }
''' + body((ROOT / 'gpu/vk/vk_main.cpp').read_text(encoding='utf-8'), 'static void portable_driver_cache()') + r'''
int main() {
    setenv("MESA_DISK_CACHE_SINGLE_FILE","1",1);
    unsetenv("MESA_SHADER_CACHE_DIR"); portable_driver_cache(); assert(!getenv("MESA_SHADER_CACHE_DIR"));
    assert(std::string(getenv("MESA_DISK_CACHE_SINGLE_FILE"))=="1");
    directory=true; portable_driver_cache();
    assert(std::string(getenv("MESA_SHADER_CACHE_DIR"))=="/tmp/a moved \xc3\xa9 game/hookshot_steamdeck_cache");
    setenv("MESA_SHADER_CACHE_DIR","/steam/cache",1); portable_driver_cache();
    assert(std::string(getenv("MESA_SHADER_CACHE_DIR"))==found);
    assert(std::string(getenv("MESA_DISK_CACHE_SINGLE_FILE"))=="0");
    assert(std::string(getenv("MESA_DISK_CACHE_DATABASE"))=="0");
    assert(std::string(getenv("MESA_DISK_CACHE_MULTI_FILE"))=="1");
    setenv("MESA_SHADER_CACHE_DIR","",1); portable_driver_cache(); assert(std::string(getenv("MESA_SHADER_CACHE_DIR"))==found);
}
'''
        if __import__('os').name != 'nt':
            source.write_text(path_fixture, encoding='utf-8')
            subprocess.run([args.cxx, '-std=c++20', str(source), '-o', str(exe)], check=True, timeout=60)
            subprocess.run([str(exe)], check=True, timeout=15)
    print('PASS: offline preparation bounds live handles and restores disk metadata')


if __name__ == '__main__':
    main()
