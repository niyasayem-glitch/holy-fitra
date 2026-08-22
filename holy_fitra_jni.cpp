#include <jni.h>

#include <cstdint>
#include <condition_variable>
#include <limits>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "holy_fitra_runtime.h"

namespace {

constexpr uint64_t kMaxQueueCapacity = 1u << 20;
constexpr uint64_t kHandleMax = std::numeric_limits<uint64_t>::max();

struct hf_jni_runtime;
struct hf_jni_request;

std::mutex g_registry_mutex;
uint64_t g_next_handle = 1;
std::unordered_map<uint64_t, std::shared_ptr<hf_jni_runtime>> g_runtimes;
std::unordered_map<uint64_t, std::shared_ptr<hf_jni_request>> g_requests;

struct hf_jni_runtime {
    jobject packed_ref = nullptr;
    jobject scales_ref = nullptr;
    jobject bias_ref = nullptr;
    hf_holyfitra_runtime *runtime = nullptr;
    mutable std::mutex mutex;
    std::mutex lifecycle_mutex;
    std::condition_variable condition;
    bool closing = false;
    uint32_t active_operations = 0;
};

struct hf_jni_request {
    jobject input_ref = nullptr;
    jobject output_ref = nullptr;
    hf_runtime_request *request = nullptr;
    std::shared_ptr<hf_jni_runtime> owner;
    mutable std::mutex mutex;
    std::condition_variable condition;
    bool destroying = false;
    bool destroyed = false;
    uint32_t active_operations = 0;
};

struct RuntimeLease {
    std::shared_ptr<hf_jni_runtime> value;
    ~RuntimeLease() {
        if (!value) return;
        std::lock_guard<std::mutex> lock(value->mutex);
        if (value->active_operations > 0) --value->active_operations;
        value->condition.notify_all();
    }
};

struct RequestLease {
    std::shared_ptr<hf_jni_request> value;
    ~RequestLease() {
        if (!value) return;
        std::lock_guard<std::mutex> lock(value->mutex);
        if (value->active_operations > 0) --value->active_operations;
        value->condition.notify_all();
    }
};

static void throw_exception(JNIEnv *env, const char *class_name, const char *message) {
    if (!env || env->ExceptionCheck()) return;
    jclass clazz = env->FindClass(class_name);
    if (clazz) {
        env->ThrowNew(clazz, message);
        env->DeleteLocalRef(clazz);
    }
}

static bool next_handle(uint64_t &result) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    if (g_next_handle == 0 || g_next_handle == kHandleMax) return false;
    result = g_next_handle++;
    return true;
}

static uint64_t register_runtime(const std::shared_ptr<hf_jni_runtime> &runtime) {
    uint64_t token = 0;
    if (!next_handle(token)) return 0;
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    g_runtimes.emplace(token, runtime);
    return token;
}

static uint64_t register_request(const std::shared_ptr<hf_jni_request> &request) {
    uint64_t token = 0;
    if (!next_handle(token)) return 0;
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    g_requests.emplace(token, request);
    return token;
}

static std::shared_ptr<hf_jni_runtime> lookup_runtime(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    auto found = g_runtimes.find(token);
    return found == g_runtimes.end() ? nullptr : found->second;
}

static std::shared_ptr<hf_jni_request> lookup_request(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    auto found = g_requests.find(token);
    return found == g_requests.end() ? nullptr : found->second;
}

static std::shared_ptr<hf_jni_runtime> erase_runtime(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    auto found = g_runtimes.find(token);
    if (found == g_runtimes.end()) return nullptr;
    auto result = found->second;
    g_runtimes.erase(found);
    return result;
}

static std::shared_ptr<hf_jni_request> erase_request(uint64_t token) {
    std::lock_guard<std::mutex> lock(g_registry_mutex);
    auto found = g_requests.find(token);
    if (found == g_requests.end()) return nullptr;
    auto result = found->second;
    g_requests.erase(found);
    return result;
}

