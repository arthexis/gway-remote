plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.arthexis.gwayremote"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.arthexis.gwayremote"
        minSdk = 26
        targetSdk = 35
        versionCode = System.getenv("GWAY_ANDROID_VERSION_CODE")?.toIntOrNull() ?: 4
        versionName = System.getenv("GWAY_ANDROID_VERSION_NAME") ?: "0.1.3"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    val keyStorePath = System.getenv("GWAY_APK_KEYSTORE")
    val signingAlias = System.getenv("GWAY_APK_KEY_ALIAS")
    val signingPassword = System.getenv("GWAY_APK_KEY_PASSWORD")
    val signingStorePassword = System.getenv("GWAY_APK_STORE_PASSWORD")
    if (listOf(keyStorePath, signingAlias, signingPassword, signingStorePassword).all { !it.isNullOrBlank() }) {
        signingConfigs {
            create("distribution") {
                storeFile = file(keyStorePath!!)
                storePassword = signingStorePassword
                keyAlias = signingAlias
                keyPassword = signingPassword
            }
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("distribution")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("org.json:json:20240303")
}
