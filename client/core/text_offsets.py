"""Convert Python string indices to Windows text offsets without touching UI.

Keep suggestions and error sounds aligned after emoji and multiline text.
These helpers do not change cursor movement or screen-reader behavior.
"""


def native_offset(text: str, index: int, newline_width: int = 1) -> int:
    prefix = text[:max(0, min(index, len(text)))]
    return len(prefix.encode("utf-16-le", errors="surrogatepass")) // 2 + (
        newline_width - 1
    ) * prefix.count("\n")


def text_index(text: str, offset: int, newline_width: int = 1) -> int:
    position = 0
    for index, char in enumerate(text):
        width = newline_width if char == "\n" else (2 if ord(char) > 0xFFFF else 1)
        if position >= offset or position + width > offset:
            return index
        position += width
    return len(text)