static RuntimeLease acquire_runtime(JNIEnv *env, jlong token) {
    if (token <= 0) {
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra runtime handle is invalid or closed");
        return {};
    }
    auto runtime = lookup_runtime(static_cast<uint64_t>(token));
    if (!runtime) {
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra runtime handle is stale or closed");
        return {};
    }
    {
        std::lock_guard<std::mutex> lock(runtime->mutex);
        if (runtime->closing || !runtime->runtime) {
            throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra runtime is closed");
            return {};
        }
        ++runtime->active_operations;
    }
    return {std::move(runtime)};
}

static RequestLease acquire_request(JNIEnv *env, jlong token) {
    if (token <= 0) {
        throw_exception(env, "java/lang/IllegalStateException", "request handle is invalid or destroyed");
        return {};
    }
    auto request = lookup_request(static_cast<uint64_t>(token));
    if (!request) {
        throw_exception(env, "java/lang/IllegalStateException", "request handle is stale or destroyed");
        return {};
    }
    {
        std::lock_guard<std::mutex> lock(request->mutex);
        if (request->destroying || request->destroyed || !request->request) {
            throw_exception(env, "java/lang/IllegalStateException", "request is already destroyed");
            return {};
        }
        ++request->active_operations;
    }
    return {std::move(request)};
}

static bool direct_buffer(JNIEnv *env, jobject buffer, const char *message, size_t element_size, size_t alignment, void **address, size_t *elements) {
    if (!buffer) {
        throw_exception(env, "java/lang/IllegalArgumentException", message);
        return false;
    }
    void *raw = env->GetDirectBufferAddress(buffer);
    const jlong capacity_bytes = env->GetDirectBufferCapacity(buffer);
    if (env->ExceptionCheck()) return false;
    if (!raw || capacity_bytes < 0 || element_size == 0 || static_cast<uint64_t>(capacity_bytes) % element_size != 0 || (alignment > 1 && reinterpret_cast<uintptr_t>(raw) % alignment != 0)) {
        throw_exception(env, "java/lang/IllegalArgumentException", "buffer must be direct, aligned, and have an exact element-size capacity");
        return false;
    }
    *address = raw;
    *elements = static_cast<size_t>(static_cast<uint64_t>(capacity_bytes) / element_size);
    return true;
}

static void delete_global_refs(JNIEnv *env, const std::shared_ptr<hf_jni_runtime> &handle) {
    if (!handle) return;
    if (handle->packed_ref) env->DeleteGlobalRef(handle->packed_ref);
    if (handle->scales_ref) env->DeleteGlobalRef(handle->scales_ref);
    if (handle->bias_ref) env->DeleteGlobalRef(handle->bias_ref);
    handle->packed_ref = nullptr;
    handle->scales_ref = nullptr;
    handle->bias_ref = nullptr;
}

static void delete_request_refs(JNIEnv *env, const std::shared_ptr<hf_jni_request> &request) {
    if (!request) return;
    if (request->input_ref) env->DeleteGlobalRef(request->input_ref);
    if (request->output_ref) env->DeleteGlobalRef(request->output_ref);
    request->input_ref = nullptr;
    request->output_ref = nullptr;
}

static bool retain_runtime_refs(JNIEnv *env, const std::shared_ptr<hf_jni_runtime> &handle, jobject packed, jobject scales, jobject bias) {
    handle->packed_ref = env->NewGlobalRef(packed);
    if (env->ExceptionCheck() || !handle->packed_ref) return false;
    handle->scales_ref = env->NewGlobalRef(scales);
    if (env->ExceptionCheck() || !handle->scales_ref) return false;
    handle->bias_ref = bias ? env->NewGlobalRef(bias) : nullptr;
    if (bias && (env->ExceptionCheck() || !handle->bias_ref)) return false;
    return true;
}

static bool retain_request_refs(JNIEnv *env, const std::shared_ptr<hf_jni_request> &request, jobject input, jobject output) {
    request->input_ref = env->NewGlobalRef(input);
    if (env->ExceptionCheck() || !request->input_ref) return false;
    request->output_ref = env->NewGlobalRef(output);
    if (env->ExceptionCheck() || !request->output_ref) return false;
    return true;
}

