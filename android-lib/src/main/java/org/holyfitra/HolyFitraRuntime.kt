package org.holyfitra

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** End-to-end JNI facade for the Holy Fitra native runtime. */
class HolyFitraRuntime private constructor(private val nativeHandle: Long) : AutoCloseable {
    private var closed = false

    fun submitMatvec(
        input: ByteBuffer,
        output: ByteBuffer,
        coreClass: CoreClass = CoreClass.BIG_PREFERRED,
        priority: Priority = Priority.INTERACTIVE,
        deadlineNs: Long = 0L,
    ): Request {
        check(!closed) { "Holy Fitra runtime is closed" }
        require(input.isDirect && output.isDirect) { "input and output must be direct ByteBuffers" }
        require(deadlineNs >= 0L) { "deadlineNs must be non-negative" }
        val handle = nativeSubmitMatvec(nativeHandle, input, output, coreClass.id, priority.id, deadlineNs)
        check(handle != 0L) { "Holy Fitra request submission failed" }
        return Request(handle)
    }

    fun submitMatvecBatch(
        input: ByteBuffer,
        batchCount: Int,
        inputStrideFloats: Int,
        output: ByteBuffer,
        outputStrideFloats: Int,
        coreClass: CoreClass = CoreClass.ANY,
        priority: Priority = Priority.THROUGHPUT,
        deadlineNs: Long = 0L,
    ): Request {
        check(!closed) { "Holy Fitra runtime is closed" }
        require(input.isDirect && output.isDirect) { "input and output must be direct ByteBuffers" }
        require(batchCount > 0 && inputStrideFloats > 0 && outputStrideFloats > 0) { "batch and strides must be positive" }
        require(deadlineNs >= 0L) { "deadlineNs must be non-negative" }
        val requiredInput = batchCount.toLong() * inputStrideFloats.toLong() * Float.SIZE_BYTES
        val requiredOutput = batchCount.toLong() * outputStrideFloats.toLong() * Float.SIZE_BYTES
        require(requiredInput <= input.capacity().toLong() && requiredOutput <= output.capacity().toLong()) { "batch buffers are too small" }
        val handle = nativeSubmitMatvecBatch(nativeHandle, input, batchCount, inputStrideFloats, output, outputStrideFloats, coreClass.id, priority.id, deadlineNs)
        check(handle != 0L) { "Holy Fitra batch request submission failed" }
        return Request(handle)
    }

    fun setThermal(state: ThermalState) {
        check(!closed) { "Holy Fitra runtime is closed" }
        nativeSetThermal(nativeHandle, state.id)
    }

    fun stats(): Stats {
        check(!closed) { "Holy Fitra runtime is closed" }
        val values = nativeStats(nativeHandle)
        require(values.size >= 9) { "invalid native statistics payload" }
        return Stats(values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7] != 0L, values[8].toInt())
    }

    override fun close() {
        if (!closed) {
            nativeClose(nativeHandle)
            closed = true
        }
    }

    class Request internal constructor(private val nativeHandle: Long) : AutoCloseable {
        private var closed = false

        fun waitFor(timeoutMs: Long = 0L): Status {
            check(!closed) { "request is closed" }
            require(timeoutMs >= 0L) { "timeoutMs must be non-negative" }
            return Status.fromId(nativeWait(nativeHandle, timeoutMs))
        }

        fun cancel() {
            if (!closed) nativeCancel(nativeHandle)
        }

        override fun close() {
            if (!closed) {
                nativeDestroyRequest(nativeHandle)
                closed = true
            }
        }
    }

    data class Stats(
        val submitted: Long,
        val completed: Long,
        val cancelled: Long,
        val deadlineMissed: Long,
        val rejected: Long,
        val stolen: Long,
        val queued: Long,
        val hasNeon: Boolean,
        val abiVersion: Int,
    )

    enum class CoreClass(val id: Int) { ANY(0), BIG_ONLY(1), LITTLE_ONLY(2), BIG_PREFERRED(3), LITTLE_PREFERRED(4) }
    enum class Priority(val id: Int) { BACKGROUND(0), THROUGHPUT(1), LATENCY(2), INTERACTIVE(3) }
    enum class ThermalState(val id: Int) { NORMAL(0), WARM(1), HOT(2), CRITICAL(3) }
    enum class Status(val id: Int) {
        OK(0), INVALID_ARGUMENT(1), BUFFER_TOO_SMALL(2), UNSUPPORTED_ABI(3), OVERFLOW(4), KERNEL_FAILURE(5), CANCELLED(6), DEADLINE_MISSED(7), TIMEOUT(8);
        companion object { fun fromId(id: Int): Status = entries.firstOrNull { it.id == id } ?: KERNEL_FAILURE }
    }

    companion object {
        init { System.loadLibrary("holyfitra_runtime") }

        fun create(
            packed: ByteBuffer,
            scales: ByteBuffer,
            bias: ByteBuffer?,
            inDim: Int,
            outDim: Int,
            groupSize: Int,
            queueCapacity: Int = 256,
            pinThreads: Boolean = true,
        ): HolyFitraRuntime {
            require(packed.isDirect && scales.isDirect) { "model buffers must be direct" }
            require(bias == null || bias.isDirect) { "bias must be direct when provided" }
            val handle = nativeCreate(packed, scales, bias, inDim, outDim, groupSize, queueCapacity, pinThreads)
            check(handle != 0L) { "Holy Fitra native runtime creation failed" }
            return HolyFitraRuntime(handle)
        }

        fun directBytes(bytes: Int): ByteBuffer = ByteBuffer.allocateDirect(bytes).order(ByteOrder.nativeOrder())
        fun directFloats(count: Int): ByteBuffer {
            require(count >= 0) { "count must be non-negative" }
            return directBytes(Math.multiplyExact(count, Float.SIZE_BYTES))
        }

        private external fun nativeCreate(packed: ByteBuffer, scales: ByteBuffer, bias: ByteBuffer?, inDim: Int, outDim: Int, groupSize: Int, queueCapacity: Int, pinThreads: Boolean): Long
        private external fun nativeClose(nativeHandle: Long)
        private external fun nativeSubmitMatvec(nativeHandle: Long, input: ByteBuffer, output: ByteBuffer, coreClass: Int, priority: Int, deadlineNs: Long): Long
        private external fun nativeSubmitMatvecBatch(nativeHandle: Long, input: ByteBuffer, batchCount: Int, inputStrideFloats: Int, output: ByteBuffer, outputStrideFloats: Int, coreClass: Int, priority: Int, deadlineNs: Long): Long
        private external fun nativeWait(requestHandle: Long, timeoutMs: Long): Int
        private external fun nativeCancel(requestHandle: Long)
        private external fun nativeDestroyRequest(requestHandle: Long)
        private external fun nativeSetThermal(nativeHandle: Long, thermalState: Int)
        private external fun nativeStats(nativeHandle: Long): LongArray
    }
}
