using System.Text.Json.Nodes;
using HookshotBuilder;

// The real Upgrader, Updater, BuilderSettings, BuilderHome and Strings; only the window, the tools and WPF's Application are fakes.
static class Program
{
    static int checks, failures;

    static void Check(bool condition, string message)
    {
        checks++;
        if (condition) return;
        failures++;
        Console.Error.WriteLine("FAIL: " + message);
    }

    static void Throws<T>(Action action, string message) where T : Exception
    {
        try { action(); }
        catch (T) { Check(true, message); return; }
        catch (Exception e) { Check(false, $"{message} (threw {e.GetType().Name}: {e.Message})"); return; }
        Check(false, message + " (did not throw)");
    }

    const string Sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    static string List(string lines, string tag = "v3.0.0", string format = "1") => $"tag {tag}\nformat {format}\n{lines}\n";

    static void Manifests(string fixtures)
    {
        var sample = File.ReadAllText(Path.Combine(fixtures, "hookshot-launcher.txt"));
        var m = Upgrader.ParseManifest(sample, "v3.0.0");
        Check(m.Tag == "v3.0.0", "The sample's tag was not read.");
        Check(m.Launchers.Count == 2, "The sample's unknown platform was not skipped.");
        Check(m.This.Sha == new string('1', 64) && m.This.Size == 52428800 &&
              m.This.Url == "https://github.com/NotRexed/Hookshot/releases/download/v3.0.0/HookshotLauncher-v3.0.0-Windows-x64.zip",
              "The sample's Windows line was not read.");
        Check(Upgrader.ParseManifest(sample, null).Tag == "v3.0.0", "The latest release's list was refused.");
        Throws<InvalidDataException>(() => Upgrader.ParseManifest(sample, "v3.0.1"), "A list for another tag was taken.");
        var good = $"launcher windows-x64 {Sha} 10 https://example.invalid/a";
        foreach (var bad in new[]
                 {
                     List($"launcher windows-x64 {Sha.ToUpperInvariant()} 10 https://example.invalid/a"),
                     List($"launcher windows-x64 {Sha[1..]} 10 https://example.invalid/a"),
                     List($"launcher windows-x64 {Sha} 10 http://example.invalid/a"),
                     List($"launcher windows-x64 {Sha} ten https://example.invalid/a"),
                     List($"launcher windows-x64 {Sha} 0 https://example.invalid/a"),
                     List($"launcher windows-x64 {Sha} 10"),
                     List(good + "\n" + good),
                     List(good + $"\npart {Sha} 10 . https://example.invalid/a"),
                     List(good, tag: ".."), List(good, format: "one"), List(good, format: "0"),
                     "format 1\n" + good + "\n", "tag v3.0.0\n" + good + "\n",
                 })
            Throws<InvalidDataException>(() => Upgrader.ParseManifest(bad, bad.Contains("tag v3.0.0") ? "v3.0.0" : null),
                                         "A bad list was taken: " + bad.Replace("\n", " | "));
        Throws<Upgrader.TooNewException>(() => Upgrader.ParseManifest(List(good, format: "2"), "v3.0.0"), "A higher format was taken.");
        var comments = Upgrader.ParseManifest("# a note\r\n\r\n" + List("# another\n\n" + good).Replace("\n", "\r\n"), "v3.0.0");
        Check(comments.This.Size == 10, "Comments, blank lines or CRLF were not skipped.");
        var linuxOnly = Upgrader.ParseManifest(List($"launcher linux-x64 {Sha} 10 https://example.invalid/a"), "v3.0.0");
        Throws<InvalidDataException>(() => _ = linuxOnly.This, "A release without a Windows launcher gave one.");

        Check(Upgrader.ListUrl("v3.0.0-rc.1") == "https://github.com/NotRexed/Hookshot/releases/download/v3.0.0-rc.1/hookshot-launcher.txt",
              "A tag's list is not on its release.");
        Check(Upgrader.ListUrl("v2.3.0-12-g1a2b3c4") == "https://github.com/NotRexed/Hookshot/releases/download/nightly/hookshot-launcher.txt",
              "A nightly's list is not on the nightly release.");
        Check(Upgrader.ListUrl(null) == "https://github.com/NotRexed/Hookshot/releases/latest/download/hookshot-launcher.txt",
              "The latest release's list is not the latest download.");
    }

    static bool SameOrder(JsonNode? a, JsonNode? b) =>
        a is JsonObject x && b is JsonObject y
            ? x.Select(p => p.Key).SequenceEqual(y.Select(p => p.Key)) && x.All(p => SameOrder(p.Value, y[p.Key]))
            : true;

