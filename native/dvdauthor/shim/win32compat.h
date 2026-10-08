/* Force-included (gcc -include) when building dvdauthor for Windows with MinGW.
 * System headers are pulled in first, so the macros below do not touch their prototypes. */
#ifndef DVD_WIN32COMPAT_H
#define DVD_WIN32COMPAT_H

#include <direct.h>
#include <io.h>
#include <string.h>
#include <sys/stat.h>

#define mkdir(path, mode) _mkdir(path)
#define fsync(fd) _commit(fd)
#define bzero(p, n) memset((p), 0, (n))

#endif
