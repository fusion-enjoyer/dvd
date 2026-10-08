/*
 * Launcher for the packaged app: runs the bundled Python with the app module.
 *
 *   <app>\DVD Studyo.exe  ->  <app>\python\pythonw.exe -m dvd.gui.app [args]   (built with -DGUI)
 *   <app>\dvd.exe         ->  <app>\python\python.exe  -m dvd [args]           (console)
 *
 * The console launcher waits and returns Python's exit code.
 */

#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

#ifdef GUI
#define PYTHON L"pythonw.exe"
#define MODULE L"dvd.gui.app"
#else
#define PYTHON L"python.exe"
#define MODULE L"dvd"
#endif

/* The command line after the program name, so arguments pass through unchanged. */
static const wchar_t *arguments(const wchar_t *cmd)
{
    int quoted = 0;
    while (*cmd && (quoted || (*cmd != L' ' && *cmd != L'\t'))) {
        if (*cmd == L'"')
            quoted = !quoted;
        cmd++;
    }
    while (*cmd == L' ' || *cmd == L'\t')
        cmd++;
    return cmd;
}

static int run(void)
{
    wchar_t dir[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (n == 0 || n == MAX_PATH)
        return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash)
        *slash = 0;

    wchar_t python[MAX_PATH + 32];
    swprintf(python, MAX_PATH + 32, L"%ls\\python\\%ls", dir, PYTHON);
    const wchar_t *args = arguments(GetCommandLineW());
    size_t size = wcslen(python) + wcslen(args) + 64;
    wchar_t *cmd = malloc(size * sizeof *cmd);
    swprintf(cmd, size, L"\"%ls\" -m %ls %ls", python, MODULE, args);

    STARTUPINFOW si = {sizeof si};
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(python, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        MessageBoxW(NULL, L"python\\ klasörü bulunamadı. Uygulamayı yeniden kurun.",
                    L"DVD Stüdyo", MB_ICONERROR);
        free(cmd);
        return 1;
    }
    free(cmd);
    DWORD code = 0;
#ifndef GUI
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
#endif
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}

#ifdef GUI
int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR c, int s)
{
    (void)h; (void)p; (void)c; (void)s;
    return run();
}
#else
int wmain(void)
{
    return run();
}
#endif