    static void Import(string fixtures)
    {
        var settings = BuilderSettings.Load(Path.Combine(fixtures, "builder-settings.json"));
        var want = JsonNode.Parse(File.ReadAllText(Path.Combine(fixtures, "import-windows.json")));
        var got = JsonNode.Parse(Upgrader.ImportJson(settings, null, "v2.3.0-rc.2", "fr-FR", @"D:\HookshotWork"));
        Check(JsonNode.DeepEquals(got, want), "The sample settings did not make the sample import:\n" + got);
        Check(SameOrder(got, want), "The import's keys are not in the contract's order.");
        // (no settings saved: the folder alone, every key there)
        var none = JsonNode.Parse(Upgrader.ImportJson(null, @"C:\Games\Hookshot", null, null, null))!;
        Check((string?)none["folder"] == @"C:\Games\Hookshot" && none["version"] == null && (string?)none["track"] == "release" &&
              (bool?)none["settings"]!["prepareShaders"] == true && none["settings"]!["memoryGb"] == null &&
              ((JsonObject)none["settings"]!).Count == 12, "An import without settings is not complete.");
        var nightly = JsonNode.Parse(Upgrader.ImportJson(new BuilderSettings { Track = "beta" }, "/g", "v2.3.0-4-g1a2b3c4", "", ""))!;
        Check((string?)nightly["track"] == "nightly" && nightly["settings"]!["language"] == null && nightly["settings"]!["work"] == null,
              "An unknown saved track or empty value was handed over.");
    }

    static void Stamps()
    {
        Check(Upgrader.RewriteStamp("version=v2.3.0\r\nbuilder=C:\\old\\HookshotBuilder.exe\r\nbuilder_args=x y\r\nother=1\r\n", @"C:\L\HookshotLauncher.exe")
              == "version=v2.3.0\nbuilder=C:\\L\\HookshotLauncher.exe\nother=1\n", "builder= or builder_args= was not rewritten.");
        Check(Upgrader.RewriteStamp("version=v2.3.0\n", "L") == "version=v2.3.0\nbuilder=L\n", "A stamp without builder= got none.");
        Check(Upgrader.RewriteStamp("version=v2.3.0\nbuilder_local=1\nbuilder=x\n", "L") == null, "A portable folder's stamp was rewritten.");
    }

    static void Forwards()
    {
        static string? F(params string[] a) => Upgrader.Forward(a) is { } f ? string.Join(" ", f) : null;
        Check(F("--launch", @"C:\g") == @"--launch C:\g", "--launch was not passed on.");
        Check(F("--update", @"C:\g", "--tag", "v3.0.0", "--fetched") == @"--update C:\g --tag v3.0.0 --fetched", "--update was not passed on.");
        Check(F("--update", @"C:\g") == @"--update C:\g", "--update without a tag was not passed on.");
        Check(F() == null && F("--play") == null && F("--launch") == null && F("--update", "") == null, "Something else was passed on.");
        var (folder, tag, fetched) = Upgrader.UpdateArgs(new[] { "app", "--update", "g", "--tag", "v3.0.0" });
        Check(folder == "g" && tag == "v3.0.0" && !fetched, "The --update arguments were not read.");
    }

