import java.net.URI

plugins {
    alias(libs.plugins.android.application)
}

// Set this locally through an environment variable or the user's Gradle properties.
val apiBaseUrl = providers.gradleProperty("porciaApiBaseUrl")
    .orElse(providers.environmentVariable("PORCIA_API_BASE_URL"))
    .orElse("https://api.example.invalid/")
    .get().trim()
val apiUri = URI(apiBaseUrl)
require(apiUri.scheme in listOf("http", "https") && !apiUri.host.isNullOrBlank()
        && apiBaseUrl.endsWith("/") && apiUri.userInfo == null
        && apiUri.rawQuery == null && apiUri.rawFragment == null) {
    "API URL must be an http(s) base URL ending in /, without credentials, query or fragment"
}
val apiBaseUrlLiteral = "\"" + apiBaseUrl.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    buildFeatures {
        buildConfig = true
    }
    namespace = "ru.pershin.nutriplan"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "ru.pershin.nutriplan"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "API_BASE_URL", apiBaseUrlLiteral)

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}