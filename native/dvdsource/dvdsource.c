/*
 * DvdSource: AviSynth source filter that pulls frames from the engine's frame server.
 *
 * HCEnc is a 32-bit program that only reads AviSynth scripts, while the engine's
 * VapourSynth pipeline runs in a 64-bit Python process. The engine serves frames over a
 * Windows named pipe (see src/dvd/video/frameserver.py); this plugin requests them by
 * frame number, so random access and multiple encoder passes work.
 *
 * Usage in a script:  LoadCPlugin("DvdSource.dll")  DvdSource("pipe-name")
 *
 * Protocol (little endian, byte-mode pipe):
 *   server -> header: "DVDF" u32 version, i32 width, i32 height, u32 fps_num, u32 fps_den,
 *                     i32 num_frames, u32 format (1 = YV12 8-bit)
 *   client -> i32 frame number
 *   server -> Y, U, V planes, tightly packed
 */

#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define AVSC_NO_DECLSPEC
#include "avisynth_c.h"

#define PROTOCOL_VERSION 1
#define FORMAT_YV12 1

typedef struct {
    char magic[4];
    uint32_t version;
    int32_t width;
    int32_t height;
    uint32_t fps_num;
    uint32_t fps_den;
    int32_t num_frames;
    uint32_t format;
} Header;

typedef struct {
    HANDLE pipe;
    CRITICAL_SECTION lock;
    uint8_t *buffer;
    size_t frame_size;
} Source;

static AVS_Library *avs;

static int read_full(HANDLE h, void *buf, DWORD size)
{
    uint8_t *p = (uint8_t *)buf;
    while (size > 0) {
        DWORD got = 0;
        if (!ReadFile(h, p, size, &got, NULL) || got == 0)
            return 0;
        p += got;
        size -= got;
    }
    return 1;
}

static int write_full(HANDLE h, const void *buf, DWORD size)
{
    const uint8_t *p = (const uint8_t *)buf;
    while (size > 0) {
        DWORD put = 0;
        if (!WriteFile(h, p, size, &put, NULL) || put == 0)
            return 0;
        p += put;
        size -= put;
    }
    return 1;
}

static void copy_plane(AVS_VideoFrame *frame, int plane, const uint8_t *src, int width, int height)
{
    BYTE *dst = avs->avs_get_write_ptr_p(frame, plane);
    int pitch = avs->avs_get_pitch_p(frame, plane);
    for (int y = 0; y < height; y++)
        memcpy(dst + (size_t)y * pitch, src + (size_t)y * width, width);
}

static AVS_VideoFrame *AVSC_CC get_frame(AVS_FilterInfo *fi, int n)
{
    Source *s = (Source *)fi->user_data;
    int w = fi->vi.width, h = fi->vi.height;
    int32_t request = n;
    AVS_VideoFrame *frame = avs->avs_new_video_frame_a(fi->env, &fi->vi, AVS_FRAME_ALIGN);

    EnterCriticalSection(&s->lock);
    int ok = write_full(s->pipe, &request, sizeof request)
          && read_full(s->pipe, s->buffer, (DWORD)s->frame_size);
    LeaveCriticalSection(&s->lock);

    if (!ok) {
        fi->error = "DvdSource: lost connection to the frame server";
        return frame;
    }
    const uint8_t *y = s->buffer;
    const uint8_t *u = y + (size_t)w * h;
    const uint8_t *v = u + (size_t)(w / 2) * (h / 2);
    copy_plane(frame, AVS_PLANAR_Y, y, w, h);
    copy_plane(frame, AVS_PLANAR_U, u, w / 2, h / 2);
    copy_plane(frame, AVS_PLANAR_V, v, w / 2, h / 2);
    return frame;
}

static int AVSC_CC get_parity(AVS_FilterInfo *fi, int n)
{
    (void)fi; (void)n;
    return 0;
}

