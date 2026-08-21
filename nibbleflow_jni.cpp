#include <jni.h>
#include <cstdint>
#include "nibbleflow_android.h"

struct hf_jni_model {
    jobject packed_ref;
    jobject scales_ref;
    jobject bias_ref;
    hf_nibbleflow_model model;
};

static void throw_illegal_argument(JNIEnv *env, const char *message) {
    jclass clazz = env->FindClass("java/lang/IllegalArgumentException");
    if (clazz) env->ThrowNew(clazz, message);
}

static void throw_runtime(JNIEnv *env, const char *message) {
    jclass clazz = env->FindClass("java/lang/IllegalStateException");
    if (clazz) env->ThrowNew(clazz, message);
}

static bool require_direct(JNIEnv *env, jobject buffer, const char *name, void **address, jlong *capacity) {
    if (!buffer) {
        throw_illegal_argument(env, name);
        return false;
    }
    *address = env->GetDirectBufferAddress(buffer);
    *capacity = env->GetDirectBufferCapacity(buffer);
    if (!*address || *capacity < 0) {
        throw_illegal_argument(env, "buffers must be direct ByteBuffer/FloatBuffer instances");
        return false;
    }
    return true;
}

extern "C" JNIEXPORT jlong JNICALL Java_org_holyfitra_NibbleFlow_nativeCreate(
    JNIEnv *env, jclass, jobject packed, jobject scales, jobject bias,
    jint in_dim, jint out_dim, jint group_size) {
    void *packed_address = nullptr;
    void *scales_address = nullptr;
    void *bias_address = nullptr;
    jlong packed_capacity = 0;
    jlong scales_capacity = 0;
    jlong bias_capacity = 0;
    if (!require_direct(env, packed, "packed buffer is required", &packed_address, &packed_capacity)) return 0;
    if (!require_direct(env, scales, "scales buffer is required", &scales_address, &scales_capacity)) return 0;
    if (bias && !require_direct(env, bias, "bias buffer is invalid", &bias_address, &bias_capacity)) return 0;
    hf_jni_model *handle = new hf_jni_model();
    handle->packed_ref = env->NewGlobalRef(packed);
    handle->scales_ref = env->NewGlobalRef(scales);
    handle->bias_ref = bias ? env->NewGlobalRef(bias) : nullptr;
    handle->model = hf_nibbleflow_model{
        static_cast<const uint8_t *>(packed_address),
        static_cast<size_t>(packed_capacity),
        static_cast<const float *>(scales_address),
        static_cast<size_t>(scales_capacity / static_cast<jlong>(sizeof(float))),
        static_cast<const float *>(bias_address),
        static_cast<size_t>(bias ? bias_capacity / static_cast<jlong>(sizeof(float)) : 0),
        in_dim, out_dim, group_size, hf_nibbleflow_runtime_abi()
    };
    if (hf_nibbleflow_validate_model(&handle->model) != HF_OK) {
        env->DeleteGlobalRef(handle->packed_ref);
        env->DeleteGlobalRef(handle->scales_ref);
        if (handle->bias_ref) env->DeleteGlobalRef(handle->bias_ref);
        delete handle;
        throw_illegal_argument(env, "NibbleFlow model metadata or buffer capacities are invalid");
        return 0;
    }
    return reinterpret_cast<jlong>(handle);
}

extern "C" JNIEXPORT void JNICALL Java_org_holyfitra_NibbleFlow_nativeClose(JNIEnv *env, jclass, jlong native_handle) {
    hf_jni_model *handle = reinterpret_cast<hf_jni_model *>(native_handle);
    if (!handle) return;
    if (handle->packed_ref) env->DeleteGlobalRef(handle->packed_ref);
    if (handle->scales_ref) env->DeleteGlobalRef(handle->scales_ref);
    if (handle->bias_ref) env->DeleteGlobalRef(handle->bias_ref);
    delete handle;
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_NibbleFlow_nativeMatvec(
    JNIEnv *env, jclass, jlong native_handle, jobject input, jobject output) {
    hf_jni_model *handle = reinterpret_cast<hf_jni_model *>(native_handle);
    if (!handle) {
        throw_runtime(env, "NibbleFlow handle is closed");
        return HF_INVALID_ARGUMENT;
    }
    void *input_address = nullptr;
    void *output_address = nullptr;
    jlong input_capacity = 0;
    jlong output_capacity = 0;
    if (!require_direct(env, input, "input buffer is invalid", &input_address, &input_capacity)) return HF_INVALID_ARGUMENT;
    if (!require_direct(env, output, "output buffer is invalid", &output_address, &output_capacity)) return HF_INVALID_ARGUMENT;
    const hf_status status = hf_nibbleflow_matvec(&handle->model, static_cast<const float *>(input_address), static_cast<size_t>(input_capacity / static_cast<jlong>(sizeof(float))), static_cast<float *>(output_address), static_cast<size_t>(output_capacity / static_cast<jlong>(sizeof(float))));
    if (status != HF_OK) throw_illegal_argument(env, hf_status_string(status));
    return status;
}

extern "C" JNIEXPORT jint JNICALL Java_org_holyfitra_NibbleFlow_nativeAbiVersion(JNIEnv *, jclass) {
    return static_cast<jint>(hf_nibbleflow_runtime_abi());
}

extern "C" JNIEXPORT jboolean JNICALL Java_org_holyfitra_NibbleFlow_nativeHasNeon(JNIEnv *, jclass) {
    return hf_nibbleflow_has_neon() ? JNI_TRUE : JNI_FALSE;
}
