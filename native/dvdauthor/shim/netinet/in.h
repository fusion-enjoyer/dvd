/* Byte-order helpers without pulling in winsock2.h (and windows.h) into dvdauthor. */
#ifndef DVD_NETINET_IN_H
#define DVD_NETINET_IN_H

#include <stdint.h>

static inline uint32_t htonl(uint32_t x) { return __builtin_bswap32(x); }
static inline uint32_t ntohl(uint32_t x) { return __builtin_bswap32(x); }
static inline uint16_t htons(uint16_t x) { return __builtin_bswap16(x); }
static inline uint16_t ntohs(uint16_t x) { return __builtin_bswap16(x); }

#endif
