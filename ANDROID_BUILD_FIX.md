# Android build fix

The GitHub Actions failure was caused by AndroidX dependencies being used while `android.useAndroidX` was not enabled.

This release adds `android-companion/gradle.properties` with:

- `android.useAndroidX=true`
- `android.enableJetifier=true`

The existing workflow already uses Java 17 and Gradle 8.11.1, matching the Android Gradle Plugin configuration in this project.
