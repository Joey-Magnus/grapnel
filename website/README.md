# Hookshot documentation preview

An Astro Starlight interface for the repository's Markdown docs, with the original `assets/hookshot.png` logo and a
forest-green, parchment and gold theme. The preview belongs to `bibigurl-yum/Hookshot`; it is not an upstream site.

- Source branch: `docs/starlight-preview`
- Published output branch: `preview/starlight-pages`
- Preview URL: https://bibigurl-yum.github.io/Hookshot/

## Build and check

Use a Node version supported by the pinned Astro release (Node 22.23.4 or newer; built locally with Node 26).
From `website/`:

```sh
npm ci
npm run build
npm run check
npm run preview
```

Open the local URL printed by Astro, including `/Hookshot/`. For live editing use `npm run dev`. If repository
Markdown changes while the server is running, restart it to rerun content preparation.

The check traverses the generated HTML: internal pages and anchors, assets, the `/Hookshot/` project base,
Report a bug links, the search index and the original logo's exact bytes. Search runs against the production
Pagefind index after a build; use `npm run preview` when checking search.

## Edit content and appearance

- The ordinary Markdown in `../docs/`, `../readme.md`, `../CONTRIBUTING.md` and the pipeline-state reference remains
  the source for the imported pages. Do not edit `src/content/docs/generated/`.
- `scripts/prepare-content.mjs` adds page metadata and rewrites relative links at build time. Code samples stay
  unchanged. Generated content, copied public assets, dependencies and build output are ignored in this branch.
- `src/components/` contains the header, landing-page hero, guide cards and footer.
- `src/styles/forest.css` defines light/dark themes and responsive layouts.
- `astro.config.mjs` defines navigation and the fork's Pages URL.
- The logo is copied unchanged from the original README asset. The older GitBook experiment is on `docs/gitbook`.

## Publish the preview

Build and run the checks locally. Commit and push source changes to `docs/starlight-preview` in the fork. Publish
**only the contents of `dist/`** to `preview/starlight-pages`, with `.nojekyll` at its root. The output branch is
separate from source and contains no game installation, caches, saves or build tools.

GitHub Pages is configured to deploy from `preview/starlight-pages`, directory `/`. No custom Actions workflow,
GitBook account or subscription is needed for this public preview. Rebuild and republish when the source changes;
source pushes alone do not update the preview. Keep normal fast-forward history on the output branch.

Before adapting this for upstream, change the configured owner/site URL and get maintainer agreement about hosting.
Do not open an upstream pull request until the preview has been reviewed.

## Verification limits

The initial build and link checks were run locally. Browser automation was unavailable in the authoring session;
review the preview in a browser at desktop and mobile widths, including search, the menu, light/dark themes and
keyboard navigation. No change to the game's runtime is made by this site.
