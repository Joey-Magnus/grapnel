# Publishing this guide

The Markdown is ready for GitBook Git Sync and remains readable on GitHub. The repository configuration selects
`docs/README.md` as the home page and `SUMMARY.md` as navigation. It keeps the repository root as the content
root so the existing reference manual, contribution rules and technical guides can be used in place.

## Connect GitBook

1. In GitBook, create or select the documentation space/site and configure Git Sync with GitHub.
2. Grant the GitBook integration access to the repository you intend to publish.
3. For this contribution branch, select `bibigurl-yum/Hookshot`, branch `docs/gitbook`, and the repository root as
   the project/space directory. Let `.gitbook.yaml` select the home page and navigation.
4. Choose **GitHub → GitBook** for the initial import. The content already lives in Git.
5. Preview the imported pages and links, then publish when the site is ready.

After upstream merges the documentation, an upstream maintainer can connect their GitBook site to
`NotRexed/Hookshot:main`. A merged pull request does not itself create a GitBook site or grant access to one.
Keep any site/space keys GitBook generates stable on subsequent syncs.

See GitBook's [Git Sync configuration](https://gitbook.com/docs/docs-as-code/git-sync/content-configuration) and
[initial import guide](https://gitbook.com/docs/guides/editing-and-publishing-documentation/import-or-migrate-your-content-to-gitbook-with-git-sync).

## Apply the forest-and-gold identity

The artwork uses an original hook-and-compass emblem, layered forest silhouettes and gold ornament. It is inspired
by Zelda's adventure atmosphere and keeps Hookshot's name as the identity. No game art or game fonts are included.

| Element | Value or asset |
|---|---|
| Site title | Hookshot field guide |
| Theme | Clean; light and dark modes |
| Primary / light-mode link color | Forest green `#1F6246` |
| Dark background direction | Deep forest `#102D26` |
| Light background direction | Parchment `#F6F1E5` |
| Decorative accent | Antique gold `#C8A969` |
| Main text on light backgrounds | Deep forest `#102D26` |
| Site icon | [Hook emblem](assets/hook-emblem.svg) |
| Light-mode wordmark | [Forest wordmark](assets/wordmark-light.svg) |
| Dark-mode wordmark | [Parchment wordmark](assets/wordmark-dark.svg) |
| Landing-page artwork | [Field-guide cover](assets/field-guide-cover.svg) |
| Social image | [1200×630 PNG](assets/social-card.png) |
| Header action | **Report a bug** → `https://github.com/NotRexed/Hookshot/issues/new/choose` |

The landing-page artwork is already embedded in Markdown. Set the site logo, icon, colors and header link in
GitBook's **Customization** interface; `.gitbook.yaml` configures content, not those site-wide appearance settings.
Use the controls available on the site's plan. The standard font is suitable for body text; serif lettering is
limited to the supplied artwork. Gold is decorative, not the main text color on parchment.

GitBook documents its appearance controls in
[Icons, colors, and themes](https://gitbook.com/docs/manage-your-site/customization/icons-colors-and-themes).
The PNG social image is supplied because GitBook does not accept SVG for that slot.

## Keep a single reference

The short player guides introduce a task and link to the detailed reference manual. Update `readme.md` when a
setting changes, then check the matching guide for outdated advice. Existing development documents stay at their
current paths; the technical-notes index groups them without moving files.

For [Common issues](common-issues.md), re-read the linked responses and destination trackers. Do not interpret a
closed duplicate as a released fix. Keep the review date and the affected version visible.

Check every navigation target, relative link and image after changes. Preview both light and dark mode and a narrow
screen in GitBook after connecting it; local asset rendering cannot verify GitBook's hosted layout or sync.

## Artwork source and license

The SVG files in `docs/assets/` are original vector artwork created for this documentation. `social-card.png` is a
render of `social-card.svg`; both belong to the documentation, not a game build. The artwork follows this
repository's [GPL-3.0-or-later license](../LICENSE). It contains no copied Nintendo artwork or font files.

To regenerate the PNG with librsvg installed:

```sh
rsvg-convert docs/assets/social-card.svg -o docs/assets/social-card.png
```
