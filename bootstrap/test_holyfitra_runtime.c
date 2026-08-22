#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void *hf_dyn_i32_new(uint64_t capacity);
_Bool hf_dyn_i32_push(void *, int32_t);
uint64_t hf_dyn_i32_len(void *);
int32_t hf_dyn_i32_get(void *, uint64_t);
void hf_dyn_i32_free(void *);
void *hf_file_open(const char *);
void *hf_file_read_all(void *);
void hf_file_close(void *);
void *hf_read_text(const char *);
void *hf_buf_new(uint64_t);
_Bool hf_buf_append_byte(void *, int32_t);
_Bool hf_buf_append_str(void *, const char *);
_Bool hf_buf_append_i32(void *, int32_t);
char *hf_buf_finish(void *);
void hf_buf_free(void *);
void hf_string_free(void *);
char *hf_path_canonicalize(const char *);
char *hf_string_slice32(const char *, int32_t, int32_t);
_Bool hf_write_text(const char *, const char *);

int main(void) {
    assert(hf_dyn_i32_new(0) == NULL);
    assert(hf_dyn_i32_new(((uint64_t)1u << 20) + 1) == NULL);
    void *array = hf_dyn_i32_new(2);
    assert(array != NULL);
    assert(hf_dyn_i32_len(array) == 0);
    assert(hf_dyn_i32_push(array, 40));
    assert(hf_dyn_i32_push(array, 2));
    assert(!hf_dyn_i32_push(array, 99));
    assert(hf_dyn_i32_len(array) == 2);
    assert(hf_dyn_i32_get(array, 0) == 40);
    assert(hf_dyn_i32_get(array, 1) == 2);
    hf_dyn_i32_free(array);
    assert(hf_file_open("/path/that/does/not/exist") == NULL);
    assert(hf_read_text("/path/that/does/not/exist") == NULL);
    char *canonical = hf_path_canonicalize("/a/./b/../c");
    assert(canonical != NULL);
    assert(strcmp(canonical, "/a/c") == 0);
    hf_string_free(canonical);
    canonical = hf_path_canonicalize("a/../b");
    assert(canonical != NULL);
    assert(strcmp(canonical, "b") == 0);
    hf_string_free(canonical);
    assert(hf_path_canonicalize("/../../escape") == NULL);
    char too_long_path[4097];
    memset(too_long_path, 'x', sizeof(too_long_path) - 1);
    too_long_path[sizeof(too_long_path) - 1] = '\0';
    assert(hf_path_canonicalize(too_long_path) == NULL);
    char *slice = hf_string_slice32("abcdef", 2, 3);
    assert(slice != NULL);
    assert(strcmp(slice, "cde") == 0);
    hf_string_free(slice);
    assert(hf_string_slice32("abcdef", -1, 2) == NULL);
    assert(hf_string_slice32("abcdef", 4, 3) == NULL);

    assert(hf_buf_new(0) == NULL);
    assert(hf_buf_new(((uint64_t)64u << 20) + 1) == NULL);
    void *buffer = hf_buf_new(3);
    assert(buffer != NULL);
    assert(hf_buf_append_str(buffer, "ab"));
    assert(!hf_buf_append_str(buffer, "cd"));
    char *finished = hf_buf_finish(buffer);
    assert(finished != NULL);
    assert(strcmp(finished, "ab") == 0);
    hf_string_free(finished);
    hf_buf_free(buffer);

    void *bytes = hf_buf_new(2);
    assert(bytes != NULL);
    assert(hf_buf_append_byte(bytes, 0));
    assert(hf_buf_append_byte(bytes, 255));
    assert(!hf_buf_append_byte(bytes, 256));
    finished = hf_buf_finish(bytes);
    assert(finished != NULL);
    assert((unsigned char)finished[0] == 0);
    assert((unsigned char)finished[1] == 255);
    hf_string_free(finished);
    hf_buf_free(bytes);

    void *number = hf_buf_new(11);
    assert(number != NULL);
    assert(hf_buf_append_i32(number, INT32_MIN));
    finished = hf_buf_finish(number);
    assert(finished != NULL);
    assert(strcmp(finished, "-2147483648") == 0);
    hf_string_free(finished);
    hf_buf_free(number);

    assert(!hf_write_text(NULL, "bad"));
    assert(!hf_write_text("/tmp/holyfitra_runtime_atomic.txt", NULL));
    assert(hf_write_text("/tmp/holyfitra_runtime_atomic.txt", "atomic-ok"));
    char *round_trip = (char *)hf_read_text("/tmp/holyfitra_runtime_atomic.txt");
    assert(round_trip != NULL);
    assert(strcmp(round_trip, "atomic-ok") == 0);
    hf_string_free(round_trip);
    assert(remove("/tmp/holyfitra_runtime_atomic.txt") == 0);

    puts("holyfitra_runtime_checks=passed");
    return 0;
}
