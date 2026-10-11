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
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    val keyStorePath = System.getenv("GWAY_APK_KEYSTORE")
    val keyAlias = System.getenv("GWAY_APK_KEY_ALIAS")
    val keyPassword = System.getenv("GWAY_APK_KEY_PASSWORD")
    val storePassword = System.getenv("GWAY_APK_STORE_PASSWORD")
    if (listOf(keyStorePath, keyAlias, keyPassword, storePassword).all { !it.isNullOrBlank() }) {
        signingConfigs {
            create("distribution") {
                storeFile = file(keyStorePath!!)
                storePassword = storePassword
                this.keyAlias = keyAlias
                this.keyPassword = keyPassword
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
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    testImplementation("junit:junit:4.13.2")
}
