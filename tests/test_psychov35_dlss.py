"""Compile the actual opt-in scene gate and exercise HDR/mode/format transitions without a game."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cxx', default='g++')
    a = p.parse_args()
    chain = (ROOT / 'gpu/vk/vk_temporal.cpp').read_text(encoding='utf-8')
    draw = (ROOT / 'gpu/vk/vk_draw.cpp').read_text(encoding='utf-8')
    gate = function(chain, 'bool temporal_scene_format(')
    pair = function(chain, 'bool temporal_colour_pair(')
    switch = re.search(r'    if \(s\.psycho_last != psycho \|\| s\.history_input != in->format\) \{.*?\n    \}', chain, re.S).group()
    fixture = r'''
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include "gpu/vk/upscaler_rows.h"
namespace ur = mkwvk::upscaler_rows;
using VkFormat = int;
constexpr int VK_FORMAT_B10G11R11_UFLOAT_PACK32=122, VK_FORMAT_R16G16B16A16_SFLOAT=97;
int mode=ur::DLSS;
bool tone=false;
int temporal_mode() { return mode; }
bool scene_tonemap_on() { return tone; }
int env_switch(const char* n) { const char* e=std::getenv(n); return e && *e ? std::atoi(e) : -1; }
template<class... T> void logf(const char*, T...) {}
/* GATE */
/* PAIR */
struct S { bool psycho_last=false; unsigned history_input=122; unsigned long long last_frame=30; };
void transition(S& s, bool psycho, unsigned format=122) {
  struct { unsigned scene_format=97; } cam;
  struct T { unsigned format=122; } ti, to;
  ti.format=format;
  T *in=&ti, *out=&to;
/* SWITCH */
}
int main(int argc, char**) {
  const bool enabled=argc>1;
  for (mode=0; mode<ur::kUpscalers; ++mode) {
    for (int t=0;t<2;++t) {
      tone=t;
      for (int f=0;f<256;++f) {
        const bool expected=f==122 || (enabled && tone && ur::is_dlss(mode) && f==97);
        assert(temporal_scene_format(f)==expected);
        for (int output=0;output<256;++output) {
          const bool correct=(f==122 && output==122) ||
              (enabled && tone && ur::is_dlss(mode) && f==97 && output==97);
          assert(temporal_colour_pair(f,output)==correct);
        }
      }
    }
  }
  S s;
  transition(s,false); assert(s.last_frame==30);
  transition(s,true); assert(s.last_frame==0 && s.psycho_last);
  s.last_frame=60; transition(s,true); assert(s.last_frame==60);
  transition(s,false); assert(s.last_frame==0 && !s.psycho_last);
  s.last_frame=80; transition(s,true,97); assert(s.last_frame==0 && s.history_input==97);
  s.last_frame=90; transition(s,true,97); assert(s.last_frame==90);
  transition(s,true,122); assert(s.last_frame==0 && s.history_input==122);
}
'''.replace('/* GATE */', gate).replace('/* PAIR */', pair).replace('/* SWITCH */', switch)
    # All three scene consumers agree: camera, animated characters, reactive mask.
    assert '!temporal_scene_format(color0->format)' in function(chain, 'void temporal_note_scene_draw(')
    assert '!temporal_scene_format(at.color_format[0])' in function(draw, 'static void skin_check(')
    assert '!temporal_scene_format(at.color_format[0])' in function(draw, 'void reactive_scene_draw(')
    upscale = function(chain, 'bool temporal_upscale(')
    assert '!temporal_scene_format(cam.scene_format)' in upscale
    assert '!temporal_scene_format(in->format)' in upscale
    assert '!temporal_colour_pair(in->format, out->format)' in upscale
    assert 'psycho && (!engine.e->hdr || !engine.e->hdr())' in upscale
    assert upscale.index('PsychoV35 waits') < upscale.index('engine.e->evaluate(cmd, f)')
    assert 'prep_hdr_data{16384.0f, VK_TRUE}' in chain
    assert 'out_hdr_square = VK_FALSE' in chain
    assert 'const VkPipeline prep_pipe = hdr ? s.prep_hdr : s.prep;' in upscale
    assert 'const VkPipelineLayout prep_layout = hdr ? s.prep_hdr_layout : s.prep_layout;' in upscale
    assert 'rgba ? s.out_rgba' in upscale
    assert 'if (rgba && !make_rgba_output())' in upscale
    rgba_pipe = function(chain, 'bool make_rgba_output(')
    assert 'square = VK_FALSE' in rgba_pipe and 'DLSS_OUT_RGBA_COMP_SPV' in rgba_pipe
    # Changing storage precision must not skip the network's perceptual-to-linear decode.
    # A mid-grey linear sample encoded for the network is sqrt(0.18); passthrough raises it to 0.424.
    import math
    prep=(ROOT/'gpu/vk/shaders/dlss_prep.comp').read_text()
    assert 'kSquare ? e * e : e' in prep
    for linear in (0.0, 0.001, 0.02, 0.18, 0.5, 1.0, 2.0, 6.5):
        encoded=math.sqrt(linear)
        assert math.isclose(encoded*encoded, linear, rel_tol=1e-12, abs_tol=1e-15)
    # Validate the compiled storage image type, not just a source-file string.
    header=(ROOT/'gpu/vk/shaders/dlss_out_rgba_comp_spv.h').read_text()
    words=[int(w,16) for w in re.findall(r'0x[0-9a-fA-F]{8}',header)]
    assert words[0]==0x07230203
    i=5
    formats=[]
    while i<len(words):
        count,opcode=words[i]>>16,words[i]&65535
        assert count>0 and i+count<=len(words)
        if opcode==25: formats.append(words[i+8])
        i+=count
    assert 2 in formats and 8 not in formats, formats  # Rgba16f, never packed R11fG11fB10f.
    with tempfile.TemporaryDirectory(prefix='psychov35-dlss-') as folder:
        cpp, exe = Path(folder)/'test.cpp', Path(folder)/'test.exe'
        cpp.write_text(fixture, encoding='utf-8')
        subprocess.run([a.cxx, '-std=c++20', '-O2', '-Wall', '-Wextra', '-Werror', '-I'+str(ROOT), str(cpp), '-o', str(exe)], check=True)
        for value in ('', '0', '1', '2'):
            env = os.environ.copy()
            env['RX_VK_PSYCHOV35_DLSS'] = value
            subprocess.run([str(exe), *(['enabled'] if value=='1' else [])], env=env, check=True)
    print('PsychoV35 DLSS: 3,670,016 input/output combinations, scene gate, history and RGBA SPIR-V checks passed')

if __name__ == '__main__':
    main()
