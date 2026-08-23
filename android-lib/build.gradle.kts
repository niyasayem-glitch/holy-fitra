plugins {
    id("com.android.library")
    kotlin("android")
}

android {
    namespace = "org.holyfitra"
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Pin the exact NDK used for reproducible Bionic builds. Override this
    // deliberately in a downstream project only after rerunning the complete
    // Android validation matrix.
    ndkVersion = "28.0.13004108"

    defaultConfig {
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                // Gradle supplies the Android NDK toolchain, ANDROID_ABI, and
                // ANDROID_PLATFORM. These project flags make the contract
                // explicit and fail closed if CMake is invoked incorrectly.
                arguments += listOf(
                    "-DHF_REQUIRE_ANDROID=ON",
                    "-DHF_ENABLE_16K_PAGE_ALIGNMENT=ON",
                    "-DHF_ENABLE_ARM64_BRANCH_PROTECTION=OFF",
                    "-DHF_ENABLE_BENCHMARK=ON",
                    "-DANDROID_STL=c++_shared"
                )
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    sourceSets["main"].java.srcDirs("src/main/java")

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    packaging {
        // AGP 8.5.1+ with uncompressed JNI libraries is the recommended
        // packaging mode for 16 KB page-size devices. Verify the final AAR/APK
        // with llvm-readelf and zipalign in CI.
        jniLibs.useLegacyPackaging = false
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    implementation(kotlin("stdlib"))
}
