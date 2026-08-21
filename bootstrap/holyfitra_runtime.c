// Holy Fitra bootstrap runtime: bounded handles and read-only file I/O.
// Build with generated LLVM:
//   clang generated.ll holyfitra_runtime.c -O2 -o program

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HF_MAX_DYNAMIC_I32_CAPACITY ((uint64_t)1u << 20)
#define HF_MAX_FILE_BYTES ((uint64_t)64u << 20)

typedef struct {
    uint64_t size;
    uint64_t capacity;
    int32_t *data;
} HF_DynI32;

static void hf_abort_invalid(void) {
    abort();
}

void *hf_dyn_i32_new(uint64_t capacity) {
    if (capacity == 0 || capacity > HF_MAX_DYNAMIC_I32_CAPACITY) return NULL;
    HF_DynI32 *array = (HF_DynI32 *)calloc(1, sizeof(HF_DynI32));
    if (!array) return NULL;
    array->data = (int32_t *)calloc((size_t)capacity, sizeof(int32_t));
    if (!array->data) {
        free(array);
        return NULL;
    }
    array->capacity = capacity;
    return array;
}

_Bool hf_dyn_i32_push(void *opaque, int32_t value) {
    HF_DynI32 *array = (HF_DynI32 *)opaque;
    if (!array || !array->data || array->size >= array->capacity) return 0;
    array->data[array->size++] = value;
    return 1;
}

uint64_t hf_dyn_i32_len(void *opaque) {
    HF_DynI32 *array = (HF_DynI32 *)opaque;
    if (!array || !array->data) return 0;
    return array->size;
}

int32_t hf_dyn_i32_get(void *opaque, uint64_t index) {
    HF_DynI32 *array = (HF_DynI32 *)opaque;
    if (!array || !array->data || index >= array->size) hf_abort_invalid();
    return array->data[index];
}

void hf_dyn_i32_free(void *opaque) {
    HF_DynI32 *array = (HF_DynI32 *)opaque;
    if (!array) return;
    free(array->data);
    free(array);
}

void *hf_file_open(const char *path) {
    if (!path || path[0] == '\0') return NULL;
    return (void *)fopen(path, "rb");
}

void *hf_file_read_all(void *opaque) {
    FILE *file = (FILE *)opaque;
    if (!file) return NULL;
    if (fseek(file, 0, SEEK_END) != 0) return NULL;
    long signed_size = ftell(file);
    if (signed_size < 0 || (uint64_t)signed_size > HF_MAX_FILE_BYTES) return NULL;
    if (fseek(file, 0, SEEK_SET) != 0) return NULL;
    size_t size = (size_t)signed_size;
    char *buffer = (char *)malloc(size + 1);
    if (!buffer) return NULL;
    size_t read_count = fread(buffer, 1, size, file);
    if (read_count != size) {
        free(buffer);
        return NULL;
    }
    buffer[size] = '\0';
    return buffer;
}

void hf_file_close(void *opaque) {
    if (opaque) fclose((FILE *)opaque);
}

void *hf_read_text(const char *path) {
    void *file = hf_file_open(path);
    if (!file) return NULL;
    void *text = hf_file_read_all(file);
    hf_file_close(file);
    return text;
}
