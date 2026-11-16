// Install-time asset pack with the retrieval models for release bundles (Google Play installs it with the app). Its
// assets are staged from the repository's pinned, hash-checked models by :app:stageLensModelsPack; never edit them here.
plugins {
    id("com.android.asset-pack")
}

assetPack {
    packName.set("lensmodels")
    dynamicDelivery {
        deliveryType.set("install-time")
    }
}

if (providers.gradleProperty("lensModels").orNull != "false")
    tasks.configureEach { if (name != "clean") dependsOn(":app:stageLensModelsPack") }
