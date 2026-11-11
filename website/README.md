# Hookshot documentation site

An optional Astro Starlight site using the original `assets/hookshot.png` logo. The game build does not depend on Node
or this site. Adopting the website, its dependencies, and hosting remains the upstream maintainer's decision.

## Typography

The site uses the main UI's bundled fallback set: Libertinus Sans Regular (400) for body text, Sans Bold (700) for
emphasis, and Serif Semibold (600) for headings. The unchanged version 7.051 TTF files are copied from
`third_party/fonts/libertinus/` into `src/assets/fonts/libertinus/`; CSS-relative imports let Astro process the font
URLs for the configured site base. No external font service is needed. Code retains Starlight's monospace font.

The game UI's preferred fonts come from the player's game files and are not included in this website. Keep the
Libertinus copyright and SIL Open Font License with the font assets; `public/fonts/libertinus/OFL.txt` publishes that
notice with the site. When updating these copies, use the repository's bundled font version and retain its notice.

## Build and check

Use Node 22.23.4 or newer. From `website/`:

```sh
npm ci
npm run build
npm run check
npm run preview
```

Open the printed local URL with `/Hookshot/`. For live editing use `npm run dev`; restart it when imported Markdown
changes. The checks validate published routes, local links and anchors, edit-link targets, logo bytes, search output,
compatibility source review, and the calculator and release-fetch behavior.

## Hosting and edit links

`site.config.mjs` is shared by Astro, content preparation, and validation. Defaults target upstream:

| Variable | Default |
|---|---|
| `DOCS_SITE_URL` | `https://notrexed.github.io` |
| `DOCS_SOURCE_REPOSITORY` | `NotRexed/Hookshot` |
| `DOCS_SOURCE_BRANCH` | `main` |

The project path is `/Hookshot/`. Set the same environment for build and check when overriding hosting.
Handwritten pages inherit the configured edit base; imported pages link to their original Markdown source.
These defaults do not enable an upstream site or change Pages settings.

For bibigurl-yum's existing preview, run `npm run build:preview`. It builds and checks with the fork's host and
`docs/starlight-preview` edit branch. Publish **only `dist/`** to the fork's `preview/starlight-pages` branch, whose
root contains `.nojekyll`. The preview is at https://bibigurl-yum.github.io/Hookshot/.

## What gets published

`content-sources.mjs` explicitly lists eight imported pages: five short player guides, the existing save guide,
the README as the reference manual, and CONTRIBUTING.md. Home, about, antivirus, and compatibility pages are
written in `src/content/docs/`. Internal design notes, development docs, workflow notes, and pipeline references
remain on GitHub and are linked there. Adding a file to `docs/` does not publish it automatically.

The manual is generated from `readme.md`, not maintained as another copy. Player guides link to its sections
rather than repeat requirement tables, menu settings, paths, or update procedures. Edit imported content in its
original location; generated pages and copied assets are ignored.

## Compatibility source review

The calculator translates selected README requirements into checks. `compatibility-review.json` records SHA-256
hashes of the reviewed **Project status** and **What you need** sections. Both build preparation and `npm run check`
stop if either section changes. A regression test verifies that requirement and GPU-status edits trigger the guard.
This catches changes in the checked-out source at build time; it does not monitor upstream in the background.

When the guard fails:

1. Read the changed README sections and review `src/lib/compatibility.mjs`, its tests, and the labels in
   `src/components/CompatibilityChecker.astro`. Adjust the checks and advice as needed.
2. Update the review date on the compatibility page and in `compatibility-review.json`.
3. After reviewing, compute the new section hashes from the repository root:

   ```sh
   node --input-type=module -e 'import {readFile} from "node:fs/promises"; import {sectionDigest} from "./website/scripts/verify-compatibility-sources.mjs"; const text = await readFile("readme.md", "utf8"); for (const heading of ["## Project status", "### What you need"]) console.log(heading, sectionDigest(text, heading));'
   ```

4. Put the reviewed hashes in the JSON file, then build and check. Do not refresh hashes without reviewing the rules.

Common-issue entries are historical examples with direct links to responses and trackers. They do not claim a
current open/fixed status. Review the source before changing an example. Antivirus signing information is explicitly
dated. The release badge fetches GitHub's latest stable version on page load and retains a permanent release link
if the API is unavailable or rate-limited. No game files or calculator answers are uploaded.

## Progress overview

The **Progress & updates** page searches upstream reports, feature requests, proposed changes and releases.
Its **Current version watch** groups open reports that explicitly name the latest stable version. It does not
infer affected versions, confirmed bugs, severity or released fixes from activity counts or merge dates.
See [PROGRESS.md](PROGRESS.md) for the implementation plan, editorial review rules, coverage and hosting options.

Run `npm run progress:sync` before a build to include a current static snapshot. Normal builds remain offline.
`npm run progress:serve` provides an optional shared feed with a five-minute cache. GitHub Pages can serve the
snapshot but cannot run this server; automatic public updates require hosting or scheduled deployment configured
separately. No public service, deploy workflow, schedule, commit or PR update is enabled by these scripts.

## Maintenance and deployment

Astro, Starlight, and their dependencies are pinned in the lockfile. Use `npm ci`; review dependency upgrades and
run the checks before publication. Node is needed for documentation tooling only. There is no new dependency-update
workflow or deploy workflow in this contribution.

If upstream adopts the site, a GitHub Action can build/check docs changes and publish successful builds from `main`.
Keep PR checks read-only; grant `pages: write` and `id-token: write` only to deployment, and upload only `website/dist`.
See [GitHub's custom Pages workflow instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
If hosting stays on the fork, sync upstream through a reviewed branch and rebuild. Human review is still needed
for issue advice and calculator changes; a scheduled job should propose updates for review.

## Verification limits

Browser access was unavailable in the authoring environment. Desktop/mobile visual review, keyboard interaction,
search, and light/dark-mode screenshots are still outstanding. Build, source-guard, rule, and link checks run locally.
