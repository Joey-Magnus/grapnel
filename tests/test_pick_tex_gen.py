"""The last picks' program stands across a uniform buffer's bind when its textures are the same.

A graphics program's answers (the types its translation was told of the bound textures) are read from c2 of its stages: nothing else
in the bindings can change them, so the pair of last picks (prog_fast) need not wait for bind_gen, which every uniform buffer moves. A
handle program (it reads uniform memory), another bank, a secondary handle in another bank, a compute or a task / mesh program keeps
the old condition. The mask is kept with the pick (Pick::amask), not worked out again at each one.
python -I -B tests/test_pick_tex_gen.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main():
    shader = (ROOT / "gpu" / "vk" / "vk_shader.cpp").read_text(encoding="utf-8")
    mask = block(shader, "uint32_t answer_stage_mask(")
    for needle in ("handle_program == ~0U", "cbuf_index == 2", "secondary_cbuf_index == 2", "nvn_stage > 4) return ~0u"):
        if needle not in mask:
            raise SystemExit(f"an answer may come from somewhere tex_gen does not cover: {needle} missing")
    if mask.count("return ~0u") != 2 or "image_descriptors" not in mask or "texture_descriptors" not in mask:
        raise SystemExit("answer_stage_mask does not refuse every other source")
    pick = block(shader, "const Program* program_for(")
    if "RX_VK_PICK_BIND_GEN" not in pick or "!compute && f.amask != ~0u" not in pick:
        raise SystemExit("the switch is missing, or a compute program is picked by textures")
    if "f.tex_gen[k] != s.tex_gen[k]" not in pick or "f.amask >> k & 1" not in pick:
        raise SystemExit("the stages' textures are not compared")
    keep = pick[pick.index("auto keep = "):]
    if "f.amask = amask" not in keep or "f.tex_gen, s.tex_gen" not in keep:
        raise SystemExit("a kept pick does not remember its stages' textures")
    # (the mask is worked out once, when the pick is made, and kept with it: every keep is given the pick's own)
    if "pk.amask = picked_amask = compute ? ~0u : answer_stage_mask(*picked)" not in keep:
        raise SystemExit("a pick's mask is not answer_stage_mask of its program")
    if keep.count("keep(pk.p, pk.amask)") != 3 or "return keep(picked, picked_amask)" not in keep or "keep(pk.p)" in keep:
        raise SystemExit("a kept pick is not given its own program's mask")
    if keep.index("picks.clear()") < keep.index("pk.amask = picked_amask"):
        raise SystemExit("the pick's mask is read after the picks were cleared")
    for field in ("serial", "stages", "reg", "ub", "nvattr", "vattr", "ct"):
        if f"f.{field}" not in pick[: pick.index("auto keep = ")]:
            raise SystemExit(f"the last pick is taken without comparing its {field}")
    print("PASS: the last picks stand while their textures do")


if __name__ == "__main__":
    main()
