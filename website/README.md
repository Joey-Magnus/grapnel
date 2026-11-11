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
It also runs the compatibility rules against supported, unsupported, incomplete, and low-memory configurations.

## Edit content and appearance

- The ordinary Markdown in `../docs/`, `../readme.md`, `../CONTRIBUTING.md` and the pipeline-state reference remains
  the source for the imported pages. Do not edit `src/content/docs/generated/`.
- `scripts/prepare-content.mjs` adds page metadata and rewrites relative links at build time. Code samples stay
  unchanged. Generated content, copied public assets, dependencies and build output are ignored in this branch.
- `src/components/` contains the header, landing-page hero, guide cards and footer.
- `src/styles/forest.css` defines light/dark themes and responsive layouts.
- `src/lib/compatibility.mjs` holds the browser-only requirements check. Update its rules and the dated sources in
  `src/content/docs/compatibility.mdx` together when upstream requirements change. No answers or files are uploaded.
- `src/content/docs/antivirus.md` records the maintainer's explanation and the date the signing status was checked.
- The front-page release badge reads GitHub's public latest-stable-release API on page load. It needs no token or
  rebuild, and keeps a link to the latest release if the API fails or is rate-limited.
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

## Keeping the docs current

The build imports the repository's README, contribution guide, pipeline-state reference, and Markdown in `docs/`.
Those pages follow the checked-out source automatically; they do not need a second copy maintained by hand.

If this site is adopted upstream, use a GitHub Actions workflow to run `npm ci`, `npm run build`, and `npm run check`
from `website/` on pull requests and pushes that change `readme.md`, `CONTRIBUTING.md`, `docs/**`, `website/**`,
or the referenced assets. Deploy successful builds from `main` with GitHub Pages. Keep pull-request checks read-only;
give only the deployment job `pages: write` and `id-token: write`, and upload only `website/dist`.
GitHub documents the setup in [custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

The owner needs to choose the hosting repository and URL before enabling deployment. This preview currently uses
the fork's URL and edit links; no new workflow is enabled by this contribution.

Short player guides, common-issue answers, antivirus status, and compatibility rules are curated content. Review
them when releases or their cited issues change, and update the review date. A closed issue alone is not evidence
of a released fix. If the preview remains in the fork, sync upstream changes through a reviewed branch and rebuild;
a scheduled update can propose a PR, but should not rewrite these answers or publish them without review.

## Verification limits

The initial build and link checks were run locally. Browser automation was unavailable in the authoring session;
review the preview in a browser at desktop and mobile widths, including search, the menu, light/dark themes and
keyboard navigation. No change to the game's runtime is made by this site.
