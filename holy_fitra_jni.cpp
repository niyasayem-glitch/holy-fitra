#include <jni.h>
#include <cstdint>
#include <vector>

#include "holy_fitra_runtime.h"

struct hf_jni_runtime {
    jobject packed_ref;
    jobject scales_ref;
    jobject bias_ref;
    hf_holyfitra_runtime *runtime;
};

struct hf_jni_request {
    jobject input_ref;
    jobject output_ref;
    hf_runtime_request *request;
};

static void throw_exception(JNIEnv *env, const char *class_name, const char *message) {
    jclass clazz = env->FindClass(class_name);
    if (clazz) env->ThrowNew(clazz, message);
}

static bool direct_buffer(JNIEnv *env, jobject buffer, const char *message, void **address, jlong *capacity_bytes) {
    if (!buffer) {
        throw_exception(env, "java/lang/IllegalArgumentException", message);
        return false;
    }
    *address = env->GetDirectBufferAddress(buffer);
    *capacity_bytes = env->GetDirectBufferCapacity(buffer);
    if (!*address || *capacity_bytes < 0) {
        throw_exception(env, "java/lang/IllegalArgumentException", "all runtime buffers must be direct ByteBuffers");
        return false;
    }
    return true;
}

static void delete_global_refs(JNIEnv *env, hf_jni_runtime *handle) {
    if (!handle) return;
    if (handle->packed_ref) env->DeleteGlobalRef(handle->packed_ref);
    if (handle->scales_ref) env->DeleteGlobalRef(handle->scales_ref);
    if (handle->bias_ref) env->DeleteGlobalRef(handle->bias_ref);
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeCreate(
    JNIEnv *env, jclass, jobject packed, jobject scales, jobject bias,
    jint in_dim, jint out_dim, jint group_size, jint queue_capacity, jboolean pin_threads) {
    void *packed_address = nullptr;
    void *scales_address = nullptr;
    void *bias_address = nullptr;
    jlong packed_capacity = 0;
    jlong scales_capacity = 0;
    jlong bias_capacity = 0;
    if (!direct_buffer(env, packed, "packed weights are required", &packed_address, &packed_capacity)) return 0;
    if (!direct_buffer(env, scales, "scales are required", &scales_address, &scales_capacity)) return 0;
    if (bias && !direct_buffer(env, bias, "bias buffer is invalid", &bias_address, &bias_capacity)) return 0;
    hf_nibbleflow_model model{
        static_cast<const uint8_t *>(packed_address), static_cast<size_t>(packed_capacity),
        static_cast<const float *>(scales_address), static_cast<size_t>(scales_capacity / static_cast<jlong>(sizeof(float))),
        static_cast<const float *>(bias_address), static_cast<size_t>(bias ? bias_capacity / static_cast<jlong>(sizeof(float)) : 0),
        in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()
    };
    if (hf_nibbleflow_validate_model(&model) != HF_OK) {
        throw_exception(env, "java/lang/IllegalArgumentException", "invalid NibbleFlow model layout or direct-buffer capacity");
        return 0;
    }
    auto *handle = new hf_jni_runtime{nullptr, nullptr, nullptr, nullptr};
    handle->packed_ref = env->NewGlobalRef(packed);
    handle->scales_ref = env->NewGlobalRef(scales);
    handle->bias_ref = bias ? env->NewGlobalRef(bias) : nullptr;
    handle->runtime = hf_runtime_create(&model, static_cast<size_t>(queue_capacity), pin_threads == JNI_TRUE ? 1 : 0);
    if (!handle->runtime) {
        delete_global_refs(env, handle);
        delete handle;
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra native runtime creation failed");
        return 0;
    }
    return reinterpret_cast<jlong>(handle);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeClose(JNIEnv *env, jclass, jlong native_handle) {
    auto *handle = reinterpret_cast<hf_jni_runtime *>(native_handle);
    if (!handle) return;
    hf_runtime_destroy(handle->runtime);
    delete_global_refs(env, handle);
    delete handle;
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSubmitMatvec(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jobject output,
    jint core_class, jint priority, jlong deadline_ns) {
    auto *handle = reinterpret_cast<hf_jni_runtime *>(native_handle);
    if (!handle || !handle->runtime) {
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra runtime is closed");
        return 0;
    }
    void *input_address = nullptr;
    void *output_address = nullptr;
    jlong input_capacity = 0;
    jlong output_capacity = 0;
    if (!direct_buffer(env, input, "input must be a direct ByteBuffer", &input_address, &input_capacity)) return 0;
    if (!direct_buffer(env, output, "output must be a direct ByteBuffer", &output_address, &output_capacity)) return 0;
    hf_jni_request *handle_request = new hf_jni_request{env->NewGlobalRef(input), env->NewGlobalRef(output), nullptr};
    const hf_status status = hf_runtime_submit_matvec(handle->runtime, static_cast<const float *>(input_address), static_cast<size_t>(input_capacity / static_cast<jlong>(sizeof(float))), static_cast<float *>(output_address), static_cast<size_t>(output_capacity / static_cast<jlong>(sizeof(float))), core_class, priority, static_cast<uint64_t>(deadline_ns), &handle_request->request);
    if (status != HF_OK) {
        if (handle_request->input_ref) env->DeleteGlobalRef(handle_request->input_ref);
        if (handle_request->output_ref) env->DeleteGlobalRef(handle_request->output_ref);
        delete handle_request;
        throw_exception(env, "java/lang/IllegalStateException", hf_runtime_status_string(status));
        return 0;
    }
    return reinterpret_cast<jlong>(handle_request);
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSubmitMatvecBatch(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jint batch_count, jint input_stride, jobject output, jint output_stride,
    jint core_class, jint priority, jlong deadline_ns) {
    auto *handle = reinterpret_cast<hf_jni_runtime *>(native_handle);
    if (!handle || !handle->runtime) {
        throw_exception(env, "java/lang/IllegalStateException", "Holy Fitra runtime is closed");
        return 0;
    }
    if (batch_count <= 0 || input_stride <= 0 || output_stride <= 0) {
        throw_exception(env, "java/lang/IllegalArgumentException", "batch and stride values must be positive");
        return 0;
    }
    void *input_address = nullptr;
    void *output_address = nullptr;
    jlong input_capacity = 0;
    jlong output_capacity = 0;
    if (!direct_buffer(env, input, "input must be a direct ByteBuffer", &input_address, &input_capacity)) return 0;
    if (!direct_buffer(env, output, "output must be a direct ByteBuffer", &output_address, &output_capacity)) return 0;
    const uint64_t required_input_bytes = static_cast<uint64_t>(batch_count) * static_cast<uint64_t>(input_stride) * sizeof(float);
    const uint64_t required_output_bytes = static_cast<uint64_t>(batch_count) * static_cast<uint64_t>(output_stride) * sizeof(float);
    if (required_input_bytes > static_cast<uint64_t>(input_capacity) || required_output_bytes > static_cast<uint64_t>(output_capacity)) {
        throw_exception(env, "java/lang/IllegalArgumentException", "batch buffer capacity is too small");
        return 0;
    }
    auto *handle_request = new hf_jni_request{env->NewGlobalRef(input), env->NewGlobalRef(output), nullptr};
    const hf_status status = hf_runtime_submit_matvec_batch(handle->runtime, static_cast<const float *>(input_address), static_cast<size_t>(batch_count), static_cast<size_t>(input_stride), static_cast<float *>(output_address), static_cast<size_t>(output_stride), core_class, priority, static_cast<uint64_t>(deadline_ns), &handle_request->request);
    if (status != HF_OK) {
        if (handle_request->input_ref) env->DeleteGlobalRef(handle_request->input_ref);
        if (handle_request->output_ref) env->DeleteGlobalRef(handle_request->output_ref);
        delete handle_request;
        throw_exception(env, "java/lang/IllegalStateException", hf_runtime_status_string(status));
        return 0;
    }
    return reinterpret_cast<jlong>(handle_request);
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeWait(JNIEnv *env, jclass, jlong request_handle, jlong timeout_ms) {
    auto *handle = reinterpret_cast<hf_jni_request *>(request_handle);
    if (!handle || !handle->request) {
        throw_exception(env, "java/lang/IllegalStateException", "request is invalid");
        return HF_INVALID_ARGUMENT;
    }
    return static_cast<jint>(hf_runtime_wait(handle->request, static_cast<uint64_t>(timeout_ms)));
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeCancel(JNIEnv *, jclass, jlong request_handle) {
    auto *handle = reinterpret_cast<hf_jni_request *>(request_handle);
    if (handle) hf_runtime_cancel(handle->request);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeDestroyRequest(JNIEnv *env, jclass, jlong request_handle) {
    auto *handle = reinterpret_cast<hf_jni_request *>(request_handle);
    if (!handle) return;
    hf_runtime_request_destroy(handle->request);
    if (handle->input_ref) env->DeleteGlobalRef(handle->input_ref);
    if (handle->output_ref) env->DeleteGlobalRef(handle->output_ref);
    delete handle;
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeSetThermal(JNIEnv *, jclass, jlong native_handle, jint thermal_state) {
    auto *handle = reinterpret_cast<hf_jni_runtime *>(native_handle);
    if (handle) hf_runtime_set_thermal(handle->runtime, thermal_state);
}

extern "C" JNIEXPORT jlongArray JNICALL Java_org_holyfitra_HolyFitraRuntime_nativeStats(JNIEnv *env, jclass, jlong native_handle) {
    auto *handle = reinterpret_cast<hf_jni_runtime *>(native_handle);
    const hf_runtime_stats stats = handle ? hf_runtime_get_stats(handle->runtime) : hf_runtime_stats{};
    const jlong values[] = {static_cast<jlong>(stats.submitted), static_cast<jlong>(stats.completed), static_cast<jlong>(stats.cancelled), static_cast<jlong>(stats.deadline_missed), static_cast<jlong>(stats.rejected), static_cast<jlong>(stats.stolen), static_cast<jlong>(stats.queued), static_cast<jlong>(stats.has_neon), static_cast<jlong>(stats.abi_version)};
    jlongArray result = env->NewLongArray(static_cast<jsize>(sizeof(values) / sizeof(values[0])));
    if (result) env->SetLongArrayRegion(result, 0, static_cast<jsize>(sizeof(values) / sizeof(values[0])), values);
    return result;
}
