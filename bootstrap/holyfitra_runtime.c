// Holy Fitra bootstrap runtime: bounded handles and read-only file I/O.
// Build with generated LLVM:
//   clang generated.ll holyfitra_runtime.c -O2 -o program

#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define HF_MAX_DYNAMIC_I32_CAPACITY ((uint64_t)1u << 20)
#define HF_MAX_FILE_BYTES ((uint64_t)64u << 20)
#define HF_MAX_BUFFER_BYTES ((uint64_t)64u << 20)
#define HF_MAX_PATH_BYTES ((uint64_t)4096u)

typedef struct {
    uint64_t size;
    uint64_t capacity;
    int32_t *data;
} HF_DynI32;

typedef struct {
    uint64_t size;
    uint64_t capacity;
    char *data;
} HF_Buffer;

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

int32_t hf_dyn_i32_len32(void *opaque) {
    uint64_t length = hf_dyn_i32_len(opaque);
    if (length > INT32_MAX) hf_abort_invalid();
    return (int32_t)length;
}

int32_t hf_dyn_i32_get32(void *opaque, int32_t index) {
    if (index < 0) hf_abort_invalid();
    return hf_dyn_i32_get(opaque, (uint64_t)index);
}

void hf_dyn_i32_set32(void *opaque, int32_t index, int32_t value) {
    HF_DynI32 *array = (HF_DynI32 *)opaque;
    if (!array || !array->data || index < 0 || (uint64_t)index >= array->size) hf_abort_invalid();
    array->data[index] = value;
}

int32_t hf_string_len32(const char *text) {
    if (!text) return 0;
    size_t length = strlen(text);
    if (length > INT32_MAX) hf_abort_invalid();
    return (int32_t)length;
}

int32_t hf_string_byte32(const char *text, int32_t index) {
    if (!text || index < 0 || (size_t)index >= strlen(text)) hf_abort_invalid();
    return (unsigned char)text[index];
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

_Bool hf_write_text(const char *path, const char *text) {
    if (!path || !text) return 0;
    size_t path_length = strlen(path);
    size_t text_length = strlen(text);
    if (path_length == 0 || path_length + 5 > HF_MAX_PATH_BYTES || text_length > HF_MAX_BUFFER_BYTES) return 0;
    char temporary[HF_MAX_PATH_BYTES];
    memcpy(temporary, path, path_length);
    memcpy(temporary + path_length, ".tmp", 5);
    FILE *file = fopen(temporary, "wb");
    if (!file) return 0;
    size_t written = fwrite(text, 1, text_length, file);
    int flush_status = fflush(file);
    int close_status = fclose(file);
    if (written != text_length || flush_status != 0 || close_status != 0) {
        remove(temporary);
        return 0;
    }
    if (rename(temporary, path) != 0) {
        remove(temporary);
        return 0;
    }
    return 1;
}

void hf_string_free(void *opaque) {
    free(opaque);
}

void *hf_buf_new(uint64_t capacity) {
    if (capacity == 0 || capacity > HF_MAX_BUFFER_BYTES || capacity == UINT64_MAX) return NULL;
    HF_Buffer *buffer = (HF_Buffer *)calloc(1, sizeof(HF_Buffer));
    if (!buffer) return NULL;
    buffer->data = (char *)calloc((size_t)(capacity + 1), sizeof(char));
    if (!buffer->data) {
        free(buffer);
        return NULL;
    }
    buffer->capacity = capacity;
    return buffer;
}

static _Bool hf_buf_append_bytes(HF_Buffer *buffer, const char *text, uint64_t length) {
    if (!buffer || !buffer->data || (!text && length != 0)) return 0;
    if (length > buffer->capacity - buffer->size) return 0;
    if (length != 0) memcpy(buffer->data + buffer->size, text, (size_t)length);
    buffer->size += length;
    buffer->data[buffer->size] = '\0';
    return 1;
}

_Bool hf_buf_append_byte(void *opaque, int32_t value) {
    if (value < 0 || value > 255) return 0;
    char byte = (char)value;
    return hf_buf_append_bytes((HF_Buffer *)opaque, &byte, 1);
}

_Bool hf_buf_append_str(void *opaque, const char *text) {
    HF_Buffer *buffer = (HF_Buffer *)opaque;
    if (!text) return 0;
    size_t length = strlen(text);
    return length <= UINT64_MAX ? hf_buf_append_bytes(buffer, text, (uint64_t)length) : 0;
}

_Bool hf_buf_append_i32(void *opaque, int32_t value) {
    char text[12];
    int written = snprintf(text, sizeof(text), "%" PRId32, value);
    if (written < 0 || (size_t)written >= sizeof(text)) return 0;
    return hf_buf_append_bytes((HF_Buffer *)opaque, text, (uint64_t)written);
}

char *hf_buf_finish(void *opaque) {
    HF_Buffer *buffer = (HF_Buffer *)opaque;
    if (!buffer || !buffer->data || buffer->size > HF_MAX_BUFFER_BYTES) return NULL;
    char *result = (char *)malloc((size_t)(buffer->size + 1));
    if (!result) return NULL;
    memcpy(result, buffer->data, (size_t)(buffer->size + 1));
    return result;
}

void hf_buf_free(void *opaque) {
    HF_Buffer *buffer = (HF_Buffer *)opaque;
    if (!buffer) return;
    free(buffer->data);
    free(buffer);
}
