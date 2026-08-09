#include <stdio.h>

/* Positive control: gets() is widely flagged as unsafe (buffer overflow). */
void unsafe_read(void) {
    char buf[16];
    gets(buf);
    puts(buf);
}

int main(void) {
    unsafe_read();
    return 0;
}
