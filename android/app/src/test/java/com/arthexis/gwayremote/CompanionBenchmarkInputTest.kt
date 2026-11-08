package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionBenchmarkInputTest {
    @Test fun defaultsMatchExistingUi() {
        val input = CompanionBenchmarkInput()
        assertEquals("100", input.samples)
        assertEquals("5", input.warmup)
        assertEquals("5", input.timeout)
        assertEquals("0", input.payload)
        assertEquals("Unspecified", input.label)
        assertEquals(BenchmarkMode.BOTH, input.mode)
        assertEquals(listOf("benchmark-echo", "status"), input.commands())
    }

    @Test fun modePreservesCommandOrder() {
        assertEquals(listOf("benchmark-echo"), CompanionBenchmarkInput(mode = BenchmarkMode.ECHO).commands())
        assertEquals(listOf("status"), CompanionBenchmarkInput(mode = BenchmarkMode.STATUS).commands())
    }

    @Test fun conversionPreservesTimeoutUnitsAndErrors() {
        val config = CompanionBenchmarkInput(samples = "10", warmup = "2", timeout = "3", payload = "8").config()
        assertEquals(10, config.samples)
        assertEquals(2, config.warmup)
        assertEquals(3000, config.timeoutMs)
        assertEquals(8, config.payloadBytes)
        try {
            CompanionBenchmarkInput(samples = "bad").config()
            fail("Expected NumberFormatException")
        } catch (_: NumberFormatException) {}
    }

    @Test fun editsAreImmutableAndPreserveUntrimmedText() {
        val initial = CompanionBenchmarkInput()
        val changed = initial.copy(label = " Wi-Fi ", samples = " 10 ")
        assertEquals("Unspecified", initial.label)
        assertEquals(" Wi-Fi ", changed.label)
        assertEquals(" 10 ", changed.samples)
    }
}
