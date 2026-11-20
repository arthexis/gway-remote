package com.arthexis.gwayremote

/** Enforces allowlisted command policy independently of the Android UI. */
object PanelExecution {
    fun canRun(id: String, explicit: Boolean, confirmed: Boolean, inputsValid: Boolean): Boolean {
        val spec = OperationRegistry.get(id) ?: return false
        if (!inputsValid) return false
        return when (spec.policy) {
            ExecutionPolicy.AUTO_READ -> true
            ExecutionPolicy.EXPLICIT_INPUT -> explicit
            ExecutionPolicy.CONFIRM -> explicit && confirmed
        }
    }
}
