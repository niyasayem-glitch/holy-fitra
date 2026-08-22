package org.holyfitra

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer

/**
 * JNI wrapper for a verified NibbleFlow model.
 * The direct buffers remain alive while the native handle exists.
 */
class NibbleFlow private constructor(private val nativeHandle: Long) : AutoCloseable {
    private var closed = false

    fun matvec(input: FloatBuffer, output: FloatBuffer) {
        check(!closed) { "NibbleFlow has been closed" }
        require(input.isDirect && output.isDirect) { "input and output must be direct buffers" }
        val status = nativeMatvec(nativeHandle, input, output)
        check(status == 0) { "NibbleFlow matvec failed with status $status" }
    }

    override fun close() {
        if (!closed) {
            nativeClose(nativeHandle)
            closed = true
        }
    }

    companion object {
        init {
            System.loadLibrary("holyfitra_nibbleflow")
        }

        @JvmStatic
        fun abiVersion(): Int = nativeAbiVersion()

        @JvmStatic
        fun hasNeon(): Boolean = nativeHasNeon()

        @JvmStatic
        fun create(
            packed: ByteBuffer,
            scales: FloatBuffer,
            bias: FloatBuffer?,
            inDim: Int,
            outDim: Int,
            groupSize: Int,
        ): NibbleFlow {
            require(packed.isDirect) { "packed must be a direct ByteBuffer" }
            require(scales.isDirect) { "scales must be a direct FloatBuffer" }
            require(bias == null || bias.isDirect) { "bias must be direct when provided" }
            require(inDim > 0 && outDim > 0 && groupSize > 0 && groupSize % 2 == 0) { "model dimensions and group size are invalid" }
            val handle = nativeCreate(packed, scales, bias, inDim, outDim, groupSize)
            check(handle != 0L) { "NibbleFlow native model creation failed" }
            return NibbleFlow(handle)
        }

        fun directBytes(size: Int): ByteBuffer = ByteBuffer.allocateDirect(size).order(ByteOrder.nativeOrder())
        fun directFloats(count: Int): FloatBuffer {
            require(count >= 0) { "count must be non-negative" }
            return directBytes(Math.multiplyExact(count, Float.SIZE_BYTES)).asFloatBuffer()
        }

        private external fun nativeCreate(packed: ByteBuffer, scales: FloatBuffer, bias: FloatBuffer?, inDim: Int, outDim: Int, groupSize: Int): Long
        private external fun nativeClose(nativeHandle: Long)
        private external fun nativeMatvec(nativeHandle: Long, input: FloatBuffer, output: FloatBuffer): Int
        private external fun nativeAbiVersion(): Int
        private external fun nativeHasNeon(): Boolean
    }
}
