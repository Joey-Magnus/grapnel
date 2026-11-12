"""Prepared Deck caches avoid retaining all programs at startup only while still current."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ['--cxx', '{cxx}']
RUN_ALL_SKIP = {'windows': 'portable Mesa caches are a Linux feature'}
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
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <string>
#include <vector>
using DWORD=uint32_t;
constexpr DWORD INVALID_FILE_ATTRIBUTES=~0u, FILE_ATTRIBUTE_DIRECTORY=16;
bool folder=true, again=false, keys=true, populated=false, libraries=false;
DWORD GetFileAttributesA(const char* p) {
    assert(std::string(p)=="/game/hookshot_steamdeck_cache");
    return folder?FILE_ATTRIBUTE_DIRECTORY:INVALID_FILE_ATTRIBUTES;
}
bool env_on(const char* name) { return std::string(name)=="RX_VK_PREPARE_AGAIN" && again; }
std::string prepared_path() { return "/game/hookshot_prepared.bin"; }
std::string seed_path() { return "/game/hookshot_shaders.bin"; }
uint64_t program_cache_stamp() { return 123; }
struct PreparedFor { uint64_t seed_size=1, warmed=7; };
PreparedFor kept;
enum class PrepareWhy {None,First,Translator,Seed};
PrepareWhy why=PrepareWhy::None;
PrepareWhy prepare_check(const std::string&,const std::string&,uint64_t,PreparedFor* p,double*) { *p=kept; return why; }
bool gpl_wanted() { return libraries; }
uint64_t warmed_stamp(bool lib) { return lib?8:7; }
struct Program {} program;
std::vector<uint64_t> program_cache_keys(std::vector<Program*>* loaded) {
    if(populated) loaded->push_back(&program);
    return keys?std::vector<uint64_t>{1}:std::vector<uint64_t>{};
}
void logf(const char*,...) {}
'''

MAIN = r'''
int main() {
    unsetenv("RX_VK_PRECOMPILE");
    assert(portable_cache_ready() && !precompile_wanted());
    folder=false; assert(!portable_cache_ready() && precompile_wanted()); folder=true;
    for(auto change:{PrepareWhy::First,PrepareWhy::Translator,PrepareWhy::Seed}) {
        why=change; assert(!portable_cache_ready() && precompile_wanted());
    }
    why=PrepareWhy::None;
    kept.warmed=99; assert(!portable_cache_ready() && precompile_wanted()); kept.warmed=7;
    kept.seed_size=0; assert(!portable_cache_ready()); kept.seed_size=1;
    keys=false; assert(!portable_cache_ready()); populated=true; assert(portable_cache_ready());
    populated=false; keys=true;
    again=true; assert(!portable_cache_ready() && precompile_wanted()); again=false;
    libraries=true; assert(!portable_cache_ready()); libraries=false;
    setenv("RX_VK_PRECOMPILE","1",1); assert(precompile_wanted());
    setenv("RX_VK_PRECOMPILE","0",1); folder=false; assert(!precompile_wanted());
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cxx', default='clang++')
    args = parser.parse_args()
    source = (ROOT / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8')
    fixture = HEAD + body(source, 'static bool portable_cache_ready() {') + body(source, 'bool precompile_wanted() {') + MAIN
    with tempfile.TemporaryDirectory(prefix='hookshot-deck-ready-') as tmp:
        path, exe = Path(tmp) / 'check.cpp', Path(tmp) / 'check'
        path.write_text(fixture, encoding='utf-8')
        subprocess.run([args.cxx, '-std=c++20', '-DHOOKSHOT_RELEASE=1', str(path), '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=10)
    print('PASS: portable cache startup validates readiness and preserves explicit precompile choices')


if __name__ == '__main__':
    main()
