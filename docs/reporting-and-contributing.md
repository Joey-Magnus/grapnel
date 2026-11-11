# Reporting and contributing

## Report a bug

Check [Common issues](common-issues.md) and search the
[issue tracker](https://github.com/NotRexed/Hookshot/issues). If the problem is already reported, add your details
to that issue.

Include:

- The exact Hookshot version from the log, plus your OS, GPU and driver.
- Where the problem occurs and the steps that reproduce it.
- Your output/render resolution, upscaler, frame generation and HDR choices.
- Mods, overlays or injectors, and whether it also happens without them.
- `hookshot_log.txt` from the affected run, and a screenshot or short video where useful.

The log is normally in the game folder; a terminal launch prints there instead. Read it before sharing and remove
personal information you do not want public. Use the [issue forms](https://github.com/NotRexed/Hookshot/issues/new/choose).
The [contribution rules](../CONTRIBUTING.md) explain which files must stay local.

## Contribute a pipeline list

The maintainers collect pipeline-state records in
[issue #2034](https://github.com/NotRexed/Hookshot/issues/2034) to prepare more pipelines before play. The requested file is `hookshot_pipeline_states.bin`. The issue explains how it differs from game-derived shader caches. Check the current instructions there before submitting.

1. Play using a recent build of `main`, as requested in the issue.
2. Close the game and locate `hookshot_pipeline_states.bin` beside the game executable.
3. Zip **only that file**. Open the archive to verify the member list.
4. Fill in the issue's template with the build and settings used while collecting it. Mention if the list spans
   several builds or configurations.
5. Attach the zip yourself in a comment on that issue.

Do not include shaders, other caches, executables, saves or the rest of the game folder. The repository's
[pipeline-state notes](../assets/pipeline_states/README.md) describe the format and provenance.

## Improve the documentation or code

Branch from current `main`, keep changes focused, and follow [CONTRIBUTING.md](../CONTRIBUTING.md). The
[development guide](development.md) covers local builds and checks. See the
[website instructions](https://github.com/bibigurl-yum/Hookshot/blob/docs/starlight-preview/website/README.md) to build this documentation preview.
