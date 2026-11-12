using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;

namespace HookshotBuilder;

/// The hand-over to the Hookshot Launcher (3.0), on Windows: the contract is docs/launcher-upgrade.md, and its sample files are in
/// tests/fixtures/launcher/. A release that ships the launcher carries hookshot-launcher.txt (a 404 means a Builder release, updated
/// as before). Upgrade downloads this platform's zip and checks it, unpacks it as <launcher home>\app, drops an import file for the
/// game folder in <launcher home>\import\, points the folder's hookshot_version.txt at the launcher, and starts it with --launch.
static class Upgrader
{
    public const string ListName = "hookshot-launcher.txt";
    public const int Format = 1;
    public const string Platform = "windows-x64";
    static readonly string[] Platforms = { "windows-x64", "linux-x64" };   // (any other platform's line is skipped)
    public const string ReleasesPage = "https://github.com/NotRexed/Hookshot/releases";
    const string LauncherExe = "HookshotLauncher.exe";

    public sealed record Line(string Platform, string Sha, long Size, string Url);

    public sealed record Manifest(string Tag, IReadOnlyDictionary<string, Line> Launchers)
    {
        /// This platform's launcher; InvalidDataException when the release has none for Windows
        public Line This => Launchers.TryGetValue(Platform, out var line) ? line
            : throw new InvalidDataException($"This release has no Hookshot Launcher for {Platform}. Download it from the release page.");
    }

    /// A format this Builder does not know: it does not upgrade, and says to download the launcher from the release page
    public sealed class TooNewException(string message) : Exception(message);

    static readonly Regex TagName = new(@"^[0-9A-Za-z._+-]{1,128}$");
    static readonly Regex Sha = new(@"^[0-9a-f]{64}$");
    static readonly Regex Size = new(@"^[1-9][0-9]{0,11}$");

