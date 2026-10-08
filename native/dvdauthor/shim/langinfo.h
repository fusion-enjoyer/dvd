/* dvdauthor asks for the locale charset only as a default for subtitle text.
 * The engine always passes the charset explicitly, so UTF-8 is enough here. */
#ifndef DVD_LANGINFO_H
#define DVD_LANGINFO_H

#define CODESET 14

static inline char *nl_langinfo(int item)
{
    (void)item;
    return "UTF-8";
}

#endif
