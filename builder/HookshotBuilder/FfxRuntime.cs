using System.IO;
using System.Net.Http;
using System.Security.Cryptography;

namespace HookshotBuilder;

/// AMD's FSR runtime for Vulkan (FSR SDK v2.4.0: FSR 4.1.2), fetched by the launcher itself for a release whose make_game.py
/// takes --fsr but cannot fetch it (no --fetch-fsr-runtime: v2.1.0 and the releases before it). Without it such a build has
/// FSR 4 compiled in and nothing for it to load, and the Upscaler row does not offer it.
///
/// The same pinned files and SHA-256s as scripts/ffx_sdk.py, which a newer make_game.py runs itself
/// (tests/test_ffx_runtime_pins.py keeps the two the same). AMD's files, signed by AMD, under AMD's FSR SDK license, which
/// the launcher asks to be accepted before any build with FSR 4. Kept in the builder's ffx-sdk folder (Storage.FfxSdk), each
/// one checked before it is used, and copied beside the game, where gpu/vk/vk_fsr4.cpp looks for them
static class FfxRuntime
{
    const string Commit = "7539ae8b6568ad29ed78a753404351daf3b5cca7";   // (tag v2.4.0: FSR 4.1.2, FSR 3.1.6)
    const string Base = "https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/" + Commit;

    /// (path in AMD's repository, its SHA-256, its name here)
    static readonly (string Path, string Sha, string Name)[] Files =
    {
        ("Kits/FidelityFX/signedbin/amd_fidelityfx_loader_vk.dll",
         "38a56a01fb3565c0757d9f5c1e4e69de4b65e5f2e5769b323b200dc1f142bab9", "amd_fidelityfx_loader_vk.dll"),
        ("Kits/FidelityFX/signedbin/amd_fidelityfx_upscaler_vk.dll",
         "4a7e895af6e0b615d40a84d59eb8c2b1054ad91cdd0c739567940270d51bdab7", "amd_fidelityfx_upscaler_vk.dll"),
        ("Kits/FidelityFX/docs/license.md",
         "32357259b965d6a8001e9e508ba60eda6034027c5923a7d226ffbaff813c2bfb", "LICENSE-AMD-FSR-SDK.md"),
    };

    /// The runtime in folder, each file there already with its SHA-256 or downloaded and checked (a download that does not
    /// match is deleted). Null when all of it is there, else why not
    public static async Task<string?> Ensure(string folder, CancellationToken cancel = default)
    {
        try
        {
            Directory.CreateDirectory(folder);
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(120) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd("Hookshot");
            foreach (var (path, sha, name) in Files)
            {
                var dst = System.IO.Path.Combine(folder, name);
                if (Matches(dst, sha)) continue;
                var tmp = dst + ".part";
                await using (var from = await http.GetStreamAsync(Base + "/" + path, cancel))
                await using (var to = File.Create(tmp))
                    await from.CopyToAsync(to, cancel);
                if (!Matches(tmp, sha))
                {
                    File.Delete(tmp);
                    return $"{name} as downloaded is not AMD's file (its SHA-256 differs).";
                }
                File.Move(tmp, dst, overwrite: true);
            }
            return null;
        }
        catch (OperationCanceledException) { return "cancelled"; }
        catch (Exception e) when (e is HttpRequestException or IOException or UnauthorizedAccessException)
        {
            return "it could not be downloaded from AMD's repository: " + e.Message;
        }
    }

    /// The runtime copied beside the game (gpu/vk/vk_fsr4.cpp: the game folder), each file checked first. Null when done
    public static string? CopyTo(string from, string gameFolder)
    {
        try
        {
            foreach (var (_, sha, name) in Files)
            {
                var src = System.IO.Path.Combine(from, name);
                if (!Matches(src, sha)) return $"{name} is missing or not AMD's file.";
                File.Copy(src, System.IO.Path.Combine(gameFolder, name), overwrite: true);
            }
            return null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return "it could not be copied into the game folder: " + e.Message; }
    }

    static bool Matches(string file, string sha)
    {
        if (!File.Exists(file)) return false;
        using var stream = File.OpenRead(file);
        return Convert.ToHexString(SHA256.HashData(stream)).Equals(sha, StringComparison.OrdinalIgnoreCase);
    }
}