    static void Files(string fixtures)
    {
        var root = Path.Combine(Path.GetTempPath(), "hookshot-upgrade-" + Guid.NewGuid().ToString("N"));
        try
        {
            var base_ = Path.Combine(root, "HookshotBuilder");
            var game = Path.Combine(root, "Games", "Hookshot é");
            Directory.CreateDirectory(base_);
            Directory.CreateDirectory(game);
            Environment.SetEnvironmentVariable("HOOKSHOT_SETUP_BASE", base_);   // (BuilderHome.Base, read once)
            File.WriteAllText(Path.Combine(base_, "builder-settings.json"), "{\"Out\":" + System.Text.Json.JsonSerializer.Serialize(game) +
                              ",\"Nup\":\"/d/game.nup\",\"MemoryGb\":8}");
            File.WriteAllText(Path.Combine(base_, "work.txt"), "/w/Hookshot build files\n");
            File.WriteAllText(Path.Combine(game, "hookshot_version.txt"), "version=v2.3.0\nbuilder=/old\n");
            File.WriteAllText(Path.Combine(game, "language.txt"), "de\n");
            var handed = Upgrader.ImportFor(null);
            Check(handed?.Folder == game, "The saved install folder was not handed over.");
            var json = JsonNode.Parse(handed!.Value.Json)!;
            Check((string?)json["version"] == "v2.3.0" && (string?)json["settings"]!["language"] == "de" &&
                  (string?)json["settings"]!["work"] == "/w/Hookshot build files" && (int?)json["settings"]!["memoryGb"] == 8 &&
                  (string?)json["settings"]!["nup"] == "/d/game.nup", "The folder's files were not read: " + json);
            Check(Upgrader.ImportFor(Path.Combine(root, "other"))?.Folder == Path.Combine(root, "other"), "The folder asked for was not used.");

            var home = Path.Combine(root, "HookshotLauncher");
            var path = Upgrader.WriteImport(home, game, handed.Value.Json);
            Check(Upgrader.WriteImport(home, game, handed.Value.Json) == path, "A second import of a folder added a file.");
            Check(Directory.GetFiles(Path.Combine(home, "import")).Length == 1 && path.EndsWith(".json") &&
                  File.ReadAllText(path) == handed.Value.Json, "The import file was not written whole.");
            Environment.SetEnvironmentVariable("HOOKSHOT_LAUNCHER_HOME", home);
            Check(Upgrader.Home == home && Upgrader.Installed() == null, "The launcher home is not HOOKSHOT_LAUNCHER_HOME.");
            Directory.CreateDirectory(Path.Combine(home, "app"));
            File.WriteAllText(Path.Combine(home, "app", "HookshotLauncher.exe"), "");
            Check(Upgrader.Installed() == Path.Combine(home, "app", "HookshotLauncher.exe"), "An installed launcher was not found.");
        }
        finally
        {
            Environment.SetEnvironmentVariable("HOOKSHOT_LAUNCHER_HOME", null);
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    static string Zip(string root, string name, params string[] entries)
    {
        var path = Path.Combine(root, name);
        using var zip = System.IO.Compression.ZipFile.Open(path, System.IO.Compression.ZipArchiveMode.Create);
        foreach (var entry in entries)
            using (var writer = new StreamWriter(zip.CreateEntry(entry).Open())) writer.Write(entry);
        return path;
    }

    static void Installs()
    {
        var root = Path.Combine(Path.GetTempPath(), "hookshot-install-" + Guid.NewGuid().ToString("N"));
        try
        {
            var home = Path.Combine(root, "home é");
            var app = Path.Combine(home, "app");
            Directory.CreateDirectory(root);
            bool Clean() => !Directory.Exists(app + ".part") && !Directory.Exists(app + ".old");
            bool Old() => File.Exists(Path.Combine(app, "HookshotLauncher.exe")) &&
                          File.ReadAllText(Path.Combine(app, "HookshotLauncher.exe")) == "old";

            var exe = Upgrader.Install(Zip(root, "first.zip", "HookshotLauncher.exe", "lib/a.dll"), home, CancellationToken.None);
            Check(exe == Path.Combine(app, "HookshotLauncher.exe") && File.Exists(Path.Combine(app, "lib", "a.dll")) && Clean(),
                  "The launcher was not installed whole.");
            Directory.Delete(app, true);
            Directory.CreateDirectory(app);
            File.WriteAllText(Path.Combine(app, "HookshotLauncher.exe"), "old");
            File.WriteAllText(Path.Combine(app, "stale.dll"), "old");

            Throws<FileNotFoundException>(() => Upgrader.Install(Zip(root, "noexe.zip", "lib/a.dll"), home, CancellationToken.None),
                                          "A zip without the launcher was installed.");
            Check(Old() && Clean(), "A zip without the launcher changed the installed one.");
            Throws<IOException>(() => Upgrader.Install(Zip(root, "escape.zip", "HookshotLauncher.exe", "../escaped.txt"), home,
                                                       CancellationToken.None), "A zip entry outside app.part was unpacked.");
            Check(Old() && Clean() && !File.Exists(Path.Combine(home, "escaped.txt")), "A zip entry escaped app.part.");
            using (var cancelled = new CancellationTokenSource())
            {
                cancelled.Cancel();
                Throws<OperationCanceledException>(() => Upgrader.Install(Zip(root, "cancel.zip", "HookshotLauncher.exe"), home, cancelled.Token),
                                                   "A cancelled upgrade went on.");
            }
            Check(Old() && Clean(), "A cancelled upgrade changed the installed launcher.");

            Upgrader.Install(Zip(root, "second.zip", "HookshotLauncher.exe"), home, CancellationToken.None);
            Check(File.ReadAllText(Path.Combine(app, "HookshotLauncher.exe")) == "HookshotLauncher.exe" &&
                  !File.Exists(Path.Combine(app, "stale.dll")) && Clean(), "An upgrade over an installed launcher did not replace it whole.");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    static void Main(string[] args)
    {
        var fixtures = args[0];
        Manifests(fixtures);
        Import(fixtures);
        Stamps();
        Forwards();
        Files(fixtures);
        Installs();
        // (the hand-over's texts are English only, after the update's: every text there)
        Check(Strings.All[0].Text.Length == Enum.GetValues<S>().Length, "Strings.cs has not one English text a name.");
        Console.WriteLine($"Builder upgrade checks: {checks - failures} passed, {failures} failed.");
        if (failures != 0) Environment.ExitCode = 1;
    }
}

namespace HookshotBuilder
{
    sealed class Tools
    {
        public string? Version => "v2.3.0";
        public static Tools? Find() => new();
    }

    sealed class MainWindow
    {
        public CancellationToken DownloadToken => CancellationToken.None;
        public void Note(string _) { }
        public void BeginUpdate(string folder, string? tag) { }
        public void UpdateBuild(Tools tools, string folder) => throw new Exception("Unexpected build.");
        public void DownloadProgress(double value) { }
        public void DownloadFailed(string reason) => throw new Exception("Unexpected update: " + reason);
        public string Text(S s) => Strings.All[0].Text[(int)s];
        public void HandoverNote(string _) { }
        public void HandoverProgress(double _) { }
    }
}

namespace System.Windows
{
    sealed class Application
    {
        public static Application Current => new();
        public void Shutdown() => throw new Exception("Unexpected shutdown.");
    }
}
