#include <jni.h>

#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <unordered_map>

#include "nibbleflow_android.h"

namespace {

struct hf_jni_model {
    jobject packed_ref = nullptr;
    jobject scales_ref = nullptr;
    jobject bias_ref = nullptr;
    hf_nibbleflow_model model{};
    std::mutex mutex;
    bool closing = false;
};

std::mutex g_model_registry_mutex;
uint64_t g_next_model_handle = 1;
std::unordered_map<uint64_t, std::shared_ptr<hf_jni_model>> g_model_registry;

static void throw_exception(JNIEnv *env, const char *class_name, const char *message) {
    if (!env || env->ExceptionCheck()) return;
    jclass clazz = env->FindClass(class_name);
    if (clazz) {
        env->ThrowNew(clazz, message);
        env->DeleteLocalRef(clazz);
    }
}

static bool require_direct(JNIEnv *env, jobject buffer, const char *message, size_t element_size, size_t alignment, void **address, size_t *elements) {
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

static uint64_t register_model(const std::shared_ptr<hf_jni_model> &model) {
    std::lock_guard<std::mutex> lock(g_model_registry_mutex);
    if (g_next_model_handle == 0 || g_next_model_handle == std::numeric_limits<uint64_t>::max()) return 0;
    const uint64_t token = g_next_model_handle++;
    g_model_registry.emplace(token, model);
    return token;
}

static std::shared_ptr<hf_jni_model> lookup_model(JNIEnv *env, jlong native_handle) {
    if (native_handle <= 0) {
        throw_exception(env, "java/lang/IllegalStateException", "NibbleFlow handle is invalid or closed");
        return nullptr;
    }
    std::lock_guard<std::mutex> lock(g_model_registry_mutex);
    auto found = g_model_registry.find(static_cast<uint64_t>(native_handle));
    if (found == g_model_registry.end()) {
        throw_exception(env, "java/lang/IllegalStateException", "NibbleFlow handle is stale or closed");
        return nullptr;
    }
    auto model = found->second;
    std::lock_guard<std::mutex> model_lock(model->mutex);
    if (model->closing) {
        throw_exception(env, "java/lang/IllegalStateException", "NibbleFlow handle is closing");
        return nullptr;
    }
    return model;
}

static std::shared_ptr<hf_jni_model> erase_model(jlong native_handle) {
    if (native_handle <= 0) return nullptr;
    std::lock_guard<std::mutex> lock(g_model_registry_mutex);
    auto found = g_model_registry.find(static_cast<uint64_t>(native_handle));
    if (found == g_model_registry.end()) return nullptr;
    auto model = found->second;
    g_model_registry.erase(found);
    return model;
}

static void delete_refs(JNIEnv *env, const std::shared_ptr<hf_jni_model> &model) {
    if (!model) return;
    if (model->packed_ref) env->DeleteGlobalRef(model->packed_ref);
    if (model->scales_ref) env->DeleteGlobalRef(model->scales_ref);
    if (model->bias_ref) env->DeleteGlobalRef(model->bias_ref);
    model->packed_ref = nullptr;
    model->scales_ref = nullptr;
    model->bias_ref = nullptr;
}

} // namespace

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_NibbleFlow_nativeCreate(
    JNIEnv *env, jclass, jobject packed, jobject scales, jobject bias,
    jint in_dim, jint out_dim, jint group_size) {
    void *packed_address = nullptr;
    void *scales_address = nullptr;
    void *bias_address = nullptr;
    size_t packed_bytes = 0;
    size_t scales_elements = 0;
    size_t bias_elements = 0;
    if (!require_direct(env, packed, "packed buffer is required", 1, alignof(uint8_t), &packed_address, &packed_bytes)) return 0;
    if (!require_direct(env, scales, "scales buffer is required", sizeof(float), alignof(float), &scales_address, &scales_elements)) return 0;
    if (bias && !require_direct(env, bias, "bias buffer is invalid", sizeof(float), alignof(float), &bias_address, &bias_elements)) return 0;
    auto model = std::make_shared<hf_jni_model>();
    model->model = hf_nibbleflow_model{
        static_cast<const uint8_t *>(packed_address), packed_bytes,
        static_cast<const float *>(scales_address), scales_elements,
        static_cast<const float *>(bias_address), bias ? bias_elements : 0,
        in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()
    };
    if (hf_nibbleflow_validate_model(&model->model) != HF_OK) {
        throw_exception(env, "java/lang/IllegalArgumentException", "NibbleFlow model metadata or buffer capacities are invalid");
        return 0;
    }
    model->packed_ref = env->NewGlobalRef(packed);
    if (env->ExceptionCheck() || !model->packed_ref) {
        if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain packed weights");
        return 0;
    }
    model->scales_ref = env->NewGlobalRef(scales);
    if (env->ExceptionCheck() || !model->scales_ref) {
        delete_refs(env, model);
        if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain scales");
        return 0;
    }
    if (bias) {
        model->bias_ref = env->NewGlobalRef(bias);
        if (env->ExceptionCheck() || !model->bias_ref) {
            delete_refs(env, model);
            if (!env->ExceptionCheck()) throw_exception(env, "java/lang/OutOfMemoryError", "unable to retain bias");
            return 0;
        }
    }
    const uint64_t token = register_model(model);
    if (token == 0) {
        delete_refs(env, model);
        throw_exception(env, "java/lang/IllegalStateException", "native handle registry is exhausted");
        return 0;
    }
    return static_cast<jlong>(token);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_NibbleFlow_nativeClose(JNIEnv *env, jclass, jlong native_handle) {
    auto model = erase_model(native_handle);
    if (!model) return;
    std::lock_guard<std::mutex> lock(model->mutex);
    model->closing = true;
    delete_refs(env, model);
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_NibbleFlow_nativeMatvec(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jobject output) {
    auto model = lookup_model(env, native_handle);
    if (!model) return HF_INVALID_ARGUMENT;
    void *input_address = nullptr;
    void *output_address = nullptr;
    size_t input_elements = 0;
    size_t output_elements = 0;
    if (!require_direct(env, input, "input buffer is invalid", sizeof(float), alignof(float), &input_address, &input_elements)) return HF_INVALID_ARGUMENT;
    if (!require_direct(env, output, "output buffer is invalid", sizeof(float), alignof(float), &output_address, &output_elements)) return HF_INVALID_ARGUMENT;
    std::lock_guard<std::mutex> lock(model->mutex);
    if (model->closing) {
        throw_exception(env, "java/lang/IllegalStateException", "NibbleFlow handle is closing");
        return HF_INVALID_ARGUMENT;
    }
    const hf_status status = hf_nibbleflow_matvec(&model->model, static_cast<const float *>(input_address), input_elements, static_cast<float *>(output_address), output_elements);
    if (status != HF_OK) throw_exception(env, status == HF_BUFFER_TOO_SMALL ? "java/lang/IllegalArgumentException" : "java/lang/IllegalStateException", hf_status_string(status));
    return status;
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_NibbleFlow_nativeAbiVersion(JNIEnv *, jclass) {
    return static_cast<jint>(hf_nibbleflow_runtime_abi());
}

extern "C" JNIEXPORT jboolean JNICALL Java_org_holyfitra_NibbleFlow_nativeHasNeon(JNIEnv *, jclass) {
    return hf_nibbleflow_has_neon() ? JNI_TRUE : JNI_FALSE;
}