static void destroy_request(JNIEnv *env, const std::shared_ptr<hf_jni_request> &request) {
    if (!request) return;
    {
        std::unique_lock<std::mutex> lock(request->mutex);
        if (request->destroyed || request->destroying) return;
        request->destroying = true;
        request->condition.wait(lock, [&request] { return request->active_operations == 0; });
    }
    hf_runtime_request_destroy(request->request);
    request->request = nullptr;
    delete_request_refs(env, request);
    {
        std::lock_guard<std::mutex> lock(request->mutex);
        request->destroyed = true;
        request->destroying = false;
    }
    request->condition.notify_all();
}

} // namespace

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeCreate(
    JNIEnv *env, jclass, jobject packed, jobject scales, jobject bias,
    jint in_dim, jint out_dim, jint group_size, jint queue_capacity, jboolean pin_threads) {
    void *packed_address = nullptr;
    void *scales_address = nullptr;
    void *bias_address = nullptr;
    size_t packed_bytes = 0;
    size_t scales_elements = 0;
    size_t bias_elements = 0;
    if (!direct_buffer(env, packed, "packed weights are required", 1, alignof(uint8_t), &packed_address, &packed_bytes)) return 0;
    if (!direct_buffer(env, scales, "scales are required", sizeof(float), alignof(float), &scales_address, &scales_elements)) return 0;
    if (bias && !direct_buffer(env, bias, "bias buffer is invalid", sizeof(float), alignof(float), &bias_address, &bias_elements)) return 0;
    if (queue_capacity < 0 || static_cast<uint64_t>(queue_capacity) > kMaxQueueCapacity) {
        throw_exception(env, "java/lang/IllegalArgumentException", "queue capacity is outside the safe bound");
        return 0;
    }
    hf_nibbleflow_model model{
        static_cast<const uint8_t *>(packed_address), packed_bytes,
        static_cast<const float *>(scales_address), scales_elements,
        static_cast<const float *>(bias_address), bias ? bias_elements : 0,
        in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()
    };
    if (hf_nibbleflow_validate_model(&model) != HF_OK) {
        throw_exception(env, "java/lang/IllegalArgumentException", "invalid NibbleFlow model layout or direct-buffer capacity");
        return 0;
    }
    auto handle = std::make_shared<hf_jni_runtime>();
    if (!retain_runtime_refs(env, handle, packed, scales, bias)) {
        delete_global_refs(env, handle);
        if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain model buffers");
        return 0;
    }
    handle->runtime = hf_runtime_create(&model, static_cast<size_t>(queue_capacity), pin_threads == JNI_TRUE ? 1 : 0);
    if (!handle->runtime) {
        delete_global_refs(env, handle);
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra native runtime creation failed");
        return 0;
    }
    const uint64_t token = register_runtime(handle);
    if (token == 0) {
        hf_runtime_destroy(handle->runtime);
        handle->runtime = nullptr;
        delete_global_refs(env, handle);
        throw_exception(env, "java/lang/IllegalStateException", "native handle registry is exhausted");
        return 0;
    }
    return static_cast<jlong>(token);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeClose(JNIEnv *env, jclass, jlong native_handle) {
    auto handle = native_handle > 0 ? erase_runtime(static_cast<uint64_t>(native_handle)) : nullptr;
    if (!handle) return;
    std::lock_guard<std::mutex> lifecycle_lock(handle->lifecycle_mutex);
    {
        std::unique_lock<std::mutex> lock(handle->mutex);
        if (handle->closing) return;
        handle->closing = true;
        handle->condition.wait(lock, [&handle] { return handle->active_operations == 0; });
    }
    std::vector<std::shared_ptr<hf_jni_request>> owned_requests;
    {
        std::lock_guard<std::mutex> lock(g_registry_mutex);
        for (auto iterator = g_requests.begin(); iterator != g_requests.end();) {
            if (iterator->second->owner == handle) {
                owned_requests.push_back(iterator->second);
                iterator = g_requests.erase(iterator);
            } else {
                ++iterator;
            }
        }
    }
    for (const auto &request : owned_requests) destroy_request(env, request);
    hf_runtime_destroy(handle->runtime);
    handle->runtime = nullptr;
    delete_global_refs(env, handle);
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSubmitMatvec(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jobject output,
    jint core_class, jint priority, jlong deadline_ns) {
    auto submission_owner = native_handle > 0 ? lookup_runtime(static_cast<uint64_t>(native_handle)) : nullptr;
    if (!submission_owner) {
        acquire_runtime(env, native_handle);
        return 0;
    }
    std::lock_guard<std::mutex> lifecycle_lock(submission_owner->lifecycle_mutex);
    RuntimeLease runtime_lease = acquire_runtime(env, native_handle);
    if (!runtime_lease.value) return 0;
    void *input_address = nullptr;
    void *output_address = nullptr;
    size_t input_elements = 0;
    size_t output_elements = 0;
    if (!direct_buffer(env, input, "input must be a direct float buffer", sizeof(float), alignof(float), &input_address, &input_elements)) return 0;
    if (!direct_buffer(env, output, "output must be a direct float buffer", sizeof(float), alignof(float), &output_address, &output_elements)) return 0;
    if (deadline_ns < 0) {
        throw_exception(env, "java/lang/IllegalArgumentException", "deadline must be non-negative");
        return 0;
    }
    auto request = std::make_shared<hf_jni_request>();
    request->owner = runtime_lease.value;
    if (!retain_request_refs(env, request, input, output)) {
        delete_request_refs(env, request);
        if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain request buffers");
        return 0;
    }
    const hf_status status = hf_runtime_submit_matvec(runtime_lease.value->runtime, static_cast<const float *>(input_address), input_elements, static_cast<float *>(output_address), output_elements, core_class, priority, static_cast<uint64_t>(deadline_ns), &request->request);
    if (status != HF_OK) {
        delete_request_refs(env, request);
        throw_exception(env, status == HF_BUFFER_TOO_SMALL ? "java/lang/IllegalArgumentException" : "java/lang/IllegalStateException", hf_runtime_status_string(status));
        return 0;
    }
    const uint64_t token = register_request(request);
    if (token == 0) {
        destroy_request(env, request);
        throw_exception(env, "java/lang/IllegalStateException", "native handle registry is exhausted");
        return 0;
    }
    return static_cast<jlong>(token);
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSubmitMatvecBatch(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jint batch_count, jint input_stride, jobject output, jint output_stride,
    jint core_class, jint priority, jlong deadline_ns) {
    auto submission_owner = native_handle > 0 ? lookup_runtime(static_cast<uint64_t>(native_handle)) : nullptr;
    if (!submission_owner) {
        acquire_runtime(env, native_handle);
        return 0;
    }
    std::lock_guard<std::mutex> lifecycle_lock(submission_owner->lifecycle_mutex);
    RuntimeLease runtime_lease = acquire_runtime(env, native_handle);
    if (!runtime_lease.value) return 0;
    if (batch_count <= 0 || input_stride <= 0 || output_stride <= 0 || deadline_ns < 0) {
        throw_exception(env, "java/lang/IllegalArgumentException", "batch, stride, and deadline values are invalid");
        return 0;
    }
    void *input_address = nullptr;
    void *output_address = nullptr;
    size_t input_elements = 0;
    size_t output_elements = 0;
    if (!direct_buffer(env, input, "input must be a direct float buffer", sizeof(float), alignof(float), &input_address, &input_elements)) return 0;
    if (!direct_buffer(env, output, "output must be a direct float buffer", sizeof(float), alignof(float), &output_address, &output_elements)) return 0;
    const uint64_t required_input = static_cast<uint64_t>(batch_count) * static_cast<uint64_t>(input_stride);
    const uint64_t required_output = static_cast<uint64_t>(batch_count) * static_cast<uint64_t>(output_stride);
    if (required_input > input_elements || required_output > output_elements) {
        throw_exception(env, "java/lang/IllegalArgumentException", "batch buffer capacity is too small");
        return 0;
    }
    auto request = std::make_shared<hf_jni_request>();
    request->owner = runtime_lease.value;
    if (!retain_request_refs(env, request, input, output)) {
        delete_request_refs(env, request);
        if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain request buffers");
        return 0;
    }
    const hf_status status = hf_runtime_submit_matvec_batch(runtime_lease.value->runtime, static_cast<const float *>(input_address), static_cast<size_t>(batch_count), static_cast<size_t>(input_stride), static_cast<float *>(output_address), static_cast<size_t>(output_stride), core_class, priority, static_cast<uint64_t>(deadline_ns), &request->request);
    if (status != HF_OK) {
        delete_request_refs(env, request);
        throw_exception(env, status == HF_BUFFER_TOO_SMALL ? "java/lang/IllegalArgumentException" : "java/lang/IllegalStateException", hf_runtime_status_string(status));
        return 0;
    }
    const uint64_t token = register_request(request);
    if (token == 0) {
        destroy_request(env, request);
        throw_exception(env, "java/lang/IllegalStateException", "native handle registry is exhausted");
        return 0;
    }
    return static_cast<jlong>(token);
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeWait(JNIEnv *env, jclass, jlong request_handle, jlong timeout_ms) {
    if (timeout_ms < 0) {
        throw_exception(env, "java/lang/IllegalArgumentException", "timeout must be non-negative");
        return HF_INVALID_ARGUMENT;
    }
    RequestLease request_lease = acquire_request(env, request_handle);
    if (!request_lease.value) return HF_INVALID_ARGUMENT;
    return static_cast<jint>(hf_runtime_wait(request_lease.value->request, static_cast<uint64_t>(timeout_ms)));
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeCancel(JNIEnv *env, jclass, jlong request_handle) {
    RequestLease request_lease = acquire_request(env, request_handle);
    if (request_lease.value) hf_runtime_cancel(request_lease.value->request);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeDestroyRequest(JNIEnv *env, jclass, jlong request_handle) {
    if (request_handle <= 0) return;
    auto request = lookup_request(static_cast<uint64_t>(request_handle));
    if (!request || !request->owner) return;
    std::lock_guard<std::mutex> lifecycle_lock(request->owner->lifecycle_mutex);
    request = erase_request(static_cast<uint64_t>(request_handle));
    if (request) destroy_request(env, request);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSetThermal(JNIEnv *env, jclass, jlong native_handle, jint thermal_state) {
    RuntimeLease runtime_lease = acquire_runtime(env, native_handle);
    if (runtime_lease.value) hf_runtime_set_thermal(runtime_lease.value->runtime, thermal_state);
}

extern "C" JNIEXPORT jlongArray JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeStats(JNIEnv *env, jclass, jlong native_handle) {
    RuntimeLease runtime_lease = acquire_runtime(env, native_handle);
    if (!runtime_lease.value) return nullptr;
    const hf_runtime_stats stats = hf_runtime_get_stats(runtime_lease.value->runtime);
    const jlong values[] = {static_cast<jlong>(stats.submitted), static_cast<jlong>(stats.completed), static_cast<jlong>(stats.cancelled), static_cast<jlong>(stats.deadline_missed), static_cast<jlong>(stats.rejected), static_cast<jlong>(stats.stolen), static_cast<jlong>(stats.queued), static_cast<jlong>(stats.has_neon), static_cast<jlong>(stats.abi_version)};
    jlongArray result = env->NewLongArray(static_cast<jsize>(sizeof(values) / sizeof(values[0])));
    if (!result) return nullptr;
    env->SetLongArrayRegion(result, 0, static_cast<jsize>(sizeof(values) / sizeof(values[0])), values);
    return result;
}
