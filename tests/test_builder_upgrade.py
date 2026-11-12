"""The Windows Builder's hand-over to the Hookshot Launcher (builder/HookshotBuilder/Upgrader.cs, docs/launcher-upgrade.md),
with the contract's sample files (tests/fixtures/launcher/): the import file from builder-settings.json is the sample one, the
manifest is read as strictly as the setup lists, the folder's stamp names the launcher, and the zip is swapped in whole or
not at all (an entry outside app.part, a zip without the launcher or a cancel leave the installed one). The real Upgrader.cs, Updater.cs,
BuilderSettings.cs, BuilderHome.cs, PortableArchive.cs and Strings.cs are compiled with fakes for the window only
(tests/builder_upgrade_test.cs): no WPF, no network, no game.

Built for net8.0, the builder's framework, and for this SDK's own framework when it has no .NET 8 reference pack (as
tests/test_updater_asset_digest.py, which says why; never on a GitHub runner).

python -I -B tests/test_builder_upgrade.py [--dotnet dotnet]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--dotnet", "{dotnet}"]

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("Upgrader.cs", "Updater.cs", "BuilderSettings.cs", "BuilderHome.cs", "PortableArchive.cs", "Strings.cs")
PROJECT = """<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<OutputType>Exe</OutputType><TargetFramework>%s</TargetFramework><ImplicitUsings>enable</ImplicitUsings>
<Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors><NuGetAudit>false</NuGetAudit>
<UseSharedCompilation>false</UseSharedCompilation>
</PropertyGroup></Project>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--dotnet", default="dotnet")
    args = parser.parse_args()
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        parser.error("a .NET SDK is required (the builder's is .NET 8)")
    with tempfile.TemporaryDirectory(prefix="builder-upgrade-build-") as folder:
        root = Path(folder)
        for name in SOURCES:
            shutil.copyfile(args.source / "builder/HookshotBuilder" / name, root / name)
        shutil.copyfile(ROOT / "tests/builder_upgrade_test.cs", root / "Program.cs")
        (root / "NuGet.Config").write_text("<configuration><packageSources><clear/></packageSources></configuration>", encoding="utf-8")
        project = root / "Fixture.csproj"
        project.write_text(PROJECT % "net8.0", encoding="utf-8")
        restore = subprocess.run([dotnet, "restore", str(project), "--disable-build-servers"], capture_output=True, text=True)
        if restore.returncode and "NU1100" in restore.stdout + restore.stderr:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                raise SystemExit("on a GitHub runner the upgrader must build for the builder's net8.0, and its reference "
                                 "pack is missing: no fallback to a later framework here\n" + restore.stdout + restore.stderr)
            sdk = subprocess.run([dotnet, "--version"], capture_output=True, text=True, check=True).stdout.strip()
            framework = "net%s.0" % sdk.split(".")[0]
            print("this .NET SDK (%s) has no .NET 8 reference pack: the upgrader is built for %s, not the builder's net8.0"
                  % (sdk, framework), flush=True)
            project.write_text(PROJECT % framework, encoding="utf-8")
        elif restore.returncode:
            raise SystemExit(restore.stdout + restore.stderr)
        subprocess.run([dotnet, "run", "--project", str(project), "--configuration", "Release", "--disable-build-servers",
                        "--", str(ROOT / "tests/fixtures/launcher")], check=True)


if __name__ == "__main__":
    main()