static int AVSC_CC get_audio(AVS_FilterInfo *fi, void *buf, int64_t start, int64_t count)
{
    (void)fi; (void)buf; (void)start; (void)count;
    return 0;
}

static int AVSC_CC set_cache_hints(AVS_FilterInfo *fi, int hints, int range)
{
    (void)fi; (void)range;
    /* Frames are produced on demand by the server; declare the filter MT-serialized. */
    return hints == AVS_CACHE_GET_MTMODE ? AVS_MT_SERIALIZED : 0;
}

static void AVSC_CC free_filter(AVS_FilterInfo *fi)
{
    Source *s = (Source *)fi->user_data;
    if (!s)
        return;
    int32_t bye = -1;
    write_full(s->pipe, &bye, sizeof bye);
    CloseHandle(s->pipe);
    DeleteCriticalSection(&s->lock);
    free(s->buffer);
    free(s);
    fi->user_data = NULL;
}

static HANDLE connect_pipe(const char *name)
{
    char path[512];
    snprintf(path, sizeof path, "\\\\.\\pipe\\%s", name);
    for (int attempt = 0; attempt < 100; attempt++) {
        HANDLE h = CreateFileA(path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
        if (h != INVALID_HANDLE_VALUE)
            return h;
        if (GetLastError() == ERROR_PIPE_BUSY)
            WaitNamedPipeA(path, 2000);
        else
            Sleep(100);
    }
    return INVALID_HANDLE_VALUE;
}

static AVS_Value AVSC_CC create(AVS_ScriptEnvironment *env, AVS_Value args, void *user_data)
{
    (void)user_data;
    const char *name = avs_as_string(avs_array_elt(args, 0));
    HANDLE pipe = connect_pipe(name);
    if (pipe == INVALID_HANDLE_VALUE)
        return avs_new_value_error("DvdSource: cannot connect to the frame server pipe");

    Header hd;
    if (!read_full(pipe, &hd, sizeof hd) || memcmp(hd.magic, "DVDF", 4) != 0
        || hd.version != PROTOCOL_VERSION) {
        CloseHandle(pipe);
        return avs_new_value_error("DvdSource: frame server sent an invalid header");
    }
    if (hd.format != FORMAT_YV12 || hd.width % 2 || hd.height % 2) {
        CloseHandle(pipe);
        return avs_new_value_error("DvdSource: only YV12 with even dimensions is supported");
    }

    Source *s = (Source *)calloc(1, sizeof *s);
    s->pipe = pipe;
    s->frame_size = (size_t)hd.width * hd.height * 3 / 2;
    s->buffer = (uint8_t *)malloc(s->frame_size);
    InitializeCriticalSection(&s->lock);

    AVS_FilterInfo *fi;
    AVS_Value none = avs_void;
    AVS_Clip *clip = avs->avs_new_c_filter(env, &fi, none, 0);
    memset(&fi->vi, 0, sizeof fi->vi);
    fi->vi.width = hd.width;
    fi->vi.height = hd.height;
    fi->vi.fps_numerator = hd.fps_num;
    fi->vi.fps_denominator = hd.fps_den;
    fi->vi.num_frames = hd.num_frames;
    fi->vi.pixel_type = AVS_CS_YV12;
    fi->user_data = s;
    fi->get_frame = get_frame;
    fi->get_parity = get_parity;
    fi->get_audio = get_audio;
    fi->set_cache_hints = set_cache_hints;
    fi->free_filter = free_filter;

    AVS_Value result;
    avs->avs_set_to_clip(&result, clip);
    avs->avs_release_clip(clip);
    return result;
}

__declspec(dllexport) const char *AVSC_CC avisynth_c_plugin_init(AVS_ScriptEnvironment *env)
{
    if (!avs)
        avs = avs_load_library();
    if (!avs)
        return "DvdSource: could not load the AviSynth API";
    avs->avs_add_function(env, "DvdSource", "s", create, NULL);
    return "DvdSource: frames from the DVD engine frame server";
}
