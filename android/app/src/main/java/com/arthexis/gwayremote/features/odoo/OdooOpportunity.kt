package com.arthexis.gwayremote.features.odoo

import org.json.JSONObject
import java.net.URI

/** Proposed read-only CRM contract; do not infer opportunity identity from a partner. */
internal data class Opportunity(
    val id: Int,
    val customer: String,
    val phone: String,
    val address: String,
    val priority: String,
    val requestType: String,
    val model: String,
    val vin: String,
    val consentUrl: String?,
    val quotationName: String?,
    val quotationState: String?,
    val stageId: Int? = null,
    val stageName: String? = null
) {
    val copyValues: List<String> get() = listOf(
        customer, phone, address,
        if (priority.isNotBlank() && requestType.isNotBlank() && model.isNotBlank())
            listOf(priority, requestType, model).joinToString(" - ") else "",
        vin
    )
    val status: String get() = if (quotationState == "draft") "Cotización por enviar" else stageName?.takeIf { it.isNotBlank() } ?: "Por cotizar"
}

internal fun consentDocumentUrl(raw: String?): String? {
    val uri = raw?.let { runCatching { URI(it) }.getOrNull() } ?: return null
    if (!uri.scheme.equals("https", true) || !uri.host.equals("drive.google.com", true) ||
        uri.rawUserInfo != null || uri.port != -1 || uri.rawQuery != null || uri.rawFragment != null)
        return null
    if (!Regex("/file/d/[A-Za-z0-9_-]{10,150}/view").matches(uri.rawPath ?: "")) return null
    return uri.toASCIIString()
}

internal data class OpportunityPage(val rows: List<Opportunity>, val hasNext: Boolean)

internal fun parseOpportunityPage(response: JSONObject): OpportunityPage {
    val result = response.getJSONObject("result")
    val array = result.getJSONArray("opportunities")
    require(array.length() <= 30)
    val rows = mutableListOf<Opportunity>()
    val seen = mutableSetOf<Int>()
    for (index in 0 until array.length()) {
        val row = array.getJSONObject(index)
        val id = row.getInt("id")
        require(id > 0 && seen.add(id))
        fun value(key: String): String = (row.opt(key) as? String).orEmpty().trim()
        val stage = value("disposition")
        require(stage in setOf("pending", "lost", "cancelled", "closed"))
        val state = value("quotation_state").ifEmpty { null }
        if (stage != "pending" || state in setOf("sent", "sale", "done")) continue
        require(state == null || state == "draft" || state == "cancel")
        val type = when (value("request_type")) {
            "new" -> "Nueva"
            "remove_and_install" -> "Desmontado y Montado"
            else -> ""
        }
        rows += Opportunity(id, value("customer"), value("phone"), value("complete_address"),
            value("priority"), type, value("vehicle_model"), value("vin"),
            consentDocumentUrl(value("consent_url")), value("quotation_name").takeIf { it.isNotBlank() },
            state, (row.opt("stage_id") as? Number)?.toInt()?.takeIf { it > 0 },
            value("stage_name").ifEmpty { null })
    }
    return OpportunityPage(rows, result.getBoolean("has_next"))
}