    /// hookshot-launcher.txt (section 1), as strictly as the setup lists: tag must be the tag asked for (null: the latest release,
    /// any version name), format 1 (a higher one is TooNewException), one launcher line a platform
    public static Manifest ParseManifest(string text, string? tag)
    {
        string? found = null;
        int? format = null;
        var launchers = new Dictionary<string, Line>();
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith('#')) continue;
            var bits = line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
            if (bits[0] == "tag" && bits.Length == 2 && found == null) found = bits[1];
            else if (bits[0] == "format" && bits.Length == 2 && format == null)
                format = Regex.IsMatch(bits[1], "^[0-9]{1,6}$") ? int.Parse(bits[1])
                    : throw new InvalidDataException("The launcher list's format is not a number.");
            else if (bits[0] == "launcher" && bits.Length == 5)
            {
                if (!Platforms.Contains(bits[1])) continue;
                if (launchers.ContainsKey(bits[1])) throw new InvalidDataException($"The launcher list names {bits[1]} twice.");
                if (!Sha.IsMatch(bits[2]) || !Size.IsMatch(bits[3]) || !bits[4].StartsWith("https://", StringComparison.Ordinal))
                    throw new InvalidDataException("A launcher line has a bad checksum, size or link.");
                launchers[bits[1]] = new Line(bits[1], bits[2], long.Parse(bits[3]), bits[4]);
            }
            else throw new InvalidDataException("The launcher list has a line it should not.");
        }
        if (found == null || format == null) throw new InvalidDataException("The launcher list has no tag or format.");
        if (!TagName.IsMatch(found) || found is "." or "..") throw new InvalidDataException("The launcher list's tag is not a version name.");
        if (tag != null && found != tag) throw new InvalidDataException($"The launcher list is {found}, not the {tag} asked for.");
        if (format > Format)
            throw new TooNewException($"Hookshot {found} needs a newer Builder to move over to its launcher. Download the Hookshot " +
                                      "Launcher from the release page.");
        if (format < 1) throw new InvalidDataException("The launcher list's format is not 1.");
        return new Manifest(found, launchers);
    }

    /// The release that holds a tag's files (the nightly's are on the rolling nightly release), as Updater's ReleaseOf
    static string ReleaseOf(string tag) => Updater.TrackOf(tag) == Updater.Nightly ? Updater.Nightly : tag;

    public static string ListUrl(string? tag) => tag == null
        ? "https://github.com/NotRexed/Hookshot/releases/latest/download/" + ListName
        : $"https://github.com/NotRexed/Hookshot/releases/download/{ReleaseOf(tag)}/{ListName}";

    public static string ReleasePage(string? tag) => tag == null ? ReleasesPage + "/latest" : ReleasesPage + "/tag/" + ReleaseOf(tag);

    /// The launcher release a tag is, or null when it is a Builder release (its hookshot-launcher.txt is a 404). A file download,
    /// not the API. TooNewException or InvalidDataException for a list it cannot use, HttpRequestException when GitHub did not answer
    public static async Task<Manifest?> Probe(string? tag)
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("HookshotBuilder");
        for (var attempt = 0; ; attempt++)
        {
            using var response = await http.GetAsync(ListUrl(tag));
            if (response.StatusCode == HttpStatusCode.NotFound) return null;
            if (response.IsSuccessStatusCode) return ParseManifest(await response.Content.ReadAsStringAsync(), tag);
            if ((int)response.StatusCode < 500 || attempt == 2)
                throw new HttpRequestException($"GitHub returned HTTP {(int)response.StatusCode} for {ListName}.", null, response.StatusCode);
            await Task.Delay(TimeSpan.FromSeconds(2 << attempt));
        }
    }

    // ---- where the launcher lives (section 2) ----
    public static string Home => Environment.GetEnvironmentVariable("HOOKSHOT_LAUNCHER_HOME") is { Length: > 0 } home ? home
        : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HookshotLauncher");

    /// <home>\app\HookshotLauncher.exe when it is installed, else null
    public static string? Installed()
    {
        var exe = Path.Combine(Home, "app", LauncherExe);
        return File.Exists(exe) ? exe : null;
    }

    /// What the Builder hands to an installed launcher instead of running (section 4): --launch <folder>, and
    /// --update <folder> [--tag <tag>] [--fetched]. null: anything else
    public static List<string>? Forward(IReadOnlyList<string> args)
    {
        string? Value(string name)
        {
            for (var i = 0; i + 1 < args.Count; i++)
                if (args[i] == name) return args[i + 1].Length > 0 ? args[i + 1] : null;
            return null;
        }
        if (Value("--update") is { } folder)
        {
            var forward = new List<string> { "--update", folder };
            if (Value("--tag") is { } tag) forward.AddRange(new[] { "--tag", tag });
            if (args.Contains("--fetched")) forward.Add("--fetched");
            return forward;
        }
        return Value("--launch") is { } launch ? new List<string> { "--launch", launch } : null;
    }

    /// The --update arguments the game's offer passes (host/hos_update.c), as Updater.FromCommandLine reads them
    public static (string? Folder, string? Tag, bool Fetched) UpdateArgs(IReadOnlyList<string> a)
    {
        string? folder = null, tag = null;
        var fetched = false;
        for (var i = 0; i < a.Count; i++)
        {
            if (a[i] == "--update" && i + 1 < a.Count) folder = a[++i];
            else if (a[i] == "--tag" && i + 1 < a.Count) tag = a[++i];
            else if (a[i] == "--fetched") fetched = true;
        }
        return (folder, tag, fetched);
    }

    // ---- what the Builder remembered, handed over (section 3) ----

    /// The import file from builder-settings.json's values (paths as loaded: BuilderHome.LoadPath), the game folder (null: the
    /// saved install folder), its stamp's version, its language.txt and the build files folder of work.txt
    public static string ImportJson(BuilderSettings? s, string? folder, string? version, string? language, string? work)
    {
        var track = s?.Track is { } saved && saved is Updater.Release or Updater.Candidate or Updater.Nightly ? saved : Updater.TrackOf(version);
        using var stream = new MemoryStream();
        using (var j = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            j.WriteStartObject();
            j.WriteNumber("format", 1);
            j.WriteString("folder", folder ?? s?.Out);
            j.WriteString("version", version);
            j.WriteString("track", track);
            j.WriteBoolean("default", true);
            j.WriteStartObject("settings");
            j.WriteString("nup", Empty(s?.Nup));
            j.WriteString("romfs", Empty(s?.Romfs));
            j.WriteString("exefs", Empty(s?.Exefs));
            j.WriteString("language", Empty(language));
            j.WriteBoolean("dlss", s?.Dlss == true);
            j.WriteBoolean("dlssLicense", s?.DlssLicense == true);
            j.WriteBoolean("fsr", s?.Fsr == true);
            j.WriteBoolean("fsrLicense", s?.FsrLicense == true);
            j.WriteBoolean("prepareShaders", s?.PrepareLater != true);
            if (s?.MemoryGb is { } gb) j.WriteNumber("memoryGb", gb);
            else j.WriteNull("memoryGb");
            j.WriteNull("jobs");
            j.WriteString("work", Empty(work));
            j.WriteEndObject();
            j.WriteEndObject();
        }
        return Encoding.UTF8.GetString(stream.ToArray()).Replace("\r\n", "\n") + "\n";
    }

    static string? Empty(string? value) => string.IsNullOrEmpty(value) ? null : value;

    static string? FirstLine(string path)
    {
        try { return File.Exists(path) ? Empty(File.ReadLines(path).FirstOrDefault()?.Trim()) : null; }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }

    static string? StampVersion(string folder)
    {
        try
        {
            foreach (var line in File.ReadAllLines(Path.Combine(folder, "hookshot_version.txt")))
                if (line.StartsWith("version=")) return Empty(line[8..].Trim());
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        return null;
    }

    /// ImportJson for a folder on this PC (null: the saved install folder), from the Builder's own files: (the folder, the file),
    /// or null when no folder is known
    public static (string Folder, string Json)? ImportFor(string? folder)
    {
        var s = BuilderSettings.Load(Path.Combine(BuilderHome.Base, "builder-settings.json"));
        if (s != null)
        {
            s.Out = BuilderHome.LoadPath(s.Out);
            s.Nup = BuilderHome.LoadPath(s.Nup);
            s.Romfs = BuilderHome.LoadPath(s.Romfs);
            s.Exefs = BuilderHome.LoadPath(s.Exefs);
        }
        folder = Empty(folder) ?? Empty(s?.Out);
        if (folder == null) return null;
        folder = Path.TrimEndingDirectorySeparator(Path.GetFullPath(folder));
        var work = BuilderHome.LoadPath(FirstLine(Path.Combine(BuilderHome.Base, "work.txt")));
        return (folder, ImportJson(s, folder, StampVersion(folder), FirstLine(Path.Combine(folder, "language.txt")), work));
    }

    /// hookshot_version.txt (section 4): builder= names the launcher, builder_args= goes, every other line stays. null: a portable
    /// folder (builder_local=1), left as it is
    public static string? RewriteStamp(string text, string launcher)
    {
        var lines = text.Replace("\r\n", "\n").Split('\n').ToList();
        if (lines.Count > 0 && lines[^1].Length == 0) lines.RemoveAt(lines.Count - 1);
        if (lines.Any(l => l.Trim() == "builder_local=1")) return null;
        var output = new List<string>();
        var named = false;
        foreach (var line in lines)
        {
            if (line.StartsWith("builder_args=")) continue;
            if (line.StartsWith("builder="))
            {
                if (!named) output.Add("builder=" + launcher);
                named = true;
                continue;
            }
            output.Add(line);
        }
        if (!named) output.Add("builder=" + launcher);
        return string.Join("\n", output) + "\n";
    }

    static void WriteAtomic(string path, string text)
    {
        var part = path + ".part";
        File.WriteAllText(part, text, new UTF8Encoding(false));
        File.Move(part, path, overwrite: true);
    }

    /// The import file for its folder: <home>\import\builder-<hash>.json, written as .json.part and renamed (one name a folder)
    public static string WriteImport(string home, string folder, string json)
    {
        var dir = Path.Combine(home, "import");
        Directory.CreateDirectory(dir);
        var hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(folder.ToLowerInvariant())));
        var path = Path.Combine(dir, "builder-" + hash[..16].ToLowerInvariant() + ".json");
        WriteAtomic(path, json);
        return path;
    }

    /// A Hookshot Launcher running on this PC: its files cannot be replaced, so the upgrade asks to close it before downloading
    static bool LauncherRunning()
    {
        var running = Process.GetProcessesByName(Path.GetFileNameWithoutExtension(LauncherExe));
        foreach (var p in running) p.Dispose();
        return running.Length > 0;
    }

    /// Section 2: a checked zip unpacked to <home>\app.part and swapped in for <home>\app. The old app is renamed aside first
    /// rather than deleted, because a delete stops half way at the first file in use and leaves a launcher that cannot start;
    /// a rename fails whole. Any failure, or a cancel before the swap, leaves no app.part and the old app as it was
    public static string Install(string zip, string home, CancellationToken token)
    {
        var app = Path.Combine(home, "app");
        var part = app + ".part";
        var old = app + ".old";
        Directory.CreateDirectory(home);
        try
        {
            if (Directory.Exists(part)) Directory.Delete(part, true);
            if (Directory.Exists(old)) Directory.Delete(old, true);
            // (ExtractToDirectory refuses an entry that would land outside part, ..\ or rooted: an IOException)
            ZipFile.ExtractToDirectory(zip, part);
            if (!File.Exists(Path.Combine(part, LauncherExe)))
                throw new FileNotFoundException($"The download has no {LauncherExe} (your antivirus may have removed it).");
            token.ThrowIfCancellationRequested();
            var had = Directory.Exists(app);
            if (had)
            {
                try { Directory.Move(app, old); }
                catch (IOException e) { throw new IOException("Close the Hookshot Launcher, then try again.", e); }
            }
            try { Directory.Move(part, app); }
            catch (Exception) when (had)
            {
                Directory.Move(old, app);
                throw;
            }
        }
        catch (Exception)
        {
            try { if (Directory.Exists(part)) Directory.Delete(part, true); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
            throw;
        }
        try { if (Directory.Exists(old)) Directory.Delete(old, true); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        return Path.Combine(app, LauncherExe);
    }

    /// Section 6, steps 3 to 5: the zip downloaded and checked (size and SHA-256, before anything is unpacked), installed (Install);
    /// the import file and the stamp; the launcher started with --launch <folder>; this app closes
    public static async Task Run(MainWindow w, Manifest m, string? folder)
    {
        var line = m.This;
        if (LauncherRunning()) throw new IOException("The Hookshot Launcher is open. Close it, then try again.");
        var token = w.DownloadToken;
        using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("HookshotBuilder");
        var cache = Path.Combine(BuilderHome.Base, "update");
        Directory.CreateDirectory(cache);
        var zip = Path.Combine(cache, "HookshotLauncher.zip");
        w.HandoverNote(string.Format(w.Text(S.UpgradeDownloading), m.Tag));
        var home = Home;
        string exe;
        try
        {
            await Updater.DownloadWithRetries(w, http, line.Url, null, zip, line.Size, "sha256:" + line.Sha, token, w.HandoverProgress);
            if (new FileInfo(zip).Length != line.Size) throw new InvalidDataException("The Hookshot Launcher did not download whole.");
            exe = await Task.Run(() => Install(zip, home, token), token);
        }
        finally
        {
            try { File.Delete(zip); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
        // (a failure here leaves the launcher installed, and it reads the Builder's settings itself on its first start)
        w.HandoverNote(w.Text(S.UpgradeHanding));
        var handed = ImportFor(folder);
        try
        {
            if (handed is { } h)
            {
                WriteImport(home, h.Folder, h.Json);
                var stamp = Path.Combine(h.Folder, "hookshot_version.txt");
                if (File.Exists(stamp) && RewriteStamp(File.ReadAllText(stamp), exe) is { } text) WriteAtomic(stamp, text);
            }
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        Start(exe, handed is { } at ? new List<string> { "--launch", at.Folder } : new List<string>());
        Application.Current.Shutdown();
    }

    /// The launcher with these arguments, from its own folder, without the Builder home this app was given (BuilderHome.PassTo)
    public static void Start(string exe, IEnumerable<string> args)
    {
        var si = new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(exe)! };
        foreach (var arg in args) si.ArgumentList.Add(arg);
        si.Environment.Remove("HOOKSHOT_SETUP_BASE");
        si.Environment.Remove("HOOKSHOT_BUILDER_PORTABLE");
        Process.Start(si);
    }
}
