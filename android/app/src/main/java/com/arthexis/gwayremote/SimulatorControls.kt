package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.json.JSONObject

@Composable
fun SimulatorControls(host: String, port: String, status: String, busy: Boolean,
                      execute: (String, JSONObject) -> Unit) {
    var scenario by remember { mutableStateOf("boot") }
    var menu by remember { mutableStateOf(false) }
    var cp by remember { mutableStateOf("SIM001") }
    var power by remember { mutableStateOf("7.2") }
    var duration by remember { mutableStateOf("60") }
    var connector by remember { mutableStateOf("1") }
    var connectors by remember { mutableStateOf("2") }
    var rfid by remember { mutableStateOf("SIMTEST") }
    var meter by remember { mutableStateOf("5") }
    var battery by remember { mutableStateOf("60") }
    var soc by remember { mutableStateOf("30") }
    var seed by remember { mutableStateOf("7") }

    val active = status.startsWith("running") || status.startsWith("stopping")
    fun intOk(s: String, low: Int, high: Int) = s.toIntOrNull()?.let { it in low..high } == true
    fun numOk(s: String, low: Double, high: Double) =
        s.toDoubleOrNull()?.let { it.isFinite() && it in low..high } == true
    fun idOk(s: String, limit: Int) =
        s.length in 1..limit && s.all { it.code < 128 && (it.isLetterOrDigit() || it == '_' || it == '-') }
    val valid = host.isNotBlank() && intOk(port, 1, 65535) && idOk(cp, 32) &&
        (scenario == "boot" || (numOk(power, 0.1, 100.0) && intOk(meter, 1, 3600))) &&
        (scenario != "charge" || (intOk(duration, 1, 86400) && intOk(connector, 1, 16) &&
            idOk(rfid, 20))) &&
        (scenario !in listOf("remote", "battery") || intOk(connectors, 1, 16)) &&
        (scenario != "battery" || (numOk(battery, 1.0, 300.0) && numOk(soc, 0.0, 100.0) &&
            intOk(seed, 0, Int.MAX_VALUE)))

    Box {
        OutlinedButton(enabled = !busy && !active, onClick = { menu = true }) { Text("Scenario: $scenario") }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            listOf("boot", "charge", "remote", "battery").forEach { name ->
                DropdownMenuItem(text = { Text(name) }, onClick = { scenario = name; menu = false })
            }
        }
    }
    OutlinedTextField(cp, { cp = it }, label = { Text("Charge point ID") },
        enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
    if (scenario != "boot") {
        OutlinedTextField(power, { power = it }, label = { Text("Power (kW)") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(meter, { meter = it }, label = { Text("Meter interval (seconds)") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
    }
    if (scenario == "charge") {
        OutlinedTextField(duration, { duration = it }, label = { Text("Duration (seconds)") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(connector, { connector = it }, label = { Text("Connector") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(rfid, { rfid = it }, label = { Text("RFID") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
    }
    if (scenario == "remote" || scenario == "battery") {
        OutlinedTextField(connectors, { connectors = it }, label = { Text("Connectors") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
    }
    if (scenario == "battery") {
        OutlinedTextField(battery, { battery = it }, label = { Text("Battery capacity (kWh)") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(soc, { soc = it }, label = { Text("Initial SOC (%)") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(seed, { seed = it }, label = { Text("Random seed") },
            enabled = !busy && !active, modifier = Modifier.fillMaxWidth())
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(enabled = !busy && !active && valid, onClick = {
            val args = JSONObject().put("host", host.trim()).put("port", port.toInt())
                .put("cp", cp).put("scenario", scenario)
            if (scenario != "boot") {
                args.put("power", power.toDouble()).put("meter_interval", meter.toInt())
            }
            if (scenario == "charge") {
                args.put("duration", duration.toInt()).put("connector", connector.toInt())
                    .put("rfid", rfid)
            }
            if (scenario == "remote" || scenario == "battery") args.put("connectors", connectors.toInt())
            if (scenario == "battery") {
                args.put("battery_kwh", battery.toDouble()).put("soc", soc.toDouble())
                    .put("seed", seed.toInt())
            }
            execute("simulator-start", args)
        }) { Text("Start simulation") }
        OutlinedButton(enabled = !busy && status.startsWith("running"),
            onClick = { execute("simulator-stop", JSONObject()) }) { Text("Stop simulation") }
    }
    if (!valid) Text("Check target and scenario parameters", color = MaterialTheme.colorScheme.error)
}
