import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("kotlin-android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("dev.flutter.flutter-gradle-plugin")
}

val localProperties = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.scrapp.app"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    defaultConfig {
        applicationId = "com.scrapp.app"
        minSdk = 31 // Meta DAT samples target Android 12+ (Bluetooth runtime permissions)
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // Developer Mode in the Meta AI app accepts "0". For beta/production use the IDs from
        // the Wearables Developer Center (put them in android/local.properties).
        manifestPlaceholders["mwdat_application_id"] = localProperties.getProperty("mwdat_application_id", "0")
        manifestPlaceholders["mwdat_client_token"] = localProperties.getProperty("mwdat_client_token", "0")
        // ARCore Geospatial API key (Google Cloud, "ARCore API" enabled). Optional: geo anchors only.
        manifestPlaceholders["arcore_api_key"] = localProperties.getProperty("arcore_api_key", "")
    }

    buildFeatures { compose = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }

    androidResources { noCompress += "tflite" }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    packaging { resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" } }
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_21) } }

flutter {
    source = "../.."
}

dependencies {
    // Meta Wearables Device Access Toolkit (Maven Central, no token needed)
    val mwdat = "1.0.1"
    implementation("com.meta.wearable:mwdat-core:$mwdat")
    implementation("com.meta.wearable:mwdat-camera:$mwdat")
    implementation("com.meta.wearable:mwdat-inputs:$mwdat")
    implementation("com.meta.wearable:mwdat-speech:$mwdat")
    implementation("com.meta.wearable:mwdat-mockdevice:$mwdat")

    // AR: SceneView (Filament + ARCore, Compose) and MediaPipe object detection for "hold up an apple"
    implementation("io.github.sceneview:arsceneview:4.18.0")
    implementation("com.google.mediapipe:tasks-vision:0.10.14")

    implementation(platform("androidx.compose:compose-bom:2026.05.01"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
    implementation("androidx.exifinterface:exifinterface:1.4.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    testImplementation("junit:junit:4.13.2")
}
