"""A draw after a uniform buffer's bind builds its uniform ranges alone, and only when the rest of its set cannot have moved.

OoT binds a uniform buffer for nearly every draw, so nine draws in ten built their whole descriptor set again. A draw of the
program last built whole, whose stages' textures and storage buffers stand, now writes the uniform ranges over that build
(vk_draw.cpp desc_rest_stands, rebuild_uniform_ranges). What is checked here, on the real Program / Stage / Eden descriptor
types with the functions cut from the source:
  - which programs may (uniform_only_of): storage buffers read through c0 and texture handles through c2 of graphics stages,
    nothing written, no images, no texel buffers, no handle program, no table;
  - what refuses a draw (desc_rest_stands): another program built since, a stage's textures or storage buffers bound anew, the
    texture epoch, the pools' and mirrors' stamp, a texture newly GPU-written, a dump;
  - what is written (rebuild_uniform_ranges): the uniform ranges, each at its place, and no storage buffer's;
  - and, in the text of draw(), that the path keeps the conditions of a draw that keeps its whole set and its bookkeeping.

python -I -B tests/test_desc_uniform_only.py --headers <Vulkan-Headers/include> [--cxx clang++]
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")

RUN_ALL_ARGS = ["--cxx", "clang++", "--headers", "{vulkan_headers}"]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''
// SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstdlib>
#include <memory>
#include "vk_shader.h"
namespace mkwvk {
static bool partial_on = true, dumping = false;
static uint32_t epoch_now = 7;
static uint64_t stamp_now = 100, written_now = 200;
bool desc_partial_on() { return partial_on; }
bool dump_on() { return dumping; }
uint32_t texture_epoch() { return epoch_now; }
uint64_t gpu_bind_stamp() { return stamp_now; }
uint64_t texture_written_generation() { return written_now; }
STRUCT_DESC_WRITER
static DescWriter writer;
DescWriter& dw() { return writer; }
static int ranges_asked = 0;
// (a range that names what was asked: the stage in the offset, the bank index in the range)
VkDescriptorBufferInfo uniform_range(const NvnState&, const Stage& st, uint32_t index) {
    ranges_asked++;
    return {(VkBuffer)(uintptr_t)0x1000, (VkDeviceSize)st.nvn_stage, (VkDeviceSize)index};
}
CUT_FUNCTIONS
static unsigned failed = 0, checked = 0;
static void check(bool ok, const char* what) { checked++; if (!ok) { failed++; fprintf(stderr, "FAIL: %s\n", what); } }
// (a vertex and a fragment stage: c0, c1 and two user uniform buffers each, one storage buffer in the stage's table, two textures in c2)
static std::unique_ptr<Program> plain() {
    auto p = std::make_unique<Program>();
    for (int ns = 0; ns < 2; ns++) {
        p->stages.emplace_back();
        Stage& st = p->stages.back();
        st.nvn_stage = ns;
        for (uint32_t index : {0u, 1u, 3u, 4u}) {
            Shader::ConstantBufferDescriptor c{};
            c.index = index, c.count = 1;
            st.info.constant_buffer_descriptors.push_back(c);
        }
        Shader::StorageBufferDescriptor sb{};
        sb.cbuf_index = 0, sb.cbuf_offset = ns ? 0x510 : 0x110, sb.count = 1, sb.is_written = false;
        st.info.storage_buffers_descriptors.push_back(sb);
        for (uint32_t i = 0; i < 2; i++) {
            Shader::TextureDescriptor t{};
            t.type = Shader::TextureType::Color2D, t.count = 1, t.cbuf_index = 2, t.cbuf_offset = 0x168 + 8 * i;
            st.info.texture_descriptors.push_back(t);
        }
    }
    return p;
}
static void built(const NvnState& s, const Program& p) {   // (what draw() keeps after a whole build is bound)
    desc_built_prog = &p;
    for (int k = 0; k < 5; k++) last_desc_tex[k] = s.tex_gen[k], last_desc_ssbo[k] = s.ssbo_gen[k];
    last_desc_stamp = stamp_now, last_desc_written = written_now, last_desc_epoch = epoch_now;
}
}
int main() {
    using namespace mkwvk;
    auto s = std::make_unique<NvnState>();
    {   // ---- which programs
        check(uniform_only_of(*plain()), "a program that reads c0 and c2 of its graphics stages may");
        Program none;
        check(!uniform_only_of(none), "a program without stages may not");
        auto p = plain(); p->compute = true; check(!uniform_only_of(*p), "a compute program may not");
        p = plain(); p->mesh = true; check(!uniform_only_of(*p), "a mesh program may not");
        p = plain(); p->fallback = true; check(!uniform_only_of(*p), "a mesh fallback program may not");
        for (int ns : {-1, 5, 6, 7}) { p = plain(); p->stages[1].nvn_stage = ns; check(!uniform_only_of(*p), "a stage that is not a graphics stage refuses"); }
        p = plain(); p->stages[1].info.image_descriptors.emplace_back(); check(!uniform_only_of(*p), "a storage image refuses");
        p = plain(); p->stages[0].info.texture_buffer_descriptors.emplace_back(); check(!uniform_only_of(*p), "a texel buffer refuses");
        p = plain(); p->stages[0].info.image_buffer_descriptors.emplace_back(); check(!uniform_only_of(*p), "a storage texel buffer refuses");
        p = plain(); p->stages[1].info.storage_buffers_descriptors[0].is_written = true; check(!uniform_only_of(*p), "a written storage buffer refuses");
        p = plain(); p->stages[1].info.storage_buffers_descriptors[0].count = 3; check(!uniform_only_of(*p), "a storage buffer table refuses");
        p = plain(); p->stages[1].info.storage_buffers_descriptors[0].cbuf_index = 4; check(!uniform_only_of(*p), "a storage buffer named in a uniform buffer refuses");
        p = plain(); p->stages[1].info.storage_buffers_descriptors[0].cbuf_index = 1; check(!uniform_only_of(*p), "a storage buffer named in c1 refuses");
        p = plain(); p->stages[1].info.storage_buffers_descriptors[0].cbuf_offset = 0xff0; check(!uniform_only_of(*p), "the miss log's buffer refuses");
        p = plain(); p->stages[1].info.texture_descriptors[1].handle_program = 0; check(!uniform_only_of(*p), "a handle program refuses");
        p = plain(); p->stages[1].info.texture_descriptors[1].cbuf_index = 3; check(!uniform_only_of(*p), "a handle in a uniform buffer refuses");
        p = plain(); p->stages[0].info.texture_descriptors[0].has_secondary = true, p->stages[0].info.texture_descriptors[0].secondary_cbuf_index = 3;
        check(!uniform_only_of(*p), "a secondary handle word in a uniform buffer refuses");
        p->stages[0].info.texture_descriptors[0].secondary_cbuf_index = 2; check(uniform_only_of(*p), "a secondary handle word in c2 may");
        // (asked once a program, and the answer kept on it)
        p = plain(); check(p->uniform_only.load() == -1 && program_uniform_only(*p) && p->uniform_only.load() == 1, "the answer is kept on the program");
        p->compute = true; check(program_uniform_only(*p), "and not worked out again");
        p = plain(); p->mesh = true; check(!program_uniform_only(*p) && p->uniform_only.load() == 0, "a refusal is kept too");
    }
    {   // ---- what refuses a draw
        auto p = plain(), q = plain();
        for (int k = 0; k < kNvnStages; k++) s->tex_gen[k] = 10 + k, s->ssbo_gen[k] = 20 + k;
        check(!desc_rest_stands(*s, *p), "nothing was built: refused");
        built(*s, *p);
        check(desc_rest_stands(*s, *p), "the program last built, nothing moved: stands");
        s->bind_gen += 5; check(desc_rest_stands(*s, *p), "a uniform buffer bound (bind_gen alone): stands");
        check(!desc_rest_stands(*s, *q), "another program: refused");
        partial_on = false; check(!desc_rest_stands(*s, *p), "the switch off: refused"); partial_on = true;
        dumping = true; check(!desc_rest_stands(*s, *p), "a dump: refused"); dumping = false;
        for (int k = 0; k < 5; k++) {
            s->tex_gen[k]++; check(!desc_rest_stands(*s, *p), "a graphics stage's textures bound anew: refused"); s->tex_gen[k]--;
            s->ssbo_gen[k]++; check(!desc_rest_stands(*s, *p), "a graphics stage's storage buffers bound anew: refused"); s->ssbo_gen[k]--;
        }
        s->tex_gen[5]++, s->ssbo_gen[5]++, s->tex_gen[6]++, s->ssbo_gen[7]++;
        check(desc_rest_stands(*s, *p), "a dispatch's or a mesh draw's bindings do not refuse a graphics program");
        epoch_now++; check(!desc_rest_stands(*s, *p), "another texture epoch: refused"); epoch_now--;
        stamp_now++; check(!desc_rest_stands(*s, *p), "the pools or mirrors moved: refused"); stamp_now--;
        written_now++; check(!desc_rest_stands(*s, *p), "a texture newly GPU-written: refused"); written_now--;
        check(desc_rest_stands(*s, *p), "all back as built: stands");
        desc_built_prog = nullptr; check(!desc_rest_stands(*s, *p), "a whole build begun since (not bound yet): refused");
        auto m = plain(); m->mesh = true; built(*s, *m); check(!desc_rest_stands(*s, *m), "a program that may not: refused");
    }
    {   // ---- what is written
        auto p = plain();
        writer.reset(); writer.prog = p.get();
        const VkDescriptorBufferInfo old{(VkBuffer)(uintptr_t)0x2000, 99, 99};
        writer.bufs.assign(10, old);   // (per stage: 4 uniform ranges, then its storage buffer)
        ranges_asked = 0;
        check(rebuild_uniform_ranges(*s, *p) && ranges_asked == 8, "eight uniform ranges asked");
        const uint32_t index[4] = {0, 1, 3, 4};
        bool placed = true, kept = true;
        for (int ns = 0; ns < 2; ns++) {
            for (int i = 0; i < 4; i++) {
                const VkDescriptorBufferInfo& b = writer.bufs[ns * 5 + i];
                placed &= b.buffer == (VkBuffer)(uintptr_t)0x1000 && b.offset == (VkDeviceSize)ns && b.range == index[i];
            }
            const VkDescriptorBufferInfo& sb = writer.bufs[ns * 5 + 4];
            kept &= sb.buffer == old.buffer && sb.offset == 99 && sb.range == 99;
        }
        check(placed, "each uniform range at its stage's and bank's place");
        check(kept, "the storage buffers' ranges left as built");
        writer.bufs.assign(9, old); ranges_asked = 0;
        check(!rebuild_uniform_ranges(*s, *p) && ranges_asked == 0, "a build of another size is not written to");
        auto q = plain(); writer.bufs.assign(10, old); writer.prog = q.get();
        check(!rebuild_uniform_ranges(*s, *p) && ranges_asked == 0, "another program's build is not written to");
        bool untouched = true;
        for (const VkDescriptorBufferInfo& b : writer.bufs) untouched &= b.buffer == old.buffer;
        check(untouched, "and stays as it was");
    }
    printf("checks=%u failures=%u\n", checked, failed);
    return failed ? 1 : 0;
}
'''


def text_checks(draw_cpp, texture_cpp):
    draw = block(draw_cpp, "void draw(VkCommandBuffer cmd, NvnState& s, const DrawArgs& d) {")
    cond = draw[draw.index("bool uniform_only = "):]
    cond = cond[: cond.index(";")]
    # (the conditions of a draw that keeps its whole set, all but the bindings' and the uniform updates' generations)
    for needed in ("!same_desc", "!no_reuse", "slotgen", "last_desc_valid", "last_desc_prog == &p", "last_desc_dgen == dgen",
                   "desc_slots_kept(reg_gen)", "desc_rest_stands(s, p)"):
        if needed not in cond:
            raise SystemExit("a draw builds its uniform ranges alone without checking: " + needed)
    if "last_desc_bind" in cond or "last_desc_ub" in cond:
        raise SystemExit("the uniform-only path waits for bind_gen or ub_gen: it would never be taken")
    whole = draw[draw.index("if (!same_desc && !uniform_only) {"):]
    whole = whole[: whole.index("build_descriptors(s, p);")]
    for needed in ("desc_built_prog = nullptr;", "last_desc_stamp = gpu_bind_stamp()", "last_desc_written = texture_written_generation()",
                   "last_desc_epoch = texture_epoch()"):
        if needed not in whole:
            raise SystemExit("a whole build does not read, before it begins: " + needed)
    if "if (!same_desc && !uniform_only) gfx_sampled() = draw_sampled();" not in draw:
        raise SystemExit("a uniform-only draw replaces the textures its last whole build sampled")
    bind = draw[draw.index("if (uniform_only) {   // (the rest is the last build's"):]
    part, rest = bind[: bind.index("} else if (!same_desc) {")], bind[bind.index("} else if (!same_desc) {"):]
    rest = rest[: rest.index("st_desc_reused++")]
    if "bind_descriptors(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, p)) SKIP_HERE();" not in part or \
            "last_desc_bind = s.bind_gen, last_desc_ub = ub_gen;" not in part:
        raise SystemExit("a uniform-only draw does not bind its set, or does not note the bindings it stands for")
    for kept in ("last_desc_fp()", "last_desc_reg", "last_desc_dgen", "last_desc_prog", "desc_built_prog", "last_desc_tex"):
        if kept in part:
            raise SystemExit("a uniform-only draw rewrites what its last whole build kept: " + kept)
    for needed in ("desc_built_prog = &p;", "last_desc_tex[k] = s.tex_gen[k], last_desc_ssbo[k] = s.ssbo_gen[k]"):
        if needed not in rest:
            raise SystemExit("a whole build, once bound, does not keep: " + needed)
    if rest.index("bind_descriptors(") > rest.index("desc_built_prog = &p;"):
        raise SystemExit("a build is offered to the next draw before it is bound")
    on = block(draw_cpp, "bool desc_partial_on() {")
    for needed in ('getenv("RX_VK_DESC_PARTIAL")', "env_value_off(e)", "desc_slotgen_on()", '"RX_VK_DRAW_STATS"', '"RX_VK_SSBO_STRETCH"',
                   '"RX_VK_SSBO_WIDE"', '"RX_VK_HANDLES_LIVE"'):
        if needed not in on:
            raise SystemExit("desc_partial_on: " + needed + " missing")
    # (a recording's first draw builds whole: the same resets as the whole set's reuse)
    if draw_cpp.count("last_desc_valid = false") < 4:
        raise SystemExit("a new recording no longer drops the last draw's descriptors")
    written = block(texture_cpp, "void texture_written(Texture* tex, const char* why) {")
    if written.index("if (!tex->gpu_written) written_gen.fetch_add(1") > written.index("tex->gpu_written = true;"):
        raise SystemExit("texture_written does not move the GPU-written generation when a texture becomes written")
    if texture_cpp.count("gpu_written = true") != 1:
        raise SystemExit("a texture becomes GPU-written somewhere texture_written_generation does not see")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    parser.add_argument("--headers", type=Path, required=True)
    args = parser.parse_args()
    vk = ROOT / "gpu" / "vk"
    draw_cpp = (vk / "vk_draw.cpp").read_text(encoding="utf-8-sig")
    text_checks(draw_cpp, (vk / "vk_texture.cpp").read_text(encoding="utf-8-sig"))
    start = draw_cpp.index("thread_local const Program* desc_built_prog = nullptr;")
    state = draw_cpp[start: draw_cpp.index("int64_t st_desc_uniform_only;", start)]
    functions = state + "\n" + "\n\n".join(block(draw_cpp, m) for m in (
        "bool uniform_only_of(", "bool program_uniform_only(", "bool desc_rest_stands(", "bool rebuild_uniform_ranges("))
    fixture = FIXTURE.replace("STRUCT_DESC_WRITER", block(draw_cpp, "struct DescWriter {") + ";").replace("CUT_FUNCTIONS", functions)
    flags = ["-std=c++20", "-include", ENV_ON_H, "-O1", "-w", "-DNDEBUG", "-DVK_NO_PROTOTYPES", "-DMKWVK_INCLUDES=2"]
    for header in ("algorithm", "cstdio", "cstdlib", "cstring", "functional", "string", "vector"):
        flags += ["-include", header]
    includes = [vk, vk / "compat", ROOT / "gpu/compat", vk / "eden", ROOT / "gpu/third_party/suyu", args.headers]
    if os.name != "nt":
        includes.insert(0, ROOT / "host/posix")
    flags += ["-I" + str(path.resolve()) for path in includes]
    with tempfile.TemporaryDirectory(prefix="desc-uniform-only-") as temp:
        folder = Path(temp)
        cpp, exe = folder / "fixture.cpp", folder / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, *flags, str(cpp), "-o", str(exe)], cwd=folder, check=True)
        if subprocess.run([str(exe)], cwd=folder).returncode:
            raise SystemExit(1)
    print("PASS: a draw builds its uniform ranges alone only over a build that still stands")


if __name__ == "__main__":
    main()
